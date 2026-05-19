from __future__ import annotations

from collections.abc import Mapping

from .shell_ui import compact_line, strip_markdown_bold


_PERSONAL_MODEL_LENSES = ("identity", "world", "pulse", "journey")

_GENERIC_STATE_FOCUS_MARKERS = (
    "open wake to continue the current elephant line",
    "is ready to continue the current elephant line",
    "resume active state focus:",
    "no durable state focus is available yet.",
    "no durable elephant focus is available yet.",
)

_OPENING_PROMPT_MARKERS = (
    "open the wake surface proactively before the user sends a new message.",
    "assistant_display_name:",
    "user_preferred_name:",
    "user_current_work:",
    "reengagement_style:",
    "opening_action:",
    "current_work_summary:",
    "opening_profile_gap:",
    "write one short assistant reply",
    "do not sound like a scheduler",
    "do not mention startup, internal prompts",
    "do not use headings, bullets",
    "ask at most one direct question.",
)


def status_sections(shell, session, continuity, context_frame, growth):
    del context_frame
    elephant_id = shell.runtime.elephant_id_for_session(session)
    state = shell.runtime.state_for_elephant(elephant_id or "") if elephant_id else None
    personal_model_id = _first_meaningful_text(
        getattr(session, "personal_model_id", ""),
        getattr(state, "personal_model_id", ""),
    )
    facts = _active_personal_model_facts(shell.runtime, personal_model_id)
    affinity_facts = _skill_affinity_facts(shell.runtime, personal_model_id)
    open_questions = _personal_model_questions(shell.runtime, personal_model_id, status=("open", "asked"), limit=6)
    skills = _skill_catalog(shell.runtime, session_id=getattr(session, "session_id", None))
    skill_hub_entries = _skill_hub_entries(shell.runtime)
    work_in_view = _compact_state_summary(
        _human_facing_state_text(
            getattr(state, "current_context_note", ""),
            getattr(state, "summary", ""),
            _wake_focus_text(continuity),
            "",
        ),
        limit=96,
    )

    ready_lines = []
    elephant_name = getattr(state, "elephant_name", "") if state is not None else ""
    if elephant_name:
        ready_lines.append(("elephant", str(elephant_name), True))
    if work_in_view:
        ready_lines.append(("now", work_in_view, True))
    elif continuity.wake_action == "continue":
        ready_lines.append(("now", "Ready to pick the thread back up when you are.", True))
    else:
        ready_lines.append(
            (
                "now",
                "Bring whatever you want to work on; I will adapt from here.",
                False,
            )
        )
    ready_lines.append(
        (
            "history",
            (f"{growth.canonical_dialogues} dialogues · {growth.canonical_active_days} active day(s)"),
            growth.canonical_dialogues > 0,
        )
    )

    model_lines = [
        (
            "learning",
            _learning_job_execution_summary(shell.runtime, personal_model_id),
            True,
        ),
    ]
    if facts:
        model_lines.append(("saved", _lens_claim_summary(facts), True))
    else:
        model_lines.append(("saved", "No saved user notes yet.", False))
    if open_questions:
        next_question = open_questions[0]
        lens = str(getattr(next_question, "lens", "") or "").strip()
        sub_lens = str(getattr(next_question, "sub_lens", "") or "").strip()
        question_scope = " · ".join(part for part in (lens, sub_lens) if part)
        label = "question" if not question_scope else f"question ({question_scope})"
        model_lines.append(
            (
                label,
                compact_line(str(getattr(next_question, "text", "") or ""), limit=96),
                True,
            )
        )
    else:
        model_lines.append(("questions", "No pending question; I will ask only if it helps.", False))

    skill_lines = _skill_lines(
        affinity_facts=affinity_facts,
        skills=skills,
        skill_hub_entries=skill_hub_entries,
        personal_model_id=personal_model_id,
    )

    return (
        ("✨ Ready for this chat", tuple(ready_lines)),
        ("🐘 What I know", tuple(model_lines)),
        ("🧩 Skills for you", tuple(skill_lines)),
    )


