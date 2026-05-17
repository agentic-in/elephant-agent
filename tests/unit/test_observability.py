from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import unittest

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from packages.observability.context import (
    TraceContext,
    TraceContextFilter,
    get_context,
    set_context,
    update_context,
    _current_context,
)
from packages.observability.logger import (
    _JSONFormatter,
    _RedactingFilter,
    _redact,
    configure_logging,
    get_logger,
)
import packages.observability.spans as spans_mod
import packages.observability.metrics as metrics_mod


class TraceContextTests(unittest.TestCase):
    def setUp(self) -> None:
        _current_context.set(None)

    def test_get_context_creates_default(self) -> None:
        ctx = get_context()
        self.assertIsInstance(ctx, TraceContext)
        self.assertTrue(len(ctx.trace_id) > 0)

    def test_set_and_get_roundtrip(self) -> None:
        ctx = TraceContext(trace_id="abc", episode_id="ep1")
        set_context(ctx)
        self.assertIs(get_context(), ctx)

    def test_update_context(self) -> None:
        set_context(TraceContext(trace_id="t1"))
        update_context(episode_id="ep2", loop_id="lp3")
        ctx = get_context()
        self.assertEqual(ctx.episode_id, "ep2")
        self.assertEqual(ctx.loop_id, "lp3")
        self.assertEqual(ctx.trace_id, "t1")

    def test_filter_injects_fields(self) -> None:
        set_context(TraceContext(
            trace_id="trace123",
            episode_id="ep456",
            loop_id="loop789",
        ))
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        f = TraceContextFilter()
        f.filter(record)
        self.assertEqual(record.trace_id, "trace123")
        self.assertEqual(record.episode_id, "ep456")
        self.assertEqual(record.loop_id, "loop789")

    def test_filter_handles_no_context(self) -> None:
        _current_context.set(None)
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        f = TraceContextFilter()
        f.filter(record)
        self.assertEqual(record.trace_id, "")


class RedactionTests(unittest.TestCase):
    def test_redacts_api_key(self) -> None:
        self.assertIn("[REDACTED]", _redact("key is key-abcdefghijklmnopqrstuvwxyz1234"))

    def test_redacts_bearer_token(self) -> None:
        self.assertIn("[REDACTED]", _redact("Authorization: Bearer eyJhbGciOiJIUz"))

    def test_redacts_api_key_assignment(self) -> None:
        result = _redact('api_key: "my-secret-value-12345"')
        self.assertNotIn("my-secret-value", result)

    def test_preserves_normal_text(self) -> None:
        text = "this is a normal log message about episode ep-123"
        self.assertEqual(_redact(text), text)

    def test_redacting_filter_handles_dict_args(self) -> None:
        record = logging.LogRecord("test", logging.INFO, "", 0, "key=%(key)s", None, None)
        record.args = {"key": "key-abcdefghijklmnopqrstuvwxyz1234"}
        f = _RedactingFilter()
        f.filter(record)
        self.assertNotIn("key-abcdef", record.getMessage())


class JSONFormatterTests(unittest.TestCase):
    def test_formats_as_json(self) -> None:
        record = logging.LogRecord("elephant.test", logging.INFO, "", 0, "hello world", (), None)
        record.trace_id = "t1"
        record.episode_id = "e1"
        record.loop_id = "l1"
        record.step_id = ""
        record.request_id = "r1"
        formatter = _JSONFormatter()
        line = formatter.format(record)
        parsed = json.loads(line)
        self.assertEqual(parsed["msg"], "hello world")
        self.assertEqual(parsed["trace_id"], "t1")
        self.assertEqual(parsed["episode_id"], "e1")
        self.assertEqual(parsed["level"], "INFO")


class ConfigureLoggingTests(unittest.TestCase):
    def test_log_file_created(self) -> None:
        import packages.observability.logger as logger_mod
        original = logger_mod._configured
        logger_mod._configured = False
        try:
            with TemporaryDirectory() as tmpdir:
                log_path = Path(tmpdir) / "test.log"
                configure_logging(log_file=str(log_path))
                logger = get_logger("test_config")
                _current_context.set(TraceContext(trace_id="cfg-test"))
                logger.info("config test message")
                for handler in logging.getLogger("elephant").handlers[:]:
                    handler.flush()
                self.assertTrue(log_path.exists())
                content = log_path.read_text()
                self.assertIn("config test message", content)
        finally:
            logger_mod._configured = original
            root = logging.getLogger("elephant")
            for h in root.handlers[:]:
                root.removeHandler(h)


class _InMemorySpanExporter:
    def __init__(self) -> None:
        self.spans: list = []

    def export(self, spans):
        self.spans.extend(spans)
        from opentelemetry.sdk.trace.export import SpanExportResult
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 0) -> bool:
        return True


class SpanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter = _InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self._orig_tracer = spans_mod._tracer
        spans_mod._tracer = self.provider.get_tracer("elephant-agent")

    def tearDown(self) -> None:
        spans_mod._tracer = self._orig_tracer

    def test_trace_kernel_turn_creates_span(self) -> None:
        with spans_mod.trace_kernel_turn(episode_id="ep1", loop_id="lp1", trigger_type="user_input"):
            pass
        self.assertEqual(len(self.exporter.spans), 1)
        span = self.exporter.spans[0]
        self.assertEqual(span.name, "invoke_agent")
        self.assertEqual(span.attributes["gen_ai.operation.name"], "invoke_agent")
        self.assertEqual(span.attributes["elephant.episode_id"], "ep1")

    def test_trace_model_call_creates_span(self) -> None:
        with spans_mod.trace_model_call(provider_id="openai", model_id="gpt-5.5"):
            pass
        self.assertEqual(len(self.exporter.spans), 1)
        span = self.exporter.spans[0]
        self.assertEqual(span.name, "chat gpt-5.5")
        self.assertEqual(span.attributes["gen_ai.request.model"], "gpt-5.5")
        self.assertEqual(span.attributes["gen_ai.provider.name"], "openai")

    def test_trace_tool_execution_creates_span(self) -> None:
        with spans_mod.trace_tool_execution(tool_name="shell.execute", episode_id="ep2"):
            pass
        self.assertEqual(len(self.exporter.spans), 1)
        span = self.exporter.spans[0]
        self.assertEqual(span.name, "execute_tool shell.execute")
        self.assertEqual(span.attributes["gen_ai.tool.name"], "shell.execute")

    def test_record_token_usage_sets_attributes(self) -> None:
        with spans_mod.trace_model_call(provider_id="anthropic", model_id="claude-4") as span:
            spans_mod.record_token_usage(span, input_tokens=100, output_tokens=50, cache_read_tokens=20)
        recorded = self.exporter.spans[0]
        self.assertEqual(recorded.attributes["gen_ai.usage.input_tokens"], 100)
        self.assertEqual(recorded.attributes["gen_ai.usage.output_tokens"], 50)
        self.assertEqual(recorded.attributes["gen_ai.usage.cache_read.input_tokens"], 20)

    def test_parent_child_span_hierarchy(self) -> None:
        with spans_mod.trace_kernel_turn(episode_id="ep1", loop_id="lp1"):
            with spans_mod.trace_model_call(provider_id="openai", model_id="gpt-5"):
                pass
        self.assertEqual(len(self.exporter.spans), 2)
        model_span = self.exporter.spans[0]
        turn_span = self.exporter.spans[1]
        self.assertEqual(model_span.parent.span_id, turn_span.context.span_id)


class MetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reader = InMemoryMetricReader()
        self.provider = MeterProvider(metric_readers=[self.reader])
        meter = self.provider.get_meter("elephant-agent")
        self._patches = [
            mock.patch.object(metrics_mod, "_meter", meter),
            mock.patch.object(metrics_mod, "token_usage", meter.create_histogram("gen_ai.client.token.usage", unit="{token}")),
            mock.patch.object(metrics_mod, "operation_duration", meter.create_histogram("gen_ai.client.operation.duration", unit="s")),
            mock.patch.object(metrics_mod, "tool_duration", meter.create_histogram("elephant.tool.duration", unit="s")),
            mock.patch.object(metrics_mod, "kernel_turn_duration", meter.create_histogram("elephant.kernel.turn.duration", unit="s")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def _metric_names(self) -> list[str]:
        data = self.reader.get_metrics_data()
        return [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]

    def test_record_model_metrics(self) -> None:
        metrics_mod.record_model_metrics(provider_id="openai", model_id="gpt-5", input_tokens=100, output_tokens=50, duration_s=1.5)
        names = self._metric_names()
        self.assertIn("gen_ai.client.token.usage", names)
        self.assertIn("gen_ai.client.operation.duration", names)

    def test_record_tool_metrics(self) -> None:
        metrics_mod.record_tool_metrics(tool_name="shell", duration_s=0.5, status="success")
        self.assertIn("elephant.tool.duration", self._metric_names())

    def test_record_turn_metrics(self) -> None:
        metrics_mod.record_turn_metrics(episode_id="ep1", duration_s=2.0, trigger_type="user_input")
        self.assertIn("elephant.kernel.turn.duration", self._metric_names())

    def test_duration_timer(self) -> None:
        timer = metrics_mod.DurationTimer()
        time.sleep(0.01)
        elapsed = timer.elapsed()
        self.assertGreater(elapsed, 0.005)


class SetupTests(unittest.TestCase):
    def test_setup_is_idempotent(self) -> None:
        import packages.observability.setup as setup_mod
        original = setup_mod._initialized
        setup_mod._initialized = False
        try:
            from packages.observability import setup_observability
            setup_observability(service_name="test-1")
            setup_observability(service_name="test-2")
        finally:
            setup_mod._initialized = original


class InstrumentorTests(unittest.TestCase):
    def test_instrument_and_uninstrument(self) -> None:
        from packages.observability.instrumentor import instrument, uninstrument, _instrumented, _originals
        import packages.observability.instrumentor as inst_mod

        inst_mod._instrumented = False
        inst_mod._originals.clear()
        try:
            from packages.kernel.runtime_impl import KernelService
            original_run = KernelService.run

            instrument()
            self.assertIsNot(KernelService.run, original_run)

            uninstrument()
            self.assertIs(KernelService.run, original_run)
        finally:
            inst_mod._instrumented = False
            inst_mod._originals.clear()

    def test_instrument_is_idempotent(self) -> None:
        from packages.observability.instrumentor import instrument, uninstrument
        import packages.observability.instrumentor as inst_mod
        inst_mod._instrumented = False
        inst_mod._originals.clear()
        try:
            from packages.kernel.runtime_impl import KernelService
            instrument()
            run_after_first = KernelService.run
            instrument()
            self.assertIs(KernelService.run, run_after_first)
        finally:
            from packages.observability.instrumentor import uninstrument
            uninstrument()
            inst_mod._instrumented = False
            inst_mod._originals.clear()


if __name__ == "__main__":
    unittest.main()
