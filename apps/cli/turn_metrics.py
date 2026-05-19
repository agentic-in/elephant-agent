"""Chat turn metric rendering helpers for CLI surfaces."""

from __future__ import annotations

from collections import Counter

from packages.kernel.runtime import KernelOutcome

from .shell_progress_support import outcome_state_focus_meta


_TOOL_SUMMARY_LABELS: dict[str, str] = {
    "tool.file.read": "read",
    "tool.file.list": "listed",
    "tool.file.write": "wrote",
    "tool.file.patch": "edited",
    "tool.file.search": "searched",
    "tool.terminal.exec": "ran",
    "tool.process.manage": "managed process",
    "tool.personal_model.search": "checked understanding",
    "tool.conversation.search": "searched history",
    "tool.personal_model.update": "updated understanding",
    "tool.personal_model.questions": "checked questions",
    "tool.sub_agents": "consulted sub-agent",
    "tool.web.fetch": "fetched",
    "tool.web.search": "searched web",
}


def _tool_verb(tool_id: str) -> str:
    """Short human verb for a tool id. Used only in end-of-turn summaries."""
    tool_id = (tool_id or "").strip()
    if not tool_id:
        return "tool"
    if tool_id in _TOOL_SUMMARY_LABELS:
        return _TOOL_SUMMARY_LABELS[tool_id]
    # Fallback: last segment of tool.foo.bar becomes "bar".
    parts = [part for part in tool_id.split(".") if part]
    if not parts:
        return tool_id
    tail = parts[-1].replace("_", " ")
    return tail


def condense_tool_summary(events: list[tuple[str, bool, int]]) -> str:
    """Fold a per-turn tool-event list into a single human line.

    Input: list of (tool_id, succeeded, started_ns) entries.
    Output: "read × 3 · edited · searched · 1 failed" (or "" if empty).
    Groups by verb, counts, pins any failures into a trailing segment.
    """
    if not events:
        return ""
    succeeded_counter: Counter[str] = Counter()
    failed_counter: Counter[str] = Counter()
    for tool_id, succeeded, _started in events:
        verb = _tool_verb(tool_id)
        if succeeded:
            succeeded_counter[verb] += 1
        else:
            failed_counter[verb] += 1
    segments: list[str] = []
    for verb, count in succeeded_counter.most_common():
        segments.append(f"{verb} × {count}" if count > 1 else verb)
    failed_total = sum(failed_counter.values())
    if failed_total == 1:
        (verb,) = tuple(failed_counter.keys())
        segments.append(f"{verb} failed")
    elif failed_total > 1:
        segments.append(f"{failed_total} failures")
    return " · ".join(segments)


def cache_hit_metric_line(execution: object) -> str:
    if not bool(getattr(execution, "cache_usage_reported", False)):
        return ""
    prompt_tokens = max(0, int(getattr(execution, "prompt_tokens", 0) or 0))
    cached_tokens = max(0, int(getattr(execution, "cached_prompt_tokens", 0) or 0))
    creation_tokens = max(0, int(getattr(execution, "cache_creation_prompt_tokens", 0) or 0))
    if prompt_tokens <= 0:
        return "cache_hit_rate: n/a"
    label = f"{(cached_tokens / prompt_tokens) * 100:.1f}%"
    creation_note = f"; cache_write_tokens={creation_tokens}" if creation_tokens else ""
    return f"cache_hit_rate: {label} ({cached_tokens}/{prompt_tokens} input tokens cached{creation_note})"


def cache_hit_meta_segment(execution: object) -> str:
    if not bool(getattr(execution, "cache_usage_reported", False)):
        return ""
    prompt_tokens = max(0, int(getattr(execution, "prompt_tokens", 0) or 0))
    if prompt_tokens <= 0:
        return ""
    cached_tokens = max(0, int(getattr(execution, "cached_prompt_tokens", 0) or 0))
    if cached_tokens <= 0:
        return ""
    return f"cache hit · {(cached_tokens / prompt_tokens) * 100:.1f}%"


