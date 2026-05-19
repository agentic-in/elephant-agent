"""Deterministic time range parsing for conversation recall."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_FUZZY_TIME_WINDOW_LABELS = frozenset(
    {
        "last_night",
        "yesterday_evening",
        "this_morning",
        "today_afternoon",
        "today_evening",
    }
)


@dataclass(frozen=True, slots=True)
class RecallTimeRange:
    start_at: datetime | None = None
    end_at: datetime | None = None
    label: str = ""
    timezone: str = ""
    search_start_at: datetime | None = None
    search_end_at: datetime | None = None

    def contains(self, value: datetime | None) -> bool:
        if value is None:
            return self.start_at is None and self.end_at is None
        when = _aware(value)
        lower = self.search_start_at or self.start_at
        upper = self.search_end_at or self.end_at
        if lower is not None and when < _aware(lower):
            return False
        if upper is not None and when >= _aware(upper):
            return False
        return True

    def payload(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.start_at is not None:
            out["start_at"] = _aware(self.start_at).isoformat(timespec="minutes")
        if self.end_at is not None:
            out["end_at"] = _aware(self.end_at).isoformat(timespec="minutes")
        if self.search_start_at is not None:
            out["search_start_at"] = _aware(self.search_start_at).isoformat(timespec="minutes")
        if self.search_end_at is not None:
            out["search_end_at"] = _aware(self.search_end_at).isoformat(timespec="minutes")
        if self.timezone:
            out["timezone"] = self.timezone
        if self.label:
            out["label"] = self.label
        return out


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _timezone_name(value: object) -> str:
    return str(value or "").strip() or "Asia/Shanghai"


def _timezone(value: object) -> timezone | ZoneInfo:
    name = _timezone_name(value)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _with_timezone(value: datetime, tz: timezone | ZoneInfo) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=tz)


def _parse_datetime(value: object, *, tz: timezone | ZoneInfo | None = None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(_with_timezone(parsed, tz or timezone.utc))


def _local_day_bounds(day: datetime, tz: timezone | ZoneInfo) -> tuple[datetime, datetime]:
    start = day.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _with_local_time(day: datetime, tz: timezone | ZoneInfo, *, hour: int, minute: int = 0) -> datetime:
    return day.astimezone(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _parse_relative_expr(
    expr: str, *, now: datetime, tz: timezone | ZoneInfo
) -> tuple[datetime | None, datetime | None]:
    match = re.fullmatch(r"last:(\d+)([hdw])", expr)
    if match:
        amount = max(1, int(match.group(1)))
        unit = match.group(2)
        delta = {
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
            "w": timedelta(weeks=amount),
        }[unit]
        return now - delta, now
    if expr in {"today", "this:day"}:
        return _local_day_bounds(now, tz)
    if expr in {"yesterday", "previous:day"}:
        start, _end = _local_day_bounds(now - timedelta(days=1), tz)
        return start, start + timedelta(days=1)
    if expr == "this:week":
        local_now = now.astimezone(tz)
        start = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if expr == "previous:week":
        local_now = now.astimezone(tz)
        this_week = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return this_week - timedelta(days=7), this_week
    if expr == "now":
        return now, now
    if expr in {"this:episode", "this_episode", "current_episode"}:
        return None, None  # No time constraint — current episode is always included
    return None, None


def _parse_human_window_expr(
    expr: str, *, now: datetime, tz: timezone | ZoneInfo
) -> tuple[datetime | None, datetime | None]:
    local_now = now.astimezone(tz)
    today = local_now
    yesterday = local_now - timedelta(days=1)
    if expr == "last_night":
        start = _with_local_time(yesterday, tz, hour=18)
        end = _with_local_time(today, tz, hour=6)
        if local_now.hour < 6:
            end = local_now
        return start, end
    if expr == "yesterday_evening":
        return _with_local_time(yesterday, tz, hour=18), _with_local_time(today, tz, hour=0)
    if expr == "this_morning":
        return _with_local_time(today, tz, hour=6), _with_local_time(today, tz, hour=12)
    if expr == "today_afternoon":
        return _with_local_time(today, tz, hour=12), _with_local_time(today, tz, hour=18)
    if expr == "today_evening":
        return _with_local_time(today, tz, hour=18), _with_local_time(today + timedelta(days=1), tz, hour=0)
    return None, None


def _parse_iso_date_expr(expr: str, *, tz: timezone | ZoneInfo) -> tuple[datetime | None, datetime | None]:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", expr) is None:
        return None, None
    start_at = _parse_datetime(expr, tz=tz)
    if start_at is None:
        return None, None
    return start_at, start_at + timedelta(days=1)


def _parse_iso_interval_expr(expr: str, *, tz: timezone | ZoneInfo) -> tuple[datetime | None, datetime | None]:
    if "/" not in expr:
        return None, None
    start_raw, end_raw = (part.strip() for part in expr.split("/", 1))
    start_at = _parse_datetime(start_raw, tz=tz)
    if start_at is None:
        return None, None
    duration_match = re.fullmatch(r"P(?:T(?:(\d+)H)?(?:(\d+)M)?)|P(\d+)D", end_raw)
    if duration_match:
        hours = int(duration_match.group(1) or 0)
        minutes = int(duration_match.group(2) or 0)
        days = int(duration_match.group(3) or 0)
        return start_at, start_at + timedelta(days=days, hours=hours, minutes=minutes)
    end_at = _parse_datetime(end_raw, tz=tz)
    return start_at, end_at


def recall_time_range_from_payload(value: object, *, now: datetime | None = None) -> RecallTimeRange | None:
    if not isinstance(value, Mapping):
        return None
    timezone_name = _timezone_name(value.get("timezone") or value.get("tz"))
    tz = _timezone(timezone_name)
    effective_now = _aware(now or datetime.now(timezone.utc)).astimezone(tz)
    expr = str(value.get("expr") or value.get("window") or value.get("label") or "").strip()
    start_at = _parse_datetime(value.get("start_at") or value.get("start"), tz=tz)
    end_at = _parse_datetime(value.get("end_at") or value.get("end"), tz=tz)
    label = expr or str(value.get("label") or value.get("window") or "").strip()
    if start_at is None and end_at is None and expr:
        start_at, end_at = _parse_relative_expr(expr, now=effective_now, tz=tz)
    if start_at is None and end_at is None and expr:
        start_at, end_at = _parse_human_window_expr(expr, now=effective_now, tz=tz)
    if start_at is None and end_at is None and expr:
        start_at, end_at = _parse_iso_date_expr(expr, tz=tz)
    if start_at is None and end_at is None and expr:
        start_at, end_at = _parse_iso_interval_expr(expr, tz=tz)
    if start_at is None and end_at is None:
        return None
    search_start_at = _parse_datetime(value.get("search_start_at"), tz=tz)
    search_end_at = _parse_datetime(value.get("search_end_at"), tz=tz)
    if expr in _FUZZY_TIME_WINDOW_LABELS:
        search_start_at = search_start_at or (start_at - timedelta(hours=1) if start_at is not None else None)
        search_end_at = search_end_at or (end_at + timedelta(hours=2) if end_at is not None else None)
    return RecallTimeRange(
        start_at=start_at,
        end_at=end_at,
        label=label,
        timezone=timezone_name,
        search_start_at=search_start_at,
        search_end_at=search_end_at,
    )
