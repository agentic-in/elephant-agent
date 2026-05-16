"""Sectioned internal dashboard projections."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packages.growth import build_growth_snapshot, default_growth_state
from packages.runtime_layout import elephant_file_path
from packages.state import ELEPHANT_IDENTITY_FILENAME
from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID
from packages.understanding.personal_model_governance import is_skill_affinity_topic, skill_affinity_index_id

from .api_runtime_console import (
    _cron_jobs,
    _gateway,
    _logs,
    _mcp_catalog,
    _profile_overrides,
    _settings,
    _skills,
    _tools,
)
from .api_runtime_internal_methods import (
    _INTERNAL_DASHBOARD_QUERY_CONTRACT,
    _canonical_usage,
    _connection,
    _dashboard_active_provider,
    _dashboard_step_row,
    _learning_snapshot,
    _personal_model_lens_summaries,
    _now,
    _runtime_traces,
    _serialize,
    _sort_items,
    _table_exists,
)
from .api_runtime_internal_triggers import (
    trigger_diary_write,
    trigger_reflect_job,
)

_COUNT_TABLES = {
    "personal_models",
    "states",
    "episodes",
    "loops",
    "steps",
    "semantic_index_entries",
}

def _count_rows(database_path: Path, table: str) -> int:
    if table not in _COUNT_TABLES:
        raise ValueError(f"Unsupported dashboard count table: {table}")
    with _connection(database_path) as connection:
        if not _table_exists(connection, table):
            return 0
        row = connection.execute("SELECT COUNT(*) AS count FROM " + table).fetchone()
    return int(row["count"] if row is not None else 0)

def _read_optional_text(path: Path, *, max_chars: int = 20_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars].strip()
    except OSError:
        return ""

def _elephant_identity_file(elephant_id: str, *, install_root: Path | None, fallback_text: str = "") -> dict[str, Any]:
    try:
        elephant_root = elephant_file_path(elephant_id, install_root=install_root)
    except ValueError:
        return {"eggId": elephant_id, "path": "", "exists": False, "text": fallback_text.strip()}
    path = elephant_root / ELEPHANT_IDENTITY_FILENAME
    return {
        "eggId": elephant_id,
        "path": str(path),
        "exists": path.exists(),
        "text": _read_optional_text(path) or fallback_text.strip(),
    }


DASHBOARD_SECTIONS = {
    "overview",
    "personal-models",
    "herd",
    "runtime",
    "chat",
    "evidence",
    "questions",
    "providers",
    "skills",
    "tools",
    "gateway",
    "cron",
    "reflect",
    "settings",
    "usage",
    "logs",
    "usage-logs",
    "diary",
}


def _empty_learning() -> dict[str, Any]:
    return {
        "worker": {},
        "summary": {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "total": 0,
            "active_job_id": None,
            "latest_completed_at": None,
        },
        "jobs": (),
    }


def _empty_dashboard(self, *, section: str, generated_at: str) -> dict[str, Any]:
    return {
        "meta": {
            "generated_at": generated_at,
            "database_path": str(self.repository.database_path),
            "section": section,
            "available_sections": tuple(sorted(DASHBOARD_SECTIONS)),
            "query_contract": _INTERNAL_DASHBOARD_QUERY_CONTRACT,
        },
        "overview": {
            "counts": {},
            "current_state_id": None,
            "current_personal_model_id": None,
            "provider_status": "unknown",
            "semantic_index_status": "unknown",
            "note": "Internal dashboard sections are fetched on demand by route.",
        },
        "herd": (),
        "personal_models": (),
        "states": (),
        "runtime": {"episodes": (), "loops": (), "steps": (), "episode_traces": (), "learning_jobs": ()},
        "learning": _empty_learning(),
        "evidence": {
            "semantic_index_entries": (),
        },
        "questions": {
            "facts": (),
            "waiting_questions": (),
            "asked_questions": (),
            "answered_questions": (),
            "dismissed_questions": (),
            "lens_coverage": (),
            "learning_intensity": "medium",
        },
        "semantic_index_health": {
            "status": "unknown",
            "entry_count": 0,
            "backend_count": 0,
            "provider_ids": (),
            "model_ids": (),
            "embedding_bootstrap_status": None,
        },
        "providers": {
            "active_provider": {},
            "doctor": {},
            "embedding_provider": {},
            "auth_states": (),
        },
        "operations": {
            "skills": (),
            "skill_affinities": (),
            "tools": (),
            "mcp": {},
            "cron": {"jobs": ()},
            "gateway": {},
            "settings": {},
            "usage": {},
            "logs": (),
            "models": {},
        },
    }


def _state_collections(self) -> tuple[tuple[Any, ...], Any]:
    states = _sort_items(self.repository.list_states(), id_field="state_id", time_field="updated_at")
    return states, self.repository.current_state()


def _state_projection_rows(
    states: tuple[Any, ...],
    *,
    current_state: Any,
    install_root: Path | None,
    repository: Any | None = None,
    episodes_by_state: Mapping[str, tuple[Any, ...]] | None = None,
    loops_by_episode: Mapping[str, tuple[Any, ...]] | None = None,
    steps_by_loop: Mapping[str, tuple[Any, ...]] | None = None,
    semantic_index_entries: tuple[Any, ...] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    episode_map = episodes_by_state or {}
    loop_map = loops_by_episode or {}
    step_map = steps_by_loop or {}
    elephant_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    for state in states:
        state_episodes = episode_map.get(state.state_id, ())
        state_loops = tuple(loop for episode in state_episodes for loop in loop_map.get(episode.episode_id, ()))
        state_steps = tuple(step for loop in state_loops for step in step_map.get(loop.loop_id, ()))
        state_index_entries = tuple(entry for entry in semantic_index_entries if getattr(entry, "state_id", None) == state.state_id)
        is_current = bool(current_state is not None and current_state.state_id == state.state_id)
        growth_state = repository.load_personal_model_growth(state.personal_model_id) if repository is not None else None
        growth = build_growth_snapshot(growth_state or default_growth_state(state.personal_model_id))
        elephant_rows.append({
            "elephant_id": state.elephant_id,
            "elephant_name": state.elephant_name,
            "state_id": state.state_id,
            "personal_model_id": state.personal_model_id,
            "profile_id": state.personal_model_id,
            "status": state.status,
            "current": is_current,
            "level": growth.level,
            "checkpoint_label": f"checkpoint {growth.level}",
            "stage": growth.stage.display_name,
            "stage_id": growth.stage.stage_id,
            "progress_percent": growth.progress_percent,
            "score_to_next_level": growth.score_to_next_level,
            "identity_mode": state.identity_mode,
            "initiative": state.initiative,
            "working_style": state.working_style,
            "summary": state.summary,
            "current_context_note": state.current_context_note,
            "elephant_identity_text": state.elephant_identity_text,
            "elephant_identity_file": _elephant_identity_file(
                state.elephant_id,
                install_root=install_root,
                fallback_text=state.elephant_identity_text,
            ),
            "updated_at": _serialize(state).get("updated_at"),
        })
        state_payload = dict(_serialize(state))
        state_payload["current_context_note"] = state.current_context_note
        state_rows.append({
            **state_payload,
            "current": is_current,
            "episode_count": len(state_episodes),
            "loop_count": len(state_loops),
            "step_count": len(state_steps),
            "semantic_index_entry_count": len(state_index_entries),
        })
    return elephant_rows, state_rows


def _personal_model_dashboard_row(model: Any, repository: Any) -> dict[str, Any]:
    row = dict(_serialize(model))
    personal_model_id = str(model.personal_model_id)
    # Derive user_profile directly from active PM facts
    from packages.state.profile_from_claims import derive_profile_from_claims
    facts = _active_personal_model_facts(repository, personal_model_id)
    user_profile = derive_profile_from_claims(facts)
    if user_profile:
        row["user_profile"] = user_profile
        preferred_name = str(user_profile.get("preferred_name") or "").strip()
        if preferred_name:
            row["user_preferred_name"] = preferred_name
    return row


def _personal_model_facts(repository: Any, personal_model_id: str, status: str | tuple[str, ...]) -> tuple[Any, ...]:
    list_facts = getattr(repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    try:
        return tuple(list_facts(personal_model_id=personal_model_id, status=status))
    except Exception:
        return ()


def _active_personal_model_facts(repository: Any, personal_model_id: str) -> tuple[Any, ...]:
    return _personal_model_facts(repository, personal_model_id, "active")


def _personal_model_rows(
    *,
    personal_models: tuple[Any, ...],
    states: tuple[Any, ...],
    semantic_index_entries: tuple[Any, ...],
    repository: Any,
) -> list[dict[str, Any]]:
    states_by_personal_model = {
        model.personal_model_id: tuple(state for state in states if state.personal_model_id == model.personal_model_id)
        for model in personal_models
    }
    rows: list[dict[str, Any]] = []
    for model in personal_models:
        model_index_entries = tuple(entry for entry in semantic_index_entries if entry.personal_model_id == model.personal_model_id)
        model_facts = _active_personal_model_facts(repository, str(model.personal_model_id))
        model_all_facts = _personal_model_facts(repository, str(model.personal_model_id), ("active", "retired", "disputed"))
        rows.append({
            **_personal_model_dashboard_row(model, repository),
            "state_count": len(states_by_personal_model.get(model.personal_model_id, ())),
            "personal_model_fact_count": len(model_facts),
            "semantic_index_entry_count": len(model_index_entries),
            "states": tuple({
                "state_id": state.state_id,
                "elephant_id": state.elephant_id,
                "elephant_name": state.elephant_name,
                "status": state.status,
                "summary": state.summary,
                "current_context_note": state.current_context_note,
                "updated_at": _serialize(state).get("updated_at"),
            } for state in states_by_personal_model.get(model.personal_model_id, ())),
            "understanding_components": _personal_model_lens_summaries(
                model_facts=model_facts,
            ),
            "personal_model_facts": tuple(_serialize(fact) for fact in model_facts),
            "personal_model_all_facts": tuple(_serialize(fact) for fact in model_all_facts),
            "semantic_index_entries": tuple(_serialize(entry) for entry in model_index_entries),
        })
    return rows


def _basic_personal_model_rows(personal_models: tuple[Any, ...], *, repository: Any) -> tuple[dict[str, Any], ...]:
    return tuple(_personal_model_dashboard_row(model, repository) for model in personal_models)


def _runtime_collections(self) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]:
    episodes = _sort_items(self.repository.list_episodes(), id_field="episode_id", time_field="started_at")
    loops = _sort_items(self.repository.list_loops(), id_field="loop_id", time_field="started_at")
    steps = _sort_items(self.repository.list_steps(), id_field="step_id", time_field="created_at")
    return episodes, loops, steps


def _runtime_maps(
    *,
    states: tuple[Any, ...],
    episodes: tuple[Any, ...],
    loops: tuple[Any, ...],
    steps: tuple[Any, ...],
) -> tuple[dict[str, tuple[Any, ...]], dict[str, tuple[Any, ...]], dict[str, tuple[Any, ...]]]:
    episodes_by_state = {state.state_id: tuple(episode for episode in episodes if episode.state_id == state.state_id) for state in states}
    loops_by_episode = {episode.episode_id: tuple(loop for loop in loops if loop.episode_id == episode.episode_id) for episode in episodes}
    steps_by_loop = {loop.loop_id: tuple(step for step in steps if step.loop_id == loop.loop_id) for loop in loops}
    return episodes_by_state, loops_by_episode, steps_by_loop


def _episode_rows(episodes: tuple[Any, ...], loops_by_episode: Mapping[str, tuple[Any, ...]], steps_by_loop: Mapping[str, tuple[Any, ...]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        episode_loops = loops_by_episode.get(episode.episode_id, ())
        episode_steps = tuple(step for loop in episode_loops for step in steps_by_loop.get(loop.loop_id, ()))
        rows.append({**_serialize(episode), "loop_count": len(episode_loops), "step_count": len(episode_steps)})
    return rows


def _loop_rows(loops: tuple[Any, ...], steps_by_loop: Mapping[str, tuple[Any, ...]]) -> list[dict[str, Any]]:
    return [{**_serialize(loop), "step_count": len(steps_by_loop.get(loop.loop_id, ()))} for loop in loops]


def _semantic_index_health(semantic_index_entries: tuple[Any, ...], active_provider: Mapping[str, Any]) -> dict[str, Any]:
    semantic_index_status = str(active_provider.get("embedding_bootstrap_status") or ("indexed" if semantic_index_entries else "empty"))
    return {
        "status": semantic_index_status,
        "entry_count": len(semantic_index_entries),
        "backend_count": len({entry.backend for entry in semantic_index_entries}),
        "provider_ids": tuple(sorted({entry.provider_id for entry in semantic_index_entries})),
        "model_ids": tuple(sorted({entry.model_id for entry in semantic_index_entries})),
        "embedding_bootstrap_status": active_provider.get("embedding_bootstrap_status"),
    }


def _operation_settings(self) -> tuple[dict[str, Any], Mapping[str, Any], Path]:
    database_path = self.repository.database_path
    state_dir = database_path.parent
    settings = _settings(state_dir, database_path)
    global_config = settings.get("globalConfig") if isinstance(settings.get("globalConfig"), Mapping) else {}
    return settings, global_config, state_dir


def _provider_catalog_rows(self, active_provider: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    from dataclasses import asdict

    active_provider_id = str(active_provider.get("provider_id") or "")
    rows: list[dict[str, Any]] = []
    for record in self.model_provider.runtime_resolver.list_catalog():
        row = record.as_mapping()
        provider_id = str(row.get("provider_id") or "")
        if provider_id == active_provider_id:
            row["status"] = active_provider.get("status")
            row["source"] = active_provider.get("source")
        else:
            try:
                discovered_state = asdict(self.model_provider.discovered_provider_state(provider_id))
                row["discovered_state"] = discovered_state
                row["status"] = discovered_state.get("status")
                row["source"] = discovered_state.get("source")
            except Exception:
                pass
        rows.append(row)
    return tuple(rows)


def _operation_model_snapshot(self, *, active_provider: Mapping[str, Any], embedding_provider: Mapping[str, Any]) -> dict[str, Any]:
    provider_keys = self.list_provider_keys()
    return {
        "activeProvider": _dashboard_active_provider(dict(active_provider)),
        "providers": _provider_catalog_rows(self, active_provider),
        "doctor": {"status": active_provider.get("status") or "unknown"},
        "keys": tuple(provider_keys.get("keys", ())),
        "embeddingProvider": dict(embedding_provider),
    }


def _fill_states(dashboard: dict[str, Any], self) -> tuple[tuple[Any, ...], Any]:
    states, current_state = _state_collections(self)
    elephant_rows, state_rows = _state_projection_rows(
        states,
        current_state=current_state,
        install_root=self.config.install_root,
        repository=self.repository,
    )
    dashboard["herd"] = tuple(elephant_rows)
    dashboard["states"] = tuple(state_rows)
    return states, current_state


def _learning_overview(self) -> dict[str, Any]:
    list_jobs = getattr(self.repository, "list_learning_jobs", None)
    jobs = tuple(list_jobs(limit=500)) if callable(list_jobs) else ()
    counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for job in jobs:
        status = str(getattr(job, "status", "") or "").strip().lower()
        if status in counts:
            counts[status] += 1
    job_rows = tuple(
        {
            "job_id": job.job_id,
            "trigger": job.trigger,
            "status": job.status,
            "summary": job.summary,
            "created_at": job.created_at.isoformat() if job.created_at else "",
            "finished_at": job.finished_at.isoformat() if job.finished_at else "",
            "metadata": dict(job.metadata) if job.metadata else {},
        }
        for job in jobs[-50:]
    )
    return {
        "worker": {},
        "summary": {**counts, "total": len(jobs), "active_job_id": None, "latest_completed_at": None},
        "jobs": job_rows,
    }


def _latest_episode_row(self, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
    """Return the most-recent `limit` Episodes as dashboard rows.

    Historically this returned only the single newest Episode, which
    made the dashboard history look like one flat thread even after
    `/clear` had opened a fresh Episode. The dashboard chat page and
    the Console recent-episode summary both expect a list ordered
    newest-first; returning the full recent tail lets them render a
    real timeline.
    """
    episodes = _sort_items(self.repository.list_episodes(), id_field="episode_id", time_field="started_at")
    if not episodes:
        return ()
    recent = episodes[:max(1, int(limit))]
    return tuple(
        {**_serialize(episode), "loop_count": 0, "step_count": 0, "loops": (), "timeline": ()}
        for episode in recent
    )


def _fill_overview(dashboard: dict[str, Any], self) -> None:
    database_path = self.repository.database_path
    states, current_state = _fill_states(dashboard, self)
    personal_models = _sort_items(self.repository.list_personal_models(), id_field="personal_model_id", time_field="updated_at")
    canonical_models = tuple(
        model for model in personal_models if model.personal_model_id == DEFAULT_PERSONAL_MODEL_ID
    )[:1]
    overview_target_models = canonical_models or personal_models[:1]
    current_personal_model_id = DEFAULT_PERSONAL_MODEL_ID
    semantic_index_entries = self.repository.list_semantic_index_entries() if hasattr(self.repository, "list_semantic_index_entries") else ()
    overview_models = tuple(_personal_model_rows(
        personal_models=overview_target_models,
        states=states,
        semantic_index_entries=tuple(semantic_index_entries),
        repository=self.repository,
    ))
    active_provider = dict(self.model_provider.describe())
    learning = _learning_overview(self)
    semantic_index_count = _count_rows(database_path, "semantic_index_entries")
    provider_auth_states = self.repository.list_provider_auth_states() if hasattr(self.repository, "list_provider_auth_states") else ()
    dashboard["personal_models"] = overview_models
    dashboard["runtime"] = {**dashboard["runtime"], "episode_traces": _latest_episode_row(self)}
    dashboard["learning"] = learning
    dashboard["overview"] = {
        "counts": {
            "personal_models": len(overview_target_models),
            "herd": len(states),
            "states": len(states),
            "episodes": _count_rows(database_path, "episodes"),
            "loops": _count_rows(database_path, "loops"),
            "steps": _count_rows(database_path, "steps"),
            "semantic_index_entries": semantic_index_count,
            "provider_auth_states": len(provider_auth_states),
            "learning_jobs": learning["summary"]["total"],
            "learning_jobs_queued": learning["summary"]["queued"],
            "learning_jobs_running": learning["summary"]["running"],
            "learning_jobs_completed": learning["summary"]["completed"],
            "learning_jobs_failed": learning["summary"]["failed"],
        },
        "current_state_id": current_state.state_id if current_state is not None else None,
        "current_personal_model_id": current_personal_model_id,
        "provider_status": str(active_provider.get("status") or "unknown"),
        "semantic_index_status": str(active_provider.get("embedding_bootstrap_status") or ("indexed" if semantic_index_count else "empty")),
        "note": "Overview fetches counts, current elephant, current PersonalModel identity, and latest Episode summary only.",
    }


def _fill_personal_models(dashboard: dict[str, Any], self) -> None:
    states, _ = _state_collections(self)
    personal_models = _sort_items(self.repository.list_personal_models(), id_field="personal_model_id", time_field="updated_at")
    canonical_models = tuple(model for model in personal_models if model.personal_model_id == DEFAULT_PERSONAL_MODEL_ID)
    dashboard["personal_models"] = tuple(_personal_model_rows(
        personal_models=canonical_models or personal_models[:1],
        states=states,
        semantic_index_entries=_sort_items(self.repository.list_semantic_index_entries(), id_field="semantic_index_entry_id", time_field="updated_at"),
        repository=self.repository,
    ))


def _fill_runtime(dashboard: dict[str, Any], self) -> None:
    """History page: recent episode traces (capped at 10 episodes for traces)."""
    states, current_state = _state_collections(self)
    all_episodes = _sort_items(self.repository.list_episodes(), id_field="episode_id", time_field="started_at")
    # Full trace only for 10 most recent episodes
    recent_episodes = all_episodes[:10]
    recent_loops: list[Any] = []
    for ep in recent_episodes:
        recent_loops.extend(self.repository.list_loops(episode_id=ep.episode_id))
    recent_loops_tuple = tuple(recent_loops)
    recent_steps: list[Any] = []
    for loop in recent_loops_tuple:
        recent_steps.extend(self.repository.list_steps(loop_id=loop.loop_id))
    recent_steps_tuple = tuple(recent_steps)
    loops_by_episode = {ep.episode_id: tuple(loop for loop in recent_loops_tuple if loop.episode_id == ep.episode_id) for ep in recent_episodes}
    steps_by_loop = {loop.loop_id: tuple(step for step in recent_steps_tuple if step.loop_id == loop.loop_id) for loop in recent_loops_tuple}
    elephant_rows, state_rows = _state_projection_rows(
        states,
        current_state=current_state,
        install_root=self.config.install_root,
        repository=self.repository,
    )
    dashboard["herd"] = tuple(elephant_rows)
    dashboard["states"] = tuple(state_rows)
    dashboard["runtime"] = {
        "episodes": tuple(_episode_rows(all_episodes, loops_by_episode, steps_by_loop)),
        "episode_traces": _runtime_traces(episodes=recent_episodes, loops_by_episode=loops_by_episode, steps_by_loop=steps_by_loop, source_payloads={}),
        "learning_jobs": (),
    }


def _fill_reflect(dashboard: dict[str, Any], self) -> None:
    """Lightweight reflect section: only learning jobs + worker state."""
    states, current_state = _state_collections(self)
    episodes = _sort_items(self.repository.list_episodes(), id_field="episode_id", time_field="started_at")
    learning = _learning_snapshot(
        self,
        state_dir=self.repository.database_path.parent,
        states_by_id={state.state_id: state for state in states},
        episodes_by_id={episode.episode_id: episode for episode in episodes},
    )
    dashboard["learning"] = learning
    dashboard["runtime"] = {"learning_jobs": learning["jobs"]}


def _fill_chat(dashboard: dict[str, Any], self) -> None:
    states, current_state = _state_collections(self)
    episodes, loops, steps = _runtime_collections(self)
    _, loops_by_episode, steps_by_loop = _runtime_maps(states=states, episodes=episodes, loops=loops, steps=steps)
    elephant_rows, state_rows = _state_projection_rows(
        states,
        current_state=current_state,
        install_root=self.config.install_root,
        repository=self.repository,
    )
    personal_models = tuple(
        model
        for model in _sort_items(self.repository.list_personal_models(), id_field="personal_model_id", time_field="updated_at")
        if model.personal_model_id == DEFAULT_PERSONAL_MODEL_ID
    )
    dashboard["herd"] = tuple(elephant_rows)
    dashboard["states"] = tuple(state_rows)
    dashboard["personal_models"] = _basic_personal_model_rows(personal_models, repository=self.repository)
    dashboard["runtime"] = {**dashboard["runtime"], "episode_traces": _runtime_traces(episodes=episodes, loops_by_episode=loops_by_episode, steps_by_loop=steps_by_loop, source_payloads={})}
    dashboard["overview"] = {**dashboard["overview"], "current_state_id": current_state.state_id if current_state is not None else None, "current_personal_model_id": current_state.personal_model_id if current_state is not None else DEFAULT_PERSONAL_MODEL_ID}


def _fill_evidence(dashboard: dict[str, Any], self) -> None:
    # Steps, Episodes, and Facts own evidence. This section only exposes the
    # shared semantic index that makes those rows searchable.
    semantic_index_entries = _sort_items(self.repository.list_semantic_index_entries(), id_field="semantic_index_entry_id", time_field="updated_at")
    active_provider = dict(self.model_provider.describe())
    dashboard["evidence"] = {
        "semantic_index_entries": tuple(_serialize(entry) for entry in semantic_index_entries),
    }
    dashboard["semantic_index_health"] = _semantic_index_health(semantic_index_entries, active_provider)


def _fill_questions(dashboard: dict[str, Any], self) -> None:
    """Populate the Personal Model Questions section.

    This section exposes lens/topic-bound questions and their resulting
    claims. Active claims remain on the You page; raw support material stays
    behind Evidence inspection.
    """
    repository = self.repository
    personal_model_id = DEFAULT_PERSONAL_MODEL_ID
    ensure_default = getattr(repository, "ensure_default_personal_model", None)
    if callable(ensure_default):
        try:
            ensure_default(personal_model_id=personal_model_id)
        except Exception:
            pass
    facts: tuple = ()
    waiting_questions: tuple = ()
    asked_questions: tuple = ()
    answered_questions: tuple = ()
    dismissed_questions: tuple = ()
    lens_coverage: list[dict[str, Any]] = []
    learning_intensity = "medium"

    list_facts = getattr(repository, "list_personal_model_facts", None)
    if callable(list_facts):
        try:
            facts = tuple(list_facts(personal_model_id=personal_model_id, status="active"))
        except Exception:
            facts = ()

    list_questions = getattr(repository, "list_open_questions", None)
    if callable(list_questions):
        try:
            waiting_questions = tuple(list_questions(personal_model_id=personal_model_id, status="open"))
        except Exception:
            waiting_questions = ()
        try:
            asked_questions = tuple(list_questions(personal_model_id=personal_model_id, status="asked"))
        except Exception:
            asked_questions = ()
        try:
            answered_questions = tuple(list_questions(personal_model_id=personal_model_id, status="answered"))
        except Exception:
            answered_questions = ()
        try:
            dismissed_questions = tuple(list_questions(personal_model_id=personal_model_id, status="dismissed"))
        except Exception:
            dismissed_questions = ()

    question_config = _dashboard_question_config(repository)
    configured_intensity = str(question_config.get("learning_intensity") or "").strip().lower()
    if configured_intensity in {"low", "medium", "high"}:
        learning_intensity = configured_intensity
    effective_policy = _effective_question_policy(learning_intensity, question_config)

    # Coverage grid — one row per (lens, facet) with durable Fact counts.
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in facts:
        key = (str(getattr(fact, "lens", "") or ""), str(getattr(fact, "facet", "") or ""))
        row = by_key.setdefault(key, {"lens": key[0], "facet": key[1], "facts": 0})
        row["facts"] += 1
    for row in by_key.values():
        row["covered"] = row["facts"] > 0
        lens_coverage.append(row)
    lens_coverage.sort(key=lambda r: (r["lens"], r["facet"]))

    # Build an index so the dashboard can show the resulting claims next to
    # each answered question.
    facts_by_id: dict[str, Any] = {}
    for fact in facts:
        fid = str(getattr(fact, "fact_id", "") or "")
        if fid:
            facts_by_id[fid] = fact

    def _serialize_question(question: Any) -> dict[str, Any]:
        payload = dict(_serialize(question))
        generated_ids = getattr(question, "generated_fact_ids", ()) or ()
        resulting: list[dict[str, Any]] = []
        for fid in generated_ids:
            fact = facts_by_id.get(str(fid))
            if fact is not None:
                resulting.append(dict(_serialize(fact)))
        if resulting:
            payload["resulting_facts"] = tuple(resulting)
        return payload

    dashboard["questions"] = {
        "facts": tuple(_serialize(fact) for fact in facts),
        "waiting_questions": tuple(_serialize_question(q) for q in waiting_questions),
        "asked_questions": tuple(_serialize_question(q) for q in asked_questions),
        "answered_questions": tuple(_serialize_question(q) for q in answered_questions),
        "dismissed_questions": tuple(_serialize_question(q) for q in dismissed_questions),
        "lens_coverage": tuple(lens_coverage),
        "learning_intensity": learning_intensity,
        "question_config": _serialize(question_config),
        "effective_policy": effective_policy,
    }


def _dashboard_question_config(repository) -> dict[str, Any]:
    try:
        from packages.runtime_config import (
            personal_model_question_config_from_global,
            global_config_path_for_state_dir,
            load_global_config,
        )
        state_dir = repository.database_path.parent
        config = load_global_config(
            global_config_path_for_state_dir(state_dir),
            state_dir=state_dir,
        )
        return personal_model_question_config_from_global(config)
    except Exception:  # pragma: no cover
        return {}


def _effective_question_policy(learning_intensity: str, question_config: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve effective proactive ask policy from config.

    The new config format uses direct numeric fields under personal_model_questions.proactive_ask:
      enabled, idle_threshold_minutes, daily_max, quiet_hours.
    Falls back to tier-based defaults for migration.
    """
    proactive = question_config.get("proactive_ask") if isinstance(question_config, Mapping) else None
    if not isinstance(proactive, Mapping):
        proactive = {}
    enabled = proactive.get("enabled") is not False and question_config.get("enabled") is not False
    idle_threshold_minutes = int(proactive.get("idle_threshold_minutes") or 180)
    daily_max = int(proactive.get("daily_max") or 8)
    quiet_hours = proactive.get("quiet_hours")
    if isinstance(quiet_hours, (list, tuple)) and len(quiet_hours) == 2:
        quiet_start, quiet_end = int(quiet_hours[0]) % 24, int(quiet_hours[1]) % 24
    else:
        quiet_start, quiet_end = 23, 7
    return {
        "enabled": enabled,
        "idle_threshold_minutes": idle_threshold_minutes,
        "daily_max": daily_max,
        "quiet_hours_start_local": quiet_start,
        "quiet_hours_end_local": quiet_end,
    }


