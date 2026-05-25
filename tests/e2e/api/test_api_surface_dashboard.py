from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.auth import AuthProfile, ProviderAuthState, SecretReference
from packages.storage.repository_bootstrap_methods import LEGACY_STORAGE_TABLES
from packages.contracts import (
    Episode,
    ExecutionResult,
    Fact,
    Loop,
    PersonalModel,
    PersonalModelGrowthState,
    SemanticIndexEntry,
    State,
    Step,
)
from packages.kernel.loop_checkpoint_support import LoopCheckpointService
from packages.runtime_config import load_global_config, parse_global_config_text
from packages.runtime_layout import elephant_file_path
from tests.e2e.api.api_surface_test_base import APISurfaceTestBase


class APISurfaceDashboardE2ETest(APISurfaceTestBase):
    def test_operator_dashboard_projection_is_empty_without_runtime_state(self) -> None:
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/overview")
        self.assertEqual(dashboard.status_code, 200)
        projection = dashboard.payload["dashboard"]
        self.assertEqual(
            projection["meta"]["database_path"], str(self.app.repository.database_path)
        )
        self.assertEqual(
            projection["meta"]["query_contract"],
            [
                "Internal dashboard inspection is centered on Personal Model claims, PM history/source rows, Questions, Elephant State, Episode, Step, semantic recall, and provider status.",
                "Dashboard management bridges may operate skills, tools, MCP, cron, gateway, provider, and settings controls; durable user understanding remains Personal Model claims.",
                "Episode resume comes from State.current_context_note copied into Episode metadata at Episode open; live work belongs in Episode, Step, recall, or explicit task tools.",
                "Runtime trace starts from Episode and renders ordered Step facts rather than profile/session summaries.",
            ],
        )
        self.assertEqual(projection["herd"], [])
        self.assertEqual(projection["personal_models"], [])
        self.assertEqual(projection["states"], [])
        self.assertEqual(projection["runtime"]["episodes"], [])
        self.assertEqual(projection["runtime"]["learning_jobs"], [])
        self.assertEqual(projection["learning"]["jobs"], [])
        self.assertEqual(projection["learning"]["summary"]["total"], 0)
        self.assertNotIn("records", projection["evidence"])
        self.assertEqual(projection["overview"]["counts"]["personal_models"], 0)
        self.assertEqual(projection["overview"]["counts"]["states"], 0)
        self.assertNotIn("records", projection["overview"]["counts"])
        self.assertEqual(projection["semantic_index_health"]["entry_count"], 0)
        self.assertIn("providers", projection)
        self.assertIn("operations", projection)
        self.assertNotIn("sessions", projection)
        self.assertNotIn("stateLanes", projection)
        self.assertNotIn("providerProfiles", projection)
        self.assertNotIn(
            "intent", json.dumps(projection["overview"], sort_keys=True).lower()
        )

    def test_internal_dashboard_exposes_cli_linked_control_surfaces(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-console",
                    "display_name": "Console Elephant",
                    "mode": "companion",
                    "episode_id": "session-console",
                    "preferences": ["brief"],
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        elephant_root = elephant_file_path(
            "profile-console", install_root=Path(self.tempdir.name)
        )
        elephant_root.mkdir(parents=True, exist_ok=True)
        (elephant_root / "ELEPHANT.md").write_text(
            "# Elephant Identity: Console Elephant\n\n- Stay exact.\n- Render this as markdown.\n",
            encoding="utf-8",
        )
        loop_service = LoopCheckpointService()
        proactive_prompt = (
            "Open the wake surface proactively before the user sends a new message."
        )
        proactive_loop = loop_service.start_loop(
            episode_id="session-console",
            source_event_id="event-console-startup",
            prompt=proactive_prompt,
        )
        self.app.repository.upsert_loop_checkpoint(proactive_loop)
        proactive_loop, proactive_context_step = loop_service.record_context_prompt(
            proactive_loop,
            system_prompt="Startup system prompt for Console Elephant.",
        )
        self.app.repository.upsert_loop_checkpoint(proactive_loop)
        self.app.repository.append_loop_checkpoint_step(proactive_context_step)
        proactive_loop, proactive_model_step = loop_service.record_model_turn(
            proactive_loop,
            summary="Bit, I already have the release State in view.",
            response_text="Bit, I already have the release State in view.",
        )
        self.app.repository.upsert_loop_checkpoint(proactive_loop)
        self.app.repository.append_loop_checkpoint_step(proactive_model_step)
        proactive_loop = loop_service.complete(
            proactive_loop,
            summary="Bit, I already have the release State in view.",
        )
        self.app.repository.upsert_loop_checkpoint(proactive_loop)
        fallback_proactive_loop = loop_service.start_loop(
            session_id="session-console",
            source_event_id="event-console-startup-summary",
            prompt=proactive_prompt,
        )
        self.app.repository.upsert_loop_checkpoint(fallback_proactive_loop)
        fallback_proactive_loop, fallback_proactive_context_step = (
            loop_service.record_context_prompt(
                fallback_proactive_loop,
                system_prompt="Startup summary-only system prompt for Console Elephant.",
            )
        )
        self.app.repository.upsert_loop_checkpoint(fallback_proactive_loop)
        self.app.repository.append_loop_checkpoint_step(fallback_proactive_context_step)
        fallback_proactive_loop = loop_service.complete(
            fallback_proactive_loop,
            summary="Bit, I am ready with the context already open.",
        )
        self.app.repository.upsert_loop_checkpoint(fallback_proactive_loop)

        run = loop_service.start_loop(
            episode_id="session-console",
            source_event_id="event-console",
            prompt="Show my current elephant evidence.",
        )
        self.app.repository.upsert_loop_checkpoint(run)
        run, context_step = loop_service.record_context_prompt(
            run,
            system_prompt="System prompt for Console Elephant.",
        )
        self.app.repository.upsert_loop_checkpoint(run)
        self.app.repository.append_loop_checkpoint_step(context_step)
        run, model_step = loop_service.record_model_turn(
            run,
            summary="I can inspect persisted evidence layers.",
            response_text="I can inspect persisted evidence layers and show the elephant profile.",
        )
        self.app.repository.upsert_loop_checkpoint(run)
        self.app.repository.append_loop_checkpoint_step(model_step)
        run, tool_step = loop_service.record_tool_step(
            run,
            tool_name="evidence.inspect",
            arguments={"profile_id": "profile-console"},
            result=ExecutionResult(
                execution_id="tool-console",
                episode_id="session-console",
                outcome="ok",
                summary="Evidence inspection returned the Console Elephant profile.",
            ),
        )
        self.app.repository.upsert_loop_checkpoint(run)
        self.app.repository.append_loop_checkpoint_step(tool_step)
        run = loop_service.complete(run, summary="Done.")
        self.app.repository.upsert_loop_checkpoint(run)
        checkpoint_loop = self.app.repository.load_loop(run.run_id)
        self.assertIsNotNone(checkpoint_loop)
        assert checkpoint_loop is not None
        self.app.repository.upsert_step(
            Step(
                step_id="step:console-usage",
                loop_id=checkpoint_loop.loop_id,
                episode_id=checkpoint_loop.episode_id,
                state_id=checkpoint_loop.state_id,
                personal_model_id=checkpoint_loop.personal_model_id,
                phase="acting",
                action="record_usage",
                status="completed",
                sequence=99,
                created_at=datetime.now(timezone.utc),
                summary="Usage reported by the provider.",
                metadata={
                    "provider_id": "openai-compatible",
                    "model_id": "openai/gpt-4o-mini",
                    "prompt_tokens": "20",
                    "completion_tokens": "8",
                    "total_tokens": "28",
                    "cached_prompt_tokens": 5,
                    "cache_creation_prompt_tokens": 2,
                    "cache_usage_reported": True,
                },
            )
        )

        payload = self._dashboard_sections(
            "herd", "skills", "tools", "usage", "logs", "settings"
        )
        operations = payload["operations"]
        self.assertEqual(
            payload["meta"]["database_path"], str(self.app.repository.database_path)
        )
        self.assertNotIn("sessions", payload)
        self.assertIn("profileManifest", operations["settings"])
        self.assertIn("globalConfigPath", operations["settings"])
        self.assertIn("globalConfig", operations["settings"])
        self.assertNotIn("eggStateFiles", operations["settings"])
        self.assertNotIn("eggStateFilesDir", operations["settings"])
        self.assertNotIn(
            "models.state_focus_mode",
            json.dumps(operations["settings"], sort_keys=True),
        )
        elephant = next(
            row for row in payload["herd"] if row["elephant_id"] == "profile-console"
        )
        self.assertEqual(
            elephant["elephant_identity_file"]["path"],
            str(elephant_root / "ELEPHANT.md"),
        )
        self.assertTrue(elephant["elephant_identity_file"]["exists"])
        self.assertIn("- Stay exact.", elephant["elephant_identity_file"]["text"])
        self.assertTrue(operations["skills"])
        self.assertTrue(operations["tools"])
        self.assertIn("mcp", operations)
        self.assertEqual(operations["mcp"]["tools"], [])
        self.assertIsInstance(operations["logs"], list)
        self.assertEqual(operations["usage"]["summary"]["runtimeStepUsageEvents"], 1)
        self.assertEqual(
            operations["usage"]["tokenEvents"][0]["cacheHitRateLabel"], "25.0%"
        )

        patched = self.app.dispatch(
            "PATCH",
            "/v1/operator/settings",
            body=self._body(
                {
                    "profileManifest": {
                        "profile_id": "profile-console",
                        "display_name": "Console Elephant",
                        "mode": "companion",
                        "preferences": ["brief", "json"],
                    }
                }
            ),
        )
        self.assertEqual(patched.status_code, 200)
        profile_json = Path(patched.payload["profileManifestPath"])
        self.assertTrue(profile_json.exists())
        patched_config = load_global_config(
            profile_json, state_dir=self.app.repository.database_path.parent
        )
        self.assertEqual(
            patched_config["runtime"]["state_dir"],
            str(self.app.repository.database_path.parent),
        )

        global_config = self.app.dispatch(
            "PATCH",
            "/v1/operator/config",
            body=self._body(
                {"yamlText": "dashboard:\n  host: 127.0.0.1\n  port: 9777\n"}
            ),
        )
        self.assertEqual(global_config.status_code, 200)
        self.assertEqual(
            global_config.payload["settings"]["globalConfig"]["dashboard"]["port"], 9777
        )
        self.assertTrue(Path(global_config.payload["globalConfigPath"]).exists())

        skill_id = operations["skills"][0]["skillId"]
        toggled = self.app.dispatch(
            "PATCH",
            f"/v1/operator/skills/{skill_id}",
            body=self._body({"enabled": False}),
        )
        self.assertEqual(toggled.status_code, 200)
        manifest = load_global_config(
            profile_json, state_dir=self.app.repository.database_path.parent
        )
        self.assertFalse(manifest["extensions"]["skill_overrides"][skill_id]["enabled"])
        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/skills")
        refreshed_skill = next(
            skill
            for skill in refreshed.payload["dashboard"]["operations"]["skills"]
            if skill["skillId"] == skill_id
        )
        self.assertFalse(refreshed_skill["enabled"])

        tool_id = operations["tools"][0]["toolId"]
        toggled_tool = self.app.dispatch(
            "PATCH",
            f"/v1/operator/tools/{tool_id}",
            body=self._body({"enabled": False}),
        )
        self.assertEqual(toggled_tool.status_code, 200)
        manifest = load_global_config(
            profile_json, state_dir=self.app.repository.database_path.parent
        )
        self.assertFalse(manifest["extensions"]["tool_overrides"][tool_id]["enabled"])
        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/tools")
        refreshed_tool = next(
            tool
            for tool in refreshed.payload["dashboard"]["operations"]["tools"]
            if tool["toolId"] == tool_id
        )
        self.assertFalse(refreshed_tool["enabled"])

        created_mcp_tool = self.app.dispatch(
            "POST",
            "/v1/operator/mcp/tools",
            body=self._body(
                {
                    "serverId": "filesystem",
                    "toolName": "read_file",
                    "serverLabel": "Filesystem",
                    "transport": "stdio",
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        "/tmp/demo",
                    ],
                    "env": {"ALLOW": "1"},
                    "displayName": "Read File",
                    "description": "Read a file from the mounted elephant file area.",
                    "family": "filesystem",
                    "defaultEnabled": True,
                    "riskClass": "medium",
                    "approvalClass": "standard",
                    "readsState": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                    "metadata": {"origin": "dashboard"},
                }
            ),
        )
        self.assertEqual(created_mcp_tool.status_code, 201)
        self.assertEqual(created_mcp_tool.payload["runtimeStatus"], "runtime_reloaded")
        global_config_path = Path(created_mcp_tool.payload["globalConfigPath"])
        stored_global_config = parse_global_config_text(
            global_config_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            stored_global_config["mcp_servers"]["filesystem"]["command"], "npx"
        )
        self.assertIn(
            "read_file", stored_global_config["mcp_servers"]["filesystem"]["tools"]
        )
        runtime_tool = self.app.tool_runtime.describe("mcp.filesystem.read_file")
        self.assertIsNotNone(runtime_tool)
        self.assertTrue(runtime_tool.enabled)
        self.assertEqual(runtime_tool.audience, "model")

        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/tools")
        custom_mcp_tool = next(
            tool
            for tool in refreshed.payload["dashboard"]["operations"]["mcp"]["tools"]
            if tool["toolKey"] == "filesystem:read_file"
        )
        self.assertEqual(custom_mcp_tool["displayName"], "Read File")
        self.assertTrue(custom_mcp_tool["enabled"])
        self.assertEqual(custom_mcp_tool["serverId"], "filesystem")

        updated_mcp_tool = self.app.dispatch(
            "PATCH",
            "/v1/operator/mcp/tools",
            body=self._body(
                {
                    "serverId": "filesystem",
                    "toolName": "read_file",
                    "displayName": "Read File (updated)",
                    "description": "Read a file from the configured MCP server.",
                    "touchesSecrets": True,
                    "metadata": {"origin": "dashboard", "edited": True},
                }
            ),
        )
        self.assertEqual(updated_mcp_tool.status_code, 200)
        self.assertEqual(updated_mcp_tool.payload["runtimeStatus"], "runtime_reloaded")
        stored_global_config = parse_global_config_text(
            global_config_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            stored_global_config["mcp_servers"]["filesystem"]["tools"]["read_file"][
                "display_name"
            ],
            "Read File (updated)",
        )
        self.assertTrue(
            stored_global_config["mcp_servers"]["filesystem"]["tools"]["read_file"][
                "touches_secrets"
            ]
        )
        runtime_tool = self.app.tool_runtime.describe("mcp.filesystem.read_file")
        self.assertEqual(runtime_tool.display_name, "Read File (updated)")
        self.assertTrue(runtime_tool.side_effects.touches_secrets)

        toggled_mcp_tool = self.app.dispatch(
            "PATCH",
            "/v1/operator/mcp/tools/enabled",
            body=self._body(
                {
                    "serverId": "filesystem",
                    "toolName": "read_file",
                    "enabled": False,
                }
            ),
        )
        self.assertEqual(toggled_mcp_tool.status_code, 200)
        self.assertEqual(toggled_mcp_tool.payload["runtimeStatus"], "runtime_reloaded")
        stored_global_config = parse_global_config_text(
            global_config_path.read_text(encoding="utf-8")
        )
        self.assertFalse(
            stored_global_config["mcp_overrides"]["filesystem:read_file"]["enabled"]
        )
        self.assertFalse(
            self.app.tool_runtime.describe("mcp.filesystem.read_file").enabled
        )
        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/tools")
        custom_mcp_tool = next(
            tool
            for tool in refreshed.payload["dashboard"]["operations"]["mcp"]["tools"]
            if tool["toolKey"] == "filesystem:read_file"
        )
        self.assertFalse(custom_mcp_tool["enabled"])

        deleted_mcp_tool = self.app.dispatch(
            "DELETE",
            "/v1/operator/mcp/tools",
            body=self._body(
                {
                    "serverId": "filesystem",
                    "toolName": "read_file",
                }
            ),
        )
        self.assertEqual(deleted_mcp_tool.status_code, 200)
        self.assertEqual(deleted_mcp_tool.payload["runtimeStatus"], "runtime_reloaded")
        stored_global_config = parse_global_config_text(
            global_config_path.read_text(encoding="utf-8")
        )
        self.assertNotIn("filesystem", stored_global_config.get("mcp_servers", {}))
        self.assertNotIn(
            "filesystem:read_file", stored_global_config.get("mcp_overrides", {})
        )
        self.assertIsNone(self.app.tool_runtime.describe("mcp.filesystem.read_file"))
        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/tools")
        self.assertNotIn(
            "filesystem",
            {
                server["serverId"]
                for server in refreshed.payload["dashboard"]["operations"]["mcp"][
                    "servers"
                ]
            },
        )

    def test_operator_namespace_no_longer_exposes_public_dashboard_reads(self) -> None:
        dashboard = self.app.dispatch("GET", "/v1/operator/dashboard")
        console = self.app.dispatch("GET", "/v1/operator/console")

        self.assertEqual(dashboard.status_code, 404)
        self.assertEqual(console.status_code, 404)

    def test_wsgi_get_request_with_no_content_length_returns_without_blocking(
        self,
    ) -> None:
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        body = b"".join(
            self.app(
                {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": "/healthz",
                    "wsgi.input": BytesIO(b""),
                    "CONTENT_LENGTH": "",
                },
                start_response,
            )
        )

        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(
            json.loads(body.decode("utf-8")),
            {"status": "ok", "service": "elephant-api"},
        )

    def test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence(
        self,
    ) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-dashboard",
            base_url=self.stub.openai_base_url,
            reference_id="secret-dashboard-token",
            extra_headers={"x-tenant": "elephant"},
        )
        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)

        now = datetime.now(timezone.utc)
        personal_model = PersonalModel(
            personal_model_id="personal-model-dashboard",
            display_name="Dashboard Personal Model",
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.app.repository.upsert_personal_model(personal_model)
        self.app.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact-dashboard-preferred-name",
                personal_model_id=personal_model.personal_model_id,
                lens="identity",
                text="Bit",
                confidence=1.0,
                committed_at=now,
                source="user_explicit",
                metadata={"topic": "identity.anchor.name.preferred"},
            )
        )
        self.app.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact-dashboard-work",
                personal_model_id=personal_model.personal_model_id,
                lens="pulse",
                text="Building durable agent systems.",
                confidence=0.92,
                committed_at=now,
                source="pm_agent_promote",
                source_episode_ids=("episode-dashboard",),
                metadata={"topic": "pulse.chapter.work.role"},
            )
        )
        self.app.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact-dashboard-style",
                personal_model_id=personal_model.personal_model_id,
                lens="identity",
                text="Prefers concise, grounded replies.",
                confidence=0.91,
                committed_at=now,
                source="pm_agent_promote",
                source_episode_ids=("episode-dashboard",),
                metadata={"topic": "identity.style.response.concise"},
            )
        )
        state = State(
            state_id="state-dashboard",
            personal_model_id=personal_model.personal_model_id,
            state_anchor="elephant-dashboard",
            status="active",
            elephant_id="elephant-dashboard",
            elephant_name="Elephant Agent Prime",
            capability_boundaries=("inspect", "ground"),
            surface_bindings=("cli", "dashboard"),
            summary="Investigating the T9 dashboard rewrite.",
            current_context_note="Investigating the T9 dashboard rewrite.",
            created_at=now,
            updated_at=now,
        )
        self.app.repository.upsert_state(state)
        self.app.repository.switch_state(state.state_id, selected_at=now)
        episode = Episode(
            episode_id="episode-dashboard",
            state_id=state.state_id,
            personal_model_id=personal_model.personal_model_id,
            entry_surface="dashboard-test",
            status="open",
            started_at=now,
            ended_at=now,
            exit_summary="Dashboard inspection episode closed cleanly.",
        )
        self.app.repository.upsert_episode(episode)
        loop = Loop(
            loop_id="loop-dashboard",
            episode_id=episode.episode_id,
            state_id=state.state_id,
            personal_model_id=personal_model.personal_model_id,
            trigger_type="manual",
            status="completed",
            started_at=now,
            ended_at=now,
            summary="Validated the internal dashboard projection.",
            outcome="success",
        )
        self.app.repository.upsert_loop(loop)
        step = Step(
            step_id="step-dashboard",
            loop_id=loop.loop_id,
            episode_id=episode.episode_id,
            state_id=state.state_id,
            personal_model_id=personal_model.personal_model_id,
            phase="reasoning",
            action="inspect_dashboard",
            status="completed",
            sequence=0,
            created_at=now,
            summary="Checked the canonical inspection payload.",
            outcome="payload rendered",
            payload_refs=("payload:dashboard",),
            metadata={
                "execution_id": "execution-dashboard",
                "provider_id": "openai-compatible",
                "model_id": "openai/gpt-4o-mini",
                "assistant_reasoning": "Inspect provider posture before opening the dashboard trace.",
                "prompt_tokens": "42",
                "completion_tokens": "11",
                "total_tokens": "53",
            },
        )
        self.app.repository.upsert_step(step)
        learning_job = self.app.repository.enqueue_learning_job(
            job_type="episode_boundary_learning",
            trigger="exit",
            personal_model_id=personal_model.personal_model_id,
            state_id=state.state_id,
            episode_id=episode.episode_id,
            loop_id=loop.loop_id,
            summary="Dashboard learning job completed.",
            metadata={"source": "dashboard-test"},
        )
        claimed_learning_job = self.app.repository.claim_learning_job(
            worker_id="dashboard-worker"
        )
        assert claimed_learning_job is not None
        self.app.repository.write_learning_job_result(
            claimed_learning_job.job_id,
            {
                "job_id": learning_job.job_id,
                "status": "completed",
                "summary": "Dashboard learning result.",
                "pm_facts": {"created_refs": ["fact-dashboard-style"]},
                "questions": {"created_ids": []},
            },
            worker_id="dashboard-worker",
            progress_detail="Dashboard learning result persisted.",
        )
        self.app.repository.complete_learning_job(
            claimed_learning_job.job_id,
            worker_id="dashboard-worker",
            finished_at=now,
            progress_detail="Dashboard learning result persisted.",
        )
        self.app.repository.upsert_auth_profile(
            AuthProfile(
                profile_id="provider-embedding-openai-compatible",
                provider_id="openai-compatible-embed",
                transport_id="openai-compatible",
                base_url=self.stub.openai_base_url,
                default_model="text-embedding-3-small",
                auth_method="api_key",
                provider_kind="embedding",
                secret_references=(
                    SecretReference(
                        reference_id="secret-embedding-dashboard",
                        provider_id="openai-compatible-embed",
                        secret_name="api_token",
                        secret_key="api_key",
                        metadata={
                            "storage": "local-vault",
                            "scope": "embedding-provider",
                            "env_var": "OPENAI_API_KEY",
                        },
                    ),
                ),
                metadata={
                    "embedding_active": "true",
                    "dimensions": "1536",
                    "configured_from": "test",
                },
            )
        )
        self.app.repository.upsert_semantic_index_entry(
            SemanticIndexEntry(
                semantic_index_entry_id="semantic-dashboard",
                owner_scope="personal_model",
                source_id="fact-dashboard-style",
                provider_id="openai-compatible",
                model_id="text-embedding-3-small",
                dimensions=1536,
                content_hash="hash-dashboard-component",
                personal_model_id=personal_model.personal_model_id,
                backend="sqlite-vec",
                vector_ref="vec://dashboard-component",
                status="indexed",
                created_at=now,
                updated_at=now,
            )
        )
        self.app.repository.upsert_provider_auth_state(
            ProviderAuthState(
                provider_id="copilot",
                auth_type="api_key",
                status="authenticated",
                source="gh-cli",
                transport_id="openai_responses",
                provider_kind="aggregator",
                base_url="https://api.githubcopilot.com",
                default_model="gpt-5.4",
                runtime_enabled=True,
                summary="authenticated via gh-cli",
                metadata={"reasoning_efforts": "minimal,low,medium,high"},
                discovered_at=now,
                updated_at=now,
            )
        )

        projection = self._dashboard_sections(
            "overview",
            "personal-models",
            "runtime",
            "reflect",
            "evidence",
            "providers",
            "usage",
        )
        self.assertEqual(projection["overview"]["counts"]["personal_models"], 1)
        self.assertEqual(projection["overview"]["counts"]["states"], 1)
        self.assertEqual(projection["overview"]["counts"]["episodes"], 1)
        self.assertEqual(projection["overview"]["counts"]["loops"], 1)
        self.assertEqual(projection["overview"]["counts"]["steps"], 1)
        self.assertNotIn("records", projection["overview"]["counts"])
        self.assertEqual(projection["overview"]["counts"]["learning_jobs"], 1)
        self.assertEqual(projection["overview"]["counts"]["learning_jobs_completed"], 1)
        for legacy_table in LEGACY_STORAGE_TABLES:
            self.assertNotIn(legacy_table, projection["overview"]["counts"])
        self.assertNotIn("skill_affinities", projection["overview"]["counts"])
        self.assertEqual(projection["overview"]["counts"]["semantic_index_entries"], 1)
        self.assertNotIn("embedding_provider_configs", projection["overview"]["counts"])
        self.assertEqual(projection["overview"]["counts"]["provider_auth_states"], 0)
        self.assertEqual(projection["overview"]["current_state_id"], state.state_id)
        self.assertEqual(
            projection["overview"]["current_personal_model_id"],
            "you",
        )
        self.assertNotIn("active_task", projection["herd"][0])
        self.assertNotIn("next_step", projection["herd"][0])
        self.assertNotIn("blockers", projection["states"][0])
        personal_model_row = projection["personal_models"][0]
        self.assertNotIn("component_records", personal_model_row)
        for legacy_table in LEGACY_STORAGE_TABLES:
            self.assertNotIn(legacy_table, personal_model_row)
        self.assertEqual(personal_model_row["states"][0]["state_id"], state.state_id)
        self.assertEqual(personal_model_row["user_preferred_name"], "Bit")
        self.assertEqual(personal_model_row["user_profile"]["preferred_name"], "Bit")
        self.assertEqual(
            personal_model_row["user_profile"]["current_work"],
            "Building durable agent systems.",
        )
        overview_only = self._dashboard_section("overview")
        self.assertEqual(
            overview_only["personal_models"][0]["user_preferred_name"], "Bit"
        )
        component_rows = {
            component["component_key"]: component
            for component in personal_model_row["understanding_components"]
        }
        self.assertEqual(component_rows["identity"]["status"], "active")
        self.assertEqual(component_rows["identity"]["claim_count"], 2)
        self.assertEqual(component_rows["pulse"]["claim_count"], 1)
        self.assertEqual(component_rows["world"]["status"], "empty")
        self.assertEqual(personal_model_row["personal_model_fact_count"], 3)
        personal_model_fact_text = {
            fact["text"] for fact in personal_model_row["personal_model_facts"]
        }
        self.assertIn("Prefers concise, grounded replies.", personal_model_fact_text)
        self.assertNotIn(
            "State-only tool test evidence",
            json.dumps(personal_model_row, sort_keys=True),
        )
        self.assertNotIn(
            "Display name: Miles", json.dumps(personal_model_row, sort_keys=True)
        )
        self.assertNotIn("reflection_proposals", personal_model_row)
        self.assertNotIn("skill_affinities", personal_model_row)
        self.assertEqual(
            personal_model_row["semantic_index_entries"][0]["semantic_index_entry_id"],
            "semantic-dashboard",
        )
        self.assertEqual(
            projection["runtime"]["episodes"][0]["episode_id"], episode.episode_id
        )
        self.assertEqual(projection["runtime"]["episodes"][0]["loop_count"], 1)
        self.assertEqual(projection["runtime"]["episodes"][0]["step_count"], 1)
        self.assertEqual(projection["learning"]["summary"]["completed"], 1)
        self.assertEqual(
            projection["learning"]["jobs"][0]["job_id"], learning_job.job_id
        )
        self.assertEqual(projection["learning"]["jobs"][0]["result_record_count"], 0)
        self.assertNotIn("result_records", projection["learning"]["jobs"][0])
        for legacy_table in LEGACY_STORAGE_TABLES:
            self.assertNotIn(
                f"result_{legacy_table}", projection["learning"]["jobs"][0]
            )
        self.assertEqual(
            projection["learning"]["jobs"][0]["result_status"], "completed"
        )
        self.assertEqual(
            projection["learning"]["jobs"][0]["learning_result"]["summary"],
            "Dashboard learning result.",
        )
        self.assertEqual(
            projection["runtime"]["episode_traces"][0]["timeline"][0]["detail"][
                "assistant_reasoning"
            ],
            "Inspect provider posture before opening the dashboard trace.",
        )
        usage = projection["operations"]["usage"]
        self.assertEqual(usage["summary"]["runtimeStepUsageEvents"], 1)
        self.assertEqual(usage["summary"]["usageEvents"], 1)
        self.assertEqual(usage["summary"]["totalTokens"], 53)
        self.assertEqual(usage["tokenEvents"][0]["source"], "runtime_step")
        self.assertEqual(usage["tokenTrend"][0]["totalTokens"], 53)
        self.assertEqual(usage["eggUsage"][0]["eggName"], "Elephant Agent Prime")
        self.assertNotIn("records", projection["evidence"])
        for legacy_table in LEGACY_STORAGE_TABLES:
            self.assertNotIn(legacy_table, projection["evidence"])
        self.assertNotIn("skill_affinities", projection["evidence"])
        self.assertEqual(projection["semantic_index_health"]["entry_count"], 1)
        self.assertNotIn("embedding_configs", projection["providers"])
        self.assertEqual(
            projection["providers"]["embedding_provider"]["source"], "configured"
        )
        self.assertEqual(
            projection["providers"]["embedding_provider"]["model_id"],
            "text-embedding-3-small",
        )
        self.assertEqual(
            projection["providers"]["active_provider"]["model_id"],
            "openai/gpt-4o-mini",
        )
        self.assertNotIn("state_focus_mode", projection["providers"]["active_provider"])
        self.assertNotIn("strong_model", projection["providers"]["active_provider"])
        self.assertNotIn("weak_model", projection["providers"]["active_provider"])
        self.assertNotIn(
            "state_focus_mode",
            json.dumps(projection["providers"]["doctor"], sort_keys=True),
        )
        self.assertNotIn("stateLanes", projection)
        self.assertNotIn("sessions", projection)
        serialized = json.dumps(projection, sort_keys=True)
        self.assertNotIn("sk-live-123", serialized)

    def test_internal_dashboard_projection_ignores_legacy_session_graph_rows(
        self,
    ) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-dashboard",
            base_url=self.stub.openai_base_url,
            reference_id="secret-dashboard-token",
            extra_headers={"x-tenant": "elephant"},
        )
        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-dashboard-legacy",
                    "display_name": "Legacy lane",
                    "mode": "companion",
                    "episode_id": "session-dashboard-legacy",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/overview")
        self.assertEqual(dashboard.status_code, 200)
        projection = dashboard.payload["dashboard"]
        self.assertEqual(projection["overview"]["counts"]["states"], 1)
        self.assertNotIn("records", projection["overview"]["counts"])
        self.assertEqual(
            projection["herd"][0]["elephant_id"], "profile-dashboard-legacy"
        )
        self.assertEqual(
            projection["states"][0]["state_id"], "state:profile-dashboard-legacy"
        )
        self.assertNotIn("stateLanes", projection)
        self.assertNotIn("sessions", projection)
        self.assertNotIn("ops", projection)


if __name__ == "__main__":
    unittest.main()
