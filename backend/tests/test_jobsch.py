from unittest.mock import Mock

import pytest

from app.fetcher import parse_settings
from app.sources import jobsch
from app.sources.base import SourceConfigError, SourceUnavailable
from app.sources.jobsch import JobsChSource, parse_detail, parse_search_item
from app.sources.text import html_to_text

RAW = {
    "enabled": True,
    "adapter": "jobsch",
    "interval_minutes": 60,
    "fetch_on_startup": False,
    "request_delay_seconds": 0,
    "timeout_seconds": 5,
    "search_url": "https://example.test/search?query={query}",
    "query": "Dev Ops",
    "detail_url": "https://example.test/job/{id}",
}


def make_source(**changes) -> JobsChSource:
    return JobsChSource(parse_settings("jobsch", {**RAW, **changes}))


def response(status: int = 200, body: object = None) -> Mock:
    res = Mock(status_code=status)
    res.json.return_value = body
    return res


@pytest.fixture
def http(monkeypatch):
    get = Mock()
    monkeypatch.setattr(jobsch.requests, "get", get)
    return get


@pytest.fixture
def sleeps(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(jobsch.time, "sleep", sleep)
    return sleep


def test_every_search_sample_maps(load_sample):
    documents = load_sample("search.json")["documents"]
    items = [parse_search_item(doc) for doc in documents]
    assert len({item.external_id for item in items}) == 300
    assert all(item.title and item.url is None and item.description_text is None for item in items)


def test_search_item_fields(load_sample):
    doc = load_sample("search.json")["documents"][0]
    item = parse_search_item(doc)
    assert item.external_id == "bec83357-3b90-4364-8b80-5384b6de19ce"
    assert item.title == "Senior AI Software Developer (80-100%)"
    assert item.company == "DV Bern AG"
    assert item.location == "Bern"
    assert item.workload == "80-100%"
    assert item.published_at == "2026-10-19T16:27:30+00:00"
    assert item.raw is doc


def test_search_item_optional_fields_missing():
    item = parse_search_item({"id": "1", "title": "Dev", "company": None, "locations": [], "employmentGrades": []})
    assert (item.company, item.location, item.workload, item.published_at) == (None, None, None, None)


def test_location_falls_back_to_cities():
    doc = {"id": "1", "title": "Dev", "place": None, "locations": [{"city": "Bern"}, {"city": "Basel"}]}
    assert parse_search_item(doc).location == "Bern, Basel"


def test_single_grade_workload():
    assert parse_search_item({"id": "1", "title": "Dev", "employmentGrades": [100]}).workload == "100%"


def test_search_item_without_id_fails():
    with pytest.raises(ValueError):
        parse_search_item({"title": "Dev"})


@pytest.mark.parametrize(
    "name", ["detail.json", "detail_unpaid_1.json", "detail_unpaid_2.json", "detail_unpaid_3.json"]
)
def test_detail_samples_map(load_sample, name):
    data = load_sample(name)
    link, description = parse_detail(data)
    assert link == data["_links"]["detail_de"]["href"]
    assert len(description) > 200
    assert "<" not in description


def test_detail_without_description_fails():
    with pytest.raises(ValueError):
        parse_detail({"template_text": "<p> </p>"})


def test_html_to_text():
    html = "<p>Hallo&nbsp;Welt</p><p>Zweiter<br />Teil</p><style>x{}</style><ul><li><p>Eins</p></li><li>Zwei</li></ul>"
    assert html_to_text(html) == "Hallo Welt\n\nZweiter\nTeil\n\n- Eins\n- Zwei"


def test_search_calls_url_with_browser_like_headers(http):
    http.return_value = response(body={"documents": [{"id": "1", "title": "Dev"}], "totalHits": 1, "numPages": 1})
    items = make_source(headers={"X-Test": "1"}).search()
    assert [item.external_id for item in items] == ["1"]
    assert http.call_args.args[0] == "https://example.test/search?query=Dev%20Ops&page=1"
    headers = http.call_args.kwargs["headers"]
    assert headers["User-Agent"].startswith("Mozilla/")
    assert headers["Accept"] == "application/json"
    assert headers["X-Test"] == "1"
    assert http.call_args.kwargs["timeout"] == 5.0


@pytest.mark.parametrize(
    "body",
    [
        {"rows": 300},
        {"documents": [], "totalHits": 5, "numPages": 1},
        {"documents": [{"id": "1", "title": "Dev"}], "totalHits": 1},
        {"documents": [{"id": "1", "title": "Dev"}], "totalHits": 1, "numPages": "2"},
        ["not", "an", "object"],
    ],
)
def test_unexpected_search_response_fails_loudly(http, body):
    http.return_value = response(body=body)
    with pytest.raises(ValueError):
        make_source().search()


def test_empty_search_with_no_hits_is_valid(http):
    http.return_value = response(body={"documents": [], "totalHits": 0, "numPages": 0})
    assert make_source().search() == []
    assert http.call_count == 1


def docs(*ids: str) -> list[dict]:
    return [{"id": external_id, "title": "Dev"} for external_id in ids]


def test_search_loads_all_pages_and_keeps_query(http, sleeps):
    http.side_effect = [
        response(body={"documents": docs("1", "2"), "totalHits": 3, "numPages": 2}),
        response(body={"documents": docs("3"), "totalHits": 3, "numPages": 2}),
    ]
    url = "https://example.test/search?query={query}&rows=300"
    items = make_source(search_url=url, query="Software Developer", request_delay_seconds=2).search()
    assert [item.external_id for item in items] == ["1", "2", "3"]
    assert [call.args[0] for call in http.call_args_list] == [
        "https://example.test/search?query=Software%20Developer&rows=300&page=1",
        "https://example.test/search?query=Software%20Developer&rows=300&page=2",
    ]
    assert [call.args[0] for call in sleeps.call_args_list] == [2.0]


def test_page_in_configured_url_is_replaced(http):
    http.return_value = response(body={"documents": docs("1"), "totalHits": 1, "numPages": 1})
    make_source(search_url="https://example.test/search?page=2&query={query}&rows=300").search()
    assert http.call_args.args[0] == "https://example.test/search?query=Dev%20Ops&rows=300&page=1"


def test_query_is_url_encoded(http):
    http.return_value = response(body={"documents": docs("1"), "totalHits": 1, "numPages": 1})
    make_source(query="C++ & Go").search()
    assert http.call_args.args[0] == "https://example.test/search?query=C%2B%2B%20%26%20Go&page=1"


def test_listing_on_two_pages_counts_once(http, sleeps):
    http.side_effect = [
        response(body={"documents": docs("1", "2"), "totalHits": 3, "numPages": 2}),
        response(body={"documents": docs("2", "3"), "totalHits": 3, "numPages": 2}),
    ]
    assert [item.external_id for item in make_source().search()] == ["1", "2", "3"]


def test_failing_later_page_fails_whole_search(http, sleeps):
    failed = response(404)
    failed.raise_for_status.side_effect = RuntimeError("404")
    http.side_effect = [response(body={"documents": docs("1"), "totalHits": 2, "numPages": 2}), failed]
    with pytest.raises(RuntimeError):
        make_source().search()


def test_empty_later_page_fails_whole_search(http, sleeps):
    http.side_effect = [
        response(body={"documents": docs("1"), "totalHits": 2, "numPages": 2}),
        response(body={"documents": [], "totalHits": 2, "numPages": 2}),
    ]
    with pytest.raises(ValueError, match="page 2"):
        make_source().search()


def test_ignored_page_parameter_fails_loudly(http, sleeps):
    http.return_value = response(body={"documents": docs("1", "2"), "totalHits": 4, "numPages": 2})
    with pytest.raises(ValueError, match="no new listings"):
        make_source().search()


def test_fetch_detail_fills_item_and_encodes_id(http):
    http.return_value = response(
        body={"template_text": "<p>Text</p>", "_links": {"detail_de": {"href": "https://public.test/1"}}}
    )
    item = parse_search_item({"id": "a/b", "title": "Dev"})
    filled = make_source().fetch_detail(item)
    assert http.call_args.args[0] == "https://example.test/job/a%2Fb"
    assert (filled.url, filled.description_text) == ("https://public.test/1", "Text")
    assert filled.raw["template_text"] == "<p>Text</p>"
    assert item.description_text is None


def test_backoff_then_success(http, sleeps):
    ok = response(body={"documents": [], "totalHits": 0, "numPages": 0})
    http.side_effect = [response(429), response(503), ok]
    make_source().search()
    assert [call.args[0] for call in sleeps.call_args_list] == [5, 15]


def test_backoff_gives_up(http, sleeps):
    http.return_value = response(429)
    with pytest.raises(SourceUnavailable):
        make_source().search()
    assert http.call_count == 4
    assert [call.args[0] for call in sleeps.call_args_list] == [5, 15, 45]


def test_client_error_is_not_retried(http, sleeps):
    res = response(404)
    res.raise_for_status.side_effect = RuntimeError("404")
    http.return_value = res
    with pytest.raises(RuntimeError):
        make_source().search()
    assert http.call_count == 1
    sleeps.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"search_url": None},
        {"search_url": "ftp://example.test/{query}"},
        {"search_url": "https://example.test/search?query=Software%20Developer"},
        {"query": ""},
        {"query": None},
        {"query": 5},
        {"detail_url": "https://example.test/job"},
        {"headers": {"X": 1}},
    ],
)
def test_invalid_adapter_settings(changes):
    with pytest.raises(SourceConfigError):
        make_source(**changes)