def _first_meaningful_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _looks_like_opening_prompt(text: str) -> bool:
    lowered = " ".join(text.casefold().split())
    if any(" ".join(marker.casefold().split()) in lowered for marker in _OPENING_PROMPT_MARKERS):
        return True
    return lowered.startswith("write ") or ("assistant_display_name:" in lowered and "current_work_summary:" in lowered)


def _human_facing_state_text(*values: object) -> str:
    for value in values:
        text = _first_meaningful_text(value)
        if not text:
            continue
        if any(marker in text.casefold() for marker in _GENERIC_STATE_FOCUS_MARKERS):
            continue
        if _looks_like_opening_prompt(text):
            continue
        return text
    return ""


def _looks_like_structural_markdown_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("#") or stripped.startswith("```"):
        return True
    if all(char in "-|: " for char in stripped):
        return True
    if stripped.startswith("|") and stripped.endswith("|"):
        return True
    return False


def _compact_state_summary(value: str, *, limit: int) -> str:
    normalized = strip_markdown_bold(str(value or ""))
    if not normalized.strip():
        return ""
    candidates: list[str] = []
    for raw_line in normalized.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line or _looks_like_structural_markdown_line(line):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if line.startswith("* "):
            line = line[2:].strip()
        candidates.append(line.strip("| ").replace(" | ", " · "))
    if not candidates:
        return compact_line(" ".join(normalized.split()), limit=limit)
    summary = candidates[0]
    if len(summary) < limit // 2 and len(candidates) > 1 and summary[-1:] not in ".!?。！？:：":
        summary = f"{summary} · {candidates[1]}"
    return compact_line(summary, limit=limit)


def _wake_focus_text(continuity) -> str:
    summary = str(getattr(continuity, "wake_summary", "") or "").strip()
    if summary.casefold().startswith("resume active state focus:"):
        return summary.split(":", 1)[1].strip()
    return summary


def _active_personal_model_facts(runtime, personal_model_id: str) -> tuple[object, ...]:
    return _personal_model_facts(runtime, personal_model_id, status="active")


