"""NSE session calendar (stdlib only).

Sessions are weekdays 09:15-15:30 IST minus exchange holidays. Holidays start
empty. Call set_holidays() with ISO dates (for example from
india_client.FMPClient.get_trading_holidays()) to make the calendar exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional

IST = timezone(timedelta(hours=5, minutes=30))
VENUE = "XNSE"
_ALIASES = {"XNSE", "NSE"}
_HOLIDAYS: set = set()


class CalendarUnavailableError(RuntimeError):
    """Raised when no session can be found inside the search horizon."""


@dataclass(frozen=True)
class Session:
    venue: str
    session_date: date
    timezone: str
    market_open: datetime
    market_close: datetime
    break_start: Optional[datetime] = None
    break_end: Optional[datetime] = None


def supported_venues() -> tuple:
    return (VENUE,)


def set_holidays(days: Iterable) -> None:
    """Replace the holiday set. Accepts date objects or YYYY-MM-DD strings."""
    out = set()
    for d in days or []:
        if isinstance(d, datetime):
            out.add(d.date())
        elif isinstance(d, date):
            out.add(d)
        else:
            try:
                out.add(date.fromisoformat(str(d)[:10]))
            except ValueError:
                continue
    _HOLIDAYS.clear()
    _HOLIDAYS.update(out)


def _venue(venue: str) -> str:
    if not isinstance(venue, str):
        raise ValueError("venue must be a string")
    if venue.strip().upper() not in _ALIASES:
        raise ValueError(f"Unsupported venue {venue!r}; expected {VENUE}")
    return VENUE


def _require_date(value, *, name: str) -> date:
    if type(value) is not date:
        raise TypeError(f"{name} must be datetime.date (not datetime)")
    return value


def require_aware(value: datetime, *, name: str = "timestamp") -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    if value.utcoffset() is None:
        raise ValueError(f"{name} must have a resolvable UTC offset")
    return value


def parse_aware_datetime(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("as-of must be a non-empty ISO-8601 timestamp")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO-8601 as-of timestamp: {value!r}") from exc
    return require_aware(parsed, name="as-of")


def _is_session_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _HOLIDAYS


def _make(d: date) -> Session:
    return Session(
        venue=VENUE,
        session_date=d,
        timezone="Asia/Kolkata",
        market_open=datetime.combine(d, time(9, 15), tzinfo=IST),
        market_close=datetime.combine(d, time(15, 30), tzinfo=IST),
    )


def session_for_date(venue: str, session_date: date) -> Optional[Session]:
    _venue(venue)
    d = _require_date(session_date, name="session_date")
    return _make(d) if _is_session_day(d) else None


def is_open_at(venue: str, timestamp: datetime) -> bool:
    _venue(venue)
    local = require_aware(timestamp).astimezone(IST)
    s = session_for_date(VENUE, local.date())
    return bool(s and s.market_open <= local < s.market_close)


def next_session_on_or_after(venue: str, start_date: date, *, max_search_days: int = 370) -> Session:
    _venue(venue)
    d = _require_date(start_date, name="start_date")
    if max_search_days < 0:
        raise ValueError("max_search_days must be non-negative")
    for i in range(max_search_days + 1):
        cand = d + timedelta(days=i)
        if _is_session_day(cand):
            return _make(cand)
    raise CalendarUnavailableError(f"No {VENUE} session within {max_search_days} days of {d}")


def next_session_after(venue: str, session_date: date, *, max_search_days: int = 370) -> Session:
    d = _require_date(session_date, name="session_date")
    if max_search_days <= 0:
        raise ValueError("max_search_days must be positive")
    return next_session_on_or_after(venue, d + timedelta(days=1), max_search_days=max_search_days - 1)


def previous_session_on_or_before(venue: str, end_date: date, *, max_search_days: int = 370) -> Session:
    _venue(venue)
    d = _require_date(end_date, name="end_date")
    if max_search_days < 0:
        raise ValueError("max_search_days must be non-negative")
    for i in range(max_search_days + 1):
        cand = d - timedelta(days=i)
        if _is_session_day(cand):
            return _make(cand)
    raise CalendarUnavailableError(f"No {VENUE} session within {max_search_days} days of {d}")


def previous_session_before(venue: str, session_date: date, *, max_search_days: int = 370) -> Session:
    d = _require_date(session_date, name="session_date")
    if max_search_days <= 0:
        raise ValueError("max_search_days must be positive")
    return previous_session_on_or_before(venue, d - timedelta(days=1), max_search_days=max_search_days - 1)


def current_or_next_session(venue: str, timestamp: datetime) -> Session:
    _venue(venue)
    local = require_aware(timestamp).astimezone(IST)
    s = session_for_date(VENUE, local.date())
    if s is not None and local < s.market_close:
        return s
    return next_session_after(VENUE, local.date())


def count_sessions(venue: str, start_date: date, end_date: date, *,
                   include_start: bool, include_end: bool) -> int:
    _venue(venue)
    a = _require_date(start_date, name="start_date")
    b = _require_date(end_date, name="end_date")
    if a > b:
        raise ValueError("start_date must be on or before end_date")
    first = a if include_start else a + timedelta(days=1)
    last = b if include_end else b - timedelta(days=1)
    n = 0
    d = first
    while d <= last:
        if _is_session_day(d):
            n += 1
        d += timedelta(days=1)
    return n
