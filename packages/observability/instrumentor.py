"""Monkey-patch instrumentor for elephant-agent runtime.

All observability instrumentation is applied here via runtime patching.
Target modules (kernel, providers, cron) are NOT modified -- this file
is the single source of truth for all instrumentation logic.
"""

from __future__ import annotations

import time
from functools import wraps

from .context import TraceContext, set_context, update_context
from .logger import get_logger
from .metrics import (
    DurationTimer,
    record_model_metrics,
    record_tool_metrics,
    record_turn_metrics,
)
from .spans import (
    record_token_usage,
    trace_kernel_turn,
    trace_model_call,
    trace_tool_execution,
)

_instrumented = False
_originals: dict[str, object] = {}


def instrument() -> None:
    global _instrumented
    if _instrumented:
        return
    _instrumented = True

    _patch_kernel_service_run()
    _patch_generate_with_steps()
    _patch_invoke_tool_call()
    _patch_http_transport_post_json()
    _patch_cron_run_due()


def uninstrument() -> None:
    global _instrumented
    if not _instrumented:
        return
    _instrumented = False

    for key, original in _originals.items():
        module_path, attr = key.rsplit(".", 1)
        obj = _resolve_module_attr(module_path)
        if obj is not None:
            setattr(obj, attr, original)
    _originals.clear()


def _save_original(key: str, original: object) -> None:
    if key not in _originals:
        _originals[key] = original


def _resolve_module_attr(dotted: str) -> object | None:
    parts = dotted.split(".")
    try:
        import importlib
        mod = importlib.import_module(parts[0])
        for part in parts[1:]:
            mod = getattr(mod, part)
        return mod
    except (ImportError, AttributeError):
        return None


def _patch_kernel_service_run() -> None:
    try:
        from packages.kernel.runtime_impl import KernelService
    except ImportError:
        return
    original = KernelService.run
    _save_original("packages.kernel.runtime_impl.KernelService.run", original)
    logger = get_logger("kernel")

    @wraps(original)
    def wrapped_run(self, request):
        timer = DurationTimer()
        trigger = getattr(request, "source_event_type", "") or ""
        request_id = getattr(request, "request_id", "") or ""
        set_context(TraceContext(request_id=request_id))

        episode_id = ""
        loop_id = ""
        try:
            with trace_kernel_turn(episode_id="", loop_id="", trigger_type=trigger) as span:
                result = original(self, request)

                episode = getattr(result, "episode", None)
                loop = getattr(result, "loop", None)
                episode_id = getattr(episode, "episode_id", "") or ""
                loop_id = getattr(loop, "loop_id", "") or ""
                span.set_attribute("elephant.episode_id", episode_id)
                span.set_attribute("elephant.loop_id", loop_id)
                set_context(TraceContext(
                    episode_id=episode_id,
                    loop_id=loop_id,
                    request_id=request_id,
                ))
        except Exception:
            duration = timer.elapsed()
            logger.error("kernel turn failed: duration=%.2fs", duration)
            record_turn_metrics(episode_id=episode_id, duration_s=duration, trigger_type=trigger)
            raise

        duration = timer.elapsed()
        record_turn_metrics(episode_id=episode_id, duration_s=duration, trigger_type=trigger)
        logger.info(
            "kernel turn completed: episode=%s loop=%s duration=%.2fs",
            episode_id, loop_id, duration,
        )
        return result

    KernelService.run = wrapped_run


def _patch_generate_with_steps() -> None:
    try:
        import packages.kernel.execution_support as mod
    except ImportError:
        return
    original = mod._generate_with_steps
    _save_original("packages.kernel.execution_support._generate_with_steps", original)
    logger = get_logger("kernel.execution")

    @wraps(original)
    def wrapped(service, profile, session, context, prompt, *, step_recorder=None, planned_summary=""):
        mp = getattr(getattr(service, "dependencies", None), "model_provider", None)
        provider_id = getattr(mp, "active_provider_id", "") or ""
        model_id = ""
        if mp is not None and hasattr(mp, "active_profile"):
            ap = mp.active_profile()
            if ap is not None:
                provider_id = provider_id or getattr(ap, "provider_id", "")
                model_id = getattr(ap, "default_model", "") or ""
        provider_id = provider_id or "unknown"
        model_id = model_id or "unknown"
        episode_id = getattr(session, "episode_id", "")
        loop_id = getattr(session, "loop_id", "") if hasattr(session, "loop_id") else ""
        update_context(episode_id=episode_id, loop_id=loop_id)

        timer = DurationTimer()
        with trace_model_call(provider_id=provider_id, model_id=model_id, episode_id=episode_id) as span:
            response = original(service, profile, session, context, prompt, step_recorder=step_recorder, planned_summary=planned_summary)
            record_token_usage(
                span,
                input_tokens=getattr(response, "prompt_tokens", 0) or 0,
                output_tokens=getattr(response, "completion_tokens", 0) or 0,
                cache_read_tokens=getattr(response, "cached_prompt_tokens", 0) or 0,
            )

        elapsed = timer.elapsed()
        record_model_metrics(
            provider_id=provider_id,
            model_id=model_id,
            input_tokens=getattr(response, "prompt_tokens", 0) or 0,
            output_tokens=getattr(response, "completion_tokens", 0) or 0,
            duration_s=elapsed,
        )
        logger.info(
            "model call completed: provider=%s model=%s tokens=%d/%d duration=%.2fs",
            provider_id, model_id,
            getattr(response, "prompt_tokens", 0) or 0,
            getattr(response, "completion_tokens", 0) or 0,
            elapsed,
        )
        return response

    mod._generate_with_steps = wrapped


