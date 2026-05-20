from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools import (
    BuiltinToolDependencies,
    CallableApprovalGateway,
    InMemoryToolExecutor,
    InMemoryToolRegistry,
    ToolRuntime,
    builtin_tool_definitions,
    register_builtin_tools,
)


class _OperatorSurfaceStub:
    def __init__(self) -> None:
        self.inspect_args: dict[str, object] | None = None
        self.plan_args: dict[str, object] | None = None
        self.apply_args: dict[str, object] | None = None

    def inspect_operator(
        self,
        session_id: str,
        *,
        scope: str = "summary",
        probe: bool = False,
        include: tuple[str, ...] = (),
    ):
        self.inspect_args = {
            "session_id": session_id,
            "scope": scope,
            "probe": probe,
            "include": include,
        }
        return {
            "status": "ok",
            "freshness": "probed" if probe else "cached",
            "scope": scope,
            "components": [{"component": "runtime", "state": "ok"}],
        }

    def plan_operator_action(
        self,
        session_id: str,
        *,
        action: str,
        base_snapshot_id: str = "",
        parameters=None,
    ):
        self.plan_args = {
            "session_id": session_id,
            "action": action,
            "base_snapshot_id": base_snapshot_id,
            "parameters": parameters or {},
        }
        return {
            "planId": "operator-plan:test",
            "action": action,
            "baseSnapshotId": base_snapshot_id,
            "requiredApproval": "strict",
            "expectedChanges": ["restart daemon"],
        }

    def apply_operator_action(
        self,
        session_id: str,
        *,
        plan_id: str,
        confirmation_token: str = "",
        parameters=None,
    ):
        self.apply_args = {
            "session_id": session_id,
            "plan_id": plan_id,
            "confirmation_token": confirmation_token,
            "parameters": parameters or {},
        }
        return {
            "receiptId": "operator-receipt:test",
            "planId": plan_id,
            "result": "applied",
            "verification": {"status": "ok"},
        }


class OperatorToolsTest(unittest.TestCase):
    def _runtime(self, surface: _OperatorSurfaceStub | None) -> ToolRuntime:
        runtime = ToolRuntime(
            registry=InMemoryToolRegistry(),
            executor=InMemoryToolExecutor(),
            approval_gateway=CallableApprovalGateway(lambda *_: True),
        )
        register_builtin_tools(
            runtime,
            enabled_overrides={},
            dependencies=BuiltinToolDependencies(cwd=Path("/tmp"), operator_surface=surface),
        )
        return runtime

    def test_operator_tool_definitions_have_expected_visibility(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions(
                {},
                dependencies=BuiltinToolDependencies(cwd=Path("/tmp"), operator_surface=_OperatorSurfaceStub()),
            )
        }

        self.assertEqual(definitions["tool.operator.inspect"].audience, "both")
        self.assertEqual(definitions["tool.operator.inspect"].side_effects.writes_state, False)
        self.assertEqual(definitions["tool.operator.manage"].audience, "operator")
        self.assertEqual(definitions["tool.operator.manage"].side_effects.approval_class, "strict")
        self.assertIn("plan", definitions["tool.operator.manage"].schema["properties"]["phase"]["enum"])
        self.assertIn("apply", definitions["tool.operator.manage"].schema["properties"]["phase"]["enum"])

    def test_operator_tools_are_unavailable_without_surface(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions({}, dependencies=BuiltinToolDependencies(cwd=Path("/tmp")))
        }

        self.assertFalse(definitions["tool.operator.inspect"].available)
        self.assertFalse(definitions["tool.operator.manage"].available)
        self.assertIn("Operator management is not configured", definitions["tool.operator.inspect"].availability.reason or "")

    def test_operator_inspect_invokes_surface_with_probe_and_include(self) -> None:
        surface = _OperatorSurfaceStub()
        runtime = self._runtime(surface)

        result = runtime.invoke(
            "tool.operator.inspect",
            {"scope": "provider", "probe": True, "include": "daemon|tools"},
            session_id="session-operator",
            requester="model",
        )

        self.assertEqual(result.outcome, "success")
        self.assertIn('"scope": "provider"', result.summary)
        self.assertEqual(surface.inspect_args["probe"], True)
        self.assertEqual(surface.inspect_args["include"], ("daemon", "tools"))

    def test_operator_manage_is_operator_only_and_two_phase(self) -> None:
        surface = _OperatorSurfaceStub()
        runtime = self._runtime(surface)

        with self.assertRaises(PermissionError):
            runtime.invoke(
                "tool.operator.manage",
                {"phase": "plan", "action": "daemon_restart"},
                session_id="session-operator",
                requester="model",
            )

        plan = runtime.invoke(
            "tool.operator.manage",
            {
                "phase": "plan",
                "action": "daemon_restart",
                "base_snapshot_id": "operator-snapshot:test",
            },
            session_id="session-operator",
            requester="operator",
        )
        receipt = runtime.invoke(
            "tool.operator.manage",
            {
                "phase": "apply",
                "plan_id": "operator-plan:test",
                "confirmation_token": "confirm",
            },
            session_id="session-operator",
            requester="operator",
        )

        self.assertIn('"planId": "operator-plan:test"', plan.summary)
        self.assertIn('"receiptId": "operator-receipt:test"', receipt.summary)
        self.assertEqual(surface.plan_args["action"], "daemon_restart")
        self.assertEqual(surface.apply_args["confirmation_token"], "confirm")


if __name__ == "__main__":
    unittest.main()
