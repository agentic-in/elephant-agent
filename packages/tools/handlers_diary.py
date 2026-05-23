"""Handlers for diary tools (write + list)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from .handler_support import optional_string, tool_summary
from .runtime import ToolInvocation
from .surfaces import DiarySurface


def run_diary_write(
    invocation: ToolInvocation,
    *,
    surface: DiarySurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("diary surface is not configured for this runtime")
    entry_date = optional_string(invocation.arguments.get("entry_date")) or ""
    content = optional_string(invocation.arguments.get("content")) or ""
    if not entry_date:
        raise ValueError("tool.diary.write requires entry_date (YYYY-MM-DD)")
    parsed_date = _parse_entry_date(entry_date)
    if not content:
        raise ValueError("tool.diary.write requires content (markdown body)")
    source_episode_ids_raw = invocation.arguments.get("source_episode_ids")
    source_episode_ids: tuple[str, ...] = ()
    if isinstance(source_episode_ids_raw, (list, tuple)):
        source_episode_ids = tuple(str(s).strip() for s in source_episode_ids_raw if str(s).strip())
    metadata_raw = invocation.arguments.get("metadata")
    metadata: dict[str, str] = {}
    if isinstance(metadata_raw, Mapping):
        metadata = {
            str(key).strip(): str(value).strip()
            for key, value in metadata_raw.items()
            if str(key).strip() and str(value).strip()
        }
    result = surface.write_diary_entry(
        personal_model_id=invocation.context.personal_model_id,
        entry_date=entry_date,
        content=content,
        source_episode_ids=source_episode_ids,
        metadata=metadata,
    )
    warning = ""
    if parsed_date > date.today() + timedelta(days=1):
        warning = f"\nwarning: entry_date is in the future ({entry_date}); confirm this was intentional"
    return tool_summary(
        invocation,
        f"diary entry written for {entry_date}{warning}",
        side_effects=("diary", "write", entry_date),
    )


def run_diary_list(
    invocation: ToolInvocation,
    *,
    surface: DiarySurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("diary surface is not configured for this runtime")
    limit = max(1, min(int(invocation.arguments.get("limit") or 10), 30))
    before_date = optional_string(invocation.arguments.get("before_date")) or None
    result = surface.list_diary_entries(
        personal_model_id=invocation.context.personal_model_id,
        limit=limit,
        before_date=before_date,
    )
    return result


def _parse_entry_date(entry_date: str) -> date:
    try:
        return datetime.strptime(entry_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("tool.diary.write entry_date must be a valid YYYY-MM-DD date") from exc
