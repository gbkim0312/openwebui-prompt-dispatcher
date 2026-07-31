from datetime import datetime
from zoneinfo import ZoneInfo


class SystemClock:
    def now(self, timezone: str) -> datetime:
        return datetime.now(ZoneInfo(timezone))


class FakeClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self, timezone: str) -> datetime:
        return self.current.astimezone(ZoneInfo(timezone))
