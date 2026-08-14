from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TOKYO_TIME_ZONE = ZoneInfo("Asia/Tokyo")


def today_in_tokyo(now: datetime | None = None) -> date:
    instant = now or datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    return instant.astimezone(TOKYO_TIME_ZONE).date()