def _append_meta_segment(meta: str, segment: str) -> str:
    if not segment:
        return meta
    if not meta:
        return segment
    return f"{meta} · {segment}"


def _compose_reasoning_display(reasoning: str, content: str) -> str:
    normalized_reasoning = str(reasoning or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized_content = str(content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if normalized_reasoning and normalized_content:
        return f"<think>{normalized_reasoning}</think>\n{normalized_content}"
    if normalized_reasoning:
        return f"<think>{normalized_reasoning}</think>"
    return normalized_content


def _format_compaction_notice(frame: dict) -> str:
    """Extract a human-readable compaction summary from the kernel stage events."""
    kernel_stage_events = frame.get("kernel_stage_events")
    if not isinstance(kernel_stage_events, tuple):
        return ""
    for event in kernel_stage_events:
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict) or payload.get("stage") != "context-compact":
            continue
        detail = str(payload.get("detail") or "")
        if not detail:
            return "compacted"
        # Parse the detail string — only show messages change
        parts: list[str] = []
        for segment in detail.split():
            if segment.startswith("messages="):
                value = segment[len("messages=") :]
                parts.append(f"messages {value.replace('->', ' → ')}")
            elif segment.startswith("compressing="):
                parts.append(f"compressed {segment[len('compressing=') :]}")
        return " · ".join(parts) if parts else "compacted"
    return ""


def _append_outcome(self, outcome: KernelOutcome) -> None:
    self._last_prompt_tokens = outcome.execution.prompt_tokens
    self._last_completion_tokens = outcome.execution.completion_tokens
    self._last_total_tokens = outcome.execution.total_tokens
    if self.debug and outcome.stages:
        stage_lines = [
            f"{stage.stage} | {stage.detail} | {stage.recorded_at.isoformat(timespec='seconds')}"
            for stage in outcome.stages
        ]
        self._append_entry("status", "Runtime stages", "\n".join(stage_lines))
    assistant_name = self.runtime.inspect_profile(
        self.runtime.inspect_session(self.session_id).personal_model_id
    ).state.display_name
    assistant_body = _compose_reasoning_display(
        getattr(outcome.execution, "reasoning", ""),
        outcome.execution.summary,
    )
    assistant_lines = [assistant_body] if assistant_body else []
    if self.debug:
        assistant_lines.extend(
            [
                f"execution: {outcome.execution.outcome}",
                f"current_context: {outcome.state.summary or '<unset>'}",
                f"steps_recorded: {len(outcome.steps)}",
                f"recall_hits: {len(outcome.recall_items)}",
            ]
        )
    meta = _append_meta_segment(outcome_state_focus_meta(outcome), cache_hit_meta_segment(outcome.execution))
    self._append_entry("assistant", assistant_name, "\n".join(assistant_lines), meta=meta)
    # Condensed tool summary for the turn — shown as a lightweight notice
    # so the user sees "read × 3 · edited · searched" in one glance
    # instead of reading the entire tooltrace block.
    tool_events = list(getattr(self, "_turn_tool_events", []) or [])
    if tool_events:
        summary = condense_tool_summary(tool_events)
        if summary:
            tool_count = len(tool_events)
            title = f"⟡ {tool_count} tool{'s' if tool_count != 1 else ''}"
            self._append_entry("notice", title, summary)
    self._turn_tool_events = []
    # Context compaction notice — surface compaction stats as a transcript
    # entry so the user sees it after erase_when_done wipes the live progress.
    compaction_frame = getattr(self, "_pending_context_compaction_frame", None)
    if isinstance(compaction_frame, dict) and not getattr(self, "_pending_context_compaction_frame_rendered", False):
        compaction_summary = _format_compaction_notice(compaction_frame)
        if compaction_summary:
            self._append_entry("notice", "⟡ context compacted", compaction_summary)
        self._pending_context_compaction_frame_rendered = True
