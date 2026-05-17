# Observability

Elephant Agent includes built-in observability powered by [OpenTelemetry](https://opentelemetry.io/), covering structured logging, distributed tracing, and GenAI metrics.

## Overview

Every user request flows through a hierarchy of runtime concepts, each assigned a stable correlation ID:

- **Episode** -- a conversation session
- **Loop** -- a single turn within an episode
- **Step** -- an individual action within a loop (model call, tool execution, etc.)

These IDs are injected into log records and trace spans, enabling end-to-end debugging of any interaction.

### Architecture

Instrumentation is applied at runtime via monkey-patching. The target modules (kernel, providers, cron) are **not modified** -- all instrumentation logic lives in `packages/observability/instrumentor.py`. A single `instrument()` call at startup patches:

- `KernelService.run()` -- wraps each kernel turn with an `invoke_agent` span and structured logging
- `_generate_with_steps()` -- wraps model provider calls with a `chat` span and token usage metrics
- `_invoke_tool_call()` -- wraps tool execution with an `execute_tool` span and duration metrics
- `UrllibJSONHTTPTransport.post_json()` / `post_json_stream()` -- adds structured logging for all provider HTTP calls (both non-streaming and streaming)
- `CronRuntime.run_due()` -- initializes trace context and logging for background jobs

Calling `uninstrument()` restores all original methods.

## Configuration

### Environment variables

The simplest way to enable observability features:

| Variable | Description |
|----------|-------------|
| `ELEPHANT_OTEL_ENDPOINT` | OTLP gRPC endpoint (e.g. `http://localhost:4317`). When set, traces and metrics are exported to this endpoint. When unset, only local log files are written. |

Example:

```bash
ELEPHANT_OTEL_ENDPOINT=http://localhost:4317 elephant wake
```

Observability is enabled by default (`enabled: true` in config). The environment variable controls whether telemetry is additionally exported to a remote backend.

### Config file (optional)

Fine-grained control is available in `config.yaml` under the `observability` section:

```yaml
observability:
  enabled: true
  log_level: INFO
  log_file: ""
  otel_endpoint: ""
  service_name: elephant-agent
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Enable or disable observability entirely |
| `log_level` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `log_file` | `""` | Custom log file path. Empty uses `{state_dir}/logs/elephant.log` |
| `otel_endpoint` | `""` | OTLP gRPC endpoint for remote export. `ELEPHANT_OTEL_ENDPOINT` env var takes precedence |
| `service_name` | `elephant-agent` | Service name reported in traces and metrics |

The `ELEPHANT_OTEL_ENDPOINT` environment variable can override the `otel_endpoint` config value.

## Local Logging

Logs are written to a JSON-structured file at `{state_dir}/logs/elephant.log` (10 MB rotation, 5 backups). Logs are never printed to the console to avoid interfering with the TUI. Sensitive content (API keys, bearer tokens) is automatically redacted.

### Log file format

Each line is a JSON object:

```json
{
  "ts": "2026-05-17 14:23:01,234",
  "level": "INFO",
  "logger": "elephant.kernel",
  "msg": "kernel turn completed: episode=3a6550b0ad43 loop=loop:kernel-source-c0da duration=4.89s",
  "trace_id": "945d2e3478ab1c6f90de3456789abcde",
  "episode_id": "3a6550b0ad434c038382de91a9e1f2e2",
  "loop_id": "loop:kernel-source-c0daf56de8b9457cb69a2586a5ea65b3",
  "step_id": "",
  "request_id": ""
}
```

## Remote Export (OTLP)

To send telemetry to a remote backend, set the OTLP endpoint:

```bash
export ELEPHANT_OTEL_ENDPOINT=http://localhost:4317
```

Or in `config.yaml`:

```yaml
observability:
  otel_endpoint: "http://localhost:4317"
```

This enables export of traces and metrics to any OTLP-compatible backend. Logs remain local (structured JSON file) regardless of this setting.

## Traces

Trace spans follow the [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/):

| Span Name | Operation | Attributes |
|-----------|-----------|------------|
| `invoke_agent` | Full kernel turn | `elephant.episode_id`, `elephant.loop_id`, `elephant.trigger_type` |
| `chat {model}` | Model provider call | `gen_ai.request.model`, `gen_ai.provider.name`, token usage |
| `execute_tool {name}` | Tool execution | `gen_ai.tool.name` |

## Metrics

Metrics follow GenAI semantic conventions where applicable:

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.token.usage` | Histogram | `{token}` | Token counts per model call (input/output) |
| `gen_ai.client.operation.duration` | Histogram | `s` | Model call duration |
| `elephant.tool.duration` | Histogram | `s` | Tool execution duration |
| `elephant.kernel.turn.duration` | Histogram | `s` | Full kernel turn duration |