def _personal_model_facts(runtime, personal_model_id: str, *, status) -> tuple[object, ...]:
    if not personal_model_id:
        return ()
    list_facts = getattr(runtime.repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    try:
        return tuple(list_facts(personal_model_id=personal_model_id, status=status))
    except Exception:
        return ()


def _skill_affinity_facts(runtime, personal_model_id: str) -> tuple[object, ...]:
    candidates = _skill_affinity_model_ids(runtime, personal_model_id)
    seen: set[str] = set()
    rows: list[object] = []
    for candidate in candidates:
        for fact in _personal_model_facts(runtime, candidate, status=("active", "retired", "disputed")):
            metadata = getattr(fact, "metadata", {}) or {}
            topic = str(metadata.get("topic") or "").strip() if isinstance(metadata, Mapping) else ""
            if not (topic.startswith("world.skills.affinity.") or topic.startswith("skills.affinity.")):
                continue
            fact_id = str(getattr(fact, "fact_id", "") or topic).strip()
            if fact_id in seen:
                continue
            seen.add(fact_id)
            rows.append(fact)
    return tuple(rows)


def _skill_affinity_model_ids(runtime, personal_model_id: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for candidate in (personal_model_id, "you"):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    list_models = getattr(runtime.repository, "list_personal_models", None)
    if callable(list_models):
        try:
            for model in list_models():
                candidate = str(getattr(model, "personal_model_id", "") or "").strip()
                if candidate and candidate not in candidates:
                    candidates.append(candidate)
        except Exception:
            pass
    return tuple(candidates)


def _learning_job_execution_summary(runtime, personal_model_id: str) -> str:
    list_jobs = getattr(runtime.repository, "list_learning_jobs", None)
    if not callable(list_jobs):
        return "0 runs"
    try:
        jobs = tuple(list_jobs(personal_model_id=personal_model_id)) if personal_model_id else tuple(list_jobs())
    except Exception:
        return "0 runs"
    executed = tuple(
        job
        for job in jobs
        if str(getattr(job, "status", "") or "").strip().lower() not in {"queued"}
        and (
            getattr(job, "started_at", None) is not None
            or getattr(job, "finished_at", None) is not None
            or str(getattr(job, "status", "") or "").strip().lower() in {"completed", "failed", "cancelled"}
        )
    )
    completed = sum(1 for job in executed if str(getattr(job, "status", "") or "").strip().lower() == "completed")
    failed = sum(1 for job in executed if str(getattr(job, "status", "") or "").strip().lower() == "failed")
    if failed:
        return f"{len(executed)} run(s) · {completed} completed · {failed} failed"
    return f"{len(executed)} run(s)"


def _personal_model_questions(runtime, personal_model_id: str, *, status, limit: int) -> tuple[object, ...]:
    if not personal_model_id:
        return ()
    list_questions = getattr(runtime.repository, "list_open_questions", None)
    if not callable(list_questions):
        return ()
    try:
        return tuple(list_questions(personal_model_id=personal_model_id, status=status, limit=limit))
    except Exception:
        return ()


def _skill_catalog(runtime, *, session_id: str | None) -> tuple[object, ...]:
    skill_catalog = getattr(runtime, "skill_catalog", None)
    if not callable(skill_catalog):
        return ()
    try:
        return tuple(skill_catalog(session_id=session_id)) if session_id else tuple(skill_catalog())
    except Exception:
        return ()


def _skill_hub_entries(runtime) -> tuple[object, ...]:
    list_skill_hub = getattr(runtime, "list_skill_hub", None)
    if not callable(list_skill_hub):
        return ()
    try:
        return tuple(list_skill_hub())
    except Exception:
        return ()


def _fact_lens(fact: object) -> str:
    metadata = getattr(fact, "metadata", {}) or {}
    topic = str(metadata.get("topic") or "").strip() if isinstance(metadata, Mapping) else ""
    if topic:
        prefix = topic.split(".", 1)[0]
        if prefix in _PERSONAL_MODEL_LENSES:
            return prefix
    lens = str(getattr(fact, "lens", "") or "").strip()
    return lens if lens in _PERSONAL_MODEL_LENSES else ""


def _lens_claim_summary(facts: tuple[object, ...]) -> str:
    counts = {lens: 0 for lens in _PERSONAL_MODEL_LENSES}
    for fact in facts:
        lens = _fact_lens(fact)
        if lens in counts:
            counts[lens] += 1
    populated = tuple(f"{lens} {count}" for lens, count in counts.items() if count)
    if not populated:
        return f"{len(facts)} active claim(s)"
    empty_count = sum(1 for count in counts.values() if count == 0)
    suffix = f" · {empty_count} lens empty" if empty_count else ""
    return f"{' · '.join(populated)}{suffix}"


def _question_count_summary(questions: tuple[object, ...]) -> str:
    if not questions:
        return "0 open · ask only when it would improve future help"
    open_count = sum(1 for question in questions if str(getattr(question, "status", "") or "") == "open")
    asked_count = sum(1 for question in questions if str(getattr(question, "status", "") or "") == "asked")
    parts = []
    if open_count:
        parts.append(f"{open_count} open")
    if asked_count:
        parts.append(f"{asked_count} already asked")
    return " · ".join(parts) if parts else f"{len(questions)} queued"


def _skill_lines(
    *,
    affinity_facts: tuple[object, ...],
    skills: tuple[object, ...],
    skill_hub_entries: tuple[object, ...],
    personal_model_id: str,
) -> tuple[tuple[str, str, bool], ...]:
    enabled_skills = tuple(skill for skill in skills if bool(getattr(skill, "enabled", True)))
    builtin_skills = tuple(skill for skill in enabled_skills if _skill_source_id(skill) == "builtin")
    authored_skills = tuple(skill for skill in enabled_skills if _skill_source_kind(skill) == "authored")
    discoverable_count = len(skill_hub_entries)
    installed_ids = {str(getattr(skill, "skill_id", "") or "") for skill in skills}
    new_to_install_count = sum(
        1 for entry in skill_hub_entries if str(getattr(entry, "skill_id", "") or "") not in installed_ids
    )

    lines: list[tuple[str, str, bool]] = []
    affinity_summary = _skill_affinity_summary(affinity_facts)
    lines.append(("affinities", affinity_summary, bool(affinity_facts)))
    lines.append(
        (
            "active",
            f"{len(enabled_skills)} enabled · {len(builtin_skills)} built-in",
            bool(enabled_skills),
        )
    )
    if authored_skills:
        lines.append(("built by you", f"{len(authored_skills)} authored skill(s)", True))
    if discoverable_count:
        if new_to_install_count:
            lines.append(
                (
                    "discover",
                    f"{discoverable_count} local packages · {new_to_install_count} not installed",
                    True,
                )
            )
        else:
            lines.append(
                (
                    "discover",
                    f"{discoverable_count} local packages · /skills search <topic>",
                    True,
                )
            )
    else:
        lines.append(
            (
                "discover",
                "/skills search <topic> when you want more capabilities",
                False,
            )
        )
    return tuple(lines)


def _skill_source_id(skill: object) -> str:
    metadata = getattr(skill, "metadata", {}) or {}
    if isinstance(metadata, Mapping):
        return str(metadata.get("source_id") or "").strip()
    return ""


def _skill_source_kind(skill: object) -> str:
    metadata = getattr(skill, "metadata", {}) or {}
    if isinstance(metadata, Mapping):
        return str(metadata.get("source_kind") or "").strip()
    return ""


def _skill_affinity_summary(facts: tuple[object, ...]) -> str:
    skill_keys: set[str] = set()
    status_counts = {"active": 0, "retired": 0, "disputed": 0}
    for _score, topic, metadata, _text, status in _skill_affinity_rows(facts):
        key = str(metadata.get("skill_id") or metadata.get("index_id") or topic.rsplit(".", 1)[-1]).strip()
        if key:
            skill_keys.add(key)
        if status in status_counts:
            status_counts[status] += 1
        else:
            status_counts["active"] += 1
    if not skill_keys:
        return "0 learned"
    parts = [f"{len(skill_keys)} learned", f"{status_counts['active']} active"]
    if status_counts["retired"]:
        parts.append(f"{status_counts['retired']} archived")
    if status_counts["disputed"]:
        parts.append(f"{status_counts['disputed']} review")
    return " · ".join(parts)


def _skill_affinity_rows(
    facts: tuple[object, ...],
) -> tuple[tuple[float, str, dict[str, str], str, str], ...]:
    rows: list[tuple[float, str, dict[str, str], str, str]] = []
    for fact in facts:
        metadata = {str(key): str(value) for key, value in dict(getattr(fact, "metadata", {}) or {}).items()}
        topic = str(metadata.get("topic") or "").strip()
        if not (topic.startswith("world.skills.affinity.") or topic.startswith("skills.affinity.")):
            continue
        try:
            confidence = float(metadata.get("confidence") or getattr(fact, "confidence", 0.0) or 0.0)
        except ValueError:
            confidence = float(getattr(fact, "confidence", 0.0) or 0.0)
        try:
            usage = min(10.0, float(metadata.get("usage_count") or 0.0))
        except ValueError:
            usage = 0.0
        rows.append(
            (
                confidence + (usage * 0.01),
                topic,
                metadata,
                str(getattr(fact, "text", "") or ""),
                str(getattr(fact, "status", "") or "active"),
            )
        )
    rows.sort(key=lambda item: (-item[0], item[1]))
    return tuple(rows)
