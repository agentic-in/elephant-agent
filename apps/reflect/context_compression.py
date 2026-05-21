"""Shared synchronous Reflect context compression helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from packages.contracts.runtime import LearningJob, PromptMessage


FALLBACK_NOTE = "llm_failed_using_heuristic"


def render_messages_text(messages: tuple[PromptMessage, ...], *, limit: int = 0) -> str:
    """Render prompt messages into concise text for compression evidence."""
    lines: list[str] = []
    total = 0
    pending_tool_names: list[str] = []
    for msg in messages:
        role = msg.role or "unknown"
        content = msg.content.strip()
        if role == "tool":
            continue
        if role == "assistant" and msg.tool_calls and not content:
            for call in msg.tool_calls:
                name = str(call.get("function", {}).get("name") or call.get("name") or "tool")
                pending_tool_names.append(name)
            continue
        if pending_tool_names:
            tool_line = f"[used {len(pending_tool_names)} tools: {', '.join(dict.fromkeys(pending_tool_names))}]"
            total += len(tool_line)
            if limit and total > limit:
                lines.append("... (truncated)")
                break
            lines.append(tool_line)
            pending_tool_names = []
        if not content:
            continue
        if role == "assistant" and msg.tool_calls:
            line = f"assistant [+{len(msg.tool_calls)} tool calls]: {content[:300]}"
        elif role == "user":
            line = f"user: {content}"
        elif role == "assistant":
            line = f"assistant: {content}"
        else:
            continue
        total += len(line)
        if limit and total > limit:
            lines.append("... (truncated)")
            break
        lines.append(line)
    if pending_tool_names:
        tool_line = f"[used {len(pending_tool_names)} tools: {', '.join(dict.fromkeys(pending_tool_names))}]"
        lines.append(tool_line)
    return "\n".join(lines)


def reflect_compress_summary(
    runtime: Any,
    *,
    session_id: str,
    frozen_epoch: Any,
    to_summarize: tuple[PromptMessage, ...],
    tail: tuple[PromptMessage, ...],
    context_limit: int,
    log: Any | None = None,
) -> tuple[str, str]:
    """Run the same transient Reflect compressor used by CLI chat.

    The LearningJob is intentionally not persisted: it only carries metadata
    into `run_reflect_agent`, while the caller owns saving the compacted epoch.
    """
    previous_sub_agent_active = bool(getattr(runtime, "sub_agent_active", False))
    delegation_armed = False
    if previous_sub_agent_active:
        object.__setattr__(runtime, "sub_agent_active", False)
        delegation_armed = True
    try:
        from apps.reflect.runner import run_reflect_agent

        token_budget = max(400, int(context_limit * 0.08))
        compress_metadata = {
            "compressed_messages": render_messages_text(to_summarize, limit=0),
            "previous_summary": str(getattr(frozen_epoch, "compacted_history_summary", "") or ""),
            "token_budget": str(token_budget),
            "tail_hint": render_messages_text(tail, limit=1500),
            "features": "compress",
        }
        session = _load_runtime_session(runtime, session_id)
        now = datetime.now(timezone.utc)
        job = LearningJob(
            job_id=f"sync-compress:{uuid4().hex[:12]}",
            job_type="context_compaction",
            trigger="context_compaction",
            status="running",
            personal_model_id=session.personal_model_id,
            state_id=session.state_id,
            episode_id=session_id,
            loop_id=None,
            summary="synchronous context compression",
            progress_stage="agent_running",
            progress_detail="synchronous compress",
            attempt_count=1,
            max_attempts=1,
            available_at=now,
            created_at=now,
            started_at=now,
            finished_at=None,
            worker_id="context-compress-sync",
            last_error="",
            metadata=compress_metadata,
        )
        result = run_reflect_agent(runtime, job, explicit_features=("compress",), persist_result=False)
        return result.summary.strip(), FALLBACK_NOTE
    except Exception as exc:
        if log is not None:
            log.warning("context compress agent failed: %s", exc, exc_info=True)
        return "", FALLBACK_NOTE
    finally:
        if delegation_armed:
            object.__setattr__(runtime, "sub_agent_active", previous_sub_agent_active)


def _load_runtime_session(runtime: Any, session_id: str) -> Any:
    load_session = getattr(runtime, "_load_session", None)
    if callable(load_session):
        return load_session(session_id)
    repository = getattr(runtime, "repository", None)
    load_episode = getattr(repository, "load_episode", None)
    if callable(load_episode):
        session = load_episode(session_id)
        if session is not None:
            return session
    raise KeyError(session_id)


__all__ = ["FALLBACK_NOTE", "reflect_compress_summary", "render_messages_text"]
