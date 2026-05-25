# Observability Package

This package owns runtime instrumentation for logs, traces, and metrics.

## Own Here

- OpenTelemetry setup and exporters
- trace context propagation into logs and spans
- instrumentation wrappers for kernel, provider, tool, and cron execution
- redaction and structured logging helpers

## Do Not Own Here

- business logic or product state transitions
- provider request construction
- kernel lifecycle decisions
- user-facing telemetry presentation

Instrumentation must stay observational. Wrappers should be idempotent,
reversible through `uninstrument()`, and careful not to alter return values,
exception behavior, or streaming semantics.
