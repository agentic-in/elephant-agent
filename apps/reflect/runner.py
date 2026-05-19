"""Reflect agent runner — composes features into an agent spec and executes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from packages.contracts.runtime import LearningJob

from .evidence import build_evidence
from .features import TRIGGER_CONSERVATISM, resolve_features
from .features.types import Feature
from .prompts import BOUNDARIES, CLAIM_TEXT_RULE, CONSERVATISM_PROMPTS, LANGUAGE_RULE, TOPIC_FORMAT


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

    sections.extend(["", LANGUAGE_RULE, "", CLAIM_TEXT_RULE, "", BOUNDARIES])

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

    # Execute
    try:
        result = runtime.run_sub_agent(
            session_id=job.episode_id,
            task=evidence,
            name=f"Reflect ({', '.join(feature_ids)})",
            skills=(),
            allowed_tools=allowed_tools,
            system_prompt=system_prompt,
            learning_agent=True,
        )
    except Exception as exc:
        raise RuntimeError(f"reflect agent failed: {exc}") from exc

    summary = str(result.get("summary") if isinstance(result, Mapping) else "")
    agent_status = str(result.get("status") if isinstance(result, Mapping) else "completed")
    tool_calls_total, tool_names = _extract_tool_stats(result)

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
