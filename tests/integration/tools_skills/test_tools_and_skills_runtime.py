from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from packages.security import SecurityPolicy
from packages.tools import (
    CallableApprovalGateway,
    InMemoryToolExecutor,
    InMemoryToolRegistry,
    JsonToolLoader,
    SecurityApprovalGateway,
    ToolApprovalResult,
    ToolDefinition,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeContext,
    ToolSideEffectMetadata,
    sync_custom_mcp_tools,
)


class _DeferredApprovalGateway:
    def authorize(
        self, definition: ToolDefinition, invocation: ToolInvocation
    ) -> ToolApprovalResult:
        return ToolApprovalResult(
            decision="deferred",
            risk_class=definition.side_effects.risk_class,
            required_controls=("external-review",),
            reason=f"waiting for approval: {invocation.tool_id}",
            approval_token=f"approval:{invocation.invocation_id}",
        )


class _CaptureSink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def emit(self, event) -> None:
        self.records.append(dict(event))


class ToolsAndSkillsIntegrationTest(unittest.TestCase):
    def test_tool_runtime_resolves_canonical_runtime_context_before_execution(
        self,
    ) -> None:
        registry = InMemoryToolRegistry()
        executor = InMemoryToolExecutor()
        runtime = ToolRuntime(
            registry=registry,
            executor=executor,
            approval_gateway=CallableApprovalGateway(lambda *_: True),
            context_resolver=lambda session_id, requester: ToolRuntimeContext(
                cwd=Path("/tmp/tool-context"),
                allowed_roots=(Path("/tmp"), Path("/var/tmp")),
                env={"A": "1"},
                surface_id=f"cli:{session_id}",
                surface_kind="cli",
                requester=requester,
                personal_model_id="you",
                state_id="state:atlas",
                elephant_id="atlas",
            ),
        )
        captured: dict[str, object] = {}
        runtime.register_tool(
            ToolDefinition(
                tool_id="tool.context.inspect",
                display_name="Context Inspect",
                version="1.0.0",
                description="Capture resolved tool runtime context.",
            ),
            handler=lambda invocation: captured.update(
                {
                    "cwd": invocation.context.cwd,
                    "allowed_roots": invocation.context.allowed_roots,
                    "surface_id": invocation.context.surface_id,
                    "state_id": invocation.context.state_id,
                    "personal_model_id": invocation.context.personal_model_id,
                    "elephant_id": invocation.context.elephant_id,
                    "requester": invocation.context.requester,
                }
            )
            or {
                "execution_id": invocation.invocation_id,
                "summary": "captured context",
                "outcome": "success",
            },
        )

        result = runtime.invoke(
            "tool.context.inspect",
            {},
            session_id="session-context",
            requester="operator",
        )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(captured["cwd"], Path("/tmp/tool-context"))
        self.assertEqual(captured["allowed_roots"], (Path("/tmp"), Path("/var/tmp")))
        self.assertEqual(captured["surface_id"], "cli:session-context")
        self.assertEqual(captured["state_id"], "state:atlas")
        self.assertEqual(captured["personal_model_id"], "you")
        self.assertEqual(captured["elephant_id"], "atlas")
        self.assertEqual(captured["requester"], "operator")

    def test_tool_runtime_emits_lifecycle_events_for_successful_invocation(
        self,
    ) -> None:
        registry = InMemoryToolRegistry()
        executor = InMemoryToolExecutor()
        runtime = ToolRuntime(
            registry=registry,
            executor=executor,
            approval_gateway=CallableApprovalGateway(lambda *_: True),
        )
        events = []
        runtime.subscribe(events.append)

        definition = ToolDefinition(
            tool_id="tool.calendar.create",
            display_name="Create Calendar Event",
            version="1.0.0",
            description="Create a calendar event.",
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                categories=("external_write", "calendar"),
            ),
        )
        runtime.register_tool(
            definition,
            handler=lambda invocation: {
                "execution_id": invocation.invocation_id,
                "summary": f"created {invocation.arguments['title']}",
                "outcome": "success",
            },
        )

        result = runtime.invoke(
            "tool.calendar.create",
            {"title": "Design review"},
            session_id="session-1",
        )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(
            [event.phase for event in events],
            [
                "requested",
                "classified",
                "approval.granted",
                "execution.started",
                "execution.completed",
            ],
        )
        self.assertEqual(events[-1].execution.summary, "created Design review")

    def test_tool_runtime_preserves_original_tool_error_in_failed_execution_path(
        self,
    ) -> None:
        registry = InMemoryToolRegistry()
        executor = InMemoryToolExecutor()
        runtime = ToolRuntime(
            registry=registry,
            executor=executor,
            approval_gateway=CallableApprovalGateway(lambda *_: True),
        )
        events = []
        runtime.subscribe(events.append)

        definition = ToolDefinition(
            tool_id="tool.web.read",
            display_name="Web Read",
            version="1.0.0",
            description="Fetch a specific URL.",
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="network",
                touches_network=True,
                categories=("fetch", "web"),
            ),
        )

        def _failing_handler(invocation: ToolInvocation):
            raise RuntimeError(f"fetch failed for {invocation.arguments['url']}")

        runtime.register_tool(definition, handler=_failing_handler)

        with self.assertRaisesRegex(
            RuntimeError, "fetch failed for https://example.com"
        ):
            runtime.invoke(
                "tool.web.read",
                {"url": "https://example.com"},
                session_id="session-error",
            )

        self.assertEqual(
            [event.phase for event in events],
            [
                "requested",
                "classified",
                "approval.granted",
                "execution.started",
                "execution.failed",
            ],
        )
        record = runtime.list_executions()[0]
        self.assertTrue(record.approved)
        self.assertEqual(record.approval.decision, "approved")
        self.assertEqual(record.detail, "fetch failed for https://example.com")

    def test_tool_runtime_registers_and_executes_with_side_effect_metadata(
        self,
    ) -> None:
        registry = InMemoryToolRegistry()
        executor = InMemoryToolExecutor()
        runtime = ToolRuntime(
            registry=registry,
            executor=executor,
            approval_gateway=CallableApprovalGateway(lambda *_: True),
        )

        definition = ToolDefinition(
            tool_id="tool.calendar.create",
            display_name="Create Calendar Event",
            version="1.0.0",
            description="Create a calendar event.",
            schema={"type": "object", "properties": {"title": {"type": "string"}}},
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                touches_network=True,
                categories=("external_write", "calendar"),
            ),
        )

        runtime.register_tool(
            definition,
            handler=lambda invocation: {
                "execution_id": invocation.invocation_id,
                "summary": f"created {invocation.arguments['title']}",
                "outcome": "success",
                "telemetry_event_ids": ("telemetry-1",),
            },
        )

        self.assertEqual(runtime.describe("tool.calendar.create"), definition)
        self.assertEqual(runtime.list_tools(), (definition,))

        result = runtime.invoke(
            "tool.calendar.create",
            {"title": "Design review"},
            session_id="session-1",
        )

        self.assertEqual(result.execution_id, "session-1:tool.calendar.create")
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.summary, "created Design review")
        self.assertEqual(result.side_effects, ("external_write", "calendar"))
        self.assertEqual(result.telemetry_event_ids, ("telemetry-1",))
        self.assertEqual(len(runtime.list_executions()), 1)
        self.assertTrue(runtime.list_executions()[0].approved)
        self.assertEqual(runtime.list_executions()[0].detail, "created Design review")

        disabled = runtime.set_enabled("tool.calendar.create", False)
        self.assertFalse(disabled.enabled)
        self.assertFalse(runtime.describe("tool.calendar.create").enabled)

        reenabled = runtime.set_enabled("tool.calendar.create", True)
        self.assertTrue(reenabled.enabled)
        self.assertTrue(runtime.describe("tool.calendar.create").enabled)

    def test_tool_runtime_blocks_model_invocation_of_operator_only_tools(self) -> None:
        registry = InMemoryToolRegistry()
        executor = InMemoryToolExecutor()
        runtime = ToolRuntime(
            registry=registry,
            executor=executor,
            approval_gateway=CallableApprovalGateway(lambda *_: True),
        )
        runtime.register_tool(
            ToolDefinition(
                tool_id="tool.skill.manage",
                display_name="Skill Manager",
                version="1.0.0",
                description="Operator-only skill mutation surface.",
                audience="operator",
                side_effects=ToolSideEffectMetadata(
                    risk_class="medium",
                    approval_class="standard",
                    writes_state=True,
                    categories=("skill", "manage"),
                ),
            ),
            handler=lambda invocation: {
                "execution_id": invocation.invocation_id,
                "summary": f"{invocation.requester or 'unknown'} handled {invocation.tool_id}",
                "outcome": "success",
            },
        )

        with self.assertRaisesRegex(
            PermissionError, "tool is not visible to model: tool.skill.manage"
        ):
            runtime.invoke(
                "tool.skill.manage",
                {"action": "install", "reference": "github:openai/skills/search-skill"},
                session_id="session-1",
                requester="model",
            )

        result = runtime.invoke(
            "tool.skill.manage",
            {"action": "install", "reference": "github:openai/skills/search-skill"},
            session_id="session-1",
            requester="operator",
        )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.summary, "operator handled tool.skill.manage")

    def test_tool_runtime_records_deferred_approval_without_executing_handler(
        self,
    ) -> None:
        registry = InMemoryToolRegistry()
        executor = InMemoryToolExecutor()
        runtime = ToolRuntime(
            registry=registry,
            executor=executor,
            approval_gateway=_DeferredApprovalGateway(),
        )
        events = []
        runtime.subscribe(events.append)
        handler = mock.Mock(
            return_value={
                "execution_id": "tool:should-not-run",
                "summary": "unexpected",
                "outcome": "success",
            }
        )
        definition = ToolDefinition(
            tool_id="tool.mail.send",
            display_name="Send Mail",
            version="1.0.0",
            description="Send an outbound message.",
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="network",
                touches_network=True,
                categories=("mail", "external_write"),
            ),
        )
        runtime.register_tool(definition, handler=handler)

        result = runtime.invoke(
            "tool.mail.send",
            {"subject": "Status"},
            session_id="session-blocked",
        )

        self.assertEqual(result.outcome, "deferred")
        handler.assert_not_called()
        self.assertEqual(
            [event.phase for event in events],
            ["requested", "classified", "approval.deferred"],
        )
        self.assertEqual(runtime.list_executions()[0].approval.decision, "deferred")
        self.assertFalse(runtime.list_executions()[0].approved)
        pending = runtime.list_pending_approvals(session_id="session-blocked")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].invocation.tool_id, "tool.mail.send")
        self.assertEqual(pending[0].approval_token, "approval:session-blocked:tool.mail.send")

    def test_tool_runtime_can_resume_deferred_invocation_after_explicit_approval(
        self,
    ) -> None:
        registry = InMemoryToolRegistry()
        executor = InMemoryToolExecutor()
        runtime = ToolRuntime(
            registry=registry,
            executor=executor,
            approval_gateway=_DeferredApprovalGateway(),
        )
        events = []
        runtime.subscribe(events.append)
        handler = mock.Mock(
            return_value={
                "execution_id": "tool:approved-run",
                "summary": "sent approved mail",
                "outcome": "success",
            }
        )
        runtime.register_tool(
            ToolDefinition(
                tool_id="tool.mail.send",
                display_name="Send Mail",
                version="1.0.0",
                description="Send an outbound message.",
                side_effects=ToolSideEffectMetadata(
                    risk_class="high",
                    approval_class="network",
                    touches_network=True,
                    categories=("mail", "external_write"),
                ),
            ),
            handler=handler,
        )

        result = runtime.invoke(
            "tool.mail.send",
            {"subject": "Status"},
            session_id="session-approval",
        )
        self.assertEqual(result.outcome, "deferred")
        handler.assert_not_called()

        record = runtime.approve_pending(
            "approval:session-approval:tool.mail.send",
            session_id="session-approval",
            approver="test",
        )

        handler.assert_called_once()
        self.assertEqual(record.result.outcome, "success")
        self.assertEqual(record.result.summary, "sent approved mail")
        self.assertTrue(record.approved)
        self.assertEqual(record.approval.decision, "approved")
        self.assertEqual(runtime.list_pending_approvals(session_id="session-approval"), ())
        self.assertEqual(
            [event.phase for event in events],
            [
                "requested",
                "classified",
                "approval.deferred",
                "approval.granted",
                "execution.started",
                "execution.completed",
            ],
        )

    def test_tool_runtime_can_deny_deferred_invocation_without_executing_handler(
        self,
    ) -> None:
        runtime = ToolRuntime(approval_gateway=_DeferredApprovalGateway())
        handler = mock.Mock(
            return_value={
                "execution_id": "tool:should-not-run",
                "summary": "unexpected",
                "outcome": "success",
            }
        )
        runtime.register_tool(
            ToolDefinition(
                tool_id="tool.mail.send",
                display_name="Send Mail",
                version="1.0.0",
                side_effects=ToolSideEffectMetadata(
                    risk_class="high",
                    approval_class="network",
                    touches_network=True,
                ),
            ),
            handler=handler,
        )

        runtime.invoke("tool.mail.send", {"subject": "Status"}, session_id="session-deny")
        record = runtime.deny_pending(
            "approval:session-deny:tool.mail.send",
            session_id="session-deny",
            approver="test",
        )

        handler.assert_not_called()
        self.assertEqual(record.result.outcome, "blocked")
        self.assertFalse(record.approved)
        self.assertEqual(record.approval.decision, "denied")
        self.assertEqual(runtime.list_pending_approvals(session_id="session-deny"), ())

    def test_security_approval_gateway_can_auto_grant_deferred_reviews(self) -> None:
        sink = _CaptureSink()
        gateway = SecurityApprovalGateway(
            policy=SecurityPolicy.default(),
            telemetry=sink,
            source="cli.tool.runtime",
            auto_approve_deferred=True,
        )
        definition = ToolDefinition(
            tool_id="tool.web.read",
            display_name="Web Read",
            version="1.0.0",
            description="Fetch a specific URL.",
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="network",
                touches_network=True,
                categories=("fetch", "web"),
            ),
        )

        approval = gateway.authorize(
            definition,
            ToolInvocation(
                invocation_id="session-1:tool.web.read",
                tool_id="tool.web.read",
                session_id="session-1",
                arguments={"url": "https://example.com"},
            ),
        )

        self.assertEqual(approval.decision, "approved")
        self.assertEqual(approval.risk_class, "critical")
        self.assertTrue(str(approval.approval_token).startswith("auto:"))
        self.assertTrue(any(record["family"] == "approval" for record in sink.records))

    def test_tool_manifest_loader_discovers_external_tools_and_runtime_feedback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "tools.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "tools": [
                            {
                                "tool_id": "tool.notes.capture",
                                "display_name": "Capture Note",
                                "version": "1.0.0",
                                "description": "Capture a structured note entry.",
                                "side_effects": {
                                    "risk_class": "medium",
                                    "approval_class": "standard",
                                    "writes_state": True,
                                    "categories": ["memory", "notes"],
                                },
                                "metadata": {"kind": "external"},
                                "execution": {
                                    "kind": "structured_result",
                                    "summary_template": "captured {title}",
                                    "execution_id_template": "{session_id}:{tool_id}:external",
                                    "telemetry_event_ids": ["telemetry-tool-notes"],
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            runtime = ToolRuntime(
                approval_gateway=CallableApprovalGateway(lambda *_: True)
            )

            manifest = runtime.load_manifest(manifest_path, loader=JsonToolLoader())
            self.assertEqual(manifest.source_path, str(manifest_path))
            self.assertEqual(
                runtime.describe("tool.notes.capture").provenance, str(manifest_path)
            )
            self.assertEqual(
                runtime.list_manifest_loads()[0].tool_ids, ("tool.notes.capture",)
            )
            self.assertEqual(
                runtime.list_manifest_loads()[0].executable_tool_ids,
                ("tool.notes.capture",),
            )

            result = runtime.invoke(
                "tool.notes.capture",
                {"title": "Operator review"},
                session_id="session-ext",
            )

            self.assertEqual(
                result.execution_id, "session-ext:tool.notes.capture:external"
            )
            self.assertEqual(result.summary, "captured Operator review")
            self.assertEqual(result.telemetry_event_ids, ("telemetry-tool-notes",))
            self.assertEqual(len(runtime.list_executions()), 1)
            self.assertEqual(
                runtime.list_executions()[0].invocation.tool_id, "tool.notes.capture"
            )
            self.assertEqual(
                runtime.list_executions()[0].detail, "captured Operator review"
            )

    def test_tool_manifest_loader_preserves_enable_override_and_records_blocked_invocations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "tools.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "tools": [
                            {
                                "tool_id": "tool.mail.send",
                                "display_name": "Send Mail",
                                "version": "1.0.0",
                                "description": "Send an outbound message.",
                                "side_effects": {
                                    "risk_class": "high",
                                    "approval_class": "standard",
                                    "touches_network": True,
                                    "categories": ["mail", "external_write"],
                                },
                                "execution": {
                                    "kind": "structured_result",
                                    "summary_template": "sent {subject}",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            runtime = ToolRuntime(
                approval_gateway=CallableApprovalGateway(lambda *_: False)
            )
            runtime.load_manifest(manifest_path, loader=JsonToolLoader())
            runtime.set_enabled("tool.mail.send", False)
            runtime.load_manifest(manifest_path, loader=JsonToolLoader())
            self.assertFalse(runtime.describe("tool.mail.send").enabled)

            runtime.set_enabled("tool.mail.send", True)
            result = runtime.invoke(
                "tool.mail.send",
                {"subject": "Status"},
                session_id="session-blocked",
            )
            self.assertEqual(result.outcome, "blocked")
            self.assertEqual(runtime.list_executions()[0].approved, False)
            self.assertEqual(
                runtime.list_executions()[0].detail,
                "blocked by callable approval gateway",
            )

    def test_sync_custom_mcp_tools_registers_model_visible_handlers_and_removes_stale_tools(
        self,
    ) -> None:
        runtime = ToolRuntime(approval_gateway=CallableApprovalGateway(lambda *_: True))
        config = {
            "mcp_servers": {
                "filesystem": {
                    "label": "Filesystem",
                    "transport": "stdio",
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        "/tmp/demo",
                    ],
                    "env": {"ALLOW": "1"},
                    "tools": {
                        "read_file": {
                            "display_name": "Read File",
                            "description": "Read one file from the mounted root.",
                            "family": "filesystem",
                            "risk_class": "medium",
                            "approval_class": "standard",
                            "reads_state": True,
                            "schema": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"],
                            },
                        }
                    },
                }
            }
        }
        observed_calls: list[dict[str, object]] = []

        def fake_call(**kwargs) -> dict[str, object]:
            observed_calls.append(dict(kwargs))
            return {"content": [{"type": "text", "text": "read ok"}]}

        synced = sync_custom_mcp_tools(
            runtime,
            config_path=Path("/tmp/global-config.yaml"),
            config=config,
            cwd=Path("/tmp/tool-root"),
        )
        self.assertEqual(synced, ("mcp.filesystem.read_file",))
        self.assertEqual(
            [
                tool.tool_id
                for tool in runtime.list_tools(
                    audience="model", enabled_only=True, available_only=True
                )
            ],
            ["mcp.filesystem.read_file"],
        )
        self.assertEqual(runtime.list_tools(audience="operator"), ())
        self.assertTrue(
            runtime.describe("mcp.filesystem.read_file").side_effects.reads_state
        )

        with mock.patch(
            "packages.tools.mcp._call_mcp_tool_sync", side_effect=fake_call
        ):
            result = runtime.invoke(
                "mcp.filesystem.read_file",
                {"path": "/tmp/demo.txt"},
                session_id="session-mcp",
            )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.summary, "read ok")
        self.assertEqual(len(observed_calls), 1)
        self.assertEqual(observed_calls[0]["tool_name"], "read_file")
        self.assertEqual(observed_calls[0]["transport"], "stdio")
        self.assertEqual(observed_calls[0]["command"], "npx")
        self.assertEqual(
            observed_calls[0]["args"],
            ("-y", "@modelcontextprotocol/server-filesystem", "/tmp/demo"),
        )
        self.assertEqual(observed_calls[0]["arguments"], {"path": "/tmp/demo.txt"})
        self.assertEqual(observed_calls[0]["cwd"], Path("/tmp/tool-root"))

        disabled_config = {
            **config,
            "mcp_overrides": {"filesystem:read_file": {"enabled": False}},
        }
        sync_custom_mcp_tools(
            runtime,
            config_path=Path("/tmp/global-config.yaml"),
            config=disabled_config,
            cwd=Path("/tmp/tool-root"),
        )
        self.assertFalse(runtime.describe("mcp.filesystem.read_file").enabled)
        self.assertEqual(
            runtime.list_tools(
                audience="model", enabled_only=True, available_only=True
            ),
            (),
        )

        sync_custom_mcp_tools(
            runtime,
            config_path=Path("/tmp/global-config.yaml"),
            config={},
            cwd=Path("/tmp/tool-root"),
        )
        self.assertIsNone(runtime.describe("mcp.filesystem.read_file"))

    def test_sync_custom_mcp_tools_remote_runtime_uses_native_mcp_client_shape(
        self,
    ) -> None:
        runtime = ToolRuntime(approval_gateway=CallableApprovalGateway(lambda *_: True))
        config = {
            "mcp_servers": {
                "remote-demo": {
                    "label": "Remote Demo",
                    "transport": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer demo"},
                    "tools": {
                        "ping": {
                            "display_name": "Ping",
                            "description": "Ping the remote MCP endpoint.",
                            "schema": {
                                "type": "object",
                                "properties": {"message": {"type": "string"}},
                            },
                        }
                    },
                }
            }
        }
        observed_calls: list[dict[str, object]] = []

        def fake_call(**kwargs) -> dict[str, object]:
            observed_calls.append(dict(kwargs))
            return {"content": [{"type": "text", "text": "pong"}]}

        sync_custom_mcp_tools(
            runtime,
            config_path=Path("/tmp/global-config.yaml"),
            config=config,
            cwd=Path("/tmp/tool-root"),
        )

        with mock.patch(
            "packages.tools.mcp._call_mcp_tool_sync", side_effect=fake_call
        ):
            result = runtime.invoke(
                "mcp.remote-demo.ping",
                {"message": "hello"},
                session_id="session-remote-mcp",
            )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.summary, "pong")
        self.assertEqual(observed_calls[0]["headers"], {"Authorization": "Bearer demo"})
        self.assertEqual(observed_calls[0]["transport"], "streamable-http")
        self.assertEqual(observed_calls[0]["url"], "https://example.com/mcp")


if __name__ == "__main__":
    unittest.main()
