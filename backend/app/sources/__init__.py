"""Registry: adapter name -> class."""

from .base import Source, SourceConfigError, SourceSettings
from .jobsch import JobsChSource

ADAPTERS: dict[str, type] = {"jobsch": JobsChSource}


def build_source(settings: SourceSettings) -> Source:
    adapter = ADAPTERS.get(settings.adapter)
    if adapter is None:
        raise SourceConfigError(f"Unknown adapter '{settings.adapter}'")
    return adapter(settings)