def _fill_providers(dashboard: dict[str, Any], self) -> None:
    active_provider = dict(self.model_provider.describe())
    embedding_provider = dict(self.embedding_provider_summary())
    dashboard["providers"] = {
        "active_provider": _serialize(_dashboard_active_provider(active_provider)),
        "doctor": {"status": active_provider.get("status") or "unknown"},
        "embedding_provider": _serialize(embedding_provider),
        "auth_states": (),
    }
    dashboard["operations"] = {
        **dashboard["operations"],
        "models": _operation_model_snapshot(self, active_provider=active_provider, embedding_provider=embedding_provider),
    }


def _skills_settings(settings: Mapping[str, Any], global_config: Mapping[str, Any]) -> dict[str, Any]:
    skills_config = global_config.get("skills") if isinstance(global_config.get("skills"), Mapping) else {}
    return {
        "globalConfigPath": settings.get("globalConfigPath", ""),
        "globalConfig": {"skills": dict(skills_config)},
    }


def _skill_affinity_rows(self) -> tuple[dict[str, Any], ...]:
    list_models = getattr(self.repository, "list_personal_models", None)
    if not callable(list_models):
        return ()
    personal_models = _sort_items(list_models(), id_field="personal_model_id", time_field="updated_at")
    canonical_models = tuple(model for model in personal_models if model.personal_model_id == DEFAULT_PERSONAL_MODEL_ID)
    target_model = (canonical_models or personal_models[:1])
    if not target_model:
        return ()
    personal_model_id = str(target_model[0].personal_model_id)
    facts = _personal_model_facts(self.repository, personal_model_id, ("active", "retired", "disputed"))
    slots: dict[str, dict[str, Any]] = {}
    for fact in facts:
        metadata = dict(getattr(fact, "metadata", {}) or {})
        topic = str(metadata.get("topic") or "").strip()
        if not is_skill_affinity_topic(topic):
            continue
        row = slots.setdefault(
            topic,
            {
                "topic": topic,
                "skillId": str(metadata.get("skill_id") or "").strip(),
                "indexId": str(metadata.get("index_id") or skill_affinity_index_id(topic)).strip(),
                "activeCount": 0,
                "retiredCount": 0,
                "disputedCount": 0,
                "latestText": "",
                "latestMetadata": {},
            },
        )
        status = str(getattr(fact, "status", "") or "active")
        if status == "retired":
            row["retiredCount"] = int(row["retiredCount"]) + 1
        elif status == "disputed":
            row["disputedCount"] = int(row["disputedCount"]) + 1
        else:
            row["activeCount"] = int(row["activeCount"]) + 1
        if not row["skillId"]:
            row["skillId"] = str(metadata.get("skill_id") or "").strip()
        row["latestText"] = str(getattr(fact, "text", "") or "")
        row["latestMetadata"] = {str(key): str(value) for key, value in metadata.items()}
    return tuple(
        sorted(
            slots.values(),
            key=lambda row: (-int(row["activeCount"]), str(row["skillId"] or row["indexId"] or row["topic"])),
        )
    )


