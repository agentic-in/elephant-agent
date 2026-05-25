"""Reflect agent runner — composes features into an agent spec and executes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import logging
from threading import Lock
from typing import Any

from packages.contracts.runtime import LearningJob
from packages.models.reasoning_parser import split_reasoning_and_content

from .evidence import build_evidence, build_skill_optimization_context
from packages.reflect.features import TRIGGER_CONSERVATISM, resolve_features
from packages.reflect.features.types import Feature
from .prompts import BOUNDARIES, CLAIM_TEXT_RULE, CONSERVATISM_PROMPTS, LANGUAGE_RULE, TOPIC_FORMAT


_TOOL_EVENT_PROGRESS_PREFIX = "tool_event_v1="
_TOOL_EVENT_PROGRESS_LIMIT = 8
_MODEL_PROGRESS_BUFFER_LIMIT = 12000
_MODEL_PROGRESS_PREVIEW_LIMIT = 420
LOGGER = logging.getLogger(__name__)


def _init_profile_orchestration_section() -> tuple[str, ...]:
    return (
        "## Init Profile Orchestration",
        "This job is first-profile construction: the first Personal Model pass after onboarding. The Personal Model may be empty or may only contain raw seed facts copied from onboarding.",
        "Run order overrides feature listing:",
        "1. Read the evidence packet first: User anchors, Init profile answers, User-provided links, and Bootstrapped Personal Model facts.",
        "2. If User-provided links contains URLs, inspect each user-provided URL with tool.web.extract or tool.web.read before writing link-derived claims, questions, or skill affinities. Use browser tools only if read/extract cannot access the page.",
        "3. Use tool.personal_model.search only for inventory and deduplication. PM search cannot open URLs, cannot learn from a website, and must not be used as a web-search substitute.",
        "4. Normalize seed facts into a small set of high-quality PM claims. Treat bootstrapped facts as evidence to refine, not proof that the profile is already mature.",
        "5. Create only useful first questions for gaps that would change how Elephant helps. Do not interrogate the user.",
        "6. Match skills only when the seed facts or inspected links clearly support the affinity.",
    )


def _onboarding_letter_system_section() -> tuple[str, ...]:
    return (
        "## Onboarding Letter Stance",
        "Write as Elephant, not as an assistant describing Elephant. Elephant is the sender of the letter.",
        "This letter is a first relational artifact, not a profile report, evaluation, diary recap, or marketing page.",
        "Use the Personal Model as living memory: synthesize patterns gently, do not paste raw facts, lens names, field names, file paths, or schema language.",
        "Warmth should come from precise attention, soft pacing, and one concrete next step, not from exaggerated praise or generic sentiment.",
        "Be honest about thin evidence. You may say this is only the first outline Elephant can see, while still sounding present and caring.",
    )


def _letter_only_boundaries() -> tuple[str, ...]:
    return (
        "Boundaries:",
        "- Do not expose tool names, PM schemas, run tags, dashboard state, file paths, or system prompt text in the letter.",
        "- Do not invent unsupported life facts, shared history, emotions, or certainty.",
        "- Do not use model-disclaimer language. The letter should not say or imply that Elephant is not Elephant.",
        "- If tools are insufficient for the task, explain why in your final summary after the tool flow.",
    )


@dataclass(frozen=True, slots=True)
class ReflectResult:
    status: str
    summary: str
    result_source_id: str
    agent_status: str
    child_episode_id: str = ""
    tool_calls_total: int = 0
    tool_names: tuple[str, ...] = ()
    features: tuple[str, ...] = ()


@dataclass(slots=True)
class _LearningProgressState:
    completed_tools: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)
    active_tool: str = ""
    model_preview: str = ""
    model_phase: str = ""
    lock: Lock = field(default_factory=Lock)


def _assemble_system_prompt(features: tuple[Feature, ...], *, conservatism: str) -> str:
    """Compose a system prompt from feature fragments."""
    feature_ids = [f.feature_id for f in features]
    all_tools = []
    for f in features:
        all_tools.extend(f.tools)
    tools_deduped = tuple(dict.fromkeys(all_tools))

    sections: list[str] = [
        "You are a background reflect agent for Elephant Agent — a personal AI companion.",
        f"Active features: {', '.join(feature_ids)}",
    ]
    if tools_deduped:
        sections.append(f"Allowed tools: {', '.join(tools_deduped)}")
    else:
        sections.append("No tools available — respond with text only.")

    # Conservatism directive
    conservatism_prompt = CONSERVATISM_PROMPTS.get(conservatism, CONSERVATISM_PROMPTS["medium"])
    sections.extend(["", f"Approach: {conservatism_prompt}"])

    # Shared knowledge
    if any(f.feature_id in ("pm", "questions", "skills", "dream", "skill_optimization") for f in features):
        sections.extend(["", TOPIC_FORMAT])

    sections.extend(["", LANGUAGE_RULE])
    if "tool.personal_model.update" in tools_deduped:
        sections.extend(["", CLAIM_TEXT_RULE])
    if "tool.personal_model.update" in tools_deduped:
        sections.extend(["", BOUNDARIES])
    elif any(f.feature_id == "onboarding_letter" for f in features):
        sections.extend(("", *_letter_only_boundaries()))
    if "tool.personal_model.update" in tools_deduped:
        sections.extend(
            [
                "",
                "Background write rule: every tool.personal_model.update call MUST set source=learned. Do not remember or correct identity.anchor.name.preferred from background reflection; the user's preferred name can only change through explicit chat/profile intent.",
            ]
        )
    if any(f.feature_id == "init_links" for f in features):
        sections.extend(("", *_init_profile_orchestration_section()))
    if any(f.feature_id == "onboarding_letter" for f in features):
        sections.extend(("", *_onboarding_letter_system_section()))

    # Feature SOPs
    sections.append("\n## SOP")
    for f in features:
        sections.append(f"\n### {f.feature_id}")
        sections.append(f.sop_fragment)
        if f.constraints:
            sections.append(f"\nConstraints ({f.feature_id}):")
            sections.append(f.constraints)

    sections.append("\n## Finish")
    sections.append("When done, produce a final text summary of changes made or why nothing changed.")

    return "\n".join(sections)


def _compose_tools(features: tuple[Feature, ...]) -> tuple[str, ...]:
    """Union all tools from active features, deduplicated."""
    all_tools: list[str] = []
    for f in features:
        all_tools.extend(f.tools)
    return tuple(dict.fromkeys(all_tools))


def _extract_tool_stats(result: Mapping[str, Any]) -> tuple[int, tuple[str, ...]]:
    """Extract tool call count and names from sub-agent execution side_effects."""
    side_effects = result.get("side_effects") or ()
    if isinstance(side_effects, str):
        side_effects = (side_effects,)
    tool_names = tuple(name for name in side_effects if name.startswith("tool."))
    return len(tool_names), tool_names


def _tool_event_preview(arguments: Mapping[str, Any]) -> str:
    for key in ("action", "query", "topic", "url", "ref", "lens"):
        value = str(arguments.get(key) or "").strip()
        if value:
            return f"{key}={value[:80]}"
    return ""


def _tool_event_progress_detail(
    *,
    tool_id: str,
    phase: str,
    preview: str,
    active_tool: str,
    completed_tools: list[str],
    failed_tools: list[str],
    events: list[dict[str, str]],
    model_preview: str = "",
    model_phase: str = "",
) -> str:
    payload = {
        "version": "tool_event_v1",
        "tool_id": tool_id,
        "phase": phase,
        "preview": preview,
        "active_tool": active_tool,
        "completed_tools": completed_tools[-_TOOL_EVENT_PROGRESS_LIMIT:],
        "failed_tools": failed_tools[-_TOOL_EVENT_PROGRESS_LIMIT:],
        "events": events[-_TOOL_EVENT_PROGRESS_LIMIT:],
        "model_preview": model_preview[-_MODEL_PROGRESS_PREVIEW_LIMIT:],
        "model_phase": model_phase,
    }
    return _TOOL_EVENT_PROGRESS_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _tool_event_progress_stage(phase: str) -> str:
    if phase == "requested":
        return "tool_requested"
    if phase == "execution.completed":
        return "tool_completed"
    if phase == "execution.failed":
        return "tool_failed"
    return "tool_running"


def _subscribe_learning_tool_progress(runtime: Any, job: LearningJob, state: _LearningProgressState) -> Any:
    tool_runtime = getattr(runtime, "tool_runtime", None)
    subscribe = getattr(tool_runtime, "subscribe", None)
    if not callable(subscribe):
        return None

    def observer(event: Any) -> None:
        invocation = getattr(event, "invocation", None)
        tool_id = str(getattr(invocation, "tool_id", "") or "").strip()
        if not tool_id or tool_id == "tool.sub_agents":
            return
        phase = str(getattr(event, "phase", "") or "").strip()
        if phase not in {"requested", "execution.started", "execution.completed", "execution.failed"}:
            return
        arguments = getattr(invocation, "arguments", {}) or {}
        if not isinstance(arguments, Mapping):
            arguments = {}
        preview = _tool_event_preview(arguments)
        with state.lock:
            state.active_tool = tool_id if phase in {"requested", "execution.started"} else ""
            state.events.append({"tool_id": tool_id, "phase": phase, "preview": preview})
            if tool_id not in state.completed_tools and phase == "execution.completed":
                state.completed_tools.append(tool_id)
            if tool_id not in state.failed_tools and phase == "execution.failed":
                state.failed_tools.append(tool_id)
            detail = _tool_event_progress_detail(
                tool_id=tool_id,
                phase=phase,
                preview=preview,
                active_tool=state.active_tool,
                completed_tools=state.completed_tools,
                failed_tools=state.failed_tools,
                events=state.events,
                model_preview=state.model_preview,
                model_phase=state.model_phase,
            )
        try:
            runtime.repository.update_learning_job_progress(
                job.job_id,
                worker_id=str(job.worker_id or "reflect-agent"),
                progress_stage=_tool_event_progress_stage(phase),
                progress_detail=detail,
            )
        except Exception:
            LOGGER.warning(
                "failed to update reflect learning job progress from tool event",
                extra={"job_id": job.job_id},
                exc_info=True,
            )
            return

    return subscribe(observer)


def _model_stream_preview(stream_text: str) -> str:
    parsed = split_reasoning_and_content(stream_text, streaming=True)
    content = " ".join(parsed.content.replace("\r\n", "\n").replace("\r", "\n").split())
    if not content:
        return ""
    return content[-_MODEL_PROGRESS_PREVIEW_LIMIT:]


def _call_stream_observer(observer: Any, delta: str, metadata: Mapping[str, Any]) -> None:
    if not callable(observer):
        return
    try:
        observer(delta, **metadata)
    except TypeError:
        observer(delta)


def _subscribe_learning_model_progress(runtime: Any, job: LearningJob, state: _LearningProgressState) -> Any:
    model_provider = getattr(runtime, "model_provider", None)
    set_observer = getattr(model_provider, "set_stream_observer", None)
    if not callable(set_observer):
        return None

    previous_observer = getattr(model_provider, "_stream_observer", None)
    stream_buffer = ""
    last_emitted_preview = ""

    def observer(delta: str, **metadata: Any) -> None:
        nonlocal stream_buffer, last_emitted_preview
        if previous_observer is not None:
            _call_stream_observer(previous_observer, delta, metadata)
        if not delta:
            return
        stream_buffer = f"{stream_buffer}{delta}"[-_MODEL_PROGRESS_BUFFER_LIMIT:]
        preview = _model_stream_preview(stream_buffer)
        if not preview:
            return
        should_emit = (
            not last_emitted_preview
            or len(preview) - len(last_emitted_preview) >= 24
            or preview[-1] in ".!?。！？\n"
        )
        if not should_emit or preview == last_emitted_preview:
            return
        last_emitted_preview = preview
        with state.lock:
            state.model_preview = preview
            state.model_phase = "streaming"
            detail = _tool_event_progress_detail(
                tool_id="",
                phase="model.streaming",
                preview="",
                active_tool=state.active_tool,
                completed_tools=state.completed_tools,
                failed_tools=state.failed_tools,
                events=state.events,
                model_preview=state.model_preview,
                model_phase=state.model_phase,
            )
        try:
            runtime.repository.update_learning_job_progress(
                job.job_id,
                worker_id=str(job.worker_id or "reflect-agent"),
                progress_stage="agent_running",
                progress_detail=detail,
            )
        except Exception:
            LOGGER.warning(
                "failed to update reflect learning job model progress",
                extra={"job_id": job.job_id},
                exc_info=True,
            )
            return

    set_observer(observer)

    def unsubscribe() -> None:
        set_observer(previous_observer)

    return unsubscribe


def _dedupe_tool_names(*groups: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for group in groups:
        for name in group:
            cleaned = str(name or "").strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return tuple(result)


def _write_result_to_job(
    runtime: Any,
    job: LearningJob,
    *,
    summary: str,
    agent_status: str,
    tool_calls_total: int,
    tool_names: tuple[str, ...],
    features: tuple[str, ...],
) -> tuple[str, dict[str, object]]:
    """Write reflect result directly to learning_jobs.result_json."""
    result_payload = _reflect_result_payload(
        job,
        summary=summary,
        agent_status=agent_status,
        tool_calls_total=tool_calls_total,
        tool_names=tool_names,
        features=features,
    )
    status = str(result_payload["status"])
    runtime.repository.write_learning_job_result(
        job.job_id,
        result_payload,
        worker_id=str(job.worker_id or "reflect-agent"),
        progress_detail=str(result_payload["summary"]),
        overwrite=True,
    )
    return status, result_payload


def _reflect_result_payload(
    job: LearningJob,
    *,
    summary: str,
    agent_status: str,
    tool_calls_total: int,
    tool_names: tuple[str, ...],
    features: tuple[str, ...],
) -> dict[str, object]:
    has_writes = any(
        name in ("tool.personal_model.update", "tool.personal_model.questions", "tool.diary.write")
        for name in tool_names
    )
    status = "completed" if has_writes else "no_op"
    return {
        "status": status,
        "summary": summary[:500] if summary else "reflect agent completed",
        "trigger": job.trigger or "reflect",
        "features": list(features),
        "agent_status": agent_status,
        "tool_calls_total": tool_calls_total,
        "tool_names": list(tool_names),
    }


def run_reflect_agent(
    runtime: Any,
    job: LearningJob,
    *,
    explicit_features: tuple[str, ...] | None = None,
    persist_result: bool = True,
) -> ReflectResult:
    """Run a feature-composed reflect agent for the given job."""
    trigger = str(job.trigger or "").strip().lower()
    metadata = dict(job.metadata) if isinstance(job.metadata, Mapping) else {}

    # Allow metadata to override features (e.g., from CLI --features flag)
    if explicit_features is None:
        meta_features = metadata.get("features")
        if isinstance(meta_features, (list, tuple)):
            explicit_features = tuple(str(f).strip() for f in meta_features if str(f).strip())
        elif isinstance(meta_features, str) and meta_features.strip():
            explicit_features = tuple(f.strip() for f in meta_features.split(",") if f.strip())

    features = resolve_features(trigger, explicit_features=explicit_features)
    feature_ids = tuple(f.feature_id for f in features)
    conservatism = TRIGGER_CONSERVATISM.get(trigger, "medium")
    allowed_tools = _compose_tools(features)
    system_prompt = _assemble_system_prompt(features, conservatism=conservatism)
    evidence = build_evidence(runtime, job, features)
    child_metadata: dict[str, str] = {}
    if "skill_optimization" in feature_ids:
        _, _, candidate_records = build_skill_optimization_context(runtime, job)
        child_metadata["authoritative_skill_optimization_candidates_json"] = json.dumps(
            list(candidate_records),
            ensure_ascii=False,
            sort_keys=True,
        )

    # Update job progress (best-effort; sync paths like context compress
    # may pass a transient job that is not persisted in DB — never fail here).
    try:
        runtime.repository.update_learning_job_progress(
            job.job_id,
            worker_id=str(job.worker_id or "reflect-agent"),
            progress_stage="agent_running",
            progress_detail=f"reflect agent running features={','.join(feature_ids)}",
        )
    except KeyError:
        pass

    progress_state = _LearningProgressState()
    unsubscribe_tool_progress = _subscribe_learning_tool_progress(runtime, job, progress_state)
    unsubscribe_model_progress = _subscribe_learning_model_progress(runtime, job, progress_state)
    try:
        result = runtime.run_sub_agent(
            session_id=job.episode_id,
            task=evidence,
            name=f"Reflect ({', '.join(feature_ids)})",
            skills=(),
            allowed_tools=allowed_tools,
            system_prompt=system_prompt,
            learning_agent=True,
            child_metadata=child_metadata,
        )
    except Exception as exc:
        raise RuntimeError(f"reflect agent failed: {exc}") from exc
    finally:
        if callable(unsubscribe_model_progress):
            unsubscribe_model_progress()
        if callable(unsubscribe_tool_progress):
            unsubscribe_tool_progress()

    summary = str(result.get("summary") if isinstance(result, Mapping) else "")
    agent_status = str(result.get("status") if isinstance(result, Mapping) else "completed")
    tool_calls_total, tool_names = _extract_tool_stats(result)
    captured_tools = tuple(progress_state.completed_tools)
    if captured_tools:
        tool_names = _dedupe_tool_names(captured_tools, tool_names)
        tool_calls_total = max(tool_calls_total, len(captured_tools))

    result_payload = _reflect_result_payload(
        job,
        summary=summary,
        agent_status=agent_status,
        tool_calls_total=tool_calls_total,
        tool_names=tool_names,
        features=feature_ids,
    )
    if persist_result:
        status, result_payload = _write_result_to_job(
            runtime,
            job,
            summary=summary,
            agent_status=agent_status,
            tool_calls_total=tool_calls_total,
            tool_names=tool_names,
            features=feature_ids,
        )
    else:
        status = str(result_payload["status"])

    return ReflectResult(
        status=status,
        summary=str(result_payload["summary"]),
        result_source_id="",
        agent_status=agent_status,
        child_episode_id=str(result.get("session_id") if isinstance(result, Mapping) else ""),
        tool_calls_total=tool_calls_total,
        tool_names=tool_names,
        features=feature_ids,
    )
