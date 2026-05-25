from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.gateway import (
    CHAT_BOT_ADAPTER_ID,
    DISCORD_ADAPTER_ID,
    FEISHU_ADAPTER_ID,
    GatewayAdapterDescriptor,
    TELEGRAM_ADAPTER_ID,
    WEIXIN_ADAPTER_ID,
    WEBHOOK_ADAPTER_ID,
    build_gateway_app,
    build_gateway_plugin_registry,
)
from apps.gateway.gateway_main_parser import _build_app
from apps.provider_runtime import provider_profile_from_payload
from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayAccountRef,
    GatewayConversationRef,
    GatewayInboundMessage,
    GatewaySenderRef,
)
from packages.models import SurfaceModelProviderCapability
from packages.runtime_config import (
    global_config_path_for_state_dir,
    save_provider_to_config,
)
from packages.storage import RuntimeStorageRepository
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase

EMBEDDING_BOOTSTRAP_STATUSES = {"ready", "pending", "downloading", "failed"}


class GatewayAdapterE2ETests(GatewayAdapterTestBase):

    def test_gateway_cli_app_reuses_cli_provider_when_im_profile_has_none(self) -> None:
        gateway_profile_dir = Path(self.tempdir.name) / "gateway-profile"
        gateway_profile_dir.mkdir()
        (gateway_profile_dir / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile:gateway",
                    "display_name": "Gateway",
                    "mode": "default",
                    "gateway": {"adapters": {}},
                }
            ),
            encoding="utf-8",
        )
        provider_manifest = self._read_runtime_manifest()["provider_profile"]
        provider_profile = provider_profile_from_payload(provider_manifest)
        cli_repository = RuntimeStorageRepository(self.state_dir / "elephant.sqlite3")
        cli_repository.bootstrap()
        cli_repository.upsert_auth_profile(provider_profile)
        SurfaceModelProviderCapability(
            repository=cli_repository,
            fallback=mock.Mock(),
            secret_key_path=self.state_dir / "provider-secrets.key",
        ).store_secret_value(
            provider_profile.secret_references[0], "sk-cli-local-vault"
        )
        app = _build_app(
            SimpleNamespace(
                profile_dir=gateway_profile_dir,
                state_dir=self.state_dir / "gateway",
                cli_profile_dir=self.profile_dir,
                cli_state_dir=self.state_dir,
            )
        )
        self.assertEqual(app.provider_runtime["provider_id"], "openai-compatible")
        self.assertEqual(app.provider_runtime["default_model"], "openai/gpt-4o-mini")
        self.assertEqual(app.provider_runtime["source"], "configured")
        self.assertEqual(
            app.model_provider.surface.resolve_credentials(app.provider_profile)[
                "api_key"
            ],
            "sk-cli-local-vault",
        )

    def test_gateway_cli_app_reuses_default_local_provider_when_dashboard_profile_has_none(
        self,
    ) -> None:
        gateway_profile_dir = Path(self.tempdir.name) / "dashboard-profile"
        cli_profile_dir = Path(self.tempdir.name) / "dashboard-cli-profile"
        default_home = Path(self.tempdir.name) / "default-home"
        default_profile_dir = default_home / "profile"
        gateway_profile_dir.mkdir()
        cli_profile_dir.mkdir()
        default_profile_dir.mkdir(parents=True)
        minimal_manifest = {
            "profile_id": "profile:gateway",
            "display_name": "Gateway",
            "mode": "default",
        }
        (gateway_profile_dir / "profile.json").write_text(
            json.dumps(minimal_manifest), encoding="utf-8"
        )
        (cli_profile_dir / "profile.json").write_text(
            json.dumps(minimal_manifest), encoding="utf-8"
        )
        (default_profile_dir / "profile.json").write_text(
            (self.profile_dir / "profile.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        default_state_dir = default_home / "herd"
        default_state_dir.mkdir(parents=True)
        save_provider_to_config(
            global_config_path_for_state_dir(default_state_dir),
            state_dir=default_state_dir,
            provider_payload=self._read_runtime_manifest()["provider_profile"],
        )
        with mock.patch.dict(
            os.environ, {"ELEPHANT_HOME": str(default_home)}, clear=False
        ):
            app = _build_app(
                SimpleNamespace(
                    profile_dir=gateway_profile_dir,
                    state_dir=self.state_dir / "gateway-default-provider",
                    cli_profile_dir=cli_profile_dir,
                    cli_state_dir=self.state_dir / "dashboard-cli-state",
                )
            )
        self.assertEqual(app.provider_runtime["provider_id"], "openai-compatible")
        self.assertEqual(app.provider_runtime["default_model"], "openai/gpt-4o-mini")
        self.assertEqual(app.provider_runtime["source"], "configured")

    def test_gateway_default_state_dir_uses_cli_runtime_personal_model(self) -> None:
        cli_state_dir = Path(self.tempdir.name) / "cli-shared-state"
        gateway_state_dir = cli_state_dir / "gateway"
        app = _build_app(
            SimpleNamespace(
                profile_dir=self.profile_dir,
                state_dir=gateway_state_dir,
                cli_profile_dir=self.profile_dir,
                cli_state_dir=cli_state_dir,
            )
        )
        self.assertEqual(
            app.repository.database_path, gateway_state_dir / "elephant.sqlite3"
        )
        app.repository.ensure_default_personal_model(
            personal_model_id="personal-model:zoey"
        )
        state = app.repository.create_state(
            personal_model_id="personal-model:zoey",
            state_id="state:zoey",
            elephant_id="zoey",
            elephant_name="Zoey",
            state_anchor="elephant:zoey",
            surface_bindings=("gateway",),
        )
        inbound = GatewayInboundMessage(
            event_id="evt-bind-zoey",
            account=GatewayAccountRef(
                adapter_id=WEIXIN_ADAPTER_ID, account_id="ops-weixin"
            ),
            conversation=GatewayConversationRef(
                conversation_id="wx-zoey", chat_type="direct"
            ),
            sender=GatewaySenderRef(external_user_id="wx-user"),
            body="/elephant create zoey",
        )
        route_identity = app.core.bind_elephant(
            inbound, elephant_id="zoey", state_id=state.state_id
        )
        route = app.core.route_inbound(inbound)
        session = app._ensure_runtime_session(route)
        self.assertEqual(route_identity.state_id, "state:zoey")
        self.assertEqual(session.personal_model_id, "personal-model:zoey")
        self.assertEqual(session.elephant_id, "zoey")
        stale = replace(
            session, personal_model_id="personal-model:old", elephant_id="old"
        )
        app.repository.upsert_episode_state(stale)
        switched_state = app.repository.create_state(
            personal_model_id="personal-model:leah",
            state_id="state:leah",
            elephant_id="leah",
            elephant_name="Leah",
            state_anchor="elephant:leah",
            surface_bindings=("gateway",),
        )
        app.core.bind_elephant(
            inbound, elephant_id="leah", state_id=switched_state.state_id
        )
        switched_session = app._ensure_runtime_session(app.core.route_inbound(inbound))
        self.assertEqual(switched_session.personal_model_id, "personal-model:leah")
        self.assertEqual(switched_session.elephant_id, "leah")

    def test_gateway_state_dir_uses_shared_runtime_database(self) -> None:
        gateway_state_dir = self.state_dir / "gateway"
        gateway_state_dir.mkdir()
        app, _, _ = build_gateway_app(
            provider_profile=self._provider_profile(),
            state_dir=gateway_state_dir,
            control_state_dir=self.state_dir,
        )
        self.assertEqual(
            app.repository.database_path, gateway_state_dir / "elephant.sqlite3"
        )
        self.assertFalse((gateway_state_dir / "gateway-runtime.sqlite3").exists())

    def test_setup_reuses_profile_bundle_and_provider_profile(self) -> None:
        app, chat_adapter, webhook_adapter = self._build()
        summary = app.setup_summary()
        self.assertEqual(summary["profile_id"], "you")
        self.assertEqual(summary["state_dir"], str(self.state_dir))
        self.assertEqual(summary["adapters"]["chat_bot"], CHAT_BOT_ADAPTER_ID)
        self.assertEqual(summary["adapters"]["feishu"], FEISHU_ADAPTER_ID)
        self.assertEqual(summary["adapters"]["webhook"], WEBHOOK_ADAPTER_ID)
        self.assertEqual(summary["adapters"]["telegram"], TELEGRAM_ADAPTER_ID)
        self.assertEqual(summary["provider"]["provider_id"], "openai-compatible")
        self.assertEqual(summary["provider"]["profile_id"], "provider-openrouter")
        self.assertEqual(summary["provider"]["default_model"], "openai/gpt-4o-mini")
        self.assertEqual(summary["provider"]["model_id"], "openai/gpt-4o-mini")
        self.assertIn(
            summary["provider"]["embedding_bootstrap_status"],
            EMBEDDING_BOOTSTRAP_STATUSES,
        )
        self.assertEqual(
            summary["adapter_setup"]["feishu"]["preferred_transport"], "long-connection"
        )
        self.assertEqual(
            summary["adapter_setup"]["feishu"]["implemented_transports"][0],
            "python-sdk-long-connection",
        )
        self.assertEqual(
            summary["adapter_setup"]["feishu"]["delivery_defaults"]["p2p"], "allow"
        )
        self.assertEqual(
            summary["adapter_setup"]["telegram"]["surface"], "telegram-bot-api"
        )
        self.assertEqual(
            summary["adapter_setup"]["telegram"]["delivery_defaults"]["private"],
            "allow",
        )
        self.assertEqual(
            summary["adapter_setup"]["telegram"]["delivery_defaults"]["group"], "review"
        )
        self.assertEqual(summary["adapters"]["discord"], DISCORD_ADAPTER_ID)
        self.assertEqual(
            summary["adapter_setup"]["discord"]["surface"], "discord-gateway"
        )
        self.assertEqual(
            summary["adapter_setup"]["discord"]["preferred_transport"], "gateway"
        )
        self.assertEqual(
            summary["adapter_setup"]["discord"]["supported_events"][0], "MESSAGE_CREATE"
        )
        self.assertEqual(
            summary["adapter_setup"]["discord"]["delivery_defaults"]["direct"], "allow"
        )
        self.assertEqual(
            summary["adapter_setup"]["discord"]["delivery_defaults"]["topic"], "review"
        )
        self.assertEqual(chat_adapter.adapter_id, CHAT_BOT_ADAPTER_ID)
        self.assertEqual(webhook_adapter.adapter_id, WEBHOOK_ADAPTER_ID)

    def test_gateway_chat_runtime_exposes_model_tools_and_skills(self) -> None:
        app, _, _ = self._build()
        self.assertIsNotNone(app.tool_runtime)
        self.assertIsNotNone(app.skill_runtime)
        self.assertIs(app.model_provider.surface.tool_runtime, app.tool_runtime)
        self.assertIs(app.kernel.dependencies.skill_runtime, app.skill_runtime)
        self.assertIsNotNone(app.kernel.dependencies.tools)
        model_visible = {
            tool.tool_id
            for tool in app.tool_runtime.list_tools(
                audience="model", enabled_only=True, available_only=True
            )
        }
        self.assertIn("tool.skill.list", model_visible)
        self.assertIn("tool.skill.view", model_visible)
        self.assertIn("tool.personal_model.search", model_visible)
        self.assertIn("tool.personal_model.update", model_visible)
        self.assertIn("tool.personal_model.questions", model_visible)
        self.assertNotIn("tool.memory.recall", model_visible)
        self.assertNotIn("tool.memory.note", model_visible)
        self.assertNotIn("tool.skill.manage", model_visible)

    def test_gateway_chat_context_discloses_skill_index_and_allows_skill_list_tool(
        self,
    ) -> None:
        app, _, _ = self._build()
        self._bind_gateway_conversation(
            app, adapter_id=CHAT_BOT_ADAPTER_ID, conversation_id="gateway-skill-context"
        )
        inbound = GatewayInboundMessage(
            event_id="evt-gateway-skill-context",
            account=GatewayAccountRef(
                adapter_id=CHAT_BOT_ADAPTER_ID, account_id=DEFAULT_GATEWAY_ACCOUNT_ID
            ),
            conversation=GatewayConversationRef(
                conversation_id="gateway-skill-context", chat_type="direct"
            ),
            sender=GatewaySenderRef(external_user_id="gateway-skill-user"),
            body="show available skills",
        )
        session = app._ensure_runtime_session(app.core.route_inbound(inbound))
        bundle = app.kernel.dependencies.context.assemble(session, (), ())
        self.assertIn("### Understanding tools", bundle.prompt_envelope.frozen_prefix)
        self.assertIn("Use `tool.personal_model.search`", bundle.rendered_prompt)
        assert app.kernel.dependencies.tools is not None
        result = app.kernel.dependencies.tools.invoke(
            "tool.skill.list", {"limit": 4}, session_id=session.episode_id
        )
        self.assertEqual(result.outcome, "success")
        self.assertIn("skill", result.side_effects)
        self.assertNotEqual(result.summary.strip(), "<empty>")

    def test_gateway_chat_model_personal_model_update_commits_claim(self) -> None:
        app, _, _ = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            conversation_id="gateway-personal-model-tools",
        )
        inbound = GatewayInboundMessage(
            event_id="evt-gateway-personal-model-tools",
            account=GatewayAccountRef(
                adapter_id=CHAT_BOT_ADAPTER_ID, account_id=DEFAULT_GATEWAY_ACCOUNT_ID
            ),
            conversation=GatewayConversationRef(
                conversation_id="gateway-personal-model-tools", chat_type="direct"
            ),
            sender=GatewaySenderRef(external_user_id="gateway-memory-user"),
            body="remember that I prefer concise replies",
        )
        session = app._ensure_runtime_session(app.core.route_inbound(inbound))
        assert app.kernel.dependencies.tools is not None
        remembered = app.kernel.dependencies.tools.invoke(
            "tool.personal_model.update",
            {
                "action": "remember",
                "lens": "identity",
                "topic": "identity.style.reply",
                "text": "User prefers concise replies.",
                "reason": "user explicitly stated this preference",
            },
            session_id=session.episode_id,
        )
        queried = app.kernel.dependencies.tools.invoke(
            "tool.personal_model.search",
            {"query": "concise", "limit": 3},
            session_id=session.episode_id,
        )
        self.assertEqual(remembered.outcome, "success")
        self.assertIn("status: active", remembered.summary)
        self.assertEqual(queried.outcome, "success")
        self.assertIn("claims:", queried.summary)
        self.assertIn("User prefers concise replies.", queried.summary)

    def test_setup_summary_accepts_custom_plugin_registry_adapter(self) -> None:
        registry = build_gateway_plugin_registry()
        registry.register_adapter(
            GatewayAdapterDescriptor(
                key="discord",
                adapter_id="messaging.discord",
                surface="discord-bot",
                default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
                operator_action="configure DISCORD_BOT_TOKEN and register a Discord gateway service",
            ),
            factory=lambda app: object(),
        )
        app, _, _ = build_gateway_app(
            provider_profile=self._provider_profile(),
            state_dir=self.state_dir,
            control_state_dir=self.state_dir,
            plugin_registry=registry,
        )
        summary = app.setup_summary()
        self.assertEqual(summary["adapters"]["discord"], "messaging.discord")
        self.assertEqual(summary["adapter_setup"]["discord"]["surface"], "discord-bot")
        self.assertEqual(
            summary["adapter_setup"]["discord"]["default_account_id"],
            DEFAULT_GATEWAY_ACCOUNT_ID,
        )


if __name__ == "__main__":
    unittest.main()
