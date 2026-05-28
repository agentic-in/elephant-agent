"""Loop execution and HTTP dispatch methods for the API runtime app."""

from __future__ import annotations

from collections.abc import Iterator
import json
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, Mapping
from urllib.parse import unquote
from uuid import uuid4

from packages.context import (
    next_session_context_epoch,
)
from packages.context.epoch_store import FileEpochStore
from packages.contracts import EventEnvelope, ExecutionResult
from packages.kernel import KernelSourceRequest, ReconciliationPipeline, StateReconciler
from packages.models.reasoning_parser import split_reasoning_and_content
from packages.operator.runtime import RecallEvidenceOperatorDetail

from .api_runtime_support import (
    APILoopRecord,
    APILoopResult,
    APIResponse,
    _jsonable,
    _now,
    _optional_str,
    _read_json_bytes,
    _split_path,
)
from .api_runtime_routes import (
    API_HEALTH_ROUTE,
    API_ROUTE_EPISODES,
    API_ROUTE_HERD,
    API_ROUTE_INTERNAL,
    API_ROUTE_OPERATOR,
    API_ROUTE_PATHS,
    API_ROUTE_PROVIDERS,
    API_ROUTE_STATES,
)
from .api_runtime_http_dispatch_helpers import (
    _cron_job_system_kind,
    _cron_payload,
    _cron_skill_ids,
    _cron_job_record,
    _read_wsgi_body,
)
from .api_runtime_personal_model_methods import (
    _dispatch_personal_model,
    _persist_proactive_ask_config,
)
from .api_runtime_context_compression import (
    compact_context_after_usage as _compact_context_after_usage,
)
from .api_runtime_elephants import _dispatch_elephants
from .api_runtime_paths import _dispatch_paths

_STREAM_KEEPALIVE_SECONDS = 15.0
_STREAM_CLARIFY_TIMEOUT_SECONDS = 600.0


class _StreamingClarifySurface:
    """Clarify surface that lets HTTP stream clients answer inline."""

    def __init__(
        self,
        *,
        episode_id: str,
        enqueue,
        pending: dict[str, tuple[str, Queue[str]]],
        pending_lock: Lock,
        timeout_seconds: float = _STREAM_CLARIFY_TIMEOUT_SECONDS,
    ) -> None:
        self.episode_id = episode_id
        self.enqueue = enqueue
        self.pending = pending
        self.pending_lock = pending_lock
        self.timeout_seconds = timeout_seconds

    def request_clarification(
        self,
        *,
        session_id: str,
        question: str,
        mode: str,
        choices: tuple[str, ...] = (),
    ) -> ExecutionResult:
        clarify_id = f"clarify-{uuid4().hex[:12]}"
        response_queue: Queue[str] = Queue(maxsize=1)
        with self.pending_lock:
            self.pending[clarify_id] = (self.episode_id, response_queue)
        self.enqueue(
            {
                "type": "clarify.requested",
                "event_type": "tool_execute",
                "id": clarify_id,
                "clarify_id": clarify_id,
                "name": "tool.clarify",
                "tool_name": "tool.clarify",
                "status": "needs_input",
                "question": question,
                "mode": mode,
                "choices": list(choices),
                "arguments": {
                    "question": question,
                    "mode": mode,
                    "choices": list(choices),
                },
                "tool_arguments": {
                    "question": question,
                    "mode": mode,
                    "choices": list(choices),
                },
                "result": "",
                "tool_result": "",
            }
        )
        try:
            try:
                answer = response_queue.get(timeout=self.timeout_seconds)
            except Empty:
                answer = (
                    "The user did not provide a response within the time limit. "
                    "Use your best judgement to make the choice and proceed."
                )
                self.enqueue(
                    {
                        "type": "clarify.expired",
                        "event_type": "tool_execute",
                        "id": clarify_id,
                        "clarify_id": clarify_id,
                        "name": "tool.clarify",
                        "tool_name": "tool.clarify",
                        "status": "timed_out",
                        "question": question,
                        "mode": mode,
                        "choices": list(choices),
                    }
                )
            return ExecutionResult(
                execution_id=f"clarify:{session_id}:{uuid4().hex[:8]}",
                episode_id=session_id,
                outcome="success",
                summary="\n".join(
                    [
                        f"question: {question}",
                        f"mode: {mode}",
                        f"user_response: {answer}",
                    ]
                ),
                side_effects=("clarify",),
            )
        finally:
            with self.pending_lock:
                self.pending.pop(clarify_id, None)


