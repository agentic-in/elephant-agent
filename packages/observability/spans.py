from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from opentelemetry import trace

_tracer = trace.get_tracer("elephant-agent")

# OTel GenAI semconv attribute keys (semconv 1.41)
ATTR_OPERATION_NAME = "gen_ai.operation.name"
ATTR_REQUEST_MODEL = "gen_ai.request.model"
ATTR_PROVIDER_NAME = "gen_ai.provider.name"
ATTR_TOOL_NAME = "gen_ai.tool.name"
ATTR_INPUT_TOKENS = "gen_ai.usage.input_tokens"
ATTR_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
ATTR_CACHE_READ_TOKENS = "gen_ai.usage.cache_read.input_tokens"

# Elephant-specific attributes
ATTR_EPISODE_ID = "elephant.episode_id"
ATTR_LOOP_ID = "elephant.loop_id"
ATTR_STEP_ID = "elephant.step_id"
ATTR_TRIGGER_TYPE = "elephant.trigger_type"


def _elephant_attrs(
    episode_id: str = "",
    loop_id: str = "",
    step_id: str = "",
) -> dict[str, str]:
    attrs: dict[str, str] = {}
    if episode_id:
        attrs[ATTR_EPISODE_ID] = episode_id
    if loop_id:
        attrs[ATTR_LOOP_ID] = loop_id
    if step_id:
        attrs[ATTR_STEP_ID] = step_id
    return attrs


@contextmanager
def trace_kernel_turn(
    *,
    episode_id: str,
    loop_id: str,
    trigger_type: str = "",
) -> Generator[trace.Span, None, None]:
    attrs: dict[str, Any] = {
        ATTR_OPERATION_NAME: "invoke_agent",
        **_elephant_attrs(episode_id=episode_id, loop_id=loop_id),
    }
    if trigger_type:
        attrs[ATTR_TRIGGER_TYPE] = trigger_type
    with _tracer.start_as_current_span(
        "invoke_agent", attributes=attrs,
    ) as span:
        yield span


@contextmanager
def trace_model_call(
    *,
    provider_id: str,
    model_id: str,
    episode_id: str = "",
    loop_id: str = "",
) -> Generator[trace.Span, None, None]:
    attrs: dict[str, Any] = {
        ATTR_OPERATION_NAME: "chat",
        ATTR_REQUEST_MODEL: model_id,
        ATTR_PROVIDER_NAME: provider_id,
        **_elephant_attrs(episode_id=episode_id, loop_id=loop_id),
    }
    with _tracer.start_as_current_span(
        f"chat {model_id}", attributes=attrs,
    ) as span:
        yield span


def record_token_usage(
    span: trace.Span,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    if input_tokens:
        span.set_attribute(ATTR_INPUT_TOKENS, input_tokens)
    if output_tokens:
        span.set_attribute(ATTR_OUTPUT_TOKENS, output_tokens)
    if cache_read_tokens:
        span.set_attribute(ATTR_CACHE_READ_TOKENS, cache_read_tokens)


@contextmanager
def trace_tool_execution(
    *,
    tool_name: str,
    episode_id: str = "",
    loop_id: str = "",
) -> Generator[trace.Span, None, None]:
    attrs: dict[str, Any] = {
        ATTR_OPERATION_NAME: "execute_tool",
        ATTR_TOOL_NAME: tool_name,
        **_elephant_attrs(episode_id=episode_id, loop_id=loop_id),
    }
    with _tracer.start_as_current_span(
        f"execute_tool {tool_name}", attributes=attrs,
    ) as span:
        yield span
