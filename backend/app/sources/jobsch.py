"""jobs.ch adapter: JSON search and detail API."""

import time
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from .base import ListingData, SourceConfigError, SourceSettings, SourceUnavailable
from .text import html_to_text

BACKOFF_SECONDS = (5, 15, 45)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "application/json",
}
LINK_KEY = "detail_de"  # the search response has no link; the detail response has one per language


class JobsChSource:
    def __init__(self, settings: SourceSettings) -> None:
        self.key = settings.key
        self._timeout = settings.timeout_seconds
        self._delay = settings.request_delay_seconds
        self._search_url = _search_url(settings.options)
        self._detail_url = _require_url(settings.options, "detail_url")
        if "{id}" not in self._detail_url:
            raise SourceConfigError("detail_url must contain {id}")
        self._headers = {**DEFAULT_HEADERS, **_read_headers(settings.options)}

    def search(self) -> list[ListingData]:
        """Load every result page. Any failing page fails the whole search."""
        items, num_pages = self._search_page(1)
        by_id = {item.external_id: item for item in items}
        for page in range(2, num_pages + 1):
            time.sleep(self._delay)
            items, _ = self._search_page(page)
            known = len(by_id)
            by_id.update((item.external_id, item) for item in items)
            if len(by_id) == known:
                raise ValueError(f"Search page {page} has no new listings; is paging still working?")
        return list(by_id.values())

    def _search_page(self, page: int) -> tuple[list[ListingData], int]:
        data = self._get_json(_with_page(self._search_url, page))
        documents, num_pages = data.get("documents"), data.get("numPages")
        if not isinstance(documents, list):
            raise ValueError("Search response has no 'documents' list")
        if not isinstance(num_pages, int) or isinstance(num_pages, bool) or num_pages < 0:
            raise ValueError("Search response has no valid 'numPages'")
        if not documents and (page > 1 or data.get("totalHits")):
            raise ValueError(f"Search page {page} has no documents")
        return [parse_search_item(document) for document in documents], num_pages

    def fetch_detail(self, item: ListingData) -> ListingData:
        url = self._detail_url.replace("{id}", quote(item.external_id, safe=""))
        data = self._get_json(url)
        public_url, description = parse_detail(data)
        return replace(item, url=public_url, description_text=description, raw=data)

    def _get_json(self, url: str) -> dict:
        for delay in (*BACKOFF_SECONDS, None):
            res = requests.get(url, headers=self._headers, timeout=self._timeout)
            if res.status_code != 429 and res.status_code < 500:
                res.raise_for_status()
                return _as_object(res.json())
            if delay is None:
                raise SourceUnavailable(f"HTTP {res.status_code} after {len(BACKOFF_SECONDS)} retries")
            time.sleep(delay)
        raise AssertionError("unreachable")


def parse_search_item(doc: dict) -> ListingData:
    external_id, title = doc.get("id"), doc.get("title")
    if not external_id or not title:
        raise ValueError("Search item without id or title")
    return ListingData(
        external_id=str(external_id),
        title=title,
        company=(doc.get("company") or {}).get("name"),
        location=_location(doc),
        workload=_workload(doc.get("employmentGrades")),
        published_at=_to_utc(doc.get("publicationDate")),
        url=None,
        description_text=None,
        raw=doc,
    )


def parse_detail(data: dict) -> tuple[str | None, str]:
    """Return (public link, plain-text description). A missing description is an error."""
    description = html_to_text(data.get("template_text") or "")
    if not description:
        raise ValueError("Detail response has no description")
    link = ((data.get("_links") or {}).get(LINK_KEY) or {}).get("href")
    return link, description


def _with_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = [(name, value) for name, value in parse_qsl(parts.query) if name != "page"]
    query.append(("page", str(page)))
    return urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))


def _location(doc: dict) -> str | None:
    if doc.get("place"):
        return doc["place"]
    cities = [loc.get("city") for loc in doc.get("locations") or [] if loc.get("city")]
    return ", ".join(cities) or None


def _workload(grades: list[int] | None) -> str | None:
    if not grades:
        return None
    low, high = min(grades), max(grades)
    return f"{low}%" if low == high else f"{low}-{high}%"


def _to_utc(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def _as_object(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Response is not a JSON object")
    return data


def _search_url(options: dict) -> str:
    url, query = _require_url(options, "search_url"), options.get("query")
    if "{query}" not in url:
        raise SourceConfigError("search_url must contain {query}")
    if not isinstance(query, str) or not query.strip():
        raise SourceConfigError("query must be a non-empty string")
    return url.replace("{query}", quote(query, safe=""))


def _require_url(options: dict, name: str) -> str:
    value = options.get(name)
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise SourceConfigError(f"{name} must be an http(s) URL")
    return value


def _read_headers(options: dict) -> dict[str, str]:
    headers = options.get("headers", {})
    valid = isinstance(headers, dict) and all(isinstance(v, str) for v in headers.values())
    if not valid:
        raise SourceConfigError("headers must be a table of strings")
    return headers