def _tools_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    return {"globalConfigPath": settings.get("globalConfigPath", "")}


def _fill_skills(dashboard: dict[str, Any], self) -> None:
    settings, global_config, state_dir = _operation_settings(self)
    skill_overrides = _profile_overrides(state_dir, "skill_overrides")
    dashboard["operations"] = {
        **dashboard["operations"],
        "skills": tuple(_skills(self, skill_overrides=skill_overrides, global_config=global_config)),
        "skill_affinities": _skill_affinity_rows(self),
        "settings": _skills_settings(settings, global_config),
    }


def _fill_tools(dashboard: dict[str, Any], self) -> None:
    settings, global_config, state_dir = _operation_settings(self)
    tool_overrides = _profile_overrides(state_dir, "tool_overrides")
    dashboard["operations"] = {
        **dashboard["operations"],
        "tools": tuple(_tools(self, tool_overrides=tool_overrides)),
        "mcp": _mcp_catalog(config_path=Path(settings["globalConfigPath"]), config=global_config),
        "settings": _tools_settings(settings),
    }


def _fill_gateway(dashboard: dict[str, Any], self) -> None:
    database_path = self.repository.database_path
    dashboard["operations"] = {
        **dashboard["operations"],
        "gateway": _gateway(database_path.parent),
    }


