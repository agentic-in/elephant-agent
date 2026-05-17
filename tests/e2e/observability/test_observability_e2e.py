"""E2E test: verify traces, metrics, and logs flow through the observability
pipeline to a live monitoring stack (Jaeger + OTel Collector + Prometheus).

Requires the monitoring stack running:
  cd deploy/docker && docker compose -f docker-compose.monitor-stack.yml up -d

Run:  uv run pytest tests/e2e/observability/test_observability_e2e.py -v -s
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
import logging
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import packages.observability.setup as setup_mod
import packages.observability.logger as logger_mod

JAEGER_QUERY = "http://localhost:16686"
PROMETHEUS_QUERY = "http://localhost:9090"
OTLP_ENDPOINT = "http://localhost:4317"


def _stack_available() -> bool:
    try:
        urllib.request.urlopen(f"{JAEGER_QUERY}/api/services", timeout=2)
        urllib.request.urlopen(f"{PROMETHEUS_QUERY}/-/ready", timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(_stack_available(), "Monitoring stack not running (need Jaeger + Prometheus on localhost)")
class ObservabilityE2ETest(unittest.TestCase):

    def setUp(self) -> None:
        setup_mod._initialized = False
        logger_mod._configured = False
        self.tmpdir = TemporaryDirectory()
        self.state_dir = self.tmpdir.name

        from packages.observability import setup_observability
        setup_observability(
            service_name="elephant-agent-e2e-test",
            log_level="DEBUG",
            state_dir=self.state_dir,
            otel_endpoint=OTLP_ENDPOINT,
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()
        root = logging.getLogger("elephant")
        for h in root.handlers[:]:
            root.removeHandler(h)

    def test_traces_metrics_and_logs(self) -> None:
        from packages.observability.context import TraceContext, set_context
        from packages.observability.spans import (
            trace_kernel_turn,
            trace_model_call,
            trace_tool_execution,
            record_token_usage,
        )
        from packages.observability.metrics import (
            record_model_metrics,
            record_tool_metrics,
            record_turn_metrics,
        )
        from packages.observability.logger import get_logger

        logger = get_logger("e2e")

        set_context(TraceContext(episode_id="ep-e2e", loop_id="lp-e2e", request_id="req-e2e"))

        with trace_kernel_turn(episode_id="ep-e2e", loop_id="lp-e2e", trigger_type="e2e_test"):
            logger.info("kernel turn started: episode=ep-e2e")

            with trace_model_call(provider_id="test-provider", model_id="test-model-e2e", episode_id="ep-e2e") as span:
                time.sleep(0.01)
                record_token_usage(span, input_tokens=200, output_tokens=100, cache_read_tokens=50)

            with trace_tool_execution(tool_name="e2e_calculator", episode_id="ep-e2e"):
                time.sleep(0.01)

            with trace_model_call(provider_id="test-provider", model_id="test-model-e2e", episode_id="ep-e2e") as span:
                time.sleep(0.01)
                record_token_usage(span, input_tokens=300, output_tokens=150)

            logger.info("kernel turn completing: tools=1 model_calls=2")

        record_model_metrics(provider_id="test-provider", model_id="test-model-e2e", input_tokens=500, output_tokens=250, duration_s=0.5)
        record_tool_metrics(tool_name="e2e_calculator", duration_s=0.02, status="success")
        record_turn_metrics(episode_id="ep-e2e", duration_s=0.6, trigger_type="e2e_test")
        logger.info("kernel turn completed: episode=ep-e2e duration=0.60s")

        from opentelemetry import trace, metrics
        tp = trace.get_tracer_provider()
        if hasattr(tp, "force_flush"):
            tp.force_flush()
        mp = metrics.get_meter_provider()
        if hasattr(mp, "force_flush"):
            mp.force_flush()

        time.sleep(5)

        # ---- TRACES (Jaeger) ----
        print("\n--- Traces (Jaeger) ---")
        traces_url = f"{JAEGER_QUERY}/api/traces?service=elephant-agent-e2e-test&limit=5"
        resp = urllib.request.urlopen(traces_url, timeout=5)
        traces_data = json.loads(resp.read())
        traces = traces_data.get("data", [])
        self.assertGreater(len(traces), 0, "No traces found in Jaeger")

        all_spans = [span for t in traces for span in t.get("spans", [])]
        operations = [s.get("operationName", "") for s in all_spans]
        print(f"  Traces: {len(traces)}, Spans: {len(all_spans)}")
        print(f"  Operations: {operations}")

        self.assertTrue(any("invoke_agent" in op for op in operations), f"No invoke_agent span: {operations}")
        self.assertTrue(any("chat" in op for op in operations), f"No chat span: {operations}")
        self.assertTrue(any("execute_tool" in op for op in operations), f"No execute_tool span: {operations}")

        chat_spans = [s for s in all_spans if "chat" in s.get("operationName", "")]
        tags = {tag["key"]: tag["value"] for tag in chat_spans[0].get("tags", [])}
        self.assertEqual(tags.get("gen_ai.request.model"), "test-model-e2e")
        print(f"  chat span: model={tags.get('gen_ai.request.model')}, "
              f"input_tokens={tags.get('gen_ai.usage.input_tokens')}, "
              f"output_tokens={tags.get('gen_ai.usage.output_tokens')}")

        # ---- METRICS (Prometheus) ----
        print("\n--- Metrics (Prometheus) ---")
        metric_queries = [
            ("gen_ai_client_token_usage_count", "gen_ai.client.token.usage"),
            ("gen_ai_client_operation_duration_count", "gen_ai.client.operation.duration"),
            ("elephant_tool_duration_count", "elephant.tool.duration"),
            ("elephant_kernel_turn_duration_count", "elephant.kernel.turn.duration"),
        ]
        for prom_query, display_name in metric_queries:
            query_url = f"{PROMETHEUS_QUERY}/api/v1/query?query={prom_query}"
            try:
                resp = urllib.request.urlopen(query_url, timeout=5)
                prom_data = json.loads(resp.read())
                results = prom_data.get("data", {}).get("result", [])
                if results:
                    value = results[0].get("value", [None, "0"])[1]
                    print(f"  {display_name}: count={value}")
                else:
                    print(f"  {display_name}: no data yet")
            except Exception as e:
                print(f"  {display_name}: query failed ({e})")

        # ---- LOGS (local file) ----
        print("\n--- Logs (local file) ---")
        log_file = Path(self.state_dir) / "logs" / "elephant.log"
        self.assertTrue(log_file.exists(), f"Log file not found at {log_file}")
        log_lines = [json.loads(line) for line in log_file.read_text().strip().split("\n") if line.strip()]
        self.assertGreater(len(log_lines), 0, "No log entries")

        episode_logs = [l for l in log_lines if l.get("episode_id") == "ep-e2e"]
        self.assertGreater(len(episode_logs), 0, "No logs with episode_id=ep-e2e")
        self.assertTrue(all(l.get("trace_id") for l in episode_logs), "Some entries missing trace_id")
        print(f"  Total entries: {len(log_lines)}, with episode_id: {len(episode_logs)}")

        for entry in log_lines:
            print(f"  [{entry.get('level')}] trace={entry.get('trace_id','')[:8]} "
                  f"episode={entry.get('episode_id')} msg={entry.get('msg','')[:80]}")

        print(f"\n  Jaeger UI: {JAEGER_QUERY}/search?service=elephant-agent-e2e-test")
        print(f"  Prometheus: {PROMETHEUS_QUERY}/graph")


if __name__ == "__main__":
    unittest.main()
