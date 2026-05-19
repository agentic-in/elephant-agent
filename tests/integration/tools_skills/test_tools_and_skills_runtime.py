from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from packages.contracts import State
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
from packages.skills import (
    InMemorySkillCatalog,
    JsonSkillLoader,
    SkillActivationContext,
    SkillDefinition,
    SkillDependency,
    SkillHub,
    SkillHubSource,
    SkillRuntime,
    SkillScope,
    builtin_elephant_skill_source_root,
    builtin_prompt_skill_catalog_entries,
    builtin_site_skill_catalog_entries,
    builtin_skill_catalog,
    builtin_skill_catalog_entries,
    builtin_skill_definitions,
    builtin_skill_hub_entries,
    build_installed_skill_provenance,
    build_public_skill_source_descriptor,
    build_skillhub_site_catalog,
    default_skill_hub_sources,
    install_bucket_for_source_descriptor,
    installed_skill_provenance_from_metadata,
    load_skill_package_definition,
    materialize_skill_package,
    public_skill_source_descriptor_from_metadata,
    skill_provenance_fields,
)


class _DeferredApprovalGateway:
    def authorize(self, definition: ToolDefinition, invocation: ToolInvocation) -> ToolApprovalResult:
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
            handler=lambda invocation: (
                captured.update(
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
                }
            ),
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

        with self.assertRaisesRegex(RuntimeError, "fetch failed for https://example.com"):
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

        with self.assertRaisesRegex(PermissionError, "tool is not visible to model: tool.skill.manage"):
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

            runtime = ToolRuntime(approval_gateway=CallableApprovalGateway(lambda *_: True))

            manifest = runtime.load_manifest(manifest_path, loader=JsonToolLoader())
            self.assertEqual(manifest.source_path, str(manifest_path))
            self.assertEqual(runtime.describe("tool.notes.capture").provenance, str(manifest_path))
            self.assertEqual(runtime.list_manifest_loads()[0].tool_ids, ("tool.notes.capture",))
            self.assertEqual(
                runtime.list_manifest_loads()[0].executable_tool_ids,
                ("tool.notes.capture",),
            )

            result = runtime.invoke(
                "tool.notes.capture",
                {"title": "Operator review"},
                session_id="session-ext",
            )

            self.assertEqual(result.execution_id, "session-ext:tool.notes.capture:external")
            self.assertEqual(result.summary, "captured Operator review")
            self.assertEqual(result.telemetry_event_ids, ("telemetry-tool-notes",))
            self.assertEqual(len(runtime.list_executions()), 1)
            self.assertEqual(runtime.list_executions()[0].invocation.tool_id, "tool.notes.capture")
            self.assertEqual(runtime.list_executions()[0].detail, "captured Operator review")

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

            runtime = ToolRuntime(approval_gateway=CallableApprovalGateway(lambda *_: False))
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
        observed_commands: list[tuple[list[str], dict[str, object]]] = []

        def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
            observed_commands.append((command, kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"content": [{"type": "text", "text": "read ok"}]}),
                stderr="",
            )

        synced = sync_custom_mcp_tools(
            runtime,
            config_path=Path("/tmp/global-config.yaml"),
            config=config,
            cwd=Path("/tmp/tool-root"),
        )
        self.assertEqual(synced, ("mcp.filesystem.read_file",))
        self.assertEqual(
            [tool.tool_id for tool in runtime.list_tools(audience="model", enabled_only=True, available_only=True)],
            ["mcp.filesystem.read_file"],
        )
        self.assertEqual(runtime.list_tools(audience="operator"), ())
        self.assertTrue(runtime.describe("mcp.filesystem.read_file").side_effects.reads_state)

        with mock.patch("packages.tools.mcp.subprocess.run", side_effect=fake_run):
            result = runtime.invoke(
                "mcp.filesystem.read_file",
                {"path": "/tmp/demo.txt"},
                session_id="session-mcp",
            )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.summary, "read ok")
        self.assertEqual(len(observed_commands), 1)
        command, kwargs = observed_commands[0]
        self.assertIn("mcporter", command)
        self.assertIn("call", command)
        self.assertIn("--stdio", command)
        self.assertIn("read_file", command)
        self.assertEqual(kwargs["cwd"], Path("/tmp/tool-root"))
        self.assertIn("--args", command)
        serialized_arguments = command[command.index("--args") + 1]
        self.assertEqual(json.loads(serialized_arguments), {"path": "/tmp/demo.txt"})

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
            runtime.list_tools(audience="model", enabled_only=True, available_only=True),
            (),
        )

        sync_custom_mcp_tools(
            runtime,
            config_path=Path("/tmp/global-config.yaml"),
            config={},
            cwd=Path("/tmp/tool-root"),
        )
        self.assertIsNone(runtime.describe("mcp.filesystem.read_file"))

    def test_sync_custom_mcp_tools_remote_runtime_uses_mcporter_config_shape(
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
        observed_remote_config: dict[str, Any] = {}

        def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
            config_path = Path(command[command.index("--config") + 1])
            observed_remote_config.update(json.loads(config_path.read_text(encoding="utf-8")))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"content": [{"type": "text", "text": "pong"}]}),
                stderr="",
            )

        sync_custom_mcp_tools(
            runtime,
            config_path=Path("/tmp/global-config.yaml"),
            config=config,
            cwd=Path("/tmp/tool-root"),
        )

        with mock.patch("packages.tools.mcp.subprocess.run", side_effect=fake_run):
            result = runtime.invoke(
                "mcp.remote-demo.ping",
                {"message": "hello"},
                session_id="session-remote-mcp",
            )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.summary, "pong")
        self.assertEqual(
            observed_remote_config["mcpServers"]["remote-demo"]["headers"]["Authorization"],
            "Bearer demo",
        )
        self.assertEqual(
            observed_remote_config["mcpServers"]["remote-demo"]["transportType"],
            "streamable-http",
        )
        self.assertEqual(
            observed_remote_config["mcpServers"]["remote-demo"]["url"],
            "https://example.com/mcp",
        )

    def test_skill_loader_resolves_scope_and_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "skills.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "skills": [
                            {
                                "skill_id": "skill.write-helper",
                                "display_name": "Write Helper",
                                "version": "1.0.0",
                                "summary": "Provides writing heuristics.",
                                "scope": {
                                    "personal_model_ids": ["you"],
                                    "state_ids": ["state:elephant-a"],
                                    "surface_kinds": ["cli"],
                                    "modes": ["companion"],
                                },
                                "metadata": {"topic": "test.writing.preference"},
                            },
                            {
                                "skill_id": "skill.voice-helper",
                                "display_name": "Voice Helper",
                                "version": "1.0.0",
                                "summary": "Provides voice turn-taking heuristics.",
                                "scope": {
                                    "personal_model_ids": ["you"],
                                    "surface_kinds": ["cli"],
                                    "modes": ["companion"],
                                },
                                "dependencies": [{"skill_id": "skill.write-helper", "required": True}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            catalog = InMemorySkillCatalog()
            runtime = SkillRuntime(
                catalog=catalog,
                context_resolver=lambda session_id: SkillActivationContext(
                    personal_model_id="you",
                    state_id="state:elephant-a",
                    surface_id=f"cli:{session_id}",
                    surface_kind="cli",
                    mode="companion",
                ),
            )

            manifest = runtime.load_manifest(manifest_path, loader=JsonSkillLoader())
            self.assertEqual(manifest.source_path, str(manifest_path))
            self.assertEqual(len(manifest.skills), 2)
            self.assertEqual(runtime.list_skills(), manifest.skills)
            self.assertEqual(
                runtime.list_manifest_loads()[0].skill_ids,
                ("skill.write-helper", "skill.voice-helper"),
            )
            self.assertEqual(
                tuple(
                    skill.skill_id
                    for skill in runtime.resolve_for_context(
                        personal_model_id="you",
                        state_id="state:elephant-a",
                        surface_id="cli:session-2",
                        surface_kind="cli",
                        mode="companion",
                    )
                ),
                ("skill.voice-helper", "skill.write-helper"),
            )

            activation = runtime.activate("skill.voice-helper", session_id="session-2")
            self.assertEqual(activation.provenance, str(manifest_path))
            self.assertEqual(activation.dependency_ids, ("skill.write-helper",))
            activations = runtime.list_activations()
            self.assertEqual(len(activations), 1)
            self.assertEqual(activations[0].skill_id, "skill.voice-helper")
            self.assertEqual(activations[0].personal_model_id, "you")
            self.assertEqual(activations[0].state_id, "state:elephant-a")
            self.assertEqual(activations[0].surface_id, "cli:session-2")
            self.assertEqual(activations[0].surface_kind, "cli")

            disabled = runtime.set_enabled("skill.voice-helper", False)
            self.assertFalse(disabled.enabled)
            with self.assertRaisesRegex(ValueError, "skill is disabled"):
                runtime.activate("skill.voice-helper", session_id="session-2")

            reenabled = runtime.set_enabled("skill.voice-helper", True)
            self.assertTrue(reenabled.enabled)
            runtime.activate("skill.voice-helper", session_id="session-3")

    def test_skill_runtime_resolve_for_context_applies_state_boundaries(self) -> None:
        catalog = InMemorySkillCatalog()
        for definition in (
            SkillDefinition(
                skill_id="skill.general",
                display_name="General",
                version="1.0.0",
                summary="General companion guidance.",
                metadata={"category": "general"},
            ),
            SkillDefinition(
                skill_id="skill.shell",
                display_name="Shell",
                version="1.0.0",
                summary="Shell workflow guidance.",
                metadata={"category": "runtime", "required_capabilities": ("shell",)},
            ),
            SkillDefinition(
                skill_id="skill.blocked",
                display_name="Blocked",
                version="1.0.0",
                summary="Blocked by state capability boundaries.",
                metadata={"category": "runtime", "required_capabilities": ("notes",)},
            ),
        ):
            catalog.register(definition)

        state = State(
            state_id="state:elephant-a",
            personal_model_id="you",
            state_anchor="elephant:elephant-a",
            capability_boundaries=("shell",),
        )
        runtime = SkillRuntime(
            catalog=catalog,
            state_resolver=lambda state_id: state if state_id == state.state_id else None,
        )

        resolved = runtime.resolve_for_context(
            personal_model_id="you",
            state_id=state.state_id,
            surface_id="cli:session-2",
            surface_kind="cli",
            mode="companion",
        )

        self.assertEqual(
            tuple(skill.skill_id for skill in resolved),
            ("skill.general", "skill.shell"),
        )
        self.assertNotIn("skill.blocked", tuple(skill.skill_id for skill in resolved))

    def test_skill_runtime_activate_rejects_suppressed_retired_and_state_blocked_skills(
        self,
    ) -> None:
        catalog = InMemorySkillCatalog()
        for definition in (
            SkillDefinition(
                skill_id="skill.allowed",
                display_name="Allowed",
                version="1.0.0",
                summary="Allowed by the state boundary.",
                metadata={"required_capabilities": ("shell",)},
            ),
            SkillDefinition(
                skill_id="skill.blocked",
                display_name="Blocked",
                version="1.0.0",
                summary="Rejected by state capability boundaries.",
                metadata={"required_capabilities": ("notes",)},
            ),
            SkillDefinition(
                skill_id="skill.suppressed",
                display_name="Suppressed",
                version="1.0.0",
                summary="Operator-suppressed skills are disabled before runtime activation.",
                enabled=False,
            ),
            SkillDefinition(
                skill_id="skill.retired",
                display_name="Retired",
                version="1.0.0",
                summary="Retired skills are disabled before runtime activation.",
                enabled=False,
            ),
        ):
            catalog.register(definition)

        context = SkillActivationContext(
            personal_model_id="you",
            state_id="state:elephant-a",
            surface_id="cli:session-activate",
            surface_kind="cli",
            mode="companion",
            episode_id="episode:one",
        )
        state = State(
            state_id=context.state_id,
            personal_model_id=context.personal_model_id,
            state_anchor="elephant:elephant-a",
            capability_boundaries=("shell",),
        )
        runtime = SkillRuntime(
            catalog=catalog,
            context_resolver=lambda session_id: context if session_id == "session-activate" else context,
            state_resolver=lambda state_id: state if state_id == context.state_id else None,
        )

        allowed = runtime.activate("skill.allowed", session_id="session-activate")
        self.assertEqual(allowed.skill_id, "skill.allowed")
        self.assertEqual(allowed.episode_id, "episode:one")

        with self.assertRaisesRegex(PermissionError, "out of scope"):
            runtime.activate("skill.blocked", session_id="session-activate")
        with self.assertRaisesRegex(ValueError, "disabled"):
            runtime.activate("skill.suppressed", session_id="session-activate")
        with self.assertRaisesRegex(ValueError, "disabled"):
            runtime.activate("skill.retired", session_id="session-activate")

    def test_skill_package_loader_reads_skill_md_and_hub_searches_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_dir = root / "search-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: Search Skill",
                        "description: Helps the agent search code and notes with bounded retrieval.",
                        "---",
                        "",
                        "# Search Skill",
                        "",
                        "Use ripgrep and semantic retrieval before editing.",
                    ]
                ),
                encoding="utf-8",
            )

            definition = load_skill_package_definition(skill_dir)
            self.assertEqual(definition.skill_id, "search-skill")
            self.assertEqual(definition.display_name, "Search Skill")
            self.assertIn("bounded retrieval", definition.summary)
            self.assertIn("semantic retrieval", definition.instruction_text)

            with mock.patch.dict("os.environ", {"ELEPHANT_SKILL_PATHS": str(root)}):
                hub = SkillHub()
                matches = hub.search("bounded retrieval")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].reference, "custom-1:search-skill")

    def test_skill_hub_keeps_disabled_installed_entries_discoverable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_dir = root / "installed-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: Installed Skill",
                        "skill_id: installed-skill",
                        "description: Stays discoverable even when disabled.",
                        "---",
                        "",
                        "# Installed Skill",
                        "",
                        "Keep this package visible in skill list and view surfaces.",
                    ]
                ),
                encoding="utf-8",
            )
            hub = SkillHub(sources=(SkillHubSource("elephant-installed", "Elephant Agent Installed", root),))

            matches = hub.list({"installed-skill": False})

            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].reference, "elephant-installed:installed-skill")
            self.assertFalse(bool(matches[0].metadata.get("default_enabled")))

    def test_external_skill_source_accepts_parent_with_symlinked_skills_dir(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            external_parent = root / ".external"
            real_skills_root = root / "real-skills"
            skill_dir = real_skills_root / "notes-helper"
            linked_source_dir = root / "linked-source" / "linked-helper"
            external_parent.mkdir()
            skill_dir.mkdir(parents=True)
            linked_source_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: Notes Helper",
                        "skill_id: notes-helper",
                        "description: Reads a symlinked external skill shelf.",
                        "---",
                        "",
                        "# Notes Helper",
                        "",
                        "Use external notes procedures.",
                    ]
                ),
                encoding="utf-8",
            )
            (linked_source_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: Linked Helper",
                        "skill_id: linked-helper",
                        "description: Reads a symlinked skill package inside the external shelf.",
                        "---",
                        "",
                        "# Linked Helper",
                        "",
                        "Use linked external procedures.",
                    ]
                ),
                encoding="utf-8",
            )
            (external_parent / "skills").symlink_to(real_skills_root, target_is_directory=True)
            (real_skills_root / "linked-helper").symlink_to(linked_source_dir, target_is_directory=True)
            hub = SkillHub(
                sources=default_skill_hub_sources(external_dirs=(external_parent,), install_root=root / "elephant")
            )

            entries = {entry.skill_id: entry for entry in hub.list()}

            self.assertIn("notes-helper", entries)
            self.assertIn("linked-helper", entries)
            self.assertEqual(entries["notes-helper"].source_id, "external")
            self.assertEqual(entries["linked-helper"].source_id, "external")
            self.assertEqual(Path(entries["notes-helper"].skill_path).resolve(), skill_dir.resolve())
            self.assertEqual(
                Path(entries["linked-helper"].skill_path).resolve(),
                linked_source_dir.resolve(),
            )

    def test_materialized_skill_package_persists_public_source_and_install_provenance(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir()
            (source_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: Search Skill",
                        "skill_id: search-skill",
                        "description: Helps the agent search before editing.",
                        "---",
                        "",
                        "# Search Skill",
                        "",
                        "Search before editing.",
                    ]
                ),
                encoding="utf-8",
            )
            source = build_public_skill_source_descriptor(
                source_id="skills-sh",
                source_label="Skills.sh",
                source_reference="skills-sh:openai/skills/search-skill",
                install_reference="github:openai/skills/search-skill",
                trust_level="trusted",
                metadata={
                    "canonical_id": "openai/skills/search-skill",
                    "detail_url": "https://skills.sh/openai/skills/search-skill",
                    "repo_url": "https://github.com/openai/skills",
                    "version": "1.2.3",
                },
            )
            install_provenance = build_installed_skill_provenance(
                source=source,
                install_action="refresh",
                installed_at="2026-04-18T10:00:00+00:00",
                install_requester="operator",
                previous_install_reference="github:openai/skills/old-search-skill",
            )

            materialized_dir = materialize_skill_package(
                root / "installed",
                source_dir,
                source_bucket=install_bucket_for_source_descriptor(source),
                install_provenance=install_provenance,
            )
            definition = load_skill_package_definition(materialized_dir)
            persisted_source = public_skill_source_descriptor_from_metadata(definition.metadata)
            persisted_install = installed_skill_provenance_from_metadata(definition.metadata)

            assert persisted_source is not None
            assert persisted_install is not None
            self.assertEqual(persisted_source.source_id, "skills-sh")
            self.assertEqual(persisted_source.install_reference, "github:openai/skills/search-skill")
            self.assertEqual(persisted_source.source_repo_url, "https://github.com/openai/skills")
            self.assertEqual(persisted_install.install_action, "refresh")
            self.assertEqual(persisted_install.install_requester, "operator")
            self.assertEqual(
                persisted_install.previous_install_reference,
                "github:openai/skills/old-search-skill",
            )
            self.assertEqual(definition.metadata["trust_level"], "trusted")
            self.assertEqual(definition.metadata["source_version"], "1.2.3")

    def test_skill_package_loader_preserves_alias_and_trigger_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_dir = root / "notes-helper"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: Notes Helper",
                        "skill_id: notes-helper",
                        'aliases: ["apple notes", "苹果备忘录"]',
                        'trigger_phrases: ["open apple notes", "打开苹果备忘录"]',
                        'keywords: ["notes", "备忘录"]',
                        "---",
                        "",
                        "# Notes Helper",
                        "",
                        "Create or update Apple Notes when the task should land in Notes.app.",
                    ]
                ),
                encoding="utf-8",
            )

            definition = load_skill_package_definition(skill_dir)

            self.assertEqual(definition.metadata.get("aliases"), ("apple notes", "苹果备忘录"))
            self.assertEqual(
                definition.metadata.get("trigger_phrases"),
                ("open apple notes", "打开苹果备忘录"),
            )
            self.assertEqual(definition.metadata.get("keywords"), ("notes", "备忘录"))

    def test_builtin_skill_creator_package_is_loadable(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        skill_dir = repo_root / "packages" / "skills" / "builtin_packages" / "software-development" / "skill-creator"

        definition = load_skill_package_definition(skill_dir)

        self.assertEqual(definition.skill_id, "skill-creator")
        self.assertEqual(definition.display_name, "Skill Creator")
        self.assertIn("write a skill", definition.metadata.get("aliases", ()))
        self.assertIn("create a skill", definition.metadata.get("trigger_phrases", ()))

    def test_builtin_elephant_agent_package_is_loadable(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        skill_dir = repo_root / "packages" / "skills" / "builtin_packages" / "autonomous-ai-agents" / "elephant-agent"

        definition = load_skill_package_definition(skill_dir)

        self.assertEqual(definition.skill_id, "elephant-agent")
        self.assertEqual(definition.display_name, "Elephant Agent")
        self.assertIn("personal-model-first ai", definition.metadata.get("aliases", ()))
        self.assertIn("what is elephant", definition.metadata.get("trigger_phrases", ()))

    def test_builtin_ascii_art_package_is_loadable(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        skill_dir = repo_root / "packages" / "skills" / "builtin_packages" / "creative" / "ascii-art"

        definition = load_skill_package_definition(skill_dir)

        self.assertEqual(definition.skill_id, "ascii-art")
        self.assertEqual(definition.display_name, "ASCII Art")
        self.assertEqual(definition.metadata.get("category"), "creative")
        self.assertEqual(definition.metadata.get("source_kind"), "elephant-builtin")
        self.assertTrue(definition.metadata.get("default_enabled"))

    def test_builtin_skill_catalog_unifies_runtime_defaults_and_hub_projection(
        self,
    ) -> None:
        default_catalog = builtin_skill_catalog()
        override_catalog = builtin_skill_catalog({"shell-execution": False, "docker-management": True})
        section_map = {section.section_id: section for section in default_catalog.sections}
        self.assertIn("runtime", section_map)
        self.assertIn("apple", section_map)
        self.assertIn("creative", section_map)
        self.assertIn("gaming", section_map)
        self.assertIn("devops", section_map)
        self.assertIn("security", section_map)
        self.assertEqual(section_map["runtime"].display_name, "Runtime")
        self.assertEqual(section_map["security"].display_name, "Security")
        self.assertTrue(
            all(entry.source_kind == "elephant-builtin" for entry in default_catalog.entries),
        )
        self.assertIn(
            "shell-execution",
            {entry.skill_id for entry in section_map["runtime"].entries},
        )
        self.assertIn(
            "plan",
            {entry.skill_id for entry in section_map["software-development"].entries},
        )
        self.assertIn("ascii-art", {entry.skill_id for entry in section_map["creative"].entries})
        self.assertIn(
            "docker-management",
            {entry.skill_id for entry in section_map["devops"].entries},
        )
        self.assertIn("1password", {entry.skill_id for entry in section_map["security"].entries})
        self.assertIn(
            "minecraft-modpack-server",
            {entry.skill_id for entry in section_map["gaming"].entries},
        )
        self.assertIn("apple-notes", {entry.skill_id for entry in section_map["apple"].entries})

        catalog = {entry.skill_id: entry for entry in builtin_skill_catalog_entries()}
        self.assertTrue(catalog["shell-execution"].default_enabled)
        self.assertFalse(catalog["shell-execution"].visibility.include_in_overlay)
        self.assertTrue(catalog["apple-notes"].default_enabled)
        self.assertTrue(catalog["ascii-art"].default_enabled)
        self.assertFalse(catalog["docker-management"].default_enabled)
        self.assertFalse(catalog["docker-management"].visibility.include_in_overlay)

        definitions = {
            definition.skill_id: definition
            for definition in builtin_skill_definitions({"shell-execution": False, "docker-management": True})
        }
        self.assertFalse(definitions["shell-execution"].enabled)
        self.assertTrue(definitions["docker-management"].enabled)
        self.assertEqual(definitions["docker-management"].display_name, "Docker Management")
        self.assertEqual(
            tuple(definition.skill_id for definition in definitions.values()),
            tuple(definition.skill_id for definition in override_catalog.definitions()),
        )

        prompt_entries = builtin_prompt_skill_catalog_entries()
        self.assertEqual(
            tuple(entry.skill_id for entry in prompt_entries),
            tuple(entry.skill_id for entry in default_catalog.prompt_entries()),
        )
        self.assertIn("shell-execution", {entry.skill_id for entry in prompt_entries})
        self.assertIn("apple-notes", {entry.skill_id for entry in prompt_entries})
        self.assertIn("ascii-art", {entry.skill_id for entry in prompt_entries})
        self.assertIn("codex", {entry.skill_id for entry in prompt_entries})
        self.assertIn("architecture-diagram", {entry.skill_id for entry in prompt_entries})
        self.assertIn("jupyter-live-kernel", {entry.skill_id for entry in prompt_entries})
        self.assertIn("webhook-subscriptions", {entry.skill_id for entry in prompt_entries})
        self.assertIn("vector-databases", {entry.skill_id for entry in prompt_entries})
        self.assertNotIn("docker-management", {entry.skill_id for entry in prompt_entries})
        self.assertNotIn("1password", {entry.skill_id for entry in prompt_entries})
        disabled_prompt_entries = builtin_prompt_skill_catalog_entries({"ascii-art": False})
        self.assertNotIn("ascii-art", {entry.skill_id for entry in disabled_prompt_entries})
        provenance_fields = dict(skill_provenance_fields(catalog["docker-management"].metadata))
        self.assertEqual(provenance_fields["source_kind"], "elephant-builtin")
        self.assertEqual(provenance_fields["storage_tier"], "builtin")
        self.assertEqual(provenance_fields["default_enabled"], "false")

        site_entries = builtin_site_skill_catalog_entries()
        self.assertEqual(
            tuple(entry.skill_id for entry in site_entries),
            tuple(entry.skill_id for entry in default_catalog.site_entries()),
        )
        site_catalog = build_skillhub_site_catalog()
        self.assertEqual(site_catalog.stats["entry_count"], len(site_entries))
        self.assertEqual(
            tuple(entry.skill_id for entry in site_catalog.entries),
            tuple(entry.skill_id for entry in site_entries),
        )
        self.assertEqual(site_catalog.stats["section_count"], len(site_catalog.sections))
        self.assertEqual(
            len({entry.slug for entry in site_catalog.entries}),
            len(site_catalog.entries),
        )
        self.assertEqual(
            site_catalog.stats["external_source_count"],
            len(site_catalog.external_sources),
        )
        self.assertLess(
            site_catalog.stats["default_enabled_count"],
            site_catalog.stats["entry_count"],
        )
        apple_notes = next(entry for entry in site_catalog.entries if entry.skill_id == "apple-notes")
        docker_management = next(entry for entry in site_catalog.entries if entry.skill_id == "docker-management")
        self.assertEqual(apple_notes.detail_doc_id, "skillhub/library/apple-notes")
        self.assertEqual(apple_notes.detail_path, "/skillhub/library/apple-notes/")
        self.assertEqual(apple_notes.reference, "apple-notes")
        self.assertEqual(apple_notes.install_reference, "apple-notes")
        self.assertEqual(apple_notes.install_command, "elephant skills install apple-notes")
        self.assertIn("Bundled", apple_notes.packaging_posture)
        self.assertIn("elephant skills install apple-notes", apple_notes.install_posture)
        self.assertEqual(docker_management.default_enabled_label, "Disabled by default")
        self.assertEqual(
            docker_management.install_command,
            "elephant skills install docker-management",
        )
        self.assertIn(
            "elephant skills install <source:reference>",
            site_catalog.operator_install_posture,
        )
        self.assertIn("Creative", {section.display_name for section in site_catalog.sections})
        self.assertIn("Data Science", {section.display_name for section in site_catalog.sections})
        self.assertIn("DevOps", {section.display_name for section in site_catalog.sections})
        self.assertIn("Gaming", {section.display_name for section in site_catalog.sections})
        self.assertIn("MLOps", {section.display_name for section in site_catalog.sections})
        self.assertIn("Security", {section.display_name for section in site_catalog.sections})
        self.assertEqual(site_catalog.external_sources[0].source_id, "github")
        self.assertIn(
            "elephant skills search <query> --source github",
            site_catalog.external_sources[0].search_command,
        )

        repo_root = Path(__file__).resolve().parents[3]
        generated_catalog_module = (repo_root / "apps" / "site" / "src" / "generated" / "skillhubCatalog.ts").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("slash_command", generated_catalog_module)
        catalog_prefix = "export const skillHubCatalog: SkillHubCatalogData = "
        catalog_suffix = (
            ";\n\nexport const skillHubCatalogById: Record<string, SkillHubSiteEntry> = Object.fromEntries("
        )
        catalog_start = generated_catalog_module.index(catalog_prefix) + len(catalog_prefix)
        catalog_end = generated_catalog_module.index(catalog_suffix, catalog_start)
        generated_catalog_payload = json.loads(generated_catalog_module[catalog_start:catalog_end])
        expected_catalog_payload = json.loads(site_catalog.to_json())
        generated_catalog_payload["generated_at"] = "<generated>"
        expected_catalog_payload["generated_at"] = "<generated>"
        self.assertEqual(generated_catalog_payload, expected_catalog_payload)

        expected_slugs = tuple(sorted(entry.slug for entry in site_catalog.entries))
        site_doc_slugs = tuple(
            sorted(path.stem for path in (repo_root / "apps" / "site" / "docs" / "skillhub" / "library").glob("*.mdx"))
        )
        site_page_slugs = tuple(
            sorted(
                path.stem
                for path in (repo_root / "apps" / "site" / "src" / "pages" / "skillhub" / "library").glob("*.tsx")
            )
        )
        self.assertEqual(site_doc_slugs, expected_slugs)
        self.assertEqual(site_page_slugs, expected_slugs)

        hub = SkillHub(sources=(SkillHubSource("builtin", "Built In", builtin_elephant_skill_source_root()),))
        entries = {entry.skill_id: entry for entry in hub.list()}
        builtin_hub_entries = {
            entry.skill_id: entry
            for entry in builtin_skill_hub_entries({"shell-execution": False, "docker-management": True})
        }
        self.assertEqual(
            tuple(entries),
            tuple(entry.skill_id for entry in builtin_skill_hub_entries()),
        )
        self.assertNotIn("shell-execution", builtin_hub_entries)
        self.assertIn("docker-management", builtin_hub_entries)
        self.assertEqual(
            tuple(builtin_hub_entries),
            tuple(entry.skill_id for entry in override_catalog.hub_entries()),
        )
        self.assertTrue(entries["shell-execution"].metadata.get("default_enabled"))
        self.assertTrue(entries["apple-notes"].metadata.get("default_enabled"))
        self.assertEqual(entries["apple-notes"].metadata.get("source_kind"), "elephant-builtin")

    def test_skill_scope_matches_strictly_by_context(self) -> None:
        scope = SkillScope(
            personal_model_ids=("you",),
            state_ids=("state:elephant-a",),
            surface_kinds=("cli",),
            modes=("companion",),
        )
        self.assertTrue(
            scope.matches(
                personal_model_id="you",
                state_id="state:elephant-a",
                surface_id="cli:session-3",
                surface_kind="cli",
                mode="companion",
            )
        )
        self.assertFalse(
            scope.matches(
                personal_model_id="personal-model-other",
                state_id="state:elephant-a",
                surface_id="cli:session-3",
                surface_kind="cli",
                mode="companion",
            )
        )

    def test_skill_dependency_validation_reports_missing_required_dependencies(
        self,
    ) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(
            SkillDefinition(
                skill_id="skill.child",
                display_name="Child",
                version="1.0.0",
                summary="Depends on a missing skill.",
                dependencies=(SkillDependency(skill_id="skill.missing", required=True),),
            )
        )

        self.assertEqual(catalog.validate_dependencies("skill.child"), ("skill.missing",))

    def test_skill_catalog_rejects_conflicting_duplicate_skill_ids(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(
            SkillDefinition(
                skill_id="skill.shared",
                display_name="Built In",
                version="1.0.0",
                summary="Built-in skill.",
                provenance="apps/cli",
            )
        )

        with self.assertRaisesRegex(ValueError, "already registered"):
            catalog.register(
                SkillDefinition(
                    skill_id="skill.shared",
                    display_name="External Override",
                    version="1.0.0",
                    summary="External skill should not silently shadow the built-in.",
                    provenance="/tmp/skills.json",
                )
            )


if __name__ == "__main__":
    unittest.main()
