import threading
from dataclasses import dataclass, field


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
