"""Unit tests for packages.tools.runtime core types and wiring logic."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools.runtime import (
    CallableApprovalGateway,
    InMemoryToolExecutor,
    InMemoryToolRegistry,
    ToolApprovalResult,
    ToolDefinition,
    ToolInvocation,
    ToolLifecycleEvent,
    ToolRuntime,
    ToolRuntimeContext,
    ToolSideEffectMetadata,
    ToolAvailability,
    _approval_phase,
    _classification_detail,
    _default_context,
    build_tool_fallback_prompt,
)


def _make_definition(**overrides: object) -> ToolDefinition:
    defaults: dict[str, object] = {
        "tool_id": "test.tool",
        "display_name": "Test Tool",
        "version": "1.0.0",
        "description": "A test tool.",
    }
    defaults.update(overrides)
    return ToolDefinition(**defaults)  # type: ignore[arg-type]


def _make_invocation(**overrides: object) -> ToolInvocation:
    defaults: dict[str, object] = {
        "invocation_id": "inv-1",
        "tool_id": "test.tool",
        "session_id": "sess-1",
        "context": ToolRuntimeContext(cwd=Path.cwd()),
    }
    defaults.update(overrides)
    return ToolInvocation(**defaults)  # type: ignore[arg-type]


# ── ToolDefinition ──────────────────────────────────────────────────────


class TestToolDefinition(unittest.TestCase):
    def test_available_property(self) -> None:
        defn = _make_definition(availability=ToolAvailability(is_available=True))
        self.assertTrue(defn.available)
        defn = _make_definition(availability=ToolAvailability(is_available=False, reason="missing"))
        self.assertFalse(defn.available)

    def test_visible_to_both(self) -> None:
        defn = _make_definition(audience="both")
        self.assertTrue(defn.visible_to("model"))
        self.assertTrue(defn.visible_to("operator"))

    def test_visible_to_model_only(self) -> None:
        defn = _make_definition(audience="model")
        self.assertTrue(defn.visible_to("model"))
        self.assertFalse(defn.visible_to("operator"))

    def test_required_fields(self) -> None:
        defn = _make_definition(schema={"required": ["code", "mode"]})
        self.assertEqual(defn.required_fields, ("code", "mode"))

    def test_required_fields_empty(self) -> None:
        defn = _make_definition(schema={})
        self.assertEqual(defn.required_fields, ())

    def test_required_fields_invalid_type(self) -> None:
        defn = _make_definition(schema={"required": "not a list"})
        self.assertEqual(defn.required_fields, ())

    def test_model_function_schema(self) -> None:
        defn = _make_definition(schema={"type": "object", "properties": {"x": {"type": "string"}}})
        schema = defn.model_function_schema()
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "test.tool")
        self.assertIn("properties", schema["function"]["parameters"])

    def test_prompt_summary(self) -> None:
        defn = _make_definition(
            description="Does things.",
            schema={"required": ["code"], "properties": {"code": {"type": "string", "description": "The code"}}},
        )
        summary = defn.prompt_summary()
        self.assertIn("test.tool", summary)
        self.assertIn("code", summary)
        self.assertIn("Does things.", summary)


# ── InMemoryToolRegistry ────────────────────────────────────────────────


class TestInMemoryToolRegistry(unittest.TestCase):
    def test_register_and_get(self) -> None:
        registry = InMemoryToolRegistry()
        defn = _make_definition()
        registry.register(defn)
        self.assertEqual(registry.get("test.tool"), defn)

    def test_get_missing_returns_none(self) -> None:
        registry = InMemoryToolRegistry()
        self.assertIsNone(registry.get("no.such.tool"))

    def test_remove(self) -> None:
        registry = InMemoryToolRegistry()
        defn = _make_definition()
        registry.register(defn)
        self.assertTrue(registry.remove("test.tool"))
        self.assertIsNone(registry.get("test.tool"))

    def test_remove_missing_returns_false(self) -> None:
        registry = InMemoryToolRegistry()
        self.assertFalse(registry.remove("no.such.tool"))

    def test_list(self) -> None:
        registry = InMemoryToolRegistry()
        a = _make_definition(tool_id="a")
        b = _make_definition(tool_id="b")
        registry.register(a)
        registry.register(b)
        ids = {d.tool_id for d in registry.list()}
        self.assertEqual(ids, {"a", "b"})


# ── InMemoryToolExecutor ────────────────────────────────────────────────


class TestInMemoryToolExecutor(unittest.TestCase):
    def test_bind_and_execute(self) -> None:
        executor = InMemoryToolExecutor()
        defn = _make_definition()
        inv = _make_invocation()
        executor.bind("test.tool", lambda _: {"summary": "ok", "outcome": "success"})
        result = executor.execute(defn, inv)
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.summary, "ok")

    def test_execute_missing_handler_raises(self) -> None:
        executor = InMemoryToolExecutor()
        defn = _make_definition()
        inv = _make_invocation()
        with self.assertRaises(KeyError):
            executor.execute(defn, inv)

    def test_unbind(self) -> None:
        executor = InMemoryToolExecutor()
        executor.bind("test.tool", lambda _: {"summary": "ok"})
        self.assertTrue(executor.unbind("test.tool"))
        self.assertFalse(executor.unbind("test.tool"))


# ── CallableApprovalGateway ─────────────────────────────────────────────


class TestCallableApprovalGateway(unittest.TestCase):
    def test_approved(self) -> None:
        gateway = CallableApprovalGateway(policy=lambda _d, _i: True)
        result = gateway.authorize(_make_definition(), _make_invocation())
        self.assertEqual(result.decision, "approved")
        self.assertTrue(result.approved)

    def test_denied(self) -> None:
        gateway = CallableApprovalGateway(policy=lambda _d, _i: False)
        result = gateway.authorize(_make_definition(), _make_invocation())
        self.assertEqual(result.decision, "denied")
        self.assertFalse(result.approved)


# ── ToolApprovalResult ──────────────────────────────────────────────────


class TestToolApprovalResult(unittest.TestCase):
    def test_approved_property(self) -> None:
        r = ToolApprovalResult(decision="approved", risk_class="low")
        self.assertTrue(r.approved)

    def test_denied_property(self) -> None:
        r = ToolApprovalResult(decision="denied", risk_class="high")
        self.assertFalse(r.approved)

    def test_deferred_property(self) -> None:
        r = ToolApprovalResult(decision="deferred", risk_class="medium")
        self.assertFalse(r.approved)


# ── Helper functions ────────────────────────────────────────────────────


class TestApprovalPhase(unittest.TestCase):
    def test_approved(self) -> None:
        self.assertEqual(
            _approval_phase(ToolApprovalResult(decision="approved", risk_class="low")),
            "approval.granted",
        )

    def test_denied(self) -> None:
        self.assertEqual(
            _approval_phase(ToolApprovalResult(decision="denied", risk_class="low")),
            "approval.denied",
        )

    def test_deferred(self) -> None:
        self.assertEqual(
            _approval_phase(ToolApprovalResult(decision="deferred", risk_class="low")),
            "approval.deferred",
        )


class TestClassificationDetail(unittest.TestCase):
    def test_includes_tool_id(self) -> None:
        defn = _make_definition()
        approval = ToolApprovalResult(decision="approved", risk_class="low")
        detail = _classification_detail(defn, approval)
        self.assertIn("test.tool", detail)
        self.assertIn("approved", detail)


class TestDefaultContext(unittest.TestCase):
    def test_returns_context_with_cwd(self) -> None:
        ctx = _default_context("sess-1", "model")
        self.assertEqual(ctx.surface_id, "session:sess-1")
        self.assertEqual(ctx.requester, "model")


# ── ToolRuntime ─────────────────────────────────────────────────────────


class TestToolRuntimeLifecycle(unittest.TestCase):
    def test_register_and_describe(self) -> None:
        runtime = ToolRuntime()
        defn = _make_definition()
        runtime.register_tool(defn)
        self.assertEqual(runtime.describe("test.tool"), defn)

    def test_describe_missing_returns_none(self) -> None:
        runtime = ToolRuntime()
        self.assertIsNone(runtime.describe("no.such.tool"))

    def test_list_tools(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(_make_definition(tool_id="a"))
        runtime.register_tool(_make_definition(tool_id="b", enabled=False))
        self.assertEqual(len(runtime.list_tools()), 2)
        self.assertEqual(len(runtime.list_tools(enabled_only=True)), 1)

    def test_list_tools_audience_filter(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(_make_definition(tool_id="a", audience="model"))
        runtime.register_tool(_make_definition(tool_id="b", audience="operator"))
        runtime.register_tool(_make_definition(tool_id="c", audience="both"))
        model_tools = runtime.list_tools(audience="model")
        ids = {t.tool_id for t in model_tools}
        self.assertIn("a", ids)
        self.assertIn("c", ids)
        self.assertNotIn("b", ids)

    def test_list_tools_available_only(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(
            _make_definition(tool_id="a", availability=ToolAvailability(is_available=False))
        )
        runtime.register_tool(_make_definition(tool_id="b"))
        self.assertEqual(len(runtime.list_tools(available_only=True)), 1)

    def test_set_enabled(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(_make_definition(tool_id="a", enabled=True))
        updated = runtime.set_enabled("a", False)
        self.assertFalse(updated.enabled)
        self.assertFalse(runtime.describe("a").enabled)  # type: ignore[union-attr]

    def test_set_enabled_missing_raises(self) -> None:
        runtime = ToolRuntime()
        with self.assertRaises(KeyError):
            runtime.set_enabled("no.such.tool", True)

    def test_unregister_tool(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(_make_definition(tool_id="a"))
        runtime.unregister_tool("a")
        self.assertIsNone(runtime.describe("a"))

    def test_unregister_missing_raises(self) -> None:
        runtime = ToolRuntime()
        with self.assertRaises(KeyError):
            runtime.unregister_tool("no.such.tool")

    def test_invoke_approved(self) -> None:
        runtime = ToolRuntime()
        defn = _make_definition()
        runtime.register_tool(defn, handler=lambda _: {"summary": "done"})
        result = runtime.invoke("test.tool", {}, session_id="sess-1")
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.summary, "done")

    def test_invoke_disabled_raises(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(_make_definition(enabled=False))
        with self.assertRaises(ValueError) as ctx:
            runtime.invoke("test.tool", {}, session_id="sess-1")
        self.assertIn("disabled", str(ctx.exception))

    def test_invoke_unavailable_raises(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(
            _make_definition(availability=ToolAvailability(is_available=False, reason="no backend"))
        )
        with self.assertRaises(ValueError) as ctx:
            runtime.invoke("test.tool", {}, session_id="sess-1")
        self.assertIn("unavailable", str(ctx.exception))

    def test_invoke_not_registered_raises(self) -> None:
        runtime = ToolRuntime()
        with self.assertRaises(KeyError):
            runtime.invoke("no.such.tool", {}, session_id="sess-1")

    def test_invoke_denied_by_gateway(self) -> None:
        gateway = CallableApprovalGateway(policy=lambda _d, _i: False)
        runtime = ToolRuntime(approval_gateway=gateway)
        runtime.register_tool(_make_definition(), handler=lambda _: {"summary": "should not run"})
        result = runtime.invoke("test.tool", {}, session_id="sess-1")
        self.assertEqual(result.outcome, "blocked")

    def test_invoke_no_approval_gateway_auto_approves(self) -> None:
        runtime = ToolRuntime(approval_gateway=None)
        runtime.register_tool(_make_definition(), handler=lambda _: {"summary": "ok"})
        result = runtime.invoke("test.tool", {}, session_id="sess-1")
        self.assertEqual(result.outcome, "success")

    def test_invoke_approval_class_none_auto_approves(self) -> None:
        runtime = ToolRuntime(approval_gateway=CallableApprovalGateway(policy=lambda _d, _i: False))
        defn = _make_definition(
            side_effects=ToolSideEffectMetadata(approval_class="none")
        )
        runtime.register_tool(defn, handler=lambda _: {"summary": "ok"})
        result = runtime.invoke("test.tool", {}, session_id="sess-1")
        # approval_class=none bypasses the gateway
        self.assertEqual(result.outcome, "success")

    def test_invoke_visible_to_check(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(_make_definition(audience="operator"))
        with self.assertRaises(PermissionError):
            runtime.invoke("test.tool", {}, session_id="sess-1", requester="model")

    def test_invoke_emits_lifecycle_events(self) -> None:
        runtime = ToolRuntime()
        events: list[ToolLifecycleEvent] = []
        runtime.subscribe(events.append)
        runtime.register_tool(_make_definition(), handler=lambda _: {"summary": "ok"})
        runtime.invoke("test.tool", {}, session_id="sess-1")
        phases = [e.phase for e in events]
        self.assertIn("requested", phases)
        self.assertIn("classified", phases)
        self.assertIn("approval.granted", phases)
        self.assertIn("execution.started", phases)
        self.assertIn("execution.completed", phases)

    def test_invoke_records_execution(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(_make_definition(), handler=lambda _: {"summary": "ok"})
        runtime.invoke("test.tool", {}, session_id="sess-1")
        executions = runtime.list_executions()
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].result.summary, "ok")

    def test_invoke_handler_exception_recorded(self) -> None:
        runtime = ToolRuntime()
        runtime.register_tool(_make_definition(), handler=lambda _: 1 / 0)
        with self.assertRaises(ZeroDivisionError):
            runtime.invoke("test.tool", {}, session_id="sess-1")
        executions = runtime.list_executions()
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].result.outcome, "error")

    def test_subscribe_and_unsubscribe(self) -> None:
        runtime = ToolRuntime()
        events: list[ToolLifecycleEvent] = []
        unsubscribe = runtime.subscribe(events.append)
        runtime.register_tool(_make_definition(), handler=lambda _: {"summary": "ok"})
        runtime.invoke("test.tool", {}, session_id="sess-1")
        self.assertGreater(len(events), 0)
        events.clear()
        unsubscribe()
        runtime.invoke("test.tool", {}, session_id="sess-1")
        self.assertEqual(len(events), 0)

    def test_load_manifest(self) -> None:
        runtime = ToolRuntime()
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(json.dumps({
                "tools": [{
                    "tool_id": "manifest.tool",
                    "display_name": "Manifest Tool",
                    "version": "1.0.0",
                    "description": "from manifest",
                }]
            }))
            manifest = runtime.load_manifest(manifest_path)
            self.assertEqual(len(manifest.tools), 1)
            self.assertIsNotNone(runtime.describe("manifest.tool"))
        loads = runtime.list_manifest_loads()
        self.assertEqual(len(loads), 1)


# ── build_tool_fallback_prompt ──────────────────────────────────────────


class TestBuildToolFallbackPrompt(unittest.TestCase):
    def test_empty_tools_returns_empty(self) -> None:
        self.assertEqual(build_tool_fallback_prompt(()), "")

    def test_produces_non_empty_prompt(self) -> None:
        tools = (_make_definition(),)
        prompt = build_tool_fallback_prompt(tools)
        self.assertIn("test.tool", prompt)
        self.assertIn("available-tools", prompt)


if __name__ == "__main__":
    unittest.main()
