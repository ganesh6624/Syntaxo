"""Small shared helpers (time handling, rounding, errors)."""
import math
import random
import time
from datetime import datetime, timedelta, timezone

DAY_MS = 86_400_000
_rng = random.SystemRandom()


class HttpError(Exception):
    """Raised anywhere in the app → turned into a JSON error response `{error, field?, ...}`."""

    def __init__(self, status: int, message: str, field: str | None = None, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field
        self.extra = extra


def now_ms() -> int:
    return int(time.time() * 1000)


def iso(dt: datetime | None = None) -> str:
    """ISO-8601 UTC string with milliseconds and a trailing Z, e.g. 2026-09-26T10:15:30.123Z."""
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_from_ms(ms: int | float) -> str:
    return iso(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ms_of(s: str | None) -> int:
    dt = parse_iso(s)
    return int(dt.timestamp() * 1000) if dt else 0


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar-month addition that clamps the day (31 Jan + 1 month → 28/29 Feb)."""
    m = dt.month - 1 + months
    year, month = dt.year + m // 12, m % 12 + 1
    import calendar
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def jround(x: float) -> int:
    """Round half up (like JavaScript Math.round), not banker's rounding."""
    return int(math.floor(x + 0.5))


def pct(a: int, b: int) -> int:
    return jround(a / b * 100) if b else 0


def ceil_div_ms(ms: int, unit_ms: int) -> int:
    return math.ceil(ms / unit_ms)


def pick(seq):
    return seq[_rng.randrange(len(seq))]


def shuffled(seq):
    a = list(seq)
    _rng.shuffle(a)
    return a


def randint(a: int, b: int) -> int:
    return _rng.randint(a, b)


def title_case(s: str) -> str:
    import re
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), str(s).replace("-", " "))


def display_name(user: dict) -> str:
    """How the app and the agent address a learner: their full name as registered."""
    return str(user.get("fullName") or user.get("username") or "").strip()


def to_date_string(iso_s: str) -> str:
    """Like JavaScript Date.toDateString(): 'Sat Sep 26 2026'."""
    dt = parse_iso(iso_s)
    return dt.strftime("%a %b %d %Y") if dt else ""


__all__ = ["HttpError", "now_ms", "iso", "iso_from_ms", "parse_iso", "ms_of", "add_months", "jround", "pct",
           "pick", "shuffled", "randint", "title_case", "display_name", "to_date_string", "DAY_MS", "timedelta"]
