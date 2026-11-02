"""Common listing format and interface for source adapters."""

from dataclasses import dataclass, field
from typing import Protocol


class SourceConfigError(ValueError):
    """A source's settings are invalid; that source stays disabled."""


class SourceUnavailable(Exception):
    """The site keeps refusing or failing; stop calling it for this run."""


@dataclass(frozen=True)
class SourceSettings:
    key: str
    enabled: bool
    adapter: str
    interval_minutes: int
    fetch_on_startup: bool
    request_delay_seconds: float
    timeout_seconds: float
    options: dict = field(default_factory=dict)  # adapter-specific, validated by the adapter


@dataclass
class ListingData:
    external_id: str  # the site's own ID
    title: str
    company: str | None
    location: str | None
    workload: str | None
    published_at: str | None  # ISO 8601
    url: str | None  # public link to the original listing
    description_text: str | None  # None when a detail request is needed
    raw: dict  # untouched source data


class Source(Protocol):
    key: str  # e.g. "jobsch"

    def search(self) -> list[ListingData]: ...  # one full result set

    def fetch_detail(self, item: ListingData) -> ListingData: ...  # fills description_text
