"""WSGI, cron, and config persistence helpers for the API runtime."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
from typing import Any
from urllib.parse import unquote

from .api_runtime_http_dispatch_helpers import _cron_job_record, _read_wsgi_body
from .api_runtime_support import APIResponse, _read_json_bytes


def _persist_proactive_ask_config(state_dir, updates: dict) -> None:
    try:
        from packages.runtime_config import (
            global_config_path_for_state_dir,
            load_global_config,
            personal_model_question_config_from_global,
            write_global_config,
        )

        config_path = global_config_path_for_state_dir(state_dir)
        config = load_global_config(config_path, state_dir=state_dir)
        question_policy = personal_model_question_config_from_global(config)
        proactive = question_policy.get("proactive_ask") if isinstance(question_policy.get("proactive_ask"), dict) else {}
        proactive.update(updates)
        question_policy["proactive_ask"] = proactive
        question_policy.pop("learning_intensity", None)
        config["personal_model_questions"] = question_policy
        write_global_config(config_path, config)
    except Exception:  # pragma: no cover
        return


def run_cron_job_now(self, job_id: str) -> dict[str, Any]:
    """Fire one cron job on demand and return its execution result."""
    from pathlib import Path as _Path

    from apps.cli.runtime import CliRuntime
    from apps.gateway.cron_service import build_gateway_cron_delivery_callback, cron_execution_should_deliver

    state_dir = _Path(str(self.repository.database_path.parent))
    cli_state_dir = state_dir
    gateway_state_dir = state_dir

    runtime = CliRuntime.create(state_dir=cli_state_dir)
    execution = runtime.run_cron_job_now(job_id)

    delivered = False
    delivery_error: str | None = None
    should_deliver = execution.outcome == "success" and cron_execution_should_deliver(execution)
    if should_deliver:
        try:
            callback = build_gateway_cron_delivery_callback(
                state_dir=gateway_state_dir,
                cli_state_dir=cli_state_dir,
                environ={},
            )
            if callback is not None:
                callback(execution.job, execution)
                delivered = True
        except Exception as error:
            delivery_error = f"{type(error).__name__}: {error}"

    return {
        "cron": {
            "job": _cron_job_record(execution.job),
            "run": {
                "outcome": execution.outcome,
                "summary": execution.summary,
                "delivered": delivered,
                "delivery_error": delivery_error,
                "recorded_at": execution.recorded_at.isoformat(),
            },
        }
    }


def __call__(self, environ: Mapping[str, Any], start_response: Any) -> Iterator[bytes] | list[bytes]:
    from .api_runtime_support import _json_bytes as encode_json

    method = str(environ.get("REQUEST_METHOD", "GET"))
    path = str(environ.get("PATH_INFO", "/"))
    payload = _read_wsgi_body(environ)

    stream_episode_id = _stream_loop_episode_id(method, path)
    if stream_episode_id is not None:
        try:
            body = _read_json_bytes(payload)
            prompt = str(body["prompt"])
        except Exception as error:
            response = APIResponse(400, {"error": "bad_request", "detail": str(error)})
            start_response(
                f"{response.status_code} {'OK' if response.status_code < 400 else 'ERROR'}",
                list(response.headers),
            )
            return [encode_json(response.payload)]

        start_response(
            "200 OK",
            [
                ("content-type", "text/event-stream; charset=utf-8"),
                ("cache-control", "no-cache"),
                ("x-accel-buffering", "no"),
            ],
        )
        return _wsgi_loop_event_stream(
            self,
            stream_episode_id,
            prompt=prompt,
            state_query=body.get("state_query"),
            tool_name=body.get("tool_name"),
            tool_arguments=body.get("tool_arguments"),
            delivery_payload=body.get("delivery_payload"),
        )

    response = self.dispatch(method, path, payload)
    start_response(
        f"{response.status_code} {'OK' if response.status_code < 400 else 'ERROR'}",
        list(response.headers),
    )
    return [encode_json(response.payload)]



def _wsgi_loop_event_stream(
    self,
    episode_id: str,
    *,
    prompt: str,
    state_query: str | None = None,
    tool_name: str | None = None,
    tool_arguments: Mapping[str, Any] | None = None,
    delivery_payload: Mapping[str, Any] | None = None,
) -> Iterator[bytes]:
    try:
        yield from (
            _sse_frame(event)
            for event in self.stream_loop_events(
                episode_id,
                prompt=prompt,
                state_query=state_query,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                delivery_payload=delivery_payload,
            )
        )
    except Exception as error:
        yield _sse_frame({"type": "loop.failed", "episode_id": episode_id, "error": str(error)})



def _stream_loop_episode_id(method: str, path_info: str) -> str | None:
    if method.upper() != "POST":
        return None
    parts = tuple(part for part in path_info.strip("/").split("/") if part)
    if len(parts) == 5 and parts[0] == "v1" and parts[1] == "episodes" and parts[3] == "loops" and parts[4] == "stream":
        return unquote(parts[2])
    return None



def _sse_frame(event: Mapping[str, Any]) -> bytes:
    event_type = str(event.get("type") or "message")
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")
