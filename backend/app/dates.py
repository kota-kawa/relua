from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TOKYO_TIME_ZONE = ZoneInfo("Asia/Tokyo")


def today_in_tokyo(now: datetime | None = None) -> date:
    instant = now or datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    return instant.astimezone(TOKYO_TIME_ZONE).date()


def add_years(value: date, years: int) -> date:
    """Shift a date by whole years, clamping February 29 onto February 28 when needed.

    ``date.replace(year=...)`` raises ``ValueError: day is out of range for month`` whenever the
    source date is a leap day and the target year is not a leap year (2028-02-29 -> 2033). A bound
    computed that way turns into an unrelated crash on exactly one calendar day every four years,
    so the clamp is done here once instead of at every call site.
    """
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # February 29 is the only date that can be invalid in another year, and February 28 is the
        # same position in the calendar for a bound that is deliberately coarse ("five years out").
        return value.replace(year=value.year + years, month=2, day=28)


def years_ahead_in_tokyo(years: int, now: datetime | None = None) -> date:
    """Upper bound for operator-supplied dates: today in JST, shifted by whole years.

    JST - not the server's local time - because every other "today" in this codebase is the
    Japanese business day the operator is working in.
    """
    return add_years(today_in_tokyo(now), years)
