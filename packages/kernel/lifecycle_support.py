"""System-layer lifecycle helpers for kernel orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping

from packages.contracts.layers import Episode, Loop, PersonalModel, State, Step
from packages.contracts.runtime import ContextBundle, ExecutionResult, PromptMessage

from .runtime_support import KernelSourceRequest, KernelStoragePort


@dataclass(frozen=True, slots=True)
class KernelRuntimeIdentity:
    personal_model: PersonalModel
    state: State


@dataclass(frozen=True, slots=True)
class KernelEpisodeLifecycle:
    episode: Episode
    close_on_completion: bool
    idle_closed_episodes: tuple[Episode, ...] = ()
    is_new_episode: bool = False


@dataclass(frozen=True, slots=True)
class KernelLoopLifecycle:
    loop: Loop


class KernelStepRecorder:
    def __init__(self, storage: KernelStoragePort, loop: Loop, *, semantic_summary_indexer: object | None = None) -> None:
        self._storage = storage
        self._loop = loop
        self._semantic_summary_indexer = semantic_summary_indexer
        self._steps = list(storage.list_steps(loop_id=loop.loop_id))

    @property
    def steps(self) -> tuple[Step, ...]:
        return tuple(self._steps)

    def record(
        self,
        *,
        phase: str,
        action: str,
        status: str,
        current: datetime,
        summary: str = "",
        outcome: str = "",
        payload_refs: tuple[str, ...] = (),
        metadata: Mapping[str, str] | None = None,
    ) -> Step:
        step = Step(
            step_id=f"step:{self._loop.loop_id}:{len(self._steps)}",
            loop_id=self._loop.loop_id,
            episode_id=self._loop.episode_id,
            state_id=self._loop.state_id,
            personal_model_id=self._loop.personal_model_id,
            phase=phase,
            action=action,
            status=status,
            sequence=len(self._steps),
            created_at=current,
            summary=summary,
            outcome=outcome,
            payload_refs=payload_refs,
            metadata=metadata or {},
        )
        self._storage.upsert_step(step)
        index_step = getattr(self._semantic_summary_indexer, "index_step", None)
        if callable(index_step):
            try:
                index_step(step)
            except Exception:
                pass
        self._steps.append(step)
        return step


def initial_turn_messages(prompt: str) -> tuple[PromptMessage, ...]:
    normalized = prompt.strip()
    if not normalized:
        return ()
    return (PromptMessage(role="user", content=normalized),)


def assistant_turn_messages(execution: ExecutionResult) -> tuple[PromptMessage, ...]:
    summary = execution.summary.strip()
    if not summary:
        return ()
    return (PromptMessage(role="assistant", content=summary),)


def context_with_turn_messages(context: ContextBundle, turn_messages: tuple[PromptMessage, ...]) -> ContextBundle:
    if not turn_messages:
        return context
    return replace(
        context,
        prompt_envelope=replace(
            context.prompt_envelope,
            messages=(*context.prompt_envelope.messages, *turn_messages),
        ),
    )


def resolve_runtime_identity(
    storage: KernelStoragePort,
    request: KernelSourceRequest,
    *,
    current: datetime,
) -> KernelRuntimeIdentity:
    if request.state_id is not None:
        state = storage.load_state(request.state_id)
        if state is None:
            raise KeyError(f"unknown state: {request.state_id}")
        if request.personal_model_id is not None and state.personal_model_id != request.personal_model_id:
            raise ValueError(
                f"state {state.state_id} belongs to PersonalModel {state.personal_model_id}, "
                f"not {request.personal_model_id}"
            )
        personal_model = storage.ensure_default_personal_model(personal_model_id=state.personal_model_id)
        storage.switch_state(state.state_id, selected_at=current)
        return KernelRuntimeIdentity(personal_model=personal_model, state=state)

    personal_model = storage.ensure_default_personal_model(
        personal_model_id=request.personal_model_id or "you"
    )
    state = storage.current_state()
    if state is None or state.personal_model_id != personal_model.personal_model_id:
        state = storage.create_state(
            personal_model_id=personal_model.personal_model_id,
            elephant_id="default",
            elephant_name="Default",
            state_id=f"state-{personal_model.personal_model_id}-default",
            state_anchor="elephant:default",
            surface_bindings=(request.surface,),
            metadata={"source": "kernel.default_state"},
        )
        storage.switch_state(state.state_id, selected_at=current)
    return KernelRuntimeIdentity(personal_model=personal_model, state=state)


def _episode_policy(request: KernelSourceRequest) -> str:
    if request.episode_policy != "auto":
        return request.episode_policy
    if request.surface == "cli" or request.surface.startswith("cli."):
        return "session_managed"
    if request.surface.startswith("gateway:"):
        return "gateway_idle_reuse"
    return "single_turn"


def _continuation_note_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _episode_resume_metadata(state: State) -> dict[str, str]:
    note = _continuation_note_text(state.current_context_note)
    if not note:
        return {}
    return {
        "opening_resume_snapshot": note,
        "opening_resume_source": "state.current_context_note",
        "opening_resume_state_id": state.state_id,
    }


def _episode_metadata(
    request: KernelSourceRequest,
    *,
    policy: str,
    current: datetime,
    state: State,
) -> dict[str, str]:
    return {
        "policy": policy,
        "route_id": request.route_id,
        "surface": request.surface,
        "last_activity_at": current.isoformat(),
        **_episode_resume_metadata(state),
    }


def _parse_episode_activity(episode: Episode) -> datetime | None:
    # Prefer the first-class updated_at field; fall back to metadata for legacy rows
    if episode.updated_at is not None:
        return episode.updated_at
    value = episode.metadata.get("last_activity_at")
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _ensure_opening_resume_snapshot(episode: Episode, state: State) -> Episode:
    if episode.metadata.get("opening_resume_snapshot"):
        return episode
    metadata = _episode_resume_metadata(state)
    if not metadata:
        return episode
    return replace(episode, metadata={**dict(episode.metadata), **metadata})


def _new_episode(
    request: KernelSourceRequest,
    identity: KernelRuntimeIdentity,
    *,
    policy: str,
    current: datetime,
) -> Episode:
    return Episode(
        episode_id=request.episode_id or f"episode:{request.request_id}",
        state_id=identity.state.state_id,
        personal_model_id=identity.personal_model.personal_model_id,
        entry_surface=request.surface,
        status="open",
        started_at=current,
        updated_at=current,
        elephant_id=identity.state.elephant_id or "",
        metadata=_episode_metadata(request, policy=policy, current=current, state=identity.state),
    )


def open_episode_lifecycle(
    storage: KernelStoragePort,
    request: KernelSourceRequest,
    identity: KernelRuntimeIdentity,
    *,
    current: datetime,
) -> KernelEpisodeLifecycle:
    policy = _episode_policy(request)
    if request.episode_id is not None:
        loaded = storage.load_episode(request.episode_id)
        is_new = loaded is None
        episode = loaded or _new_episode(
            request,
            identity,
            policy=policy,
            current=current,
        )
        if loaded is not None and loaded.status == "closed":
            raise ValueError(f"closed episode cannot be reopened: {loaded.episode_id}")
        episode = _ensure_opening_resume_snapshot(episode, identity.state)
        # First turn: episode was just created or has never been updated
        # beyond its initial creation (started_at == updated_at).
        if not is_new and episode.started_at is not None and episode.updated_at is not None:
            is_new = episode.started_at == episode.updated_at
        storage.upsert_episode(episode)
        return KernelEpisodeLifecycle(episode=episode, close_on_completion=policy == "single_turn", is_new_episode=is_new)

    idle_closed: list[Episode] = []
    if policy == "gateway_idle_reuse":
        for episode in reversed(storage.list_episodes(state_id=identity.state.state_id)):
            if episode.status != "open" or episode.metadata.get("policy") != policy:
                continue
            if episode.metadata.get("route_id") != request.route_id or episode.entry_surface != request.surface:
                continue
            last_activity = _parse_episode_activity(episode) or episode.started_at
            idle_seconds = max(0.0, (current - last_activity).total_seconds())
            if idle_seconds <= request.episode_reuse_idle_seconds:
                refreshed = replace(
                    episode,
                    updated_at=current,
                    metadata={**dict(episode.metadata), "last_activity_at": current.isoformat()},
                )
                storage.upsert_episode(refreshed)
                return KernelEpisodeLifecycle(episode=refreshed, close_on_completion=False)
            from .episode_state_machine import close_episode

            closed = close_episode(
                storage,
                episode.episode_id,
                reason="idle_timeout",
                summary="closed after gateway idle timeout",
                current=current,
            )
            idle_closed.append(closed)

    episode = _new_episode(request, identity, policy=policy, current=current)
    storage.upsert_episode(episode)
    return KernelEpisodeLifecycle(
        episode=episode,
        close_on_completion=policy == "single_turn",
        idle_closed_episodes=tuple(idle_closed),
        is_new_episode=True,
    )


def open_loop_lifecycle(
    storage: KernelStoragePort,
    request: KernelSourceRequest,
    identity: KernelRuntimeIdentity,
    episode: Episode,
    *,
    current: datetime,
) -> KernelLoopLifecycle:
    loop = Loop(
        loop_id=request.loop_id or f"loop:{request.request_id}",
        episode_id=episode.episode_id,
        state_id=identity.state.state_id,
        personal_model_id=identity.personal_model.personal_model_id,
        trigger_type=request.source_event_type,
        status="active",
        started_at=current,
        metadata={"surface": request.surface, "route_id": request.route_id},
    )
    storage.upsert_loop(loop)
    return KernelLoopLifecycle(loop=loop)


def close_loop_lifecycle(
    storage: KernelStoragePort,
    lifecycle: KernelLoopLifecycle,
    *,
    summary: str,
    outcome: str,
    current: datetime,
) -> Loop:
    if outcome == "paused":
        status = "paused"
    elif outcome == "failed":
        status = "failed"
    else:
        status = "completed"
    loop = replace(
        lifecycle.loop,
        status=status,
        ended_at=current,
        summary=summary,
        outcome=outcome,
    )
    storage.upsert_loop(loop)
    return loop


def close_episode_lifecycle(
    storage: KernelStoragePort,
    lifecycle: KernelEpisodeLifecycle,
    *,
    summary: str,
    current: datetime,
    semantic_summary_indexer: object | None = None,
) -> Episode:
    if not lifecycle.close_on_completion:
        refreshed = replace(
            lifecycle.episode,
            updated_at=current,
            metadata={**dict(lifecycle.episode.metadata), "last_activity_at": current.isoformat()},
        )
        storage.upsert_episode(refreshed)
        return refreshed
    closed = replace(
        lifecycle.episode,
        status="closed",
        ended_at=current,
        updated_at=current,
        exit_summary=summary,
        metadata={**dict(lifecycle.episode.metadata), "closed_reason": "final_response"},
    )
    storage.upsert_episode(closed)
    # Push the exit summary into the semantic index so future episodes can
    # recall it. Best-effort: indexer returns None on any failure.
    if semantic_summary_indexer is not None:
        index_exit = getattr(semantic_summary_indexer, "index_episode_exit", None)
        if callable(index_exit):
            try:
                index_exit(closed)
            except Exception:
                pass
    return closed