def _clarify_pending_state(self) -> tuple[dict[str, tuple[str, Queue[str]]], Lock]:
    pending = getattr(self, "_clarify_pending", None)
    pending_lock = getattr(self, "_clarify_pending_lock", None)
    if not isinstance(pending, dict) or pending_lock is None:
        pending = {}
        pending_lock = Lock()
        self._clarify_pending = pending
        self._clarify_pending_lock = pending_lock
    return pending, pending_lock


def _submit_stream_clarification(self, *, episode_id: str, clarify_id: str, answer: str) -> dict[str, str]:
    cleaned = answer.strip()
    if not cleaned:
        raise ValueError("clarification answer is required")
    pending, pending_lock = _clarify_pending_state(self)
    with pending_lock:
        entry = pending.get(clarify_id)
    if entry is None:
        raise KeyError(clarify_id)
    pending_episode_id, response_queue = entry
    if pending_episode_id != episode_id:
        raise KeyError(clarify_id)
    try:
        response_queue.put_nowait(cleaned)
    except Exception as error:
        raise ValueError("clarification was already answered") from error
    return {"episode_id": episode_id, "clarify_id": clarify_id, "status": "submitted"}


def _update_episode_todo(self, *, episode_id: str, item_id: str, status: str) -> dict[str, Any]:
    cleaned_item_id = item_id.strip()
    if not cleaned_item_id:
        raise ValueError("todo item_id is required")
    normalized_status = status.strip().lower()
    if normalized_status not in {"open", "done"}:
        raise ValueError("todo status must be open or done")
    action = "complete" if normalized_status == "done" else "reopen"
    result = self.tool_runtime.invoke(
        "tool.todo.manage",
        {"action": action, "item_id": cleaned_item_id},
        session_id=episode_id,
        requester="operator",
    )
    return {
        "episode_id": episode_id,
        "todo": {"item_id": cleaned_item_id, "status": normalized_status},
        "execution": _jsonable(result),
    }

def run_loop(
    self,
    episode_id: str,
    *,
    prompt: str,
    state_query: str | None = None,
    tool_name: str | None = None,
    tool_arguments: Mapping[str, Any] | None = None,
    delivery_payload: Mapping[str, Any] | None = None,
    source_event_type: str = "loop.received",
) -> APILoopResult:
    episode = self.repository.load_episode_state(episode_id)
    if episode is None:
        raise KeyError(episode_id)
    if episode.status == "closed":
        raise ValueError(f"cannot send to a closed episode: {episode_id}")
    personal_model = self.repository.load_personal_model_runtime_state(episode.personal_model_id)
    if personal_model is None:
        raise KeyError(episode.personal_model_id)
    stored_episode = self.repository.load_episode(episode_id)
    route_state = self.repository.load_state(stored_episode.state_id) if stored_episode is not None else None
    event = EventEnvelope(
        event_id=f"api:{episode_id}:loop:{uuid4().hex}",
        event_type=source_event_type,
        episode_id=episode_id,
        source="api",
        payload={
            "message": prompt,
            "content": prompt,
            "summary": prompt,
            "state_query": state_query or "",
            "tool_name": tool_name or "",
        },
    )
    outcome = self.kernel.run(
        KernelSourceRequest(
            route_id=episode_id,
            prompt=prompt,
            surface="api",
            source_event_type=source_event_type,
            source_payload=dict(event.payload),
            source_event_id=event.event_id,
            route_profile_id=episode.personal_model_id,
            route_status=episode.status,
            route_interruption_state=episode.interruption_state,
            route_started_at=episode.started_at,
            personal_model_id=route_state.personal_model_id if route_state is not None else episode.personal_model_id,
            state_id=route_state.state_id if route_state is not None else None,
            episode_id=episode.episode_id,
            episode_policy="api_session",
            state_query=state_query,
            tool_name=tool_name,
            tool_arguments=dict(tool_arguments or {}),
            delivery_payload=dict(delivery_payload or {}),
        )
    )
    observation = ReconciliationPipeline().observe_turn(
        inbound_event=event,
        execution=outcome.execution,
        decision_summary=outcome.state.summary or outcome.execution.summary,
        source="api",
        profile_id=episode.personal_model_id,
        elephant_id=episode.elephant_id,
        turn_messages=outcome.turn_messages,
    )
    StateReconciler().reconcile_turn(
        repository=self.repository,
        recall_runtime=self.recall_runtime,
        observation=observation,
    )
    _epoch_store = FileEpochStore(self.repository.database_path.parent)
    existing_epoch = _epoch_store.load(episode.episode_id)
    updated_epoch = next_session_context_epoch(
        existing_epoch,
        session=episode,
        event=outcome.event,
        execution=outcome.execution,
        context=outcome.context,
        turn_messages=outcome.turn_messages,
        thread_focus=outcome.state.summary,
    )
    if updated_epoch != existing_epoch:
        _epoch_store.save(updated_epoch)
    outcome = _compact_context_after_usage(self, episode.episode_id, outcome)
    record = APILoopRecord(
        request={
            "prompt": prompt,
            "state_query": state_query,
            "tool_name": tool_name,
            "tool_arguments": dict(tool_arguments or {}),
            "delivery_payload": dict(delivery_payload or {}),
        },
        outcome=outcome,
        recorded_at=_now(),
    )
    self._loops.setdefault(episode_id, []).append(record)
    inspection = self.inspect_episode(episode_id)
    return APILoopResult(
        episode=inspection.episode,
        outcome=outcome,
        latest_loop=record,
        inspection=inspection,
    )


