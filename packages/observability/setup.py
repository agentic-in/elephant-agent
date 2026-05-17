from __future__ import annotations

import os

from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

from .logger import configure_logging

_initialized = False


def setup_observability(
    *,
    service_name: str = "elephant-agent",
    service_version: str = "",
    log_level: str = "INFO",
    log_file: str = "",
    state_dir: str = "",
    otel_endpoint: str = "",
) -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    otel_endpoint = otel_endpoint or os.environ.get("ELEPHANT_OTEL_ENDPOINT", "")

    configure_logging(log_level=log_level, log_file=log_file, state_dir=state_dir)

    resource_attrs = {"service.name": service_name}
    if service_version:
        resource_attrs["service.version"] = service_version
    resource = Resource.create(resource_attrs)

    tracer_provider = TracerProvider(resource=resource)

    if otel_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otel_endpoint))
        )
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=otel_endpoint),
            export_interval_millis=60_000,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    else:
        meter_provider = MeterProvider(resource=resource)

    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