def _patch_invoke_tool_call() -> None:
    try:
        import packages.kernel.execution_support as mod
    except ImportError:
        return
    original = mod._invoke_tool_call
    _save_original("packages.kernel.execution_support._invoke_tool_call", original)

    @wraps(original)
    def wrapped(service, call, *, session):
        tool_name = getattr(call, "tool_name", "unknown")
        episode_id = getattr(session, "episode_id", "")
        timer = DurationTimer()
        with trace_tool_execution(tool_name=tool_name, episode_id=episode_id):
            result = original(service, call, session=session)
        outcome = getattr(result, "outcome", "unknown")
        record_tool_metrics(tool_name=tool_name, duration_s=timer.elapsed(), status=outcome)
        return result

    mod._invoke_tool_call = wrapped


def _patch_http_transport_post_json() -> None:
    try:
        from packages.models.providers.http import UrllibJSONHTTPTransport
    except ImportError:
        return
    original_post = UrllibJSONHTTPTransport.post_json
    original_stream = UrllibJSONHTTPTransport.post_json_stream
    _save_original("packages.models.providers.http.UrllibJSONHTTPTransport.post_json", original_post)
    _save_original("packages.models.providers.http.UrllibJSONHTTPTransport.post_json_stream", original_stream)
    logger = get_logger("provider.http")

    @wraps(original_post)
    def wrapped_post(self, *, url, headers, payload):
        start = time.monotonic()
        try:
            result = original_post(self, url=url, headers=headers, payload=payload)
        except Exception:
            logger.warning("provider HTTP request failed: url=%s duration=%.2fs", url, time.monotonic() - start)
            raise
        logger.debug(
            "provider HTTP request: url=%s status=%d duration=%.2fs",
            url, getattr(result, "status_code", 0), time.monotonic() - start,
        )
        return result

    @wraps(original_stream)
    def wrapped_stream(self, *, url, headers, payload):
        start = time.monotonic()
        try:
            for chunk in original_stream(self, url=url, headers=headers, payload=payload):
                yield chunk
        except Exception:
            logger.warning(
                "provider HTTP stream failed: url=%s duration=%.2fs",
                url, time.monotonic() - start,
            )
            raise
        logger.debug(
            "provider HTTP stream completed: url=%s duration=%.2fs",
            url, time.monotonic() - start,
        )

    UrllibJSONHTTPTransport.post_json = wrapped_post
    UrllibJSONHTTPTransport.post_json_stream = wrapped_stream


def _patch_cron_run_due() -> None:
    try:
        from packages.cron.runtime import CronRuntime
    except ImportError:
        return
    original = CronRuntime.run_due
    _save_original("packages.cron.runtime.CronRuntime.run_due", original)
    logger = get_logger("cron")

    @wraps(original)
    def wrapped(self, executor, *, profile_id=None, elephant_id=None, now=None):
        original_executor = executor

        def instrumented_executor(job):
            set_context(TraceContext(request_id=getattr(job, "job_id", "")))
            logger.info("cron job started: job_id=%s name=%s", job.job_id, job.name)
            try:
                outcome, summary = original_executor(job)
            except Exception as error:
                logger.error("cron job failed: job_id=%s error=%s", job.job_id, error)
                raise
            logger.info("cron job completed: job_id=%s outcome=%s", job.job_id, outcome)
            return outcome, summary

        return original(self, instrumented_executor, profile_id=profile_id, elephant_id=elephant_id, now=now)

    CronRuntime.run_due = wrapped
