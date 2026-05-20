"""Lightweight chat dashboard projection helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api_runtime_internal_methods import (
    _metadata_text,
    _serialize,
    _step_event_content,
    _step_event_type,
    _step_metadata,
)


def _chat_runtime_traces(
    *,
    episodes: tuple[Any, ...],
    loops_by_episode: Mapping[str, tuple[Any, ...]],
    steps_by_loop: Mapping[str, tuple[Any, ...]],
) -> tuple[dict[str, Any], ...]:
    traces = []
    for episode in episodes:
        episode_loops = tuple(
            sorted(
                loops_by_episode.get(episode.episode_id, ()),
                key=lambda item: (str(getattr(item, "started_at", "") or ""), str(getattr(item, "loop_id", ""))),
            )
        )
        loop_rows = []
        timeline = []
        for loop in episode_loops:
            loop_steps = tuple(
                sorted(
                    steps_by_loop.get(loop.loop_id, ()),
                    key=lambda item: (int(getattr(item, "sequence", 0) or 0), str(getattr(item, "created_at", "") or "")),
                )
            )
            step_rows = tuple(_chat_step_row(step) for step in loop_steps)
            timeline.extend(step_rows)
            loop_rows.append({**_serialize(loop), "step_count": len(step_rows), "steps": step_rows})
        traces.append(
            {
                **_serialize(episode),
                "loop_count": len(loop_rows),
                "step_count": len(timeline),
                "loops": tuple(loop_rows),
                "timeline": tuple(timeline),
            }
        )
    return tuple(traces)


def _chat_step_row(step: Any) -> dict[str, Any]:
    metadata = _step_metadata(step)
    event_type = _step_event_type(step)
    content = _compact_chat_text(_step_event_content(step, {}), limit=20_000)
    summary = _compact_chat_text(str(getattr(step, "summary", "") or ""), limit=4_000)
    tool_arguments = _compact_chat_text(_metadata_text(metadata, "tool_arguments"), limit=1_200)
    tool_result = _compact_chat_text(_metadata_text(metadata, "tool_result"), limit=1_600)
    raw_user_query = _compact_chat_text(
        _metadata_text(metadata, "raw_user_query") or _metadata_text(metadata, "user_query"),
        limit=8_000,
    )
    assistant_response = _compact_chat_text(
        _metadata_text(metadata, "assistant_response") or (content if event_type == "llm_answer" else ""),
        limit=20_000,
    )
    return {
        "step_id": str(getattr(step, "step_id", "") or ""),
        "loop_id": str(getattr(step, "loop_id", "") or ""),
        "episode_id": str(getattr(step, "episode_id", "") or ""),
        "state_id": str(getattr(step, "state_id", "") or ""),
        "personal_model_id": str(getattr(step, "personal_model_id", "") or ""),
        "sequence": int(getattr(step, "sequence", 0) or 0),
        "action": str(getattr(step, "action", "") or ""),
        "status": str(getattr(step, "status", "") or ""),
        "summary": summary,
        "created_at": str(getattr(step, "created_at", "") or ""),
        "event_type": event_type,
        "content": content,
        "metadata": {
            "user_query": _compact_chat_text(_metadata_text(metadata, "user_query"), limit=8_000),
            "raw_user_query": raw_user_query,
            "assistant_response": assistant_response,
            "tool_name": _metadata_text(metadata, "tool_name"),
            "tool_arguments": tool_arguments,
            "tool_result": tool_result,
        },
        "detail": {
            "tool_name": _metadata_text(metadata, "tool_name"),
            "tool_arguments": tool_arguments,
            "tool_result": tool_result,
            "raw_user_query": raw_user_query,
        },
    }


def _compact_chat_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."
