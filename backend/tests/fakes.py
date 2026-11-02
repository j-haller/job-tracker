import threading
from dataclasses import dataclass, field

from app.sources.base import ListingData


@dataclass
class SlowControl:
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


def slow_source_factory():
    """An adapter whose search blocks until the test releases it."""
    control = SlowControl()

    class SlowSource:
        def __init__(self, settings) -> None:
            self.key = settings.key

        def search(self):
            control.entered.set()
            control.release.wait(5)
            return []

        def fetch_detail(self, item):
            return item

    return SlowSource, control


def listing(external_id: str, title: str = "Dev") -> ListingData:
    return ListingData(external_id, title, "ACME", "Bern", "100%", None, None, None, {"id": external_id})


class FakeSource:
    def __init__(self, key: str = "fake", items: list[ListingData] | None = None) -> None:
        self.key = key
        self.items = items or []
        self.search_error: Exception | None = None
        self.detail_errors: dict[str, Exception] = {}
        self.detail_calls: list[str] = []

    def search(self) -> list[ListingData]:
        if self.search_error:
            raise self.search_error
        return list(self.items)

    def fetch_detail(self, item: ListingData) -> ListingData:
        self.detail_calls.append(item.external_id)
        if item.external_id in self.detail_errors:
            raise self.detail_errors[item.external_id]
        item.url = f"https://public.test/{item.external_id}"
        item.description_text = f"Text {item.external_id}"
        return ListingData(**{**item.__dict__, "raw": {"detail": item.external_id}})