def stream_loop_events(
    self,
    episode_id: str,
    *,
    prompt: str,
    state_query: str | None = None,
    tool_name: str | None = None,
    tool_arguments: Mapping[str, Any] | None = None,
    delivery_payload: Mapping[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Run a loop while yielding live UI-safe events.

    The CLI chat can render model deltas, kernel stages, and tool lifecycle
    events because it runs in-process. This generator exposes the same observer
    surfaces to HTTP callers without changing the synchronous loop contract.
    """
    event_queue: Queue[dict[str, Any] | object] = Queue(maxsize=2048)
    sentinel = object()
    sequence_lock = Lock()
    stream_sequence = 0

    def envelope(event: Mapping[str, Any]) -> dict[str, Any]:
        nonlocal stream_sequence
        with sequence_lock:
            stream_sequence += 1
            sequence = stream_sequence
        return _jsonable(
            {
                "episode_id": episode_id,
                "stream_sequence": sequence,
                "stream_emitted_at": _now(),
                **dict(event),
            }
        )

    def enqueue(event: Mapping[str, Any]) -> None:
        event_queue.put(envelope(event))

    def stream_observer(delta: str, **metadata: Any) -> None:
        stream_session_id = str(metadata.get("session_id") or "")
        if stream_session_id and stream_session_id != episode_id:
            return
        combined = split_reasoning_and_content(str(delta), streaming=True)
        if combined.reasoning:
            enqueue({"type": "assistant.reasoning.delta", "delta": combined.reasoning})
        if combined.content:
            enqueue({"type": "assistant.delta", "delta": combined.content})

    def tool_observer(event: Any) -> None:
        invocation = getattr(event, "invocation", None)
        if invocation is not None and getattr(invocation, "session_id", episode_id) != episode_id:
            return
        enqueue(_tool_lifecycle_stream_event(event))

    def telemetry_observer(event: Mapping[str, Any]) -> None:
        event_type = str(event.get("event_type") or event.get("type") or "")
        if event_type != "kernel.stage":
            return
        if str(event.get("episode_id") or "") not in {"", episode_id}:
            return
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        enqueue(
            {
                "type": "kernel.stage",
                "event_type": "kernel.stage",
                "id": str(event.get("event_id") or payload.get("event_id") or uuid4().hex),
                "stage": str(payload.get("stage") or ""),
                "detail": str(payload.get("detail") or ""),
                "result": str(payload.get("result") or ""),
                "status": "running",
            }
        )

    def worker() -> None:
        stream_lock = getattr(self, "_loop_stream_lock", None)
        set_stream_observer = getattr(self.model_provider, "set_stream_observer", None)
        previous_stream_observer = getattr(self.model_provider, "_stream_observer", None)
        clarify_surface = getattr(self, "_api_clarify_surface", None)
        set_clarify_delegate = getattr(clarify_surface, "set_delegate", None)
        previous_clarify_delegate = getattr(clarify_surface, "delegate", None)
        unsubscribe_tool = self.tool_runtime.subscribe(tool_observer)
        unsubscribe_telemetry = self.telemetry.subscribe(telemetry_observer)
        acquired_stream_lock = False
        try:
            enqueue({"type": "loop.started", "message": "Opening a live chat loop"})
            if stream_lock is not None:
                stream_lock.acquire()
                acquired_stream_lock = True
            if callable(set_stream_observer):
                set_stream_observer(stream_observer)
            if callable(set_clarify_delegate):
                pending, pending_lock = _clarify_pending_state(self)
                set_clarify_delegate(
                    _StreamingClarifySurface(
                        episode_id=episode_id,
                        enqueue=enqueue,
                        pending=pending,
                        pending_lock=pending_lock,
                    )
                )
            result = self.run_loop(
                episode_id,
                prompt=prompt,
                state_query=state_query,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                delivery_payload=delivery_payload,
            )
            enqueue(_loop_result_stream_completed_event(result))
        except Exception as error:
            enqueue({"type": "loop.failed", "error": str(error)})
        finally:
            if callable(set_stream_observer):
                set_stream_observer(previous_stream_observer)
            if callable(set_clarify_delegate):
                set_clarify_delegate(previous_clarify_delegate)
            unsubscribe_tool()
            unsubscribe_telemetry()
            if acquired_stream_lock and stream_lock is not None:
                stream_lock.release()
            event_queue.put(sentinel)

    Thread(target=worker, daemon=True).start()

    while True:
        try:
            event = event_queue.get(timeout=_STREAM_KEEPALIVE_SECONDS)
        except Empty:
            yield envelope({"type": "stream.heartbeat"})
            continue
        if event is sentinel:
            break
        yield event  # type: ignore[misc]

def dispatch(self, method: str, path: str, body: bytes | None = None) -> APIResponse:
    if method.upper() == "GET" and path == API_HEALTH_ROUTE:
        return APIResponse(200, {"status": "ok", "service": "elephant-api"})

    try:
        parts = _split_path(path)
        if not parts:
            return APIResponse(404, {"error": "not_found"})
        route_family = parts[0]
        if route_family == API_ROUTE_PROVIDERS:
            return self._dispatch_providers(method, parts[1:], body)
        if route_family == API_ROUTE_INTERNAL:
            return self._dispatch_internal(method, parts[1:], body)
        if route_family == API_ROUTE_OPERATOR:
            return self._dispatch_operator(method, parts[1:], body)
        if route_family == API_ROUTE_HERD:
            return _dispatch_elephants(self, method, parts[1:], body)
        if route_family == API_ROUTE_PATHS:
            return _dispatch_paths(self, method, parts[1:], body)
        if route_family == API_ROUTE_EPISODES:
            return self._dispatch_episodes(method, parts[1:], body)
        if route_family == API_ROUTE_STATES:
            return self._dispatch_states(method, parts[1:], body)
        return APIResponse(404, {"error": "not_found"})
    except KeyError as error:
        return APIResponse(404, {"error": "not_found", "missing": str(error)})
    except (ValueError, TypeError) as error:
        return APIResponse(400, {"error": "bad_request", "detail": str(error)})
    except LookupError as error:
        return APIResponse(422, {"error": "configuration_required", "detail": str(error)})
    except Exception as error:
        return APIResponse(500, {"error": "internal_error", "detail": str(error)})

def _tool_lifecycle_stream_event(event: Any) -> dict[str, Any]:
    invocation = getattr(event, "invocation", None)
    approval = getattr(event, "approval", None)
    execution = getattr(event, "execution", None)
    phase = str(getattr(event, "phase", "") or "")
    name = str(getattr(invocation, "tool_id", "") or "tool")
    arguments = getattr(invocation, "arguments", {}) if invocation is not None else {}
    result = str(getattr(execution, "summary", "") or "")
    return {
        "type": "tool.lifecycle",
        "event_type": "tool_execute",
        "id": str(getattr(event, "event_id", "") or uuid4().hex),
        "invocation_id": str(getattr(invocation, "invocation_id", "") or ""),
        "name": name,
        "tool_name": name,
        "status": _tool_lifecycle_status(phase, execution=execution, approval=approval),
        "phase": phase,
        "detail": str(getattr(event, "detail", "") or ""),
        "arguments": arguments,
        "tool_arguments": arguments,
        "result": result,
        "tool_result": result,
        "approval": _jsonable(approval) if approval is not None else None,
        "execution": _jsonable(execution) if execution is not None else None,
    }

def _tool_lifecycle_status(event_phase: str, *, execution: Any, approval: Any) -> str:
    if event_phase == "execution.completed":
        outcome = str(getattr(execution, "outcome", "") or "").lower()
        return "completed" if outcome in {"", "ok", "success"} else outcome
    if event_phase == "execution.failed":
        return "failed"
    if event_phase == "execution.started":
        return "running"
    if event_phase.startswith("approval."):
        decision = str(getattr(approval, "decision", "") or "").lower()
        if decision in {"denied", "deferred"}:
            return decision
        return "approved"
    if event_phase in {"requested", "classified"}:
        return "preparing"
    return event_phase or "running"

def _loop_result_payload(result: APILoopResult) -> dict[str, Any]:
    payload = dict(result.to_record())
    payload["reply_text"] = _loop_reply_text(result)
    return payload

def _loop_result_stream_completed_event(result: APILoopResult) -> dict[str, Any]:
    reply_text = _loop_reply_text(result)
    return {
        "type": "loop.completed",
        "reply_text": reply_text,
        "reply": {
            "episode_id": str(getattr(getattr(result, "episode", None), "episode_id", "") or ""),
            "text": reply_text,
            "tool_events": _loop_result_stream_tool_events(result),
        },
    }

def _loop_result_stream_tool_events(result: APILoopResult) -> list[dict[str, str]]:
    outcome = getattr(result, "outcome", None)
    steps = tuple(getattr(outcome, "steps", ()) or ())
    events: list[dict[str, str]] = []
    for step in steps:
        action = str(getattr(step, "action", "") or "")
        if action != "call_tool":
            continue
        metadata = getattr(step, "metadata", {}) or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        tool_name = str(metadata.get("tool_name") or "").strip()
        if not tool_name:
            continue
        status = str(getattr(step, "status", "") or "").strip() or "completed"
        events.append(
            {
                "name": tool_name,
                "tool_name": tool_name,
                "status": status,
                "arguments": _stream_preview(metadata.get("tool_arguments")),
                "result": _stream_preview(metadata.get("tool_result") or getattr(step, "summary", "") or ""),
            }
        )
    return events[-12:]

def _stream_preview(value: Any, *, limit: int = 700) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."

def _loop_reply_text(result: APILoopResult) -> str:
    outcome = getattr(result, "outcome", None)
    execution = getattr(outcome, "execution", None)
    text = str(getattr(execution, "summary", "") or "").strip()
    if text:
        return text
    for message in reversed(tuple(getattr(outcome, "turn_messages", ()) or ())):
        role = str(getattr(message, "role", "") or "").strip().lower()
        content = str(getattr(message, "content", "") or "").strip()
        if role == "assistant" and content:
            return content
    return ""
def _dispatch_episodes(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if method.upper() == "POST" and len(parts) == 0:
        payload = _read_json_bytes(body)
        result = self.create_episode(
            personal_model_id=str(payload.get("personal_model_id") or payload["profile_id"]),
            display_name=str(payload["display_name"]),
            mode=str(payload.get("mode") or "companion"),
            elephant_id=payload.get("elephant_id"),
            elephant_path=payload.get("elephant_path"),
            preferences=tuple(payload.get("preferences", ())),
            enabled_capabilities=tuple(payload.get("enabled_capabilities", ())),
            provider_profile=payload.get("provider_profile"),
            episode_id=payload.get("episode_id"),
        )
        return APIResponse(201, _jsonable(result.to_record()))
    if len(parts) < 1:
        return APIResponse(404, {"error": "not_found"})
    episode_id = parts[0]
    if method.upper() == "GET" and len(parts) == 1:
        return APIResponse(200, _jsonable(self.inspect_episode(episode_id).to_record()))
    if method.upper() == "POST" and len(parts) == 2 and parts[1] == "interrupt":
        payload = _read_json_bytes(body)
        result = self.interrupt_episode(episode_id, interruption_state=str(payload["interruption_state"]))
        return APIResponse(200, _jsonable(_loop_result_payload(result)))
    if method.upper() == "POST" and len(parts) == 2 and parts[1] == "next":
        payload = _read_json_bytes(body)
        result = self.open_next_episode(episode_id, child_episode_id=payload.get("child_episode_id"))
        return APIResponse(200, _jsonable(result.to_record()))
    if method.upper() == "POST" and len(parts) == 2 and parts[1] == "loops":
        payload = _read_json_bytes(body)
        result = self.run_loop(
            episode_id,
            prompt=str(payload["prompt"]),
            state_query=payload.get("state_query"),
            tool_name=payload.get("tool_name"),
            tool_arguments=payload.get("tool_arguments"),
            delivery_payload=payload.get("delivery_payload"),
        )
        return APIResponse(200, _jsonable(result.to_record()))
    if method.upper() == "POST" and len(parts) == 3 and parts[1] == "clarifications":
        payload = _read_json_bytes(body)
        result = _submit_stream_clarification(
            self,
            episode_id=episode_id,
            clarify_id=unquote(parts[2]).strip(),
            answer=str(payload.get("answer") or payload.get("response") or payload.get("user_response") or ""),
        )
        return APIResponse(202, _jsonable(result))
    if method.upper() == "PATCH" and len(parts) == 3 and parts[1] == "todos":
        payload = _read_json_bytes(body)
        result = _update_episode_todo(
            self,
            episode_id=episode_id,
            item_id=unquote(parts[2]).strip(),
            status=str(payload.get("status") or ("done" if payload.get("done") else "open")),
        )
        return APIResponse(200, _jsonable(result))
    if method.upper() == "GET" and len(parts) == 2 and parts[1] == "profile":
        inspection = self.inspect_episode(episode_id)
        return APIResponse(200, _jsonable({"personal_model": inspection.personal_model}))
    if len(parts) == 2 and parts[1] in {"identity", "user", "relationship", "continuity"}:
        episode = self.repository.load_episode(episode_id)
        if episode is None:
            raise KeyError(episode_id)
        return self._dispatch_states(method, (episode.state_id, parts[1]), body)
    if len(parts) == 2 and parts[1] == "recall":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"episode_id": episode_id, "recall": self.inspect_recall_evidence_surface(episode_id)}))
    if len(parts) == 3 and parts[1] == "recall" and parts[2] == "evidence":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"episode_id": episode_id, "evidence": self.list_recall_evidence(episode_id)}))
    if len(parts) == 3 and parts[1] == "recall" and parts[2] == "search":
        payload = _read_json_bytes(body)
        query = _optional_str(payload.get("query"))
        if query is None:
            raise ValueError("recall search query is required")
        limit = int(payload.get("limit", 5))
        return APIResponse(
            200,
            _jsonable({
                "episode_id": episode_id,
                "recall": self.search_recall_evidence_surface(episode_id, query=query, limit=limit),
            }),
        )
    if len(parts) == 3 and parts[1] == "recall":
        evidence_ref = parts[2]
        if method.upper() == "GET":
            detail = self.inspect_recall_evidence(episode_id, evidence_ref)
            return APIResponse(
                200,
                _jsonable(
                    {
                        "episode_id": episode_id,
                        "evidence": RecallEvidenceOperatorDetail(
                            evidence=detail["evidence"],
                            state=detail["state"],
                            lineage=detail["lineage"],
                        ),
                    }
                ),
            )
    return APIResponse(404, {"error": "not_found"})
def _dispatch_states(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if len(parts) != 2:
        return APIResponse(404, {"error": "not_found"})
    state_id, surface = parts
    if surface == "identity":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"state_id": state_id, "identity": self.inspect_identity(state_id=state_id)}))
        if method.upper() in {"PATCH", "POST"}:
            payload = _read_json_bytes(body)
            result = self.update_identity_state(
                state_id=state_id,
                display_name=_optional_str(payload.get("display_name") or payload.get("name")),
                personality_preset=_optional_str(payload.get("personality_preset") or payload.get("working_style")),
                initiative=_optional_str(payload.get("initiative")),
                elephant_identity_text=_optional_str(payload.get("elephant_identity_text") or payload.get("eggIdentityText") or payload.get("text") or payload.get("content")),
                clear_elephant_identity=bool(payload.get("clear_elephant_identity", False)),
            )
            return APIResponse(200, _jsonable({"state_id": state_id, "identity": result}))
    if surface == "user":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"state_id": state_id, "user": self.inspect_user(state_id=state_id)}))
        if method.upper() in {"PATCH", "POST"}:
            payload = _read_json_bytes(body)
            result = self.update_user_state(
                state_id=state_id,
                text=_optional_str(payload.get("text") or payload.get("content")),
                fields=payload.get("fields") if isinstance(payload.get("fields"), dict) else None,
                grounding_answers=payload.get("grounding_answers") if isinstance(payload.get("grounding_answers"), list) else None,
                append=bool(payload.get("append", False)),
                clear=bool(payload.get("clear", False)),
                split_personal_model_facts=bool(payload.get("split_personal_model_facts", False)),
            )
            return APIResponse(200, _jsonable({"state_id": state_id, "user": result}))
    if surface == "relationship":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"state_id": state_id, "relationship": self.inspect_relationship(state_id=state_id)}))
        if method.upper() in {"PATCH", "POST"}:
            payload = _read_json_bytes(body)
            result = self.update_relationship_state(
                state_id=state_id,
                text=_optional_str(payload.get("text") or payload.get("content")),
                append=bool(payload.get("append", False)),
                clear=bool(payload.get("clear", False)),
            )
            return APIResponse(200, _jsonable({"state_id": state_id, "relationship": result}))
    if surface == "continuity" and method.upper() == "GET":
        return APIResponse(200, _jsonable(self.inspect_continuity(state_id).to_record()))
    return APIResponse(404, {"error": "not_found"})
def _dispatch_providers(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if method.upper() == "GET" and len(parts) == 0:
        return APIResponse(200, _jsonable(self.list_providers()))
    if method.upper() == "GET" and len(parts) == 1 and parts[0] == "doctor":
        return APIResponse(200, _jsonable(self.doctor_provider()))
    if method.upper() == "GET" and len(parts) == 2 and parts[0] == "setup":
        return APIResponse(200, _jsonable(self.setup_provider(parts[1])))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "models":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.discover_provider_models(payload)))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "default":
        payload = _read_json_bytes(body)
        provider_profile = payload.get("provider_profile")
        if not isinstance(provider_profile, dict):
            raise ValueError("provider_profile must be an object describing the default provider configuration")
        result = self.set_default_provider(provider_profile)
        return APIResponse(200, _jsonable(result))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "test":
        payload = _read_json_bytes(body)
        result = self.test_provider(prompt=str(payload.get("prompt", "Summarize the current provider configuration.")))
        return APIResponse(200, _jsonable(result))
    if method.upper() == "GET" and len(parts) == 1 and parts[0] == "embeddings":
        return APIResponse(200, _jsonable({"embedding_provider": self.embedding_provider_summary()}))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "embeddings":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.set_embedding_provider(payload)))
    if method.upper() == "GET" and len(parts) == 1 and parts[0] == "keys":
        return APIResponse(200, _jsonable(self.list_provider_keys()))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "keys":
        payload = _read_json_bytes(body)
        return APIResponse(201, _jsonable(self.create_provider_key(payload)))
    if method.upper() == "PATCH" and len(parts) == 2 and parts[0] == "keys":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.upsert_provider_key(parts[1], payload)))
    if method.upper() == "DELETE" and len(parts) == 2 and parts[0] == "keys":
        return APIResponse(200, _jsonable(self.delete_provider_key(parts[1])))
    return APIResponse(404, {"error": "not_found"})

def _dispatch_internal(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if method.upper() == "GET" and len(parts) == 2 and parts[0] == "dashboard":
        return APIResponse(200, {"dashboard": _jsonable(self.inspect_internal_dashboard(parts[1]))})
    if method.upper() == "POST" and len(parts) == 2 and parts[0] == "diary" and parts[1] == "write":
        payload = _read_json_bytes(body)
        target_date = str(payload.get("date") or "").strip()
        if not target_date:
            return APIResponse(400, {"error": "date is required (YYYY-MM-DD)"})
        result = self.trigger_diary_write(target_date=target_date)
        return APIResponse(200, _jsonable(result))
    if method.upper() == "DELETE" and len(parts) == 2 and parts[0] == "diary":
        try:
            result = self.delete_diary_entry(entry_date=unquote(parts[1]))
        except ValueError as error:
            return APIResponse(400, {"error": str(error)})
        return APIResponse(200, _jsonable(result))
    if method.upper() == "POST" and len(parts) == 2 and parts[0] == "reflect" and parts[1] == "run":
        payload = _read_json_bytes(body)
        trigger = str(payload.get("trigger") or "manual").strip()
        features = str(payload.get("features") or "").strip() or None
        result = self.trigger_reflect_job(trigger=trigger, features=features)
        return APIResponse(200, _jsonable(result))
    return APIResponse(404, {"error": "not_found"})

def _dispatch_operator(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if parts and parts[0] == "cron":
        if method.upper() == "GET" and len(parts) == 1:
            from .api_runtime_console import _cron_jobs

            return APIResponse(200, {"cron": {"jobs": _cron_jobs(self)}})
        if method.upper() == "POST" and len(parts) == 1:
            payload = _read_json_bytes(body)
            job_payload = _cron_payload(payload)
            job = self.cron_runtime.create_job(
                name=str(payload.get("name") or "Elephant Agent job"),
                schedule_text=str(payload["schedule"]),
                payload=job_payload,
                profile_id=_optional_str(payload.get("profile_id")),
                elephant_id=_optional_str(payload.get("elephant_id")),
                timezone_name=_optional_str(payload.get("timezone_name")),
            )
            return APIResponse(201, {"cron": {"job": _cron_job_record(job)}})
        if len(parts) == 2:
            job_id = parts[1]
            if method.upper() == "GET":
                if job_id in {"system:proactive-ask", "system:dream"}:
                    from .api_runtime_console import _dream_system_job, _proactive_ask_system_job

                    job = _dream_system_job(self) if job_id == "system:dream" else _proactive_ask_system_job(self)
                    if job is None:
                        raise ValueError(f"system cron job unavailable: {job_id}")
                    return APIResponse(200, {"cron": {"job": job}})
                return APIResponse(200, {"cron": {"job": _cron_job_record(self.cron_runtime.inspect_job(job_id))}})
            if method.upper() == "PATCH":
                payload = _read_json_bytes(body)
                action = str(payload.get("action") or "").strip().lower()
                if action == "pause":
                    if job_id == "system:dream":
                        return APIResponse(403, {"error": "system_cron_job_cannot_be_paused"})
                    if job_id == "system:proactive-ask":
                        _persist_proactive_ask_config(self.repository.database_path.parent, {"enabled": False})
                        from .api_runtime_console import _proactive_ask_system_job

                        job = _proactive_ask_system_job(self)
                    else:
                        job = self.cron_runtime.pause_job(job_id)
                elif action == "resume":
                    if job_id == "system:dream":
                        return APIResponse(403, {"error": "system_cron_job_cannot_be_resumed"})
                    if job_id == "system:proactive-ask":
                        _persist_proactive_ask_config(self.repository.database_path.parent, {"enabled": True})
                        from .api_runtime_console import _proactive_ask_system_job

                        job = _proactive_ask_system_job(self)
                    else:
                        job = self.cron_runtime.resume_job(job_id)
                else:
                    raise ValueError("cron PATCH requires action=pause or action=resume")
                if job is None:
                    raise ValueError(f"system cron job unavailable: {job_id}")
                return APIResponse(200, {"cron": {"job": job if isinstance(job, Mapping) else _cron_job_record(job)}})
            if method.upper() == "DELETE":
                if job_id in {"system:proactive-ask", "system:dream"}:
                    return APIResponse(403, {"error": "system_cron_jobs_cannot_be_deleted"})
                job = self.cron_runtime.inspect_job(job_id)
                if _cron_job_system_kind(job) is not None:
                    return APIResponse(403, {"error": "system_cron_jobs_cannot_be_deleted"})
                job = self.cron_runtime.remove_job(job_id)
                return APIResponse(200, {"cron": {"job": _cron_job_record(job), "status": "removed"}})
        if len(parts) == 3 and parts[2] == "run" and method.upper() == "POST":
            # Manual-trigger ("Verify") endpoint. Runs the job once right now, goes
            # through the exact same execute → delivery pipeline the scheduler uses,
            # and returns the result synchronously so the dashboard can show it.
            if parts[1] == "system:proactive-ask":
                return APIResponse(200, _jsonable(self.run_proactive_ask_now()))
            if parts[1] == "system:dream":
                return APIResponse(200, _jsonable(self.run_dream_now()))
            return APIResponse(200, _jsonable(self.run_cron_job_now(parts[1])))
    if method.upper() == "PATCH" and len(parts) == 1 and parts[0] == "settings":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.patch_operator_settings(payload)))
    if method.upper() == "PATCH" and len(parts) == 1 and parts[0] == "config":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.patch_operator_global_config(payload)))
    if method.upper() == "POST" and len(parts) == 2 and parts[0] == "mcp" and parts[1] == "discover":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.discover_operator_mcp_server(payload)))
    if len(parts) >= 2 and parts[0] == "mcp" and parts[1] == "servers":
        payload = _read_json_bytes(body)
        if method.upper() in {"POST", "PATCH"} and len(parts) == 2:
            status_code = 200 if method.upper() == "PATCH" else 201
            return APIResponse(status_code, _jsonable(self.sync_operator_mcp_server(payload)))
        if method.upper() == "DELETE" and len(parts) == 2:
            return APIResponse(200, _jsonable(self.delete_operator_mcp_server(payload)))
    if len(parts) >= 2 and parts[0] == "mcp" and parts[1] == "tools":
        payload = _read_json_bytes(body)
        if method.upper() == "POST" and len(parts) == 2:
            return APIResponse(201, _jsonable(self.create_operator_mcp_tool(payload)))
        if method.upper() == "PATCH" and len(parts) == 2:
            return APIResponse(200, _jsonable(self.update_operator_mcp_tool(payload)))
        if method.upper() == "DELETE" and len(parts) == 2:
            return APIResponse(200, _jsonable(self.delete_operator_mcp_tool(payload)))
        if method.upper() == "PATCH" and len(parts) == 3 and parts[2] == "enabled":
            return APIResponse(200, _jsonable(self.set_operator_mcp_tool_enabled(payload)))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "gateway":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.gateway_action(payload)))
    if parts and parts[0] == "personal-model":
        return _dispatch_personal_model(self, method, parts[1:], body)
    if method.upper() == "PATCH" and len(parts) == 2 and parts[0] in {"skills", "tools"}:
        payload = _read_json_bytes(body)
        result = self.set_console_item_enabled(
            kind="skill" if parts[0] == "skills" else "tool",
            item_id=parts[1],
            enabled=bool(payload.get("enabled")),
        )
        return APIResponse(200, _jsonable(result))
    return APIResponse(404, {"error": "not_found"})
