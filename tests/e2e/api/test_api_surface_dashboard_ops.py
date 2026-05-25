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


class APISurfaceDashboardOpsE2ETest(APISurfaceTestBase):
    def test_operator_mcp_server_sync_persists_multiple_tools_and_deletes_server(
        self,
    ) -> None:
        synced_server = self.app.dispatch(
            "POST",
            "/v1/operator/mcp/servers",
            body=self._body(
                {
                    "serverId": "km",
                    "serverLabel": "KM",
                    "transport": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer demo"},
                    "tools": [
                        {
                            "name": "list_articles",
                            "description": "List KM articles.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"author": {"type": "string"}},
                            },
                        },
                        {
                            "name": "get_user",
                            "description": "Get one KM user profile.",
                            "enabled": False,
                            "inputSchema": {
                                "type": "object",
                                "properties": {"staffname": {"type": "string"}},
                                "required": ["staffname"],
                            },
                        },
                    ],
                }
            ),
        )
        self.assertEqual(synced_server.status_code, 201)
        self.assertEqual(synced_server.payload["toolCount"], 2)
        global_config_path = Path(synced_server.payload["globalConfigPath"])
        stored_global_config = parse_global_config_text(
            global_config_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            sorted(stored_global_config["mcp_servers"]["km"]["tools"].keys()),
            ["get_user", "list_articles"],
        )
        self.assertIsNotNone(self.app.tool_runtime.describe("mcp.km.list_articles"))
        self.assertIsNotNone(self.app.tool_runtime.describe("mcp.km.get_user"))
        self.assertFalse(
            stored_global_config["mcp_servers"]["km"]["tools"]["get_user"]["enabled"]
        )
        self.assertFalse(self.app.tool_runtime.describe("mcp.km.get_user").enabled)

        toggled = self.app.dispatch(
            "PATCH",
            "/v1/operator/mcp/tools/enabled",
            body=self._body(
                {
                    "serverId": "km",
                    "toolName": "get_user",
                    "enabled": False,
                }
            ),
        )
        self.assertEqual(toggled.status_code, 200)
        stored_global_config = parse_global_config_text(
            global_config_path.read_text(encoding="utf-8")
        )
        self.assertFalse(
            stored_global_config["mcp_overrides"]["km:get_user"]["enabled"]
        )

        resynced_server = self.app.dispatch(
            "PATCH",
            "/v1/operator/mcp/servers",
            body=self._body(
                {
                    "serverId": "km",
                    "serverLabel": "KM",
                    "transport": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer demo"},
                    "tools": [
                        {
                            "name": "list_articles",
                            "description": "List KM articles (updated).",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"author": {"type": "string"}},
                            },
                        }
                    ],
                }
            ),
        )
        self.assertEqual(resynced_server.status_code, 200)
        self.assertEqual(resynced_server.payload["toolCount"], 1)
        stored_global_config = parse_global_config_text(
            global_config_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            sorted(stored_global_config["mcp_servers"]["km"]["tools"].keys()),
            ["list_articles"],
        )
        self.assertNotIn("km:get_user", stored_global_config.get("mcp_overrides", {}))
        self.assertIsNone(self.app.tool_runtime.describe("mcp.km.get_user"))
        self.assertIsNotNone(self.app.tool_runtime.describe("mcp.km.list_articles"))

        deleted_server = self.app.dispatch(
            "DELETE",
            "/v1/operator/mcp/servers",
            body=self._body({"serverId": "km"}),
        )
        self.assertEqual(deleted_server.status_code, 200)
        stored_global_config = parse_global_config_text(
            global_config_path.read_text(encoding="utf-8")
        )
        self.assertNotIn("km", stored_global_config.get("mcp_servers", {}))
        self.assertIsNone(self.app.tool_runtime.describe("mcp.km.list_articles"))

    def test_internal_dashboard_surfaces_configured_external_skill_shelves(
        self,
    ) -> None:
        external_root = Path(self.tempdir.name) / ".agents" / "skills"
        skill_dir = external_root / "personal-journal"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                (
                    "---",
                    "name: Personal Journal",
                    "description: Helps review personal journal notes and recurring preferences.",
                    "---",
                    "Use this skill when the user asks to review personal journal notes.",
                )
            ),
            encoding="utf-8",
        )
        configured = self.app.dispatch(
            "PATCH",
            "/v1/operator/config",
            body=self._body(
                {"config": {"skills": {"external_dirs": [str(external_root)]}}}
            ),
        )
        self.assertEqual(configured.status_code, 200)
        now = datetime.now(timezone.utc)
        self.app.repository.upsert_personal_model(
            PersonalModel(
                personal_model_id="you",
                display_name="You",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        self.app.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact:skills:personal-journal",
                personal_model_id="you",
                lens="world",
                text="Personal journal review fits the user's recurring reflection workflow.",
                confidence=0.82,
                committed_at=now,
                source="user_explicit",
                metadata={
                    "topic": "world.skills.affinity.personal_journal",
                    "skill_id": "personal-journal",
                    "projection_policy": "skill_shelf_candidate",
                },
            )
        )

        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/skills")
        self.assertEqual(dashboard.status_code, 200)
        skills = dashboard.payload["dashboard"]["operations"]["skills"]
        affinities = dashboard.payload["dashboard"]["operations"]["skill_affinities"]
        external = next(
            skill for skill in skills if skill["skillId"] == "personal-journal"
        )

        self.assertEqual(external["sourceId"], "agents")
        self.assertEqual(external["source"], "Agents")
        self.assertFalse(external["toggleable"])
        self.assertFalse(external["enabled"])
        self.assertIn("Use this skill", external["instructionText"])
        self.assertEqual(affinities[0]["skillId"], "personal-journal")
        self.assertEqual(affinities[0]["activeCount"], 1)
        self.assertEqual(
            dashboard.payload["dashboard"]["operations"]["settings"]["globalConfig"][
                "skills"
            ]["external_dirs"],
            [str(external_root)],
        )

    def test_operator_mcp_discover_supports_stdio_and_remote_headers(self) -> None:
        observed_payloads: list[dict[str, object]] = []

        def fake_discover(**kwargs) -> dict[str, object]:
            observed_payloads.append(dict(kwargs))
            if kwargs["transport"] == "stdio":
                self.assertEqual(kwargs["cwd"], ROOT)
                self.assertEqual(kwargs["command"], "uvx")
                self.assertEqual(kwargs["args"], ("mcp-server-filesystem", "/tmp/demo"))
                self.assertEqual(kwargs["env"], {"ALLOW": "1"})
                return {
                    "status": "ok",
                    "durationMs": 123,
                    "tools": [
                        {
                            "name": "read_file",
                            "description": "Read one file.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"],
                            },
                            "options": [{"property": "path", "required": True}],
                        }
                    ],
                }
            return {
                "status": "ok",
                "durationMs": 88,
                "tools": [
                    {
                        "name": "ping",
                        "description": "Ping the remote MCP server.",
                        "inputSchema": {"type": "object", "properties": {}},
                        "options": [],
                    }
                ],
            }

        with patch(
            "apps.api.api_runtime_console_ops.discover_mcp_tools_sync",
            side_effect=fake_discover,
        ):
            discovered_stdio = self.app.dispatch(
                "POST",
                "/v1/operator/mcp/discover",
                body=self._body(
                    {
                        "serverId": "filesystem",
                        "transport": "stdio",
                        "command": "uvx",
                        "args": ["mcp-server-filesystem", "/tmp/demo"],
                        "env": {"ALLOW": "1"},
                    }
                ),
            )
            self.assertEqual(discovered_stdio.status_code, 200)
            self.assertEqual(discovered_stdio.payload["status"], "ok")
            self.assertEqual(discovered_stdio.payload["toolCount"], 1)
            self.assertEqual(discovered_stdio.payload["tools"][0]["name"], "read_file")
            self.assertEqual(
                discovered_stdio.payload["tools"][0]["requiredFields"], ["path"]
            )

            discovered_remote = self.app.dispatch(
                "POST",
                "/v1/operator/mcp/discover",
                body=self._body(
                    {
                        "serverId": "remote-demo",
                        "transport": "streamable-http",
                        "url": "https://example.com/mcp",
                        "headers": {"Authorization": "Bearer demo"},
                    }
                ),
            )
            self.assertEqual(discovered_remote.status_code, 200)
            self.assertEqual(discovered_remote.payload["transport"], "streamable-http")
            self.assertEqual(discovered_remote.payload["toolCount"], 1)
            self.assertEqual(discovered_remote.payload["tools"][0]["name"], "ping")
            self.assertEqual(
                observed_payloads[-1]["headers"], {"Authorization": "Bearer demo"}
            )
            self.assertEqual(observed_payloads[-1]["transport"], "streamable-http")

    def test_internal_dashboard_keeps_durable_state_after_episode_delete(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-orphan",
                    "display_name": "Orphan Elephant",
                    "mode": "companion",
                    "episode_id": "session-orphan",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        deleted_sessions = self.app.repository.delete_episodes(("session-orphan",))

        self.assertEqual(deleted_sessions, 1)
        self.assertIsNotNone(self.app.repository.load_personal_model("profile-orphan"))
        console = self.app.dispatch("GET", "/v1/internal/console")
        self.assertEqual(console.status_code, 404)
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/overview")
        self.assertEqual(dashboard.status_code, 200)
        payload = dashboard.payload["dashboard"]
        self.assertNotIn("sessions", payload)
        self.assertIn(
            "profile-orphan",
            [elephant["personal_model_id"] for elephant in payload["herd"]],
        )
        self.assertIn(
            "state:profile-orphan", [state["state_id"] for state in payload["states"]]
        )
        self.assertEqual(payload["overview"]["counts"]["episodes"], 0)

    def test_internal_dashboard_excludes_personal_model_growth_state_lanes(
        self,
    ) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-stale-growth",
                    "display_name": "Fresh Elephant",
                    "mode": "companion",
                    "episode_id": "session-stale-growth",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        self.app.repository.upsert_personal_model_growth(
            PersonalModelGrowthState(
                profile_id="profile-stale-growth",
                growth_score=480,
                total_dialogues=12,
                total_tokens=3400,
                created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
        )

        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/herd")

        self.assertEqual(dashboard.status_code, 200)
        elephant = next(
            elephant
            for elephant in dashboard.payload["dashboard"]["herd"]
            if elephant["elephant_id"] == "profile-stale-growth"
        )
        self.assertNotIn("growth_score", elephant)

    def test_gateway_dashboard_cards_configure_im_accounts(self) -> None:
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/gateway")
        self.assertEqual(dashboard.status_code, 200)
        services = dashboard.payload["dashboard"]["operations"]["gateway"]["services"]
        service_ids = {service["service"] for service in services}
        self.assertEqual(services[0]["service"], "weixin")
        self.assertGreaterEqual(
            service_ids, {"weixin", "feishu", "discord", "dingding", "wecom"}
        )
        self.assertIn("QR", services[0]["setupNote"])
        self.assertFalse(
            next(service for service in services if service["service"] == "feishu")[
                "configured"
            ]
        )

        configured = self.app.dispatch(
            "POST",
            "/v1/operator/gateway",
            body=self._body(
                {
                    "service": "feishu",
                    "action": "configure",
                    "config": {
                        "accountId": "ops-feishu",
                        "transport": "long-connection",
                        "eventPath": "/hooks/feishu",
                        "enabled": True,
                        "allowGroupChats": True,
                        "secrets": {
                            "app_id": "cli-feishu-app",
                            "app_secret": "cli-feishu-secret",
                        },
                    },
                }
            ),
        )
        self.assertEqual(configured.status_code, 200)
        self.assertEqual(configured.payload["action"], "configured")
        manifest_path = Path(configured.payload["profileManifestPath"])
        manifest = load_global_config(
            manifest_path, state_dir=self.app.repository.database_path.parent
        )
        feishu = manifest["gateway"]["adapters"]["feishu"]
        self.assertTrue(feishu["enabled"])
        self.assertTrue(feishu["control"]["allow_group_chats"])
        account = feishu["accounts"][0]
        self.assertEqual(account["account_id"], "ops-feishu")
        self.assertEqual(account["event_path"], "/hooks/feishu")
        self.assertNotIn("cli-feishu-secret", json.dumps(manifest))
        self.assertEqual(
            [ref["metadata"]["env_var"] for ref in account["secret_references"]],
            [
                "ELEPHANT_FEISHU_OPS_FEISHU_APP_ID",
                "ELEPHANT_FEISHU_OPS_FEISHU_APP_SECRET",
            ],
        )
        secret_file = Path(self.tempdir.name) / "gateway-local-secrets.json"
        local_secrets = json.loads(secret_file.read_text(encoding="utf-8"))
        self.assertEqual(
            local_secrets["ELEPHANT_FEISHU_OPS_FEISHU_APP_ID"], "cli-feishu-app"
        )
        self.assertEqual(
            local_secrets["ELEPHANT_FEISHU_OPS_FEISHU_APP_SECRET"], "cli-feishu-secret"
        )

        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/gateway")
        self.assertEqual(refreshed.status_code, 200)
        refreshed_feishu = next(
            service
            for service in refreshed.payload["dashboard"]["operations"]["gateway"][
                "services"
            ]
            if service["service"] == "feishu"
        )
        self.assertTrue(refreshed_feishu["configured"])
        self.assertEqual(refreshed_feishu["accountCount"], 1)
        self.assertTrue(
            all(field["hasValue"] for field in refreshed_feishu["secretFields"])
        )

        with patch(
            "apps.api.api_runtime_console_ops.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        ) as run_mock:
            started = self.app.dispatch(
                "POST",
                "/v1/operator/gateway",
                body=self._body(
                    {
                        "service": "feishu",
                        "action": "start",
                        "accountId": "ops-feishu",
                        "transport": "long-connection",
                    }
                ),
            )
        self.assertEqual(started.status_code, 200)
        command = run_mock.call_args.args[0]
        self.assertIn("--state-dir", command)
        self.assertEqual(
            command[command.index("--state-dir") + 1], str(Path(self.tempdir.name))
        )
        self.assertIn("--cli-state-dir", command)
        self.assertEqual(
            command[command.index("--cli-state-dir") + 1], str(Path(self.tempdir.name))
        )
        self.assertNotIn("--profile-dir", command)
        self.assertNotIn("--cli-profile-dir", command)


if __name__ == "__main__":
    unittest.main()