def _fill_cron(dashboard: dict[str, Any], self) -> None:
    _fill_states(dashboard, self)
    dashboard["operations"] = {**dashboard["operations"], "cron": {"jobs": tuple(_cron_jobs(self))}}


def _fill_settings(dashboard: dict[str, Any], self) -> None:
    settings, _, _ = _operation_settings(self)
    dashboard["operations"] = {**dashboard["operations"], "settings": settings}


def _fill_usage(dashboard: dict[str, Any], self) -> None:
    dashboard["operations"] = {**dashboard["operations"], "usage": _canonical_usage(self.repository.database_path)}


def _fill_logs(dashboard: dict[str, Any], self) -> None:
    dashboard["operations"] = {**dashboard["operations"], "logs": tuple(_logs(self.repository.database_path.parent))}


def _fill_diary(dashboard: dict[str, Any], self) -> None:
    try:
        pm = self.repository.ensure_default_personal_model()
        entries = self.repository.list_diary_entries(personal_model_id=pm.personal_model_id, limit=30)
    except Exception:
        entries = ()
    dashboard["diary"] = {
        "entries": tuple(
            {
                "entry_id": e.entry_id,
                "entry_date": e.entry_date,
                "content": e.content,
                "generated_at": e.generated_at.isoformat() if e.generated_at else "",
            }
            for e in entries
        ),
    }


def inspect_internal_dashboard(self, section: str) -> dict[str, Any]:
    normalized_section = section.strip().lower()
    if normalized_section not in DASHBOARD_SECTIONS:
        raise KeyError(normalized_section)
    dashboard = _empty_dashboard(self, section=normalized_section, generated_at=_now())
    if normalized_section == "overview":
        _fill_overview(dashboard, self)
    elif normalized_section == "personal-models":
        _fill_personal_models(dashboard, self)
    elif normalized_section == "herd":
        _fill_states(dashboard, self)
    elif normalized_section == "runtime":
        _fill_runtime(dashboard, self)
    elif normalized_section == "chat":
        _fill_chat(dashboard, self)
    elif normalized_section == "questions":
        _fill_questions(dashboard, self)
    elif normalized_section == "evidence":
        _fill_evidence(dashboard, self)
    elif normalized_section == "providers":
        _fill_providers(dashboard, self)
    elif normalized_section == "skills":
        _fill_skills(dashboard, self)
    elif normalized_section == "tools":
        _fill_tools(dashboard, self)
    elif normalized_section == "gateway":
        _fill_gateway(dashboard, self)
    elif normalized_section == "cron":
        _fill_cron(dashboard, self)
    elif normalized_section == "reflect":
        _fill_reflect(dashboard, self)
    elif normalized_section == "settings":
        _fill_settings(dashboard, self)
    elif normalized_section == "usage":
        _fill_usage(dashboard, self)
    elif normalized_section == "logs":
        _fill_logs(dashboard, self)
    elif normalized_section == "usage-logs":
        _fill_usage(dashboard, self)
        _fill_logs(dashboard, self)
    elif normalized_section == "diary":
        _fill_diary(dashboard, self)
    return dashboard


__all__ = ["DASHBOARD_SECTIONS", "inspect_internal_dashboard", "trigger_diary_write", "trigger_reflect_job"]
