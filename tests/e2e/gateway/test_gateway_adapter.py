from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.gateway import (
    CHAT_BOT_ADAPTER_ID,
    DEFAULT_DISCORD_BOT_TOKEN_ENV,
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    DEFAULT_TELEGRAM_BOT_TOKEN_ENV,
    DISCORD_ADAPTER_ID,
    FEISHU_ADAPTER_ID,
    DiscordGatewayService,
    DiscordMessagingAdapter,
    FeishuGatewayService,
    GatewayAdapterDescriptor,
    TelegramGatewayService,
    TELEGRAM_ADAPTER_ID,
    WECOM_ADAPTER_ID,
    WEIXIN_ADAPTER_ID,
    WEBHOOK_ADAPTER_ID,
    WecomGatewayService,
    WeixinGatewayService,
    load_discord_gateway_accounts,
    FeishuMessagingAdapter,
    TelegramMessagingAdapter,
    build_gateway_app,
    build_gateway_plugin_registry,
    create_gateway_web_app,
    load_feishu_gateway_accounts,
    load_telegram_gateway_accounts,
)
from apps.gateway.discord import DiscordPyDeliveryTransport
from apps.gateway.runtime_capabilities import GatewayRecallCapability
from apps.gateway.weixin_service import MessageDeduplicator
import apps.gateway.__main__ as gateway_main
from apps.gateway.__main__ import command_main
from apps.gateway.gateway_main_parser import _build_app
from apps.provider_runtime import provider_profile_from_payload, runtime_local_secret_env_path
from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayAccountRef,
    GatewayConversationRef,
    GatewayIdentityKey,
    GatewayInboundMessage,
    GatewayOutboundMessage,
    GatewayRouteState,
    GatewaySenderRef,
)
from packages.contracts.layers import Episode
from packages.contracts.runtime import EvidenceRetrievalRequest
from packages.models import SurfaceModelProviderCapability
from packages.runtime_config import global_config_path_for_state_dir, load_global_config, save_provider_to_config, write_global_config
from packages.security.runtime import PolicyDecision
from packages.storage import RuntimeStorageRepository


class GatewayAdapterE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.ensure_discord_sdk_patcher = mock.patch(
            "apps.gateway.gateway_main_setup_impl._ensure_discord_sdk_available",
            return_value=False,
        )
        self.ensure_discord_sdk = self.ensure_discord_sdk_patcher.start()
        self.ensure_feishu_sdk_patcher = mock.patch(
            "apps.gateway.gateway_main_setup_impl._ensure_feishu_sdk_available",
            return_value=False,
        )
        self.ensure_feishu_sdk = self.ensure_feishu_sdk_patcher.start()
        self.ensure_parser_discord_sdk_patcher = mock.patch(
            "apps.gateway.gateway_main_parser._ensure_discord_sdk_available",
            return_value=False,
        )
        self.ensure_parser_discord_sdk = self.ensure_parser_discord_sdk_patcher.start()
        self.ensure_parser_feishu_sdk_patcher = mock.patch(
            "apps.gateway.gateway_main_parser._ensure_feishu_sdk_available",
            return_value=False,
        )
        self.ensure_parser_feishu_sdk = self.ensure_parser_feishu_sdk_patcher.start()
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tempdir.name)
        self.profile_dir = root / "profile"
        self.state_dir = root / "state"
        self.profile_dir.mkdir()
        self.state_dir.mkdir()
        self.profile_manifest = {
            "profile_id": "profile:operator",
            "display_name": "Operator",
            "mode": "default",
            "provider_profile": {
                "profile_id": "provider-openrouter",
                "provider_id": "openai-compatible",
                "base_url": "https://openrouter.ai/api/v1",
                "default_model": "openai/gpt-4o-mini",
                "extra_headers": {"x-tenant": "elephant"},
                "secret_references": [
                    {
                        "reference_id": "secret-openrouter-token",
                        "provider_id": "openai-compatible",
                        "secret_name": "api_token",
                        "secret_key": "api_key",
                        "metadata": {
                            "env_var": "ELEPHANT_OPENROUTER_API_KEY",
                        },
                    }
                ],
            },
            "gateway": {
                "adapters": {
                    "feishu": {
                        "enabled": True,
                        "surface": "long-connection",
                        "event_path": "/hooks/feishu",
                        "accounts": [
                            {
                                "account_id": "ops-feishu",
                                "env": {
                                    "app_id": "ELEPHANT_TEST_FEISHU_APP_ID",
                                    "app_secret": "ELEPHANT_TEST_FEISHU_APP_SECRET",
                                },
                            }
                        ],
                    }
                }
            },
        }
        self._write_profile_manifest(self.profile_manifest)
    def tearDown(self) -> None:
        self.ensure_discord_sdk_patcher.stop()
        self.ensure_feishu_sdk_patcher.stop()
        self.ensure_parser_discord_sdk_patcher.stop()
        self.ensure_parser_feishu_sdk_patcher.stop()
        self.tempdir.cleanup()

    def test_gateway_recall_capability_accepts_episode_scope(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeRecallRuntime:
            def retrieve_evidence(self, request):
                calls.append({"evidence_request": request})
                return SimpleNamespace(candidates=(SimpleNamespace(recall="personal-recall"),), scope_episode_ids=request.lineage_episode_ids, scope_reason=request.scope_reason)

        capability = GatewayRecallCapability(FakeRecallRuntime())

        evidence_request = EvidenceRetrievalRequest(
            episode_id="session-active",
            personal_model_id="personal-model:zoey",
            elephant_id="zoey",
            lineage_episode_ids=("session-active",),
            query="what does the user prefer",
            scopes=("episode", "elephant", "personal_model"),
            scope_reason="gateway personal recall",
        )
        retrieval = capability.retrieve_evidence(evidence_request)
        self.assertEqual(retrieval.candidates[0].recall, "personal-recall")
        self.assertEqual(calls[0]["evidence_request"].scopes, ("episode", "elephant", "personal_model"))
        self.assertEqual(calls[0]["evidence_request"].personal_model_id, "personal-model:zoey")

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
        ).store_secret_value(provider_profile.secret_references[0], "sk-cli-local-vault")

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
        self.assertEqual(app.model_provider.surface.resolve_credentials(app.provider_profile)["api_key"], "sk-cli-local-vault")

    def test_gateway_cli_app_reuses_default_local_provider_when_dashboard_profile_has_none(self) -> None:
        gateway_profile_dir = Path(self.tempdir.name) / "dashboard-profile"
        cli_profile_dir = Path(self.tempdir.name) / "dashboard-cli-profile"
        default_home = Path(self.tempdir.name) / "default-home"
        default_profile_dir = default_home / "profile"
        gateway_profile_dir.mkdir()
        cli_profile_dir.mkdir()
        default_profile_dir.mkdir(parents=True)
        minimal_manifest = {"profile_id": "profile:gateway", "display_name": "Gateway", "mode": "default"}
        (gateway_profile_dir / "profile.json").write_text(json.dumps(minimal_manifest), encoding="utf-8")
        (cli_profile_dir / "profile.json").write_text(json.dumps(minimal_manifest), encoding="utf-8")
        (default_profile_dir / "profile.json").write_text((self.profile_dir / "profile.json").read_text(encoding="utf-8"), encoding="utf-8")
        default_state_dir = default_home / "herd"
        default_state_dir.mkdir(parents=True)
        save_provider_to_config(
            global_config_path_for_state_dir(default_state_dir),
            state_dir=default_state_dir,
            provider_payload=self._read_runtime_manifest()["provider_profile"],
        )

        with mock.patch.dict(os.environ, {"ELEPHANT_HOME": str(default_home)}, clear=False):
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
        self.assertEqual(app.repository.database_path, gateway_state_dir / "elephant.sqlite3")
        app.repository.ensure_default_personal_model(personal_model_id="personal-model:zoey")
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
            account=GatewayAccountRef(adapter_id=WEIXIN_ADAPTER_ID, account_id="ops-weixin"),
            conversation=GatewayConversationRef(conversation_id="wx-zoey", chat_type="direct"),
            sender=GatewaySenderRef(external_user_id="wx-user"),
            body="/elephant create zoey",
        )
        route_identity = app.core.bind_elephant(inbound, elephant_id="zoey", state_id=state.state_id)
        route = app.core.route_inbound(inbound)
        session = app._ensure_runtime_session(route)

        self.assertEqual(route_identity.state_id, "state:zoey")
        self.assertEqual(session.personal_model_id, "personal-model:zoey")
        self.assertEqual(session.elephant_id, "zoey")

        stale = replace(session, personal_model_id="personal-model:old", elephant_id="old")
        app.repository.upsert_episode_state(stale)
        switched_state = app.repository.create_state(
            personal_model_id="personal-model:leah",
            state_id="state:leah",
            elephant_id="leah",
            elephant_name="Leah",
            state_anchor="elephant:leah",
            surface_bindings=("gateway",),
        )
        app.core.bind_elephant(inbound, elephant_id="leah", state_id=switched_state.state_id)
        switched_session = app._ensure_runtime_session(app.core.route_inbound(inbound))
        self.assertEqual(switched_session.personal_model_id, "personal-model:leah")
        self.assertEqual(switched_session.elephant_id, "leah")

    def test_gateway_help_omits_hidden_top_level_aliases(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit) as exit_info, redirect_stdout(output):
            command_main(
                ["-h"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_info.exception.code, 0)
        rendered = output.getvalue()
        self.assertNotIn("==SUPPRESS==", rendered)
        self.assertIn("{setup,status,doctor,describe,feishu,discord,dingding,weixin,wecom}", rendered)
        self.assertNotIn("\n    serve", rendered)
        self.assertNotIn("\n    add", rendered)

    def test_gateway_module_has_no_legacy_top_level_parser(self) -> None:
        self.assertFalse(hasattr(gateway_main, "legacy_main"))
        self.assertFalse(hasattr(gateway_main, "_build_legacy_parser"))

    def test_gateway_provider_help_shows_public_describe_commands(self) -> None:
        for provider, expected_help in (
            ("feishu", "Print resolved Feishu account wiring as JSON."),
            ("discord", "Print resolved Discord account wiring as JSON."),
        ):
            output = io.StringIO()
            with self.assertRaises(SystemExit) as exit_info, redirect_stdout(output):
                command_main(
                    [provider, "-h"],
                    default_state_dir=self.state_dir,
                    default_control_state_dir=self.state_dir,
                )

            self.assertEqual(exit_info.exception.code, 0)
            rendered = output.getvalue()
            self.assertNotIn("==SUPPRESS==", rendered)
            self.assertIn(expected_help, rendered)

    def _write_profile_manifest(self, payload: dict[str, object]) -> None:
        serialized = json.dumps(payload)
        (self.profile_dir / "profile.json").write_text(serialized, encoding="utf-8")
        # build_gateway_app now infers the install root from state_dir and reads
        # the extension manifest from that root.
        (Path(self.tempdir.name) / "profile.json").write_text(serialized, encoding="utf-8")
        config_path = global_config_path_for_state_dir(self.state_dir)
        config = load_global_config(config_path, state_dir=self.state_dir)
        if isinstance(payload.get("gateway"), dict):
            config["gateway"] = dict(payload["gateway"])
        else:
            config.pop("gateway", None)
        write_global_config(config_path, config)
        if isinstance(payload.get("provider_profile"), dict):
            save_provider_to_config(
                config_path,
                state_dir=self.state_dir,
                provider_payload=payload["provider_profile"],
            )

    def _provider_profile(self):
        payload = json.loads((self.profile_dir / "profile.json").read_text(encoding="utf-8"))
        provider_payload = payload.get("provider_profile")
        return provider_profile_from_payload(provider_payload) if isinstance(provider_payload, dict) else None

    def _read_runtime_manifest(self) -> dict[str, object]:
        payload = json.loads((self.profile_dir / "profile.json").read_text(encoding="utf-8"))
        config = load_global_config(
            global_config_path_for_state_dir(self.state_dir),
            state_dir=self.state_dir,
        )
        if isinstance(config.get("gateway"), dict):
            payload["gateway"] = dict(config["gateway"])
        if isinstance(config.get("extensions"), dict):
            payload["extensions"] = dict(config["extensions"])
        return payload

    def _build(self):
        return build_gateway_app(
            provider_profile=self._provider_profile(),
            state_dir=self.state_dir,
            control_state_dir=self.state_dir,
        )

    def test_gateway_state_dir_uses_shared_runtime_database(self) -> None:
        gateway_state_dir = self.state_dir / "gateway"
        gateway_state_dir.mkdir()

        app, _, _ = build_gateway_app(
            provider_profile=self._provider_profile(),
            state_dir=gateway_state_dir,
            control_state_dir=self.state_dir,
        )

        self.assertEqual(app.repository.database_path, gateway_state_dir / "elephant.sqlite3")
        self.assertFalse((gateway_state_dir / "gateway-runtime.sqlite3").exists())

    def _bind_cli_control_conversation(
        self,
        service,
        *,
        account_id: str,
        conversation_id: str,
        elephant_id: str,
        session_id: str,
    ) -> None:
        assert service.cli_control is not None
        assert service.cli_control.binding_store is not None
        adapter_id = service.adapter.adapter_id if service.adapter is not None else FEISHU_ADAPTER_ID
        self._bind_gateway_conversation(
            service.app,
            adapter_id=adapter_id,
            account_id=account_id,
            conversation_id=conversation_id,
            elephant_id=elephant_id,
        )
        service.cli_control.binding_store.set(
            account_id=account_id,
            conversation_id=conversation_id,
            elephant_id=elephant_id,
            session_id=session_id,
        )

    def _update_manifest(self, mutator) -> None:
        manifest_path = self.profile_dir / "profile.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutator(payload)
        self._write_profile_manifest(payload)

    def _call_wsgi(
        self,
        app,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[str, dict[str, object]]:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/json",
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": "8788",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        response_body = b"".join(app(environ, start_response))
        return str(captured["status"]), json.loads(response_body.decode("utf-8"))

    def _wait_until(
        self,
        predicate,
        *,
        timeout: float = 2.0,
        interval: float = 0.01,
        message: str = "condition not met in time",
    ) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(interval)
        self.fail(message)

    def _gateway_route_session_id(
        self,
        *,
        adapter_id: str,
        account_id: str,
        conversation_id: str,
    ) -> str:
        return f"session:{adapter_id}:{account_id}:{conversation_id}"

    def _ensure_gateway_elephant_state(self, app, *, elephant_id: str = "demo"):
        state_id = f"state:{elephant_id}"
        existing = app.repository.load_state(state_id)
        if existing is not None:
            return existing
        return app.repository.create_state(
            state_id=state_id,
            elephant_id=elephant_id,
            elephant_name=elephant_id,
            surface_bindings=("gateway",),
            metadata={"profile_id": "profile:operator"},
        )

    def _bind_gateway_conversation(
        self,
        app,
        *,
        adapter_id: str,
        conversation_id: str,
        account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID,
        elephant_id: str = "demo",
        parent_conversation_id: str | None = None,
    ) -> None:
        state = self._ensure_gateway_elephant_state(app, elephant_id=elephant_id)
        app.core.bind_elephant(
            GatewayInboundMessage(
                event_id=f"bind:{adapter_id}:{account_id}:{conversation_id}",
                account=GatewayAccountRef(adapter_id=adapter_id, account_id=account_id),
                conversation=GatewayConversationRef(
                    conversation_id=conversation_id,
                    parent_conversation_id=parent_conversation_id,
                    chat_type="direct",
                ),
                sender=GatewaySenderRef(external_user_id="test-user"),
                body="/elephant create",
            ),
            elephant_id=state.elephant_id,
            state_id=state.state_id,
        )

    def _install_shared_runtime_stub(
        self,
        app,
        *,
        response_prefix: str = "gateway-handled",
        session_ids: dict[str, str] | None = None,
        on_call=None,
    ) -> list[dict[str, object]]:
        calls: list[dict[str, object]] = []

        def _handle_message(_app, inbound, **kwargs):
            session_id = (
                session_ids.get(inbound.conversation_id)
                if session_ids is not None and inbound.conversation_id in session_ids
                else self._gateway_route_session_id(
                    adapter_id=inbound.adapter_id,
                    account_id=inbound.account_id,
                    conversation_id=inbound.conversation_id,
                )
            )
            if callable(on_call):
                on_call(inbound, session_id)
            identity = app.core.dependencies.identity_store.lookup(
                GatewayIdentityKey(
                    adapter_id=inbound.adapter_id,
                    account_id=inbound.account_id,
                    conversation_id=inbound.conversation_id,
                )
            )
            calls.append(
                {
                    "session_id": session_id,
                    "prompt": inbound.body,
                    "conversation_id": inbound.conversation_id,
                }
            )
            now = datetime.now(UTC)
            outbound = GatewayOutboundMessage(
                message_id=f"gateway-reply:{inbound.conversation_id}",
                account=inbound.account,
                conversation=inbound.conversation,
                session_id=session_id,
                body=f"{response_prefix}:{inbound.body}",
                reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
                attachment_refs=(),
                metadata={"runtime_surface": "gateway.shared-runtime"},
            )
            return SimpleNamespace(
                route=SimpleNamespace(
                    inbound=inbound,
                    identity=identity,
                    session=GatewayRouteState(
                        session_id=session_id,
                        profile_id="profile:operator",
                        status="open",
                        started_at=now,
                        updated_at=now,
                    ),
                ),
                delivery=SimpleNamespace(
                    policy_result=SimpleNamespace(decision=PolicyDecision.ALLOW),
                    outcome="delivered",
                    outbound=outbound,
                    summary=f"{response_prefix}:{inbound.body}",
                ),
            )

        patcher = mock.patch.object(type(app), "handle_message", _handle_message)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def _feishu_message_event(
        self,
        *,
        event_id: str,
        message_id: str,
        chat_id: str,
        text: str,
        app_id: str = "cli_feishu_bot",
        sender_id: str = "ou_ws",
        sender_name: str = "WS Ada",
        chat_type: str = "p2p",
    ) -> dict[str, object]:
        return {
            "schema": "2.0",
            "header": {
                "event_id": event_id,
                "event_type": "im.message.receive_v1",
                "app_id": app_id,
                "tenant_key": "tenant-alpha",
            },
            "event": {
                "sender": {
                    "sender_id": {"open_id": sender_id},
                    "sender_type": "user",
                    "name": sender_name,
                },
                "message": {
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "chat_type": chat_type,
                    "message_type": "text",
                    "content": json.dumps({"text": text}),
                },
            },
        }

    class _FakeDiscordDeliveryTransport:
        def __init__(self) -> None:
            self.requests: list[tuple[dict[str, object], object]] = []

        async def send_request(self, request, *, account):
            normalized_request = {str(key): value for key, value in request.items()}
            self.requests.append((normalized_request, account))
            return {"id": "discord-reply-1"}

    def test_gateway_add_feishu_command_writes_secret_reference_profile_config(self) -> None:
        self._update_manifest(lambda payload: payload.pop("gateway", None))

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "feishu",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-start",
                ]
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Configured Feishu IM", rendered)
        self.assertIn("elephant gateway feishu start", rendered)

        manifest = self._read_runtime_manifest()
        self.assertIn("provider_profile", manifest)
        feishu = manifest["gateway"]["adapters"]["feishu"]
        self.assertTrue(feishu["enabled"])
        self.assertEqual(feishu["surface"], "long-connection")
        self.assertNotIn("default_elephant_id", feishu.get("control", {}))
        self.assertNotIn("default_session_id", feishu.get("control", {}))
        self.assertNotIn("auto_create_elephant", feishu.get("control", {}))
        self.assertEqual(len(feishu["accounts"]), 1)
        account = feishu["accounts"][0]
        self.assertEqual(account["account_id"], DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertEqual(account["surface"], "long-connection")
        self.assertEqual(account["event_path"], "/feishu/events")
        self.assertEqual(
            account["secret_references"],
            [
                {
                    "reference_id": "secret-feishu-default-app-id",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_id",
                    "secret_key": "app_id",
                    "metadata": {"env_var": DEFAULT_FEISHU_APP_ID_ENV},
                },
                {
                    "reference_id": "secret-feishu-default-app-secret",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_secret",
                    "secret_key": "app_secret",
                    "metadata": {"env_var": DEFAULT_FEISHU_APP_SECRET_ENV},
                },
            ],
        )

        app, _, _ = self._build()
        accounts = load_feishu_gateway_accounts(app, respect_enabled=False)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].account_id, DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertEqual(accounts[0].surface, "long-connection")
        self.assertEqual(
            tuple(reference.reference_id for reference in accounts[0].secret_references),
            ("secret-feishu-default-app-id", "secret-feishu-default-app-secret"),
        )

        description = FeishuGatewayService(app=app, respect_enabled=False).describe()
        described_account = description["accounts"][0]
        self.assertEqual(described_account["credentials_source"], "secret_references")
        self.assertEqual(
            described_account["secret_reference_ids"],
            ("secret-feishu-default-app-id", "secret-feishu-default-app-secret"),
        )
        self.ensure_feishu_sdk.assert_called_with(reason="Feishu setup")

    def test_ensure_feishu_sdk_available_installs_missing_dependency(self) -> None:
        self.ensure_feishu_sdk_patcher.stop()
        try:
            output = io.StringIO()
            with (
                mock.patch(
                    "apps.gateway.__main__.importlib.util.find_spec",
                    side_effect=[None, object()],
                ),
                mock.patch("apps.gateway.__main__.subprocess.run") as run,
                redirect_stdout(output),
            ):
                installed = gateway_main._ensure_feishu_sdk_available(reason="Feishu setup")

            self.assertTrue(installed)
            run.assert_called_once_with(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    gateway_main.FEISHU_SDK_PIP_SPEC,
                ],
                check=True,
            )
            rendered = output.getvalue()
            self.assertIn("Preparing Feishu support for Feishu setup...", rendered)
            self.assertIn("Feishu support is ready.", rendered)
        finally:
            self.ensure_feishu_sdk = self.ensure_feishu_sdk_patcher.start()

    def test_ensure_discord_sdk_available_installs_missing_dependency(self) -> None:
        self.ensure_discord_sdk_patcher.stop()
        try:
            output = io.StringIO()
            with (
                mock.patch(
                    "apps.gateway.__main__.importlib.util.find_spec",
                    side_effect=[None, object()],
                ),
                mock.patch("apps.gateway.__main__.subprocess.run") as run,
                redirect_stdout(output),
            ):
                installed = gateway_main._ensure_discord_sdk_available(reason="Discord setup")

            self.assertTrue(installed)
            run.assert_called_once_with(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    gateway_main.DISCORD_PY_PIP_SPEC,
                ],
                check=True,
            )
            rendered = output.getvalue()
            self.assertIn("Preparing Discord support for Discord setup...", rendered)
            self.assertIn("Discord support is ready.", rendered)
        finally:
            self.ensure_discord_sdk = self.ensure_discord_sdk_patcher.start()

    def test_gateway_add_discord_command_writes_profile_config_and_local_secret(self) -> None:
        self._update_manifest(lambda payload: payload["gateway"]["adapters"].pop("discord", None))

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "discord",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-wizard",
                    "--account-id",
                    "ops-discord",
                    "--no-start",
                    "--bot-token-env-var",
                    "ELEPHANT_TEST_DISCORD_BOT_TOKEN",
                    "--bot-token",
                    "discord-token-123",
                    "--allow-guild-id",
                    "123",
                    "--allow-channel-id",
                    "456",
                    "--enabled",
                ]
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Configured Discord IM", rendered)
        self.assertIn("Discord developer portal checklist:", rendered)
        self.assertIn("Open Discord Developer Portal", rendered)
        self.assertIn("MESSAGE_CONTENT", rendered)
        self.assertIn("View Channels", rendered)
        self.assertIn("Send Messages", rendered)
        self.assertIn("Send Messages in Threads", rendered)
        self.assertIn("Read Message History", rendered)
        self.assertIn("elephant gateway discord start", rendered)
        self.ensure_discord_sdk.assert_called_with(reason="Discord setup")

        manifest = self._read_runtime_manifest()
        discord = manifest["gateway"]["adapters"]["discord"]
        self.assertTrue(discord["enabled"])
        self.assertEqual(discord["surface"], "gateway")
        account = discord["accounts"][0]
        self.assertEqual(account["account_id"], "ops-discord")
        self.assertEqual(account["surface"], "gateway")
        self.assertEqual(account["env"], {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"})
        self.assertEqual(account["allow_guild_ids"], ["123"])
        self.assertEqual(account["allow_channel_ids"], ["456"])

        secret_path = self.state_dir / "gateway-local-secrets.json"
        self.assertTrue(secret_path.exists())
        local_secrets = json.loads(secret_path.read_text(encoding="utf-8"))
        self.assertEqual(local_secrets["ELEPHANT_TEST_DISCORD_BOT_TOKEN"], "discord-token-123")

        describe_output = io.StringIO()
        with redirect_stdout(describe_output):
            exit_code = command_main(
                ["discord", "describe"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        described = json.loads(describe_output.getvalue())
        account = described["discord"]["accounts"][0]
        self.assertEqual(account["account_id"], "ops-discord")
        self.assertEqual(account["credentials_status"], "configured")
        self.assertEqual(account["bot_token_env_var"], "ELEPHANT_TEST_DISCORD_BOT_TOKEN")

    def test_gateway_add_discord_command_uses_wizard_by_default_when_shell_is_interactive(self) -> None:
        self._update_manifest(lambda payload: payload["gateway"]["adapters"].pop("discord", None))
        output = io.StringIO()
        with (
            mock.patch("apps.gateway.gateway_main_setup_impl._interactive_shell_supported", return_value=True),
            mock.patch("apps.gateway.gateway_main_setup_impl._start_discord_runtime_after_setup", return_value=0) as auto_start,
            mock.patch("apps.gateway.gateway_main_setup_impl.getpass.getpass", return_value="wizard-discord-token"),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                [
                    "discord",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                ]
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Bring Discord into Elephant Agent Gateway.", rendered)
        self.assertIn("Discord portal checklist", rendered)
        self.assertIn("Configured Discord IM", rendered)
        self.assertIn("Starting the configured Discord bridge in the background...", rendered)
        self.assertIn("Discord setup is complete.", rendered)
        auto_start.assert_called_once()
        self.assertEqual(auto_start.call_args.kwargs["transport"], "gateway")

        manifest = self._read_runtime_manifest()
        discord = manifest["gateway"]["adapters"]["discord"]
        account = discord["accounts"][0]
        self.assertEqual(account["account_id"], DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertTrue(discord["enabled"])
        self.assertTrue(account["enabled"])
        self.assertNotIn("default_elephant_id", discord.get("control", {}))
        self.assertNotIn("default_session_id", discord.get("control", {}))
        self.assertNotIn("auto_create_elephant", discord.get("control", {}))
        self.assertNotIn("allow_group_chats", discord.get("control", {}))
        self.assertNotIn("allow_guild_ids", account)
        self.assertNotIn("allow_channel_ids", account)

        local_secrets = json.loads((self.state_dir / "gateway-local-secrets.json").read_text(encoding="utf-8"))
        self.assertEqual(local_secrets[DEFAULT_DISCORD_BOT_TOKEN_ENV], "wizard-discord-token")

    def test_gateway_add_discord_command_replaces_unconfigured_default_placeholder(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "discord",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-wizard",
                    "--account-id",
                    "ops-discord",
                    "--no-start",
                    "--bot-token",
                    "discord-token-ops",
                ]
            )

        self.assertEqual(exit_code, 0)
        manifest = self._read_runtime_manifest()
        discord = manifest["gateway"]["adapters"]["discord"]
        self.assertEqual(len(discord["accounts"]), 1)
        account = discord["accounts"][0]
        self.assertEqual(account["account_id"], "ops-discord")
        self.assertEqual(account["env"], {"bot_token": "ELEPHANT_DISCORD_OPS_DISCORD_BOT_TOKEN"})
        rendered = output.getvalue()
        self.assertNotIn("Configure the Discord bot token", rendered)

    def test_gateway_add_discord_command_can_disable_account_without_disabling_adapter(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "discord",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-wizard",
                    "--account-id",
                    "ops-discord",
                    "--no-start",
                    "--bot-token",
                    "discord-token-ops",
                    "--enabled",
                    "--account-disabled",
                ]
            )

        self.assertEqual(exit_code, 0)
        manifest = self._read_runtime_manifest()
        discord = manifest["gateway"]["adapters"]["discord"]
        self.assertTrue(discord["enabled"])
        self.assertFalse(discord["accounts"][0]["enabled"])
        self.assertIn("Discord account enabled for default runtime starts: no", output.getvalue())

    def test_gateway_add_feishu_command_updates_existing_account_without_clobbering_profile(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "feishu",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--account-id",
                    "ops-feishu",
                    "--transport",
                    "long-connection",
                    "--no-start",
                    "--app-id-env-var",
                    "ELEPHANT_UPDATED_FEISHU_APP_ID",
                    "--app-secret-env-var",
                    "ELEPHANT_UPDATED_FEISHU_APP_SECRET",
                    "--enabled",
                ]
            )

        self.assertEqual(exit_code, 0)
        manifest = self._read_runtime_manifest()
        self.assertEqual(manifest["provider_profile"]["profile_id"], "provider-openrouter")
        feishu = manifest["gateway"]["adapters"]["feishu"]
        self.assertTrue(feishu["enabled"])
        self.assertEqual(feishu["surface"], "long-connection")
        self.assertEqual(len(feishu["accounts"]), 1)
        account = feishu["accounts"][0]
        self.assertEqual(account["account_id"], "ops-feishu")
        self.assertEqual(account["surface"], "long-connection")
        self.assertEqual(account["event_path"], "/hooks/feishu")
        self.assertEqual(
            account["secret_references"],
            [
                {
                    "reference_id": "secret-feishu-ops-feishu-app-id",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_id",
                    "secret_key": "app_id",
                    "metadata": {"env_var": "ELEPHANT_UPDATED_FEISHU_APP_ID"},
                },
                {
                    "reference_id": "secret-feishu-ops-feishu-app-secret",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_secret",
                    "secret_key": "app_secret",
                    "metadata": {"env_var": "ELEPHANT_UPDATED_FEISHU_APP_SECRET"},
                },
            ],
        )

        app, _, _ = self._build()
        accounts = load_feishu_gateway_accounts(app)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].account_id, "ops-feishu")
        self.assertEqual(accounts[0].surface, "long-connection")
        self.assertEqual(accounts[0].event_path, "/hooks/feishu")
        self.assertEqual(
            tuple(reference.reference_id for reference in accounts[0].secret_references),
            ("secret-feishu-ops-feishu-app-id", "secret-feishu-ops-feishu-app-secret"),
        )

        description = FeishuGatewayService(app=app).describe()
        described_account = description["accounts"][0]
        self.assertEqual(described_account["credentials_source"], "secret_references")
        self.assertEqual(
            described_account["secret_reference_ids"],
            ("secret-feishu-ops-feishu-app-id", "secret-feishu-ops-feishu-app-secret"),
        )

    def test_gateway_add_feishu_command_persists_local_secret_file_for_raw_credentials(self) -> None:
        self._update_manifest(lambda payload: payload.pop("gateway", None))

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "feishu",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-wizard",
                    "--no-start",
                    "--app-id",
                    "cli-app-id-123",
                    "--app-secret",
                    "cli-app-secret-456",
                ]
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Local IM secret file:", rendered)

        secret_path = self.state_dir / "gateway-local-secrets.json"
        self.assertTrue(secret_path.exists())
        local_secrets = json.loads(secret_path.read_text(encoding="utf-8"))
        self.assertEqual(local_secrets[DEFAULT_FEISHU_APP_ID_ENV], "cli-app-id-123")
        self.assertEqual(local_secrets[DEFAULT_FEISHU_APP_SECRET_ENV], "cli-app-secret-456")

        describe_output = io.StringIO()
        with redirect_stdout(describe_output):
            exit_code = command_main(
                ["feishu", "describe"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        described = json.loads(describe_output.getvalue())
        account = described["feishu"]["accounts"][0]
        self.assertEqual(account["credentials_status"], "configured")
        self.assertEqual(account["resolved_app_id"], "cli-app-id-123")

    def test_im_setup_command_can_capture_raw_credentials(self) -> None:
        self._update_manifest(lambda payload: payload.pop("gateway", None))
        scripted_answers = iter(["3", "wizard-app-id-789"])

        output = io.StringIO()
        with (
            mock.patch("apps.gateway.gateway_main_setup_impl._start_feishu_runtime_after_setup", return_value=0) as auto_start,
            mock.patch("builtins.input", side_effect=lambda _prompt="": next(scripted_answers)),
            mock.patch("apps.gateway.gateway_main_setup_impl.getpass.getpass", return_value="wizard-app-secret-789"),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["setup"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Starting the configured Feishu bridge in the background...", rendered)
        self.assertIn("Feishu setup is complete.", rendered)
        auto_start.assert_called_once()
        self.assertEqual(auto_start.call_args.kwargs["transport"], "long-connection")
        manifest = self._read_runtime_manifest()
        feishu = manifest["gateway"]["adapters"]["feishu"]
        account = feishu["accounts"][0]
        self.assertEqual(account["account_id"], DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertNotIn("default_elephant_id", feishu.get("control", {}))
        self.assertNotIn("default_session_id", feishu.get("control", {}))
        self.assertNotIn("auto_create_elephant", feishu.get("control", {}))
        self.assertNotIn("allow_group_chats", feishu.get("control", {}))
        self.assertEqual(
            account["secret_references"],
            [
                {
                    "reference_id": "secret-feishu-default-app-id",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_id",
                    "secret_key": "app_id",
                    "metadata": {"env_var": DEFAULT_FEISHU_APP_ID_ENV},
                },
                {
                    "reference_id": "secret-feishu-default-app-secret",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_secret",
                    "secret_key": "app_secret",
                    "metadata": {"env_var": DEFAULT_FEISHU_APP_SECRET_ENV},
                },
            ],
        )

        local_secrets = json.loads((self.state_dir / "gateway-local-secrets.json").read_text(encoding="utf-8"))
        self.assertEqual(local_secrets[DEFAULT_FEISHU_APP_ID_ENV], "wizard-app-id-789")
        self.assertEqual(local_secrets[DEFAULT_FEISHU_APP_SECRET_ENV], "wizard-app-secret-789")

    def test_im_setup_command_does_not_capture_elephant_defaults(self) -> None:
        self._update_manifest(lambda payload: payload.pop("gateway", None))
        scripted_answers = iter(["3", "wizard-app-id-single"])

        with (
            mock.patch("apps.gateway.gateway_main_setup_impl._start_feishu_runtime_after_setup", return_value=0),
            mock.patch("builtins.input", side_effect=lambda _prompt="": next(scripted_answers)),
            mock.patch("apps.gateway.gateway_main_setup_impl.getpass.getpass", return_value="wizard-app-secret-single"),
        ):
            exit_code = command_main(
                ["setup"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        manifest = self._read_runtime_manifest()
        feishu = manifest["gateway"]["adapters"]["feishu"]
        self.assertNotIn("default_elephant_id", feishu.get("control", {}))
        self.assertNotIn("default_session_id", feishu.get("control", {}))

    def test_gateway_feishu_describe_serializes_default_path_overrides(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                ["feishu", "describe"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = json.loads(output.getvalue())
        control = rendered["feishu"]["control"]
        self.assertNotIn("profile_dir", control)
        self.assertEqual(control["state_dir"], str(self.state_dir))

    def test_gateway_feishu_help_lists_runtime_commands(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit) as exit_info, redirect_stdout(output):
            command_main(["feishu", "-h"])

        self.assertEqual(exit_info.exception.code, 0)
        rendered = output.getvalue()
        self.assertIn("{setup,remove,start,status,stop,restart,logs,describe,doctor,message}", rendered)
        self.assertIn("setup               Add or update a Feishu account.", rendered)
        self.assertIn("remove              Remove a Feishu account.", rendered)
        self.assertIn("status              Show Feishu status.", rendered)
        self.assertIn("logs                Show logs for one Feishu account.", rendered)

    def test_gateway_feishu_without_subcommand_defaults_to_status(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                ["feishu"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Elephant Agent Gateway runtime status", rendered)
        self.assertIn("service_key: feishu", rendered)
        self.assertIn("target: long-connection", rendered)

    def test_gateway_feishu_logs_reads_tail_and_can_print_path(self) -> None:
        log_path = self.state_dir / "feishu-long-connection.log"
        log_path.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                ["feishu", "logs", "ops-feishu", "--transport", "long-connection", "--tail", "2"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip().splitlines(), ["line-2", "line-3"])

        path_output = io.StringIO()
        with redirect_stdout(path_output):
            exit_code = command_main(
                ["feishu", "logs", "ops-feishu", "--transport", "long-connection", "--path"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(path_output.getvalue().strip(), str(log_path))

    def test_gateway_feishu_status_reports_running_detached_runtime(self) -> None:
        pid_path = self.state_dir / "feishu-long-connection.pid"
        record_path = self.state_dir / "feishu-long-connection.runtime.json"
        pid_path.write_text("43210\n", encoding="utf-8")
        record_path.write_text(
            json.dumps(
                {
                    "runtime_id": "feishu:long-connection",
                    "service_key": "feishu",
                    "transport": "long-connection",
                    "status": "running",
                    "pid": 43210,
                    "pid_path": str(pid_path),
                    "log_path": str(self.state_dir / "feishu-long-connection.log"),
                    "record_path": str(record_path),
                    "command": [sys.executable, "-m", "apps.launcher", "gateway", "start"],
                    "profile_dir": str(self.profile_dir),
                    "state_dir": str(self.state_dir),
                    "cli_profile_dir": str(self.profile_dir),
                    "cli_state_dir": str(self.state_dir),
                    "started_at": "2026-04-13T03:58:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        output = io.StringIO()
        with (
            mock.patch("apps.gateway.__main__.os.kill", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["feishu", "status", "--transport", "long-connection"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("runtime_id: feishu:long-connection", rendered)
        self.assertIn("status: running", rendered)
        self.assertIn("pid: 43210", rendered)
        self.assertIn("pid_active: yes", rendered)
        self.assertIn("recorded_status: running", rendered)

    def test_gateway_feishu_stop_updates_runtime_record_and_cleans_pid(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                ["feishu", "stop", "--transport", "long-connection", "--timeout", "0.1"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Elephant daemon is not running. Nothing to stop.", output.getvalue())
        self.assertFalse((self.state_dir / "daemon.pid").exists())

    def test_gateway_feishu_restart_replaces_existing_background_runtime(self) -> None:
        class FakeProcess:
            pid = 54321

            def poll(self) -> None:
                return None

        output = io.StringIO()
        with (
            mock.patch("apps.gateway.__main__.subprocess.Popen", return_value=FakeProcess()) as popen,
            mock.patch("apps.gateway.__main__.time.sleep", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["feishu", "restart", "--transport", "long-connection", "--timeout", "0.1"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Elephant daemon is now running in the background.", rendered)
        pid_path = self.state_dir / "daemon.pid"
        record_path = self.state_dir / "daemon.runtime.json"
        self.assertEqual(pid_path.read_text(encoding="utf-8").strip(), "54321")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "running")
        self.assertEqual(record["pid"], 54321)
        launcher_calls = [
            call
            for call in popen.call_args_list
            if len(call.args) >= 1 and call.args[0][:4] == [sys.executable, "-m", "apps.launcher", "daemon"]
        ]
        self.assertEqual(len(launcher_calls), 1)
        command = launcher_calls[0].args[0]
        self.assertEqual(command[command.index("--state-dir") + 1], str(self.state_dir))
        self.assertEqual(command[command.index("--cli-state-dir") + 1], str(self.state_dir))

    def test_gateway_feishu_start_detach_spawns_background_process(self) -> None:
        class FakeProcess:
            pid = 43210

            def poll(self) -> None:
                return None

        output = io.StringIO()
        with (
            mock.patch("apps.gateway.__main__.subprocess.Popen", return_value=FakeProcess()) as popen,
            mock.patch("apps.gateway.__main__.time.sleep", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["feishu", "start", "--transport", "long-connection", "--detach"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Elephant daemon is now running in the background.", rendered)
        self.assertIn("PID: 43210", rendered)
        self.assertIn("HTTP: http://127.0.0.1:8788", rendered)
        pid_path = self.state_dir / "daemon.pid"
        log_path = self.state_dir / "daemon.log"
        record_path = self.state_dir / "daemon.runtime.json"
        self.assertTrue(pid_path.exists())
        self.assertEqual(pid_path.read_text(encoding="utf-8").strip(), "43210")
        self.assertTrue(log_path.exists())
        self.assertTrue(record_path.exists())
        runtime_record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(runtime_record["runtime_id"], "daemon:unified")
        self.assertEqual(runtime_record["status"], "running")
        self.assertEqual(runtime_record["pid"], 43210)
        launcher_calls = [
            call
            for call in popen.call_args_list
            if len(call.args) >= 1 and call.args[0][:4] == [sys.executable, "-m", "apps.launcher", "daemon"]
        ]
        self.assertEqual(len(launcher_calls), 1)
        command = launcher_calls[0].args[0]
        self.assertEqual(command[:5], [sys.executable, "-m", "apps.launcher", "daemon", "start"])
        self.assertEqual(command[command.index("--state-dir") + 1], str(self.state_dir))
        self.assertEqual(command[command.index("--cli-state-dir") + 1], str(self.state_dir))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_gateway_feishu_start_detach_launches_unified_daemon_with_cli_state(self) -> None:
        class FakeProcess:
            pid = 43211

            def poll(self) -> None:
                return None

        output = io.StringIO()
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("apps.gateway.__main__.subprocess.Popen", return_value=FakeProcess()) as popen,
            mock.patch("apps.gateway.__main__.time.sleep", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["feishu", "start", "--transport", "long-connection", "--detach"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        launcher_calls = [
            call
            for call in popen.call_args_list
            if len(call.args) >= 1 and call.args[0][:4] == [sys.executable, "-m", "apps.launcher", "daemon"]
        ]
        self.assertEqual(len(launcher_calls), 1)
        command = launcher_calls[0].args[0]
        self.assertEqual(command[command.index("--state-dir") + 1], str(self.state_dir))
        self.assertEqual(command[command.index("--cli-state-dir") + 1], str(self.state_dir))
        self.assertNotIn("env", launcher_calls[0].kwargs)

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
        self.assertIn(summary["provider"]["embedding_bootstrap_status"], {"ready", "pending", "downloading"})
        self.assertEqual(
            summary["adapter_setup"]["feishu"]["preferred_transport"],
            "long-connection",
        )
        self.assertEqual(
            summary["adapter_setup"]["feishu"]["implemented_transports"][0],
            "python-sdk-long-connection",
        )
        self.assertEqual(
            summary["adapter_setup"]["feishu"]["delivery_defaults"]["p2p"],
            "allow",
        )
        self.assertEqual(
            summary["adapter_setup"]["telegram"]["surface"],
            "telegram-bot-api",
        )
        self.assertEqual(
            summary["adapter_setup"]["telegram"]["delivery_defaults"]["private"],
            "allow",
        )
        self.assertEqual(
            summary["adapter_setup"]["telegram"]["delivery_defaults"]["group"],
            "review",
        )
        self.assertEqual(summary["adapters"]["discord"], DISCORD_ADAPTER_ID)
        self.assertEqual(
            summary["adapter_setup"]["discord"]["surface"],
            "discord-gateway",
        )
        self.assertEqual(
            summary["adapter_setup"]["discord"]["preferred_transport"],
            "gateway",
        )
        self.assertEqual(
            summary["adapter_setup"]["discord"]["supported_events"][0],
            "MESSAGE_CREATE",
        )
        self.assertEqual(
            summary["adapter_setup"]["discord"]["delivery_defaults"]["direct"],
            "allow",
        )
        self.assertEqual(
            summary["adapter_setup"]["discord"]["delivery_defaults"]["topic"],
            "review",
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
                audience="model",
                enabled_only=True,
                available_only=True,
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

    def test_gateway_chat_context_discloses_skill_index_and_allows_skill_list_tool(self) -> None:
        app, _, _ = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            conversation_id="gateway-skill-context",
        )
        inbound = GatewayInboundMessage(
            event_id="evt-gateway-skill-context",
            account=GatewayAccountRef(
                adapter_id=CHAT_BOT_ADAPTER_ID,
                account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            ),
            conversation=GatewayConversationRef(
                conversation_id="gateway-skill-context",
                chat_type="direct",
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
            "tool.skill.list",
            {"limit": 4},
            session_id=session.episode_id,
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
                adapter_id=CHAT_BOT_ADAPTER_ID,
                account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            ),
            conversation=GatewayConversationRef(
                conversation_id="gateway-personal-model-tools",
                chat_type="direct",
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

    def test_load_discord_gateway_accounts_reads_allowlists_and_runtime_metadata(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "surface": "gateway",
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                                "allow_guild_ids": ["123", "456"],
                                "allow_channel_ids": ["789"],
                                "runtime": {"shard_count": 2, "shard_ids": [0, 1]},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        accounts = load_discord_gateway_accounts(app)

        self.assertEqual(len(accounts), 1)
        account = accounts[0]
        self.assertEqual(account.account_id, "ops-discord")
        self.assertEqual(account.bot_token_env_var, "ELEPHANT_TEST_DISCORD_BOT_TOKEN")
        self.assertEqual(account.surface, "gateway")
        self.assertEqual(account.allow_guild_ids, ("123", "456"))
        self.assertEqual(account.allow_channel_ids, ("789",))
        self.assertEqual(account.runtime_metadata["shard_count"], 2)
        self.assertEqual(tuple(account.runtime_metadata["shard_ids"]), (0, 1))

    def test_load_discord_gateway_accounts_skips_disabled_accounts_but_describe_reports_them(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "surface": "gateway",
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "enabled": True,
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            },
                            {
                                "account_id": "shadow-discord",
                                "enabled": False,
                                "env": {"bot_token": "ELEPHANT_DISABLED_DISCORD_BOT_TOKEN"},
                            },
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        accounts = load_discord_gateway_accounts(app)
        self.assertEqual(tuple(account.account_id for account in accounts), ("ops-discord",))

        description = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        ).describe()
        self.assertEqual(description["account_status"]["service_status"], "ready")
        self.assertEqual(description["account_status"]["enabled_accounts"], 1)
        self.assertEqual(description["account_status"]["disabled_accounts"], 1)
        self.assertEqual(description["account_status"]["disabled_account_ids"], ("shadow-discord",))
        self.assertEqual(len(description["accounts"]), 2)
        self.assertFalse(description["accounts"][1]["enabled"])
        self.assertEqual(description["accounts"][1]["startup_status"], "disabled")

    def test_discord_service_describe_reports_credentials_and_intents(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "surface": "gateway",
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                                "allow_guild_ids": ["123", "456"],
                                "allow_channel_ids": ["789"],
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        description = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        ).describe()

        self.assertEqual(description["adapter_id"], DISCORD_ADAPTER_ID)
        self.assertEqual(description["configured_transport"], "gateway")
        self.assertEqual(
            description["required_intents"],
            ("guilds", "messages", "message_content"),
        )
        self.assertEqual(
            description["privileged_intents"],
            ("message_content",),
        )
        self.assertEqual(description["mention_policy"], "suppress-all")
        self.assertEqual(description["runtime"]["runtime"], "managed-service")
        self.assertEqual(description["account_status"]["service_status"], "ready")
        account = description["accounts"][0]
        self.assertEqual(account["account_id"], "ops-discord")
        self.assertTrue(account["enabled"])
        self.assertEqual(account["startup_status"], "ready")
        self.assertEqual(account["credentials_status"], "configured")
        self.assertEqual(account["bot_token_env_var"], "ELEPHANT_TEST_DISCORD_BOT_TOKEN")
        self.assertEqual(account["allow_guild_ids"], ("123", "456"))
        self.assertEqual(account["allow_channel_ids"], ("789",))

    def test_gateway_describe_all_includes_discord_service(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": DEFAULT_DISCORD_BOT_TOKEN_ENV},
                            }
                        ],
                    }
                }
            )
        )
        pid = os.getpid()
        pid_path = self.state_dir / "discord-gateway.pid"
        log_path = self.state_dir / "discord-gateway.log"
        record_path = self.state_dir / "discord-gateway.runtime.json"
        pid_path.write_text(f"{pid}\n", encoding="utf-8")
        log_path.write_text("discord runtime online\n", encoding="utf-8")
        record_path.write_text(
            json.dumps(
                {
                    "runtime_id": "discord:gateway",
                    "service_key": "discord",
                    "target": "gateway",
                    "status": "running",
                    "pid": pid,
                    "pid_path": str(pid_path),
                    "log_path": str(log_path),
                    "record_path": str(record_path),
                    "command": [sys.executable, "-m", "apps.launcher", "gateway", "discord", "start"],
                    "profile_dir": str(self.profile_dir),
                    "state_dir": str(self.state_dir),
                    "started_at": datetime.now(UTC).isoformat(),
                    "transport": "gateway",
                }
            ),
            encoding="utf-8",
        )

        describe_output = io.StringIO()
        with redirect_stdout(describe_output):
            exit_code = command_main(
                ["describe"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        described = json.loads(describe_output.getvalue())
        self.assertIn("discord", described["services"])
        self.assertIn("discord", described)
        self.assertEqual(described["discord"]["accounts"][0]["account_id"], "ops-discord")
        runtime = described["discord"]["runtime"]
        self.assertEqual(runtime["runtime_status"], "running")
        self.assertEqual(runtime["recorded_status"], "running")
        self.assertEqual(runtime["target"], "gateway")
        self.assertEqual(runtime["pid"], pid)
        self.assertTrue(runtime["pid_active"])
        self.assertFalse(runtime["stale_pid_file"])
        self.assertEqual(runtime["pid_file"], str(pid_path))
        self.assertEqual(runtime["log_file"], str(log_path))
        self.assertEqual(runtime["record_file"], str(record_path))

    def test_gateway_discord_doctor_reports_runtime_state(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": DEFAULT_DISCORD_BOT_TOKEN_ENV},
                            }
                        ],
                    }
                }
            )
        )
        pid = os.getpid()
        pid_path = self.state_dir / "discord-gateway.pid"
        record_path = self.state_dir / "discord-gateway.runtime.json"
        pid_path.write_text(f"{pid}\n", encoding="utf-8")
        record_path.write_text(
            json.dumps(
                {
                    "runtime_id": "discord:gateway",
                    "service_key": "discord",
                    "target": "gateway",
                    "status": "running",
                    "pid": pid,
                    "pid_path": str(pid_path),
                    "log_path": str(self.state_dir / "discord-gateway.log"),
                    "record_path": str(record_path),
                    "command": [sys.executable, "-m", "apps.launcher", "gateway", "discord", "start"],
                    "profile_dir": str(self.profile_dir),
                    "state_dir": str(self.state_dir),
                    "started_at": datetime.now(UTC).isoformat(),
                    "transport": "gateway",
                }
            ),
            encoding="utf-8",
        )

        doctor_output = io.StringIO()
        with redirect_stdout(doctor_output):
            exit_code = command_main(
                ["discord", "doctor"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = doctor_output.getvalue()
        self.assertIn("runtime_status: running", rendered)
        self.assertIn("runtime_target: gateway", rendered)
        self.assertIn(f"runtime_pid: {pid}", rendered)
        self.assertIn("discord_portal_checklist:", rendered)
        self.assertIn("Open Discord Developer Portal", rendered)
        self.assertIn("MESSAGE_CONTENT", rendered)
        self.assertIn("View Channels", rendered)
        self.assertIn("Send Messages in Threads", rendered)
        self.assertIn("Read Message History", rendered)
        self.assertIn("already running on `gateway`", rendered)

    def test_gateway_discord_help_lists_runtime_commands(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit) as exit_info, redirect_stdout(output):
            command_main(["discord", "-h"])

        self.assertEqual(exit_info.exception.code, 0)
        rendered = output.getvalue()
        self.assertIn("{setup,remove,start,status,stop,restart,logs,describe,doctor,message}", rendered)
        self.assertIn("setup               Add or update a Discord account.", rendered)
        self.assertIn("remove              Remove a Discord account.", rendered)
        self.assertIn("status              Show Discord status.", rendered)
        self.assertIn("logs                Show logs for one Discord account.", rendered)

    def test_gateway_discord_start_detach_spawns_background_process(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        class FakeProcess:
            pid = 54322

            def poll(self) -> None:
                return None

        output = io.StringIO()
        with (
            mock.patch("apps.gateway.__main__.subprocess.Popen", return_value=FakeProcess()) as popen,
            mock.patch("apps.gateway.__main__.time.sleep", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["discord", "start", "--transport", "gateway", "--detach"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Elephant daemon is now running in the background.", rendered)
        self.assertIn("PID: 54322", rendered)
        self.assertIn("HTTP: http://0.0.0.0:8900", rendered)
        pid_path = self.state_dir / "daemon.pid"
        log_path = self.state_dir / "daemon.log"
        record_path = self.state_dir / "daemon.runtime.json"
        self.assertTrue(pid_path.exists())
        self.assertEqual(pid_path.read_text(encoding="utf-8").strip(), "54322")
        self.assertTrue(log_path.exists())
        self.assertTrue(record_path.exists())
        runtime_record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(runtime_record["runtime_id"], "daemon:unified")
        self.assertEqual(runtime_record["status"], "running")
        self.assertEqual(runtime_record["pid"], 54322)
        launcher_calls = [
            call
            for call in popen.call_args_list
            if len(call.args) >= 1 and call.args[0][:4] == [sys.executable, "-m", "apps.launcher", "daemon"]
        ]
        self.assertEqual(len(launcher_calls), 1)
        command = launcher_calls[0].args[0]
        self.assertEqual(command[:5], [sys.executable, "-m", "apps.launcher", "daemon", "start"])
        self.assertEqual(command[command.index("--state-dir") + 1], str(self.state_dir))
        self.assertEqual(command[command.index("--cli-state-dir") + 1], str(self.state_dir))
        self.assertTrue(launcher_calls[0].kwargs["start_new_session"])

    def test_discord_service_dispatch_event_delivers_dm_reply_with_mentions_suppressed(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=DISCORD_ADAPTER_ID,
            account_id="ops-discord",
            conversation_id="dm-1",
        )
        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        )
        delivery_transport = self._FakeDiscordDeliveryTransport()

        result = asyncio.run(
            service.dispatch_event(
                {
                    "id": "msg-1",
                    "channel_id": "dm-1",
                    "content": "hello from discord",
                    "chat_type": "direct",
                    "author": {
                        "id": "user-1",
                        "username": "ada",
                        "global_name": "Ada Lovelace",
                    },
                    "attachments": [],
                },
                account_id="ops-discord",
                delivery_transport=delivery_transport,
            )
        )

        self.assertEqual(result.response_body["delivery_outcome"], "delivered")
        self.assertEqual(
            result.response_body["policy_decision"],
            str(PolicyDecision.ALLOW),
        )
        self.assertEqual(result.response_body["external_message_id"], "discord-reply-1")
        self.assertEqual(len(delivery_transport.requests), 1)
        request, account = delivery_transport.requests[0]
        self.assertEqual(account.account_id, "ops-discord")
        self.assertEqual(request["path"], "/channels/dm-1/messages")
        self.assertEqual(request["channel_id"], "dm-1")
        self.assertEqual(request["body"]["allowed_mentions"], {"parse": [], "replied_user": False})
        self.assertEqual(
            request["body"]["message_reference"]["message_id"],
            "msg-1",
        )

    def test_discord_service_can_route_through_cli_control_bridge(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "surface": "gateway",
                        "control": {},
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=DISCORD_ADAPTER_ID,
            account_id="ops-discord",
            conversation_id="dm-control-1",
        )

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def session_ids_for_elephant(self, elephant_id: str) -> tuple[str, ...]:
                return (self.demo_session.episode_id,) if elephant_id == "demo" else ()

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

            def compact_session_context(self, session_id: str, **kwargs):
                raise AssertionError("gateway shared-runtime path owns compaction")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        delivery_transport = self._FakeDiscordDeliveryTransport()

        description = service.describe()
        self.assertTrue(description["control"]["enabled"])
        self.assertEqual(description["control"]["runtime_status"], "ready")
        self.assertEqual(description["control"]["known_elephants"], ("demo",))

        bind_result = asyncio.run(
            service.dispatch_event(
                {
                    "id": "msg-control-bind",
                    "channel_id": "dm-control-1",
                    "content": "/elephant create demo",
                    "chat_type": "direct",
                    "author": {
                        "id": "user-1",
                        "username": "ada",
                        "global_name": "Ada Lovelace",
                    },
                    "attachments": [],
                },
                account_id="ops-discord",
                delivery_transport=delivery_transport,
            )
        )

        self.assertIsNone(bind_result.exchange)
        self.assertEqual(bind_result.response_body["control_mode"], "cli-runtime")
        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)

        result = asyncio.run(
            service.dispatch_event(
                {
                    "id": "msg-control-1",
                    "channel_id": "dm-control-1",
                    "content": "hello from discord control",
                    "chat_type": "direct",
                    "author": {
                        "id": "user-1",
                        "username": "ada",
                        "global_name": "Ada Lovelace",
                    },
                    "attachments": [],
                },
                account_id="ops-discord",
                delivery_transport=delivery_transport,
            )
        )

        self.assertIsNotNone(result.exchange)
        self.assertEqual(result.response_body["elephant_id"], "demo")
        self.assertEqual(result.response_body["state_id"], "state:demo")
        self.assertEqual(result.response_body["session_id"], expected_session_id)
        self.assertEqual(result.response_body["delivery_outcome"], "delivered")
        self.assertEqual(result.response_body["external_message_id"], "discord-reply-1")
        self.assertEqual(shared_runtime_calls, [{"session_id": expected_session_id, "prompt": "hello from discord control", "conversation_id": "dm-control-1"}])
        self.assertEqual(len(delivery_transport.requests), 2)
        request, account = delivery_transport.requests[-1]
        self.assertEqual(account.account_id, "ops-discord")
        self.assertEqual(request["path"], "/channels/dm-control-1/messages")
        self.assertEqual(request["body"]["content"], "gateway-handled:hello from discord control")
        self.assertEqual(
            request["body"]["message_reference"]["message_id"],
            "msg-control-1",
        )

    def test_weixin_and_wecom_default_control_bridge_handles_elephant_commands(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "weixin": {
                        "enabled": True,
                        "surface": "ilink",
                        "accounts": [
                            {
                                "account_id": "ops-weixin",
                                "token": "wx-token",
                                "base_url": "https://ilinkai.weixin.qq.com",
                                "surface": "ilink",
                            }
                        ],
                    },
                    "wecom": {
                        "enabled": True,
                        "surface": "websocket",
                        "accounts": [
                            {
                                "account_id": "ops-wecom",
                                "env": {
                                    "bot_id": "ELEPHANT_TEST_WECOM_BOT_ID",
                                    "secret": "ELEPHANT_TEST_WECOM_SECRET",
                                },
                            }
                        ],
                    },
                }
            )
        )
        app, _, _ = self._build()

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def session_ids_for_elephant(self, elephant_id: str) -> tuple[str, ...]:
                return (self.demo_session.episode_id,) if elephant_id == "demo" else ()

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

            def compact_session_context(self, session_id: str, **kwargs):
                raise AssertionError("gateway shared-runtime path owns compaction")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

            def schedule_learning_for_session(self, **kwargs) -> None:
                raise AssertionError("switch learning should not run in this test")

        cases = (
            (
                WeixinGatewayService(
                    app=app,
                    cli_runtime_factory=lambda profile_dir, state_dir: FakeCliRuntime(),
                    default_cli_state_dir=str(self.state_dir),
                ),
                WEIXIN_ADAPTER_ID,
                "ops-weixin",
                "wx-user-1",
                "ilink",
                lambda service, body: service.adapter.normalize_event(
                    {
                        "message_id": f"wx-{body.replace(' ', '-')}",
                        "from_wxid": "wx-user-1",
                        "content": body,
                        "chat_type": "direct",
                        "transport": "ilink",
                    },
                    account_id="ops-weixin",
                    transport="ilink",
                ),
            ),
            (
                WecomGatewayService(
                    app=app,
                    cli_runtime_factory=lambda profile_dir, state_dir: FakeCliRuntime(),
                    default_cli_state_dir=str(self.state_dir),
                    environ={"ELEPHANT_TEST_WECOM_BOT_ID": "bot-id", "ELEPHANT_TEST_WECOM_SECRET": "secret"},
                ),
                WECOM_ADAPTER_ID,
                "ops-wecom",
                "wecom-chat-1",
                "websocket",
                lambda service, body: service.adapter.normalize_event(
                    {
                        "message_id": f"wecom-{body.replace(' ', '-')}",
                        "sender_id": "wecom-user-1",
                        "chat_id": "wecom-chat-1",
                        "chat_type": "direct",
                        "content": body,
                        "transport": "websocket",
                    },
                    account_id="ops-wecom",
                    transport="websocket",
                ),
            ),
        )

        for service, adapter_id, account_id, conversation_id, _transport, inbound_factory in cases:
            with self.subTest(service=service.service_key):
                self.assertIsNotNone(service.cli_control)
                control = service.describe()["control"]
                self.assertTrue(control["enabled"])
                self.assertEqual(control["runtime_status"], "ready")

                list_result = service.cli_control.handle_message(inbound_factory(service, "/elephant list"))
                self.assertTrue(list_result.handled)
                self.assertIn("Available local Elephant Agent herd", list_result.body or "")
                self.assertIn("demo", list_result.body or "")

                bind_result = service.cli_control.handle_message(inbound_factory(service, "/elephant create demo"))
                self.assertTrue(bind_result.handled)
                self.assertEqual(bind_result.elephant_id, "demo")
                self.assertEqual(
                    bind_result.session_id,
                    self._gateway_route_session_id(
                        adapter_id=adapter_id,
                        account_id=account_id,
                        conversation_id=conversation_id,
                    ),
                )

                follow_up = service.cli_control.handle_message(inbound_factory(service, "hello after binding"))
                self.assertFalse(follow_up.handled)
                self.assertEqual(follow_up.elephant_id, "demo")
                self.assertEqual(follow_up.session_id, bind_result.session_id)

    def test_weixin_ilink_serializes_same_conversation_across_runtime_and_reply_send(self) -> None:
        app, _, _ = self._build()
        service = WeixinGatewayService(app=app)
        service._resolved_account_id = "ops-weixin"
        service._resolved_dm_policy = "open"
        service._resolved_group_policy = "disabled"
        service._dedup = MessageDeduplicator()
        self._bind_gateway_conversation(
            app,
            adapter_id=WEIXIN_ADAPTER_ID,
            account_id="ops-weixin",
            conversation_id="wx-user-1",
            elephant_id="demo",
        )
        shared_runtime_calls = self._install_shared_runtime_stub(app)

        async def scenario() -> None:
            first_send_started = asyncio.Event()
            release_first_send = asyncio.Event()
            second_send_started = asyncio.Event()
            send_order: list[str] = []

            async def send_stub(_service, outbound) -> None:
                send_order.append(outbound.body)
                if len(send_order) == 1:
                    first_send_started.set()
                    await release_first_send.wait()
                else:
                    second_send_started.set()

            def inbound_message(message_id: str, text: str) -> dict[str, object]:
                return {
                    "message_id": message_id,
                    "from_user_id": "wx-user-1",
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                }

            with mock.patch.object(type(service), "_send_ilink_message", new=send_stub):
                first_task = asyncio.create_task(
                    service._process_message_safe(inbound_message("wx-serial-1", "first message"))
                )
                second_task = asyncio.create_task(
                    service._process_message_safe(inbound_message("wx-serial-2", "second message"))
                )

                await first_send_started.wait()
                await asyncio.sleep(0)
                self.assertFalse(second_send_started.is_set())
                self.assertEqual([call["prompt"] for call in shared_runtime_calls], ["first message"])
                self.assertEqual(send_order, ["gateway-handled:first message"])

                release_first_send.set()
                await asyncio.gather(first_task, second_task)

            self.assertEqual(
                [call["prompt"] for call in shared_runtime_calls],
                ["first message", "second message"],
            )
            self.assertEqual(
                send_order,
                ["gateway-handled:first message", "gateway-handled:second message"],
            )

        asyncio.run(scenario())

    def test_weixin_ilink_serializes_same_conversation_for_cli_control_messages(self) -> None:
        app, _, _ = self._build()
        service = WeixinGatewayService(app=app)
        service._resolved_account_id = "ops-weixin"
        service._resolved_dm_policy = "open"
        service._resolved_group_policy = "disabled"
        service._dedup = MessageDeduplicator()
        control_calls: list[str] = []

        def control_handle(inbound):
            control_calls.append(inbound.body)
            return SimpleNamespace(
                handled=True,
                body=f"control:{inbound.body}",
                session_id=f"control:{inbound.conversation_id}",
                summary=f"handled:{inbound.body}",
            )

        service.cli_control = SimpleNamespace(handle_message=control_handle)

        async def scenario() -> None:
            first_send_started = asyncio.Event()
            release_first_send = asyncio.Event()
            second_send_started = asyncio.Event()
            send_order: list[str] = []

            async def send_stub(_service, outbound) -> None:
                send_order.append(outbound.body)
                if len(send_order) == 1:
                    first_send_started.set()
                    await release_first_send.wait()
                else:
                    second_send_started.set()

            def inbound_message(message_id: str, text: str) -> dict[str, object]:
                return {
                    "message_id": message_id,
                    "from_user_id": "wx-user-1",
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                }

            with mock.patch.object(type(app), "handle_message", side_effect=AssertionError("shared runtime should not run for handled control messages")):
                with mock.patch.object(type(service), "_send_ilink_message", new=send_stub):
                    first_task = asyncio.create_task(
                        service._process_message_safe(inbound_message("wx-control-1", "first control"))
                    )
                    second_task = asyncio.create_task(
                        service._process_message_safe(inbound_message("wx-control-2", "second control"))
                    )

                    await first_send_started.wait()
                    await asyncio.sleep(0)
                    self.assertFalse(second_send_started.is_set())
                    self.assertEqual(control_calls, ["first control"])
                    self.assertEqual(send_order, ["control:first control"])

                    release_first_send.set()
                    await asyncio.gather(first_task, second_task)

            self.assertEqual(control_calls, ["first control", "second control"])
            self.assertEqual(send_order, ["control:first control", "control:second control"])

        asyncio.run(scenario())

    def test_discord_adapter_routes_thread_messages_under_parent_channel(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        )
        assert service.adapter is not None
        exchange = service.adapter.receive_event(
            {
                "id": "msg-thread-1",
                "channel_id": "thread-42",
                "parent_id": "channel-7",
                "thread_id": "thread-42",
                "guild_id": "guild-1",
                "chat_type": "topic",
                "content": "thread hello",
                "author": {
                    "id": "user-1",
                    "username": "ada",
                    "global_name": "Ada Lovelace",
                },
                "attachments": [],
            },
            account_id="ops-discord",
        )

        self.assertEqual(exchange.route.inbound.conversation_id, "thread-42")
        self.assertEqual(exchange.route.inbound.conversation.parent_conversation_id, "channel-7")
        self.assertEqual(exchange.route.inbound.conversation.thread_id, "thread-42")
        self.assertEqual(exchange.route.inbound.chat_type, "topic")
        self.assertEqual(exchange.route.session.session_id, "session:messaging.discord:ops-discord:thread-42")

    def test_discord_service_should_ignore_bot_self_and_system_sdk_messages(self) -> None:
        app, _, _ = self._build()
        service = DiscordGatewayService(app=app)

        self.assertTrue(
            service.should_ignore_sdk_message(
                SimpleNamespace(
                    author=SimpleNamespace(id="bot-1", bot=True),
                    type=SimpleNamespace(name="default"),
                )
            )
        )
        self.assertTrue(
            service.should_ignore_sdk_message(
                SimpleNamespace(
                    author=SimpleNamespace(id="self-1", bot=False),
                    type=SimpleNamespace(name="default"),
                ),
                self_user_id="self-1",
            )
        )
        self.assertTrue(
            service.should_ignore_sdk_message(
                SimpleNamespace(
                    author=SimpleNamespace(id="user-1", bot=False),
                    type=SimpleNamespace(name="thread_created"),
                )
            )
        )
        self.assertFalse(
            service.should_ignore_sdk_message(
                SimpleNamespace(
                    author=SimpleNamespace(id="user-1", bot=False),
                    type=SimpleNamespace(name="reply"),
                )
            )
        )

    def test_discord_gateway_service_starts_sdk_client_and_dispatches_replies(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        requests: list[dict[str, object]] = []
        captured: dict[str, object] = {}

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeIntents:
            def __init__(self) -> None:
                self.guilds = False
                self.messages = False
                self.message_content = False

            @classmethod
            def none(cls):
                return cls()

        class FakeSentMessage:
            def __init__(self, message_id: str) -> None:
                self.id = message_id

        class FakePartialMessage:
            def __init__(self, channel_id: object, message_id: object) -> None:
                self.channel_id = channel_id
                self.message_id = message_id

            async def reply(self, *, content, allowed_mentions=None, mention_author=None, file=None):
                requests.append(
                    {
                        "mode": "reply",
                        "channel_id": self.channel_id,
                        "message_id": self.message_id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "mention_author": mention_author,
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-send-1")

        class FakeChannel:
            def __init__(self, channel_id: object) -> None:
                self.id = channel_id

            def get_partial_message(self, message_id: object) -> FakePartialMessage:
                return FakePartialMessage(self.id, message_id)

            async def send(self, *, content, allowed_mentions=None):
                requests.append(
                    {
                        "mode": "send",
                        "channel_id": self.id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                    }
                )
                return FakeSentMessage("discord-send-2")

        class FakeClient:
            def __init__(self, *, intents) -> None:
                captured["intents"] = intents
                self._events: dict[str, object] = {}
                self.user = SimpleNamespace(id="bot-1")
                self._channel = FakeChannel("2001")

            def event(self, func):
                self._events[func.__name__] = func
                return func

            def get_channel(self, channel_id: object) -> FakeChannel:
                captured["channel_lookup"] = channel_id
                return self._channel

            async def start(self, token: str) -> None:
                captured["token"] = token
                await self._events["on_message"](
                    SimpleNamespace(
                        id="1001",
                        content="hello from sdk",
                        author=SimpleNamespace(
                            id="user-1",
                            bot=False,
                            name="ada",
                            username="ada",
                            global_name="Ada Lovelace",
                        ),
                        channel=SimpleNamespace(id="2001", parent=None),
                        guild=None,
                        attachments=(),
                        reference=None,
                        type=SimpleNamespace(name="default"),
                    )
                )

            async def close(self) -> None:
                captured["closed"] = True

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions
            Intents = FakeIntents
            Client = FakeClient

        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        )
        clients = asyncio.run(service.start_gateway(discord_module=FakeDiscord()))

        self.assertEqual(len(clients), 1)
        self.assertEqual(captured["token"], "discord-token-123")
        intents = captured["intents"]
        self.assertTrue(intents.guilds)
        self.assertTrue(intents.messages)
        self.assertTrue(intents.message_content)
        self.assertEqual(captured["channel_lookup"], 2001)
        self.assertTrue(captured["closed"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["mode"], "reply")
        self.assertEqual(requests[0]["message_id"], 1001)
        self.assertEqual(
            requests[0]["allowed_mentions"],
            {
                "everyone": False,
                "users": False,
                "roles": False,
                "replied_user": False,
            },
        )
        self.assertFalse(requests[0]["mention_author"])

    def test_discord_delivery_transport_splits_long_reply_content(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeSentMessage:
            def __init__(self, message_id: str) -> None:
                self.id = message_id

        class FakePartialMessage:
            def __init__(self, channel_id: object, message_id: object) -> None:
                self.channel_id = channel_id
                self.message_id = message_id

            async def reply(self, *, content, allowed_mentions=None, mention_author=None, file=None):
                requests.append(
                    {
                        "mode": "reply",
                        "channel_id": self.channel_id,
                        "message_id": self.message_id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "mention_author": mention_author,
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-reply-1")

        class FakeChannel:
            def __init__(self, channel_id: object) -> None:
                self.id = channel_id
                self.sent_messages = 0

            def get_partial_message(self, message_id: object) -> FakePartialMessage:
                return FakePartialMessage(self.id, message_id)

            async def send(self, *, content, allowed_mentions=None, file=None):
                self.sent_messages += 1
                requests.append(
                    {
                        "mode": "send",
                        "channel_id": self.id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "file": file,
                    }
                )
                return FakeSentMessage(f"discord-send-{self.sent_messages}")

        class FakeClient:
            def __init__(self) -> None:
                self._channel = FakeChannel("2001")

            def get_channel(self, channel_id: object) -> FakeChannel:
                self.channel_lookup = channel_id
                return self._channel

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions

        long_content = ("A" * 1500) + "\n" + ("B" * 700)
        transport = DiscordPyDeliveryTransport(client=FakeClient(), discord_module=FakeDiscord())

        response = asyncio.run(
            transport.send_request(
                {
                    "channel_id": "2001",
                    "body": {
                        "content": long_content,
                        "message_reference": {"message_id": "1001"},
                    },
                },
                account=SimpleNamespace(account_id="ops-discord"),
            )
        )

        self.assertEqual(response["id"], "discord-reply-1")
        self.assertEqual(response["chunk_count"], 2)
        self.assertEqual(response["delivery_mode"], "chunked")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["mode"], "reply")
        self.assertEqual(requests[1]["mode"], "send")
        self.assertFalse(requests[0]["mention_author"])
        self.assertIsNone(requests[0]["file"])
        self.assertIsNone(requests[1]["file"])
        self.assertEqual("".join(str(item["content"]) for item in requests), long_content)
        self.assertTrue(all(len(str(item["content"])) <= 2000 for item in requests))

    def test_discord_reply_request_wraps_command_code_and_formula_blocks(self) -> None:
        app, _, _ = self._build()
        discord = DiscordMessagingAdapter(app=app)

        rendered = discord.build_reply_request(
            GatewayOutboundMessage(
                message_id="discord-rich-1",
                account=GatewayAccountRef(
                    adapter_id=DISCORD_ADAPTER_ID,
                    account_id="ops-discord",
                    surface="discord-gateway",
                ),
                conversation=GatewayConversationRef(
                    conversation_id="dm-1",
                    chat_type="direct",
                ),
                session_id="session:discord-rich-1",
                body=(
                    "Run these commands:\n\n"
                    "uv run -m pytest\n"
                    "git status\n\n"
                    "def add(a, b):\n"
                    "    return a + b\n\n"
                    "x^2 + y^2 = z^2"
                ),
                reply_to_message_id="msg-rich-1",
            )
        )

        content = str(rendered["body"]["content"])
        self.assertIn("```bash\nuv run -m pytest\ngit status\n```", content)
        self.assertIn("```python\ndef add(a, b):\n    return a + b\n```", content)
        self.assertIn("```tex\nx^2 + y^2 = z^2\n```", content)

    def test_discord_delivery_transport_keeps_fenced_blocks_balanced_across_chunks(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeSentMessage:
            def __init__(self, message_id: str) -> None:
                self.id = message_id

        class FakePartialMessage:
            def __init__(self, channel_id: object, message_id: object) -> None:
                self.channel_id = channel_id
                self.message_id = message_id

            async def reply(self, *, content, allowed_mentions=None, mention_author=None, file=None):
                requests.append(
                    {
                        "mode": "reply",
                        "channel_id": self.channel_id,
                        "message_id": self.message_id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "mention_author": mention_author,
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-fence-reply-1")

        class FakeChannel:
            def __init__(self, channel_id: object) -> None:
                self.id = channel_id
                self.sent_messages = 0

            def get_partial_message(self, message_id: object) -> FakePartialMessage:
                return FakePartialMessage(self.id, message_id)

            async def send(self, *, content, allowed_mentions=None, file=None):
                self.sent_messages += 1
                requests.append(
                    {
                        "mode": "send",
                        "channel_id": self.id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "file": file,
                    }
                )
                return FakeSentMessage(f"discord-fence-send-{self.sent_messages}")

        class FakeClient:
            def __init__(self) -> None:
                self._channel = FakeChannel("2001")

            def get_channel(self, channel_id: object) -> FakeChannel:
                self.channel_lookup = channel_id
                return self._channel

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions

        long_content = "```python\n" + ("print('chunk-safe')\n" * 220) + "```"
        transport = DiscordPyDeliveryTransport(client=FakeClient(), discord_module=FakeDiscord())

        response = asyncio.run(
            transport.send_request(
                {
                    "channel_id": "2001",
                    "body": {
                        "content": long_content,
                        "message_reference": {"message_id": "1001"},
                    },
                },
                account=SimpleNamespace(account_id="ops-discord"),
            )
        )

        self.assertEqual(response["delivery_mode"], "chunked")
        self.assertGreater(len(requests), 1)
        self.assertEqual(response["chunk_count"], len(requests))
        self.assertTrue(all(len(str(item["content"])) <= 2000 for item in requests))
        self.assertTrue(all(str(item["content"]).count("```") % 2 == 0 for item in requests))
        self.assertTrue(str(requests[0]["content"]).startswith("```python"))
        self.assertTrue(str(requests[-1]["content"]).rstrip().endswith("```"))

    def test_discord_delivery_transport_uses_attachment_fallback_for_very_long_reply(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeFile:
            def __init__(self, *, fp, filename, description=None) -> None:
                self.filename = filename
                self.description = description
                self.content = fp.read().decode("utf-8")

        class FakeSentMessage:
            def __init__(self, message_id: str) -> None:
                self.id = message_id

        class FakePartialMessage:
            def __init__(self, channel_id: object, message_id: object) -> None:
                self.channel_id = channel_id
                self.message_id = message_id

            async def reply(self, *, content, allowed_mentions=None, mention_author=None, file=None):
                requests.append(
                    {
                        "mode": "reply",
                        "channel_id": self.channel_id,
                        "message_id": self.message_id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "mention_author": mention_author,
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-reply-attachment")

        class FakeChannel:
            def __init__(self, channel_id: object) -> None:
                self.id = channel_id

            def get_partial_message(self, message_id: object) -> FakePartialMessage:
                return FakePartialMessage(self.id, message_id)

            async def send(self, *, content, allowed_mentions=None, file=None):
                requests.append(
                    {
                        "mode": "send",
                        "channel_id": self.id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-send-attachment")

        class FakeClient:
            def __init__(self) -> None:
                self._channel = FakeChannel("2001")

            def get_channel(self, channel_id: object) -> FakeChannel:
                self.channel_lookup = channel_id
                return self._channel

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions
            File = FakeFile

        long_content = ("HTTP SERVER\n" * 900)
        transport = DiscordPyDeliveryTransport(client=FakeClient(), discord_module=FakeDiscord())

        response = asyncio.run(
            transport.send_request(
                {
                    "channel_id": "2001",
                    "body": {
                        "content": long_content,
                        "message_reference": {"message_id": "1001"},
                    },
                },
                account=SimpleNamespace(account_id="ops-discord"),
            )
        )

        self.assertEqual(response["id"], "discord-reply-attachment")
        self.assertEqual(response["delivery_mode"], "attachment")
        self.assertEqual(response["attachment_filename"], "reply.md")
        self.assertEqual(response["chunk_count"], 1)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["mode"], "reply")
        self.assertFalse(requests[0]["mention_author"])
        self.assertIn("Reply too long for Discord inline delivery", str(requests[0]["content"]))
        self.assertIsNotNone(requests[0]["file"])
        self.assertEqual(requests[0]["file"].filename, "reply.md")
        self.assertEqual(requests[0]["file"].description, "Full Discord reply body")
        self.assertEqual(requests[0]["file"].content, long_content)

    def test_discord_gateway_service_skips_blocked_enabled_accounts_during_multi_start(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "enabled": True,
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            },
                            {
                                "account_id": "shadow-discord",
                                "enabled": True,
                                "env": {"bot_token": "ELEPHANT_MISSING_DISCORD_BOT_TOKEN"},
                            },
                        ],
                    }
                }
            )
        )
        app, _, _ = self._build()
        captured_tokens: list[str] = []

        class FakeIntents:
            @staticmethod
            def none() -> "FakeIntents":
                intents = FakeIntents()
                intents.guilds = False
                intents.messages = False
                intents.message_content = False
                return intents

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.payload = dict(kwargs)

        class FakeClient:
            def __init__(self, *, intents) -> None:
                self.intents = intents
                self.user = SimpleNamespace(id="bot-1")

            def event(self, handler):
                self.on_message = handler
                return handler

            async def start(self, token: str) -> None:
                captured_tokens.append(token)

            async def close(self) -> None:
                return None

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions
            Intents = FakeIntents
            Client = FakeClient

        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            clients = asyncio.run(service.start_gateway(discord_module=FakeDiscord()))

        self.assertEqual(len(clients), 1)
        self.assertEqual(captured_tokens, ["discord-token-123"])
        self.assertIn("Skipping Discord account 'shadow-discord'", stderr.getvalue())
        self.assertEqual(service.describe()["account_status"]["service_status"], "degraded")

    def test_chat_bot_identity_mapping_and_session_reuse_persist_across_restart(self) -> None:
        app, chat_adapter, _ = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            conversation_id="chat-1",
        )

        first = chat_adapter.receive_text(
            conversation_id="chat-1",
            external_user_id="user-1",
            body="hello",
            display_name="Ada",
            event_id="evt-1",
        )
        self.assertFalse(first.route.is_new_session)
        self.assertEqual(first.delivery.outcome, "delivered")
        self.assertIsNotNone(first.delivery.outbound)
        assert first.delivery.outbound is not None
        self.assertEqual(
            first.delivery.outbound.metadata["runtime_surface"],
            "gateway.shared-runtime",
        )
        self.assertEqual(
            first.delivery.outbound.metadata["provider_id"],
            "openai-compatible",
        )
        self.assertTrue(first.delivery.outbound.metadata["context_bundle_id"].startswith("bundle:"))
        self.assertNotEqual(first.delivery.outbound.body, "ack: hello")
        first_records = app.recall_evidence_records(first.route.session.session_id)
        self.assertEqual(
            tuple(record.metadata.get("raw_user_query") for record in first_records if record.kind == "effective_user_query"),
            ("hello",),
        )
        self.assertEqual(len(tuple(record for record in first_records if record.kind == "emit_response")), 1)

        restarted_app, restarted_chat, _ = self._build()
        second = restarted_chat.receive_text(
            conversation_id="chat-1",
            external_user_id="user-1",
            body="follow-up",
            display_name="Ada Lovelace",
            event_id="evt-2",
        )

        self.assertFalse(second.route.is_new_session)
        self.assertEqual(first.route.identity.mapping_id, second.route.identity.mapping_id)
        self.assertEqual(first.route.identity.session_id, second.route.identity.session_id)
        self.assertEqual(second.route.identity.key.account_id, DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertEqual(second.route.inbound.account.account_id, DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertEqual(second.route.identity.display_name, "Ada Lovelace")
        self.assertEqual(
            second.route.session.session_id,
            f"session:{CHAT_BOT_ADAPTER_ID}:{DEFAULT_GATEWAY_ACCOUNT_ID}:chat-1",
        )
        self.assertEqual(second.route.session.profile_id, "you")
        self.assertIsNotNone(second.delivery.outbound)
        assert second.delivery.outbound is not None
        second_records = restarted_app.recall_evidence_records(second.route.session.session_id)
        self.assertEqual(
            tuple(record.metadata.get("raw_user_query") for record in second_records if record.kind == "effective_user_query"),
            ("hello", "follow-up"),
        )
        self.assertEqual(len(tuple(record for record in second_records if record.kind == "emit_response")), 2)
        self.assertEqual(len(restarted_app.identity_records()), 1)
        self.assertEqual(len(restarted_app.session_records()), 1)

    def test_chat_bot_identity_mapping_separates_accounts(self) -> None:
        app, chat_adapter, _ = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            account_id="ops-bot",
            conversation_id="chat-1",
        )
        self._bind_gateway_conversation(
            app,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            account_id="support-bot",
            conversation_id="chat-1",
        )

        first = chat_adapter.receive_text(
            account_id="ops-bot",
            conversation_id="chat-1",
            external_user_id="user-1",
            body="hello",
            event_id="evt-ops",
        )
        second = chat_adapter.receive_text(
            account_id="support-bot",
            conversation_id="chat-1",
            external_user_id="user-1",
            body="hello again",
            event_id="evt-support",
        )

        self.assertNotEqual(first.route.identity.mapping_id, second.route.identity.mapping_id)
        self.assertNotEqual(first.route.session.session_id, second.route.session.session_id)
        self.assertEqual(first.route.identity.key.account_id, "ops-bot")
        self.assertEqual(second.route.identity.key.account_id, "support-bot")
        self.assertEqual(first.route.session.session_id, f"session:{CHAT_BOT_ADAPTER_ID}:ops-bot:chat-1")
        self.assertEqual(second.route.session.session_id, f"session:{CHAT_BOT_ADAPTER_ID}:support-bot:chat-1")
        self.assertEqual(len(app.identity_records()), 2)
        self.assertEqual(len(app.session_records()), 2)

    def test_webhook_delivery_normalizes_callback_metadata(self) -> None:
        app, _, webhook_adapter = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=WEBHOOK_ADAPTER_ID,
            conversation_id="case-9",
        )

        exchange = webhook_adapter.receive_event(
            {
                "event_id": "webhook-1",
                "conversation_id": "case-9",
                "external_user_id": "customer-7",
                "body": "Need a status update.",
                "display_name": "Grace",
                "callback_url": "https://example.com/reply",
                "attachments": ["case.pdf", "case.pdf"],
                "metadata": {"source": "crm"},
            },
            reply_body="Ticket received.",
            target_trusted=True,
            consent_given=True,
        )

        self.assertEqual(exchange.delivery.outcome, "delivered")
        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.ALLOW)
        self.assertIsNotNone(exchange.delivery.outbound)
        assert exchange.delivery.outbound is not None
        self.assertEqual(
            exchange.delivery.outbound.session_id,
            f"session:{WEBHOOK_ADAPTER_ID}:{DEFAULT_GATEWAY_ACCOUNT_ID}:case-9",
        )
        self.assertEqual(exchange.delivery.outbound.attachments, ("case.pdf",))
        self.assertEqual(
            exchange.delivery.outbound.metadata["callback_url"],
            "https://example.com/reply",
        )
        self.assertEqual(exchange.delivery.outbound.metadata["source"], "crm")
        self.assertEqual(
            exchange.delivery.outbound.metadata["runtime_surface"],
            "gateway.shared-runtime",
        )
        self.assertEqual(exchange.delivery.external_message_id, exchange.delivery.outbound.message_id)

    def test_untrusted_webhook_delivery_is_blocked(self) -> None:
        app, _, webhook_adapter = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=WEBHOOK_ADAPTER_ID,
            conversation_id="case-10",
        )

        exchange = webhook_adapter.receive_event(
            {
                "event_id": "webhook-2",
                "conversation_id": "case-10",
                "external_user_id": "customer-8",
                "body": "Send this outside.",
            },
            reply_body="blocked",
            target_trusted=False,
            consent_given=False,
            is_external=True,
        )

        self.assertEqual(exchange.delivery.outcome, "blocked")
        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.REVIEW)
        self.assertIsNone(exchange.delivery.outbound)
        self.assertIn(
            "recipient-verification",
            exchange.delivery.policy_result.required_controls,
        )

    def test_feishu_p2p_event_reuses_identity_mapping_across_restart(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        first = feishu.receive_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-1",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_ada"},
                        "sender_type": "user",
                        "name": "Ada",
                    },
                    "message": {
                        "message_id": "om_direct_1",
                        "chat_id": "oc_direct_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from feishu"}),
                    },
                },
            },
            reply_body="pong",
        )
        self.assertTrue(first.route.is_new_session)
        self.assertEqual(first.route.identity.key.account_id, "cli_feishu_bot")
        self.assertEqual(first.route.inbound.account.tenant_id, "tenant-alpha")
        self.assertEqual(first.route.inbound.chat_type, "direct")
        self.assertEqual(first.delivery.policy_result.decision, PolicyDecision.ALLOW)
        self.assertIsNotNone(first.delivery.outbound)
        assert first.delivery.outbound is not None
        self.assertEqual(
            first.delivery.outbound.session_id,
            f"session:{FEISHU_ADAPTER_ID}:cli_feishu_bot:oc_direct_1",
        )

        restarted_app, _, _ = self._build()
        restarted = FeishuMessagingAdapter(app=restarted_app)
        second = restarted.receive_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-2",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_ada"},
                        "sender_type": "user",
                        "display_name": "Ada Lovelace",
                    },
                    "message": {
                        "message_id": "om_direct_2",
                        "chat_id": "oc_direct_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "follow-up"}),
                    },
                },
            }
        )

        self.assertFalse(second.route.is_new_session)
        self.assertEqual(first.route.identity.mapping_id, second.route.identity.mapping_id)
        self.assertEqual(second.route.identity.display_name, "Ada Lovelace")
        self.assertEqual(
            second.route.session.session_id,
            f"session:{FEISHU_ADAPTER_ID}:cli_feishu_bot:oc_direct_1",
        )
        self.assertEqual(len(restarted_app.identity_records()), 1)
        self.assertEqual(len(restarted_app.session_records()), 1)

    def test_feishu_group_thread_defaults_to_review_and_builds_reply_request(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        exchange = feishu.receive_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-3",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_grace"},
                        "sender_type": "user",
                        "name": "Grace",
                    },
                    "message": {
                        "message_id": "om_group_2",
                        "root_id": "om_group_root",
                        "parent_id": "om_group_parent",
                        "chat_id": "oc_group_1",
                        "chat_type": "group",
                        "message_type": "text",
                        "content": json.dumps({"text": "Need an answer here."}),
                    },
                },
            },
            reply_body="Working on it.",
        )

        self.assertEqual(exchange.route.inbound.conversation_id, "oc_group_1:om_group_root")
        self.assertEqual(exchange.route.inbound.parent_conversation_id, "oc_group_1")
        self.assertEqual(exchange.route.inbound.thread_id, "om_group_root")
        self.assertEqual(exchange.route.inbound.reply_to_message_id, "om_group_parent")
        self.assertEqual(exchange.route.inbound.chat_type, "group")
        self.assertEqual(
            exchange.route.session.session_id,
            f"session:{FEISHU_ADAPTER_ID}:cli_feishu_bot:oc_group_1:om_group_root",
        )
        self.assertEqual(exchange.delivery.outcome, "blocked")
        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.REVIEW)
        self.assertIsNone(exchange.delivery.outbound)

        rendered = feishu.build_reply_request(
            GatewayOutboundMessage(
                message_id="delivery-1",
                account=GatewayAccountRef(
                    adapter_id=FEISHU_ADAPTER_ID,
                    account_id="cli_feishu_bot",
                    tenant_id="tenant-alpha",
                    surface="feishu-long-connection",
                ),
                conversation=GatewayConversationRef(
                    conversation_id="oc_group_1:om_group_root",
                    parent_conversation_id="oc_group_1",
                    thread_id="om_group_root",
                    chat_type="group",
                ),
                session_id="session:ignored",
                body="# Working on it\n\n- Check session state\n- Send the next update",
                reply_to_message_id="om_group_2",
            )
        )
        self.assertEqual(
            rendered["path"],
            "/open-apis/im/v1/messages/om_group_2/reply",
        )
        self.assertEqual(rendered["body"]["msg_type"], "interactive")
        self.assertTrue(rendered["body"]["reply_in_thread"])
        content = json.loads(rendered["body"]["content"])
        self.assertEqual(content["schema"], "2.0")
        self.assertEqual(content["header"]["title"]["content"], "Working on it")
        self.assertEqual(content["header"]["padding"], "12px 12px 12px 12px")
        self.assertTrue(content["config"]["wide_screen_mode"])
        self.assertEqual(content["body"]["direction"], "vertical")
        self.assertEqual(content["body"]["padding"], "12px 12px 12px 12px")
        self.assertEqual(
            content["body"]["elements"],
            [
                {
                    "tag": "markdown",
                    "content": "- Check session state\n- Send the next update",
                    "text_align": "left",
                }
            ],
        )
        self.assertLessEqual(len(rendered["body"]["uuid"]), 50)
        self.assertTrue(rendered["body"]["uuid"].startswith("elephant-"))

    def test_feishu_reply_request_wraps_command_code_and_formula_blocks(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        rendered = feishu.build_reply_request(
            GatewayOutboundMessage(
                message_id="feishu-rich-1",
                account=GatewayAccountRef(
                    adapter_id=FEISHU_ADAPTER_ID,
                    account_id="cli_feishu_bot",
                    tenant_id="tenant-alpha",
                    surface="feishu-long-connection",
                ),
                conversation=GatewayConversationRef(
                    conversation_id="oc_direct_1",
                    chat_type="direct",
                ),
                session_id="session:feishu-rich-1",
                body=(
                    "Run these commands:\n\n"
                    "uv run -m pytest\n"
                    "git status\n\n"
                    "def add(a, b):\n"
                    "    return a + b\n\n"
                    "x^2 + y^2 = z^2"
                ),
                reply_to_message_id="om-rich-1",
            )
        )

        self.assertEqual(rendered["body"]["msg_type"], "interactive")
        content = json.loads(rendered["body"]["content"])
        self.assertEqual(content["schema"], "2.0")
        self.assertEqual(content["header"]["title"]["content"], "Elephant Agent")
        self.assertEqual(content["body"]["elements"][0]["tag"], "markdown")
        self.assertEqual(
            content["body"]["elements"][0]["content"],
            (
                "Run these commands:\n\n"
                "```bash\n"
                "uv run -m pytest\n"
                "git status\n"
                "```\n\n"
                "```python\n"
                "def add(a, b):\n"
                "    return a + b\n"
                "```\n\n"
                "```latex\n"
                "x^2 + y^2 = z^2\n"
                "```"
            ),
        )

    def test_feishu_post_message_body_preserves_rich_text_rows(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        inbound = feishu.normalize_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-post-command",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_post_user"},
                        "sender_type": "user",
                        "name": "Post User",
                    },
                    "message": {
                        "message_id": "om_post_command",
                        "chat_id": "oc_direct_post",
                        "chat_type": "p2p",
                        "message_type": "post",
                        "content": json.dumps(
                            {
                                "title": "",
                                "content": [
                                    [
                                        {"tag": "text", "text": "- "},
                                        {"tag": "text", "text": "/elephant create leo"},
                                    ]
                                ],
                            }
                        ),
                    },
                },
            }
        )

        self.assertEqual(inbound.body, "- /elephant create leo")
        self.assertEqual(inbound.metadata["message_type"], "post")

    def test_feishu_attachment_refs_preserve_kind_order_and_dedupe_ids(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        inbound = feishu.normalize_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-attachments",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_files"},
                        "sender_type": "user",
                        "name": "Ada Files",
                    },
                    "message": {
                        "message_id": "om_attach_1",
                        "chat_id": "oc_direct_attach",
                        "chat_type": "p2p",
                        "message_type": "file",
                        "content": json.dumps(
                            {
                                "image_key": "img-1",
                                "file_key": "file-1",
                                "audio_key": "audio-1",
                                "media_key": "media-1",
                            }
                        ),
                    },
                },
            }
        )

        self.assertEqual(inbound.attachments, ("img-1", "file-1", "audio-1", "media-1"))
        self.assertEqual(
            tuple((ref.attachment_id, ref.kind) for ref in inbound.attachment_refs),
            (
                ("img-1", "image"),
                ("file-1", "file"),
                ("audio-1", "audio"),
                ("media-1", "media"),
            ),
        )

    def test_feishu_gateway_service_uses_manifest_account_and_dispatches_reply(self) -> None:
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_direct_service",
        )
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                self.assertEqual(payload["app_id"], "cli_feishu_bot")
                self.assertEqual(payload["app_secret"], "super-secret")
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            self.assertTrue(
                url.endswith("/open-apis/im/v1/messages/om_service_bind/reply")
                or url.endswith("/open-apis/im/v1/messages/om_service_1/reply")
            )
            self.assertEqual(headers["Authorization"], "Bearer tenant-token")
            return {
                "code": 0,
                "msg": "ok",
                "data": {
                    "message_id": (
                        "om_reply_bind"
                        if url.endswith("/open-apis/im/v1/messages/om_service_bind/reply")
                        else "om_reply_1"
                    )
                },
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(execution=SimpleNamespace(summary=f"cli-handled:{prompt}"))

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        accounts = load_feishu_gateway_accounts(app)
        self.assertEqual(accounts[0].account_id, "ops-feishu")
        self.assertEqual(accounts[0].event_path, "/hooks/feishu")
        self.assertEqual(accounts[0].surface, "long-connection")

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-bind",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_service"},
                        "sender_type": "user",
                        "name": "Service Ada",
                    },
                    "message": {
                        "message_id": "om_service_bind",
                        "chat_id": "oc_direct_service",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)

        result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-1",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_service"},
                        "sender_type": "user",
                        "name": "Service Ada",
                    },
                    "message": {
                        "message_id": "om_service_1",
                        "chat_id": "oc_direct_service",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from webhook"}),
                    },
                },
            }
        )

        self.assertIsNotNone(result.exchange)
        self.assertEqual(result.response_body["elephant_id"], "demo")
        self.assertEqual(result.response_body["state_id"], "state:demo")
        self.assertEqual(result.response_body["session_id"], expected_session_id)
        self.assertEqual(result.response_body["delivery_outcome"], "delivered")
        self.assertEqual(result.response_body["external_message_id"], "om_reply_1")
        self.assertEqual(
            shared_runtime_calls,
            [
                {
                    "session_id": expected_session_id,
                    "prompt": "hello from webhook",
                    "conversation_id": "oc_direct_service",
                }
            ],
        )
        self.assertEqual(len(requests), 3)

    def test_feishu_gateway_service_supports_account_secret_references(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"]["feishu"].update(
                {
                    "accounts": [
                        {
                            "account_id": "ops-feishu",
                            "secret_references": [
                                {
                                    "reference_id": "secret-feishu-app-id",
                                    "secret_key": "app_id",
                                    "metadata": {"env_var": "ELEPHANT_TEST_FEISHU_APP_ID"},
                                },
                                {
                                    "reference_id": "secret-feishu-app-secret",
                                    "secret_key": "app_secret",
                                    "metadata": {"env_var": "ELEPHANT_TEST_FEISHU_APP_SECRET"},
                                },
                            ],
                        }
                    ]
                }
            )
        )
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_direct_service",
        )
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                self.assertEqual(payload["app_id"], "cli_feishu_bot")
                self.assertEqual(payload["app_secret"], "super-secret")
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            self.assertTrue(
                url.endswith("/open-apis/im/v1/messages/om_service_secret_ref_bind/reply")
                or url.endswith("/open-apis/im/v1/messages/om_service_secret_ref/reply")
            )
            self.assertEqual(headers["Authorization"], "Bearer tenant-token")
            return {
                "code": 0,
                "msg": "ok",
                "data": {
                    "message_id": (
                        "om_reply_secret_ref_bind"
                        if url.endswith("/open-apis/im/v1/messages/om_service_secret_ref_bind/reply")
                        else "om_reply_secret_ref"
                    )
                },
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(execution=SimpleNamespace(summary=f"cli-handled:{prompt}"))

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        accounts = load_feishu_gateway_accounts(app)
        self.assertEqual(accounts[0].account_id, "ops-feishu")
        self.assertEqual(accounts[0].app_id_env_var, "ELEPHANT_TEST_FEISHU_APP_ID")
        self.assertEqual(accounts[0].app_secret_env_var, "ELEPHANT_TEST_FEISHU_APP_SECRET")
        self.assertEqual(
            tuple(reference.reference_id for reference in accounts[0].secret_references),
            ("secret-feishu-app-id", "secret-feishu-app-secret"),
        )

        description = service.describe()
        self.assertEqual(description["accounts"][0]["credentials_source"], "secret_references")
        self.assertEqual(
            description["accounts"][0]["secret_reference_ids"],
            ("secret-feishu-app-id", "secret-feishu-app-secret"),
        )
        self.assertEqual(
            description["accounts"][0]["credential_env_vars"],
            ("ELEPHANT_TEST_FEISHU_APP_ID", "ELEPHANT_TEST_FEISHU_APP_SECRET"),
        )

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-secret-ref-bind",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_service"},
                        "sender_type": "user",
                        "name": "Service Ada",
                    },
                    "message": {
                        "message_id": "om_service_secret_ref_bind",
                        "chat_id": "oc_direct_service",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)

        result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-secret-ref",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_service"},
                        "sender_type": "user",
                        "name": "Service Ada",
                    },
                    "message": {
                        "message_id": "om_service_secret_ref",
                        "chat_id": "oc_direct_service",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from secret refs"}),
                    },
                },
            }
        )

        self.assertIsNotNone(result.exchange)
        self.assertEqual(result.response_body["elephant_id"], "demo")
        self.assertEqual(result.response_body["state_id"], "state:demo")
        self.assertEqual(result.response_body["session_id"], expected_session_id)
        self.assertEqual(result.response_body["external_message_id"], "om_reply_secret_ref")
        self.assertEqual(
            shared_runtime_calls,
            [
                {
                    "session_id": expected_session_id,
                    "prompt": "hello from secret refs",
                    "conversation_id": "oc_direct_service",
                }
            ],
        )
        self.assertEqual(len(requests), 3)

    def test_feishu_gateway_service_can_ignore_disabled_flag_when_requested(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"]["feishu"].update({"enabled": False})
        )
        app, _, _ = self._build()

        self.assertEqual(load_feishu_gateway_accounts(app), ())

        forced_accounts = load_feishu_gateway_accounts(app, respect_enabled=False)
        self.assertEqual(len(forced_accounts), 1)
        self.assertEqual(forced_accounts[0].account_id, "ops-feishu")

        service = FeishuGatewayService(
            app=app,
            environ={
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            respect_enabled=False,
        )
        description = service.describe()
        self.assertEqual(description["accounts"][0]["account_id"], "ops-feishu")
        self.assertEqual(description["accounts"][0]["credentials_status"], "configured")

    def test_feishu_gateway_service_routes_replies_back_to_matched_account(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"]["feishu"].update(
                {
                    "accounts": [
                        {
                            "account_id": "ops-feishu",
                            "event_path": "/hooks/feishu",
                            "env": {
                                "app_id": "ELEPHANT_TEST_FEISHU_APP_ID",
                                "app_secret": "ELEPHANT_TEST_FEISHU_APP_SECRET",
                            },
                        },
                        {
                            "account_id": "support-feishu",
                            "event_path": "/hooks/feishu",
                            "env": {
                                "app_id": "ELEPHANT_TEST_FEISHU_SUPPORT_APP_ID",
                                "app_secret": "ELEPHANT_TEST_FEISHU_SUPPORT_APP_SECRET",
                            },
                        },
                    ]
                }
            )
        )
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12):
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs):
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(execution=SimpleNamespace(summary=f"cli-handled:{prompt}"))

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                app_id = str(payload["app_id"])
                if app_id == "cli_feishu_bot":
                    self.assertEqual(payload["app_secret"], "super-secret")
                    return {
                        "code": 0,
                        "msg": "ok",
                        "tenant_access_token": "tenant-token-ops",
                        "expire": 7200,
                    }
                self.assertEqual(app_id, "support_feishu_bot")
                self.assertEqual(payload["app_secret"], "support-secret")
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token-support",
                    "expire": 7200,
                }
            auth = headers.get("Authorization")
            self.assertIn(auth, {"Bearer tenant-token-ops", "Bearer tenant-token-support"})
            return {
                "code": 0,
                "msg": "ok",
                "data": {
                    "message_id": (
                        "om_reply_ops"
                        if auth == "Bearer tenant-token-ops"
                        else "om_reply_support"
                    )
                },
            }

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
                "ELEPHANT_TEST_FEISHU_SUPPORT_APP_ID": "support_feishu_bot",
                "ELEPHANT_TEST_FEISHU_SUPPORT_APP_SECRET": "support-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_service_ops",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )
        self._bind_cli_control_conversation(
            service,
            account_id="support-feishu",
            conversation_id="oc_service_support",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        ops_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-ops",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-ops",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_ops"},
                        "sender_type": "user",
                        "name": "Ops Ada",
                    },
                    "message": {
                        "message_id": "om_service_ops",
                        "chat_id": "oc_service_ops",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from ops"}),
                    },
                },
            }
        )
        support_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-support",
                    "event_type": "im.message.receive_v1",
                    "app_id": "support_feishu_bot",
                    "tenant_key": "tenant-support",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_support"},
                        "sender_type": "user",
                        "name": "Support Ada",
                    },
                    "message": {
                        "message_id": "om_service_support",
                        "chat_id": "oc_service_support",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from support"}),
                    },
                },
            }
        )

        self.assertEqual(ops_result.response_body["account_id"], "ops-feishu")
        self.assertEqual(ops_result.response_body["external_message_id"], "om_reply_ops")
        self.assertEqual(support_result.response_body["account_id"], "support-feishu")
        self.assertEqual(support_result.response_body["external_message_id"], "om_reply_support")
        self.assertEqual(
            [call["prompt"] for call in shared_runtime_calls],
            ["hello from ops", "hello from support"],
        )
        self.assertEqual(len(requests), 4)
        self.assertEqual(requests[0][2]["app_id"], "cli_feishu_bot")
        self.assertEqual(requests[1][3]["Authorization"], "Bearer tenant-token-ops")
        self.assertEqual(requests[2][2]["app_id"], "support_feishu_bot")
        self.assertEqual(requests[3][3]["Authorization"], "Bearer tenant-token-support")

    def test_feishu_gateway_web_app_handles_challenge_and_event_delivery(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_web_1"},
            }

        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        web_app = create_gateway_web_app(service)

        challenge_status, challenge_body = self._call_wsgi(
            web_app,
            method="POST",
            path="/hooks/feishu",
            payload={"challenge": "verify-me"},
        )
        self.assertEqual(challenge_status, "200 OK")
        self.assertEqual(challenge_body["challenge"], "verify-me")

        event_status, event_body = self._call_wsgi(
            web_app,
            method="POST",
            path="/hooks/feishu",
            payload={
                "schema": "2.0",
                "header": {
                    "event_id": "evt-web-1",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_web"},
                        "sender_type": "user",
                        "name": "Webhook Ada",
                    },
                    "message": {
                        "message_id": "om_web_1",
                        "chat_id": "oc_web_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from http"}),
                    },
                },
            },
        )
        self.assertEqual(event_status, "200 OK")
        self.assertEqual(event_body["delivery_outcome"], "delivered")
        self.assertEqual(event_body["delivery_request_path"], "/open-apis/im/v1/messages/om_web_1/reply")
        self.assertEqual(len(requests), 2)

    def test_feishu_gateway_service_dedupes_duplicate_shared_runtime_events(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_dedupe_1"},
            }

        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt-dedupe-runtime-1",
                "event_type": "im.message.receive_v1",
                "app_id": "cli_feishu_bot",
            },
            "event": {
                "sender": {
                    "sender_id": {"open_id": "ou_runtime_dedupe"},
                    "sender_type": "user",
                    "name": "Runtime Ada",
                },
                "message": {
                    "message_id": "om_runtime_dedupe_1",
                    "chat_id": "oc_runtime_dedupe_1",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": json.dumps({"text": "hello from duplicate runtime"}),
                },
            },
        }

        first = service.dispatch_event(payload, transport="long-connection")
        duplicate = service.dispatch_event(payload, transport="long-connection")

        self.assertEqual(first.response_body["delivery_outcome"], "delivered")
        self.assertEqual(first.response_body["external_message_id"], "om_reply_dedupe_1")
        self.assertEqual(duplicate.response_body["delivery_outcome"], "deduplicated")
        self.assertTrue(duplicate.response_body["duplicate_event"])
        self.assertEqual(duplicate.response_body["duplicate_handling"], "replayed-no-delivery")
        self.assertEqual(duplicate.response_body["initial_delivery_outcome"], "delivered")
        self.assertEqual(duplicate.response_body["external_message_id"], "om_reply_dedupe_1")
        self.assertEqual(len(requests), 2)

    def test_telegram_gateway_service_uses_manifest_account_and_dispatches_reply(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "telegram": {
                        "enabled": True,
                        "event_path": "/hooks/telegram",
                        "accounts": [
                            {
                                "account_id": "ops-telegram",
                                "env": {
                                    "bot_token": "ELEPHANT_TEST_TELEGRAM_BOT_TOKEN",
                                },
                            }
                        ],
                    }
                }
            )
        )
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            self.assertEqual(method, "POST")
            self.assertTrue(url.endswith("/bottelegram-token/sendMessage"))
            self.assertEqual(payload["chat_id"], "77")
            self.assertEqual(payload["reply_to_message_id"], "301")
            return {
                "ok": True,
                "result": {"message_id": 999},
            }

        service = TelegramGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_TELEGRAM_BOT_TOKEN_ENV: "",
                "ELEPHANT_TEST_TELEGRAM_BOT_TOKEN": "telegram-token",
            },
        )

        accounts = load_telegram_gateway_accounts(app)
        self.assertEqual(accounts[0].account_id, "ops-telegram")
        self.assertEqual(accounts[0].event_path, "/hooks/telegram")
        self.assertEqual(accounts[0].surface, "webhook")

        result = service.dispatch_update(
            {
                "update_id": 3001,
                "message": {
                    "message_id": 301,
                    "chat": {"id": 77, "type": "private"},
                    "from": {"id": 12, "username": "telegram_ada"},
                    "text": "hello from telegram service",
                },
            },
            path="/hooks/telegram",
        )

        self.assertIsNotNone(result.exchange)
        self.assertEqual(result.response_body["account_id"], "ops-telegram")
        self.assertEqual(result.response_body["delivery_outcome"], "delivered")
        self.assertEqual(result.response_body["external_message_id"], "999")
        assert result.delivery_request is not None
        self.assertEqual(result.delivery_request["path_label"], "/sendMessage")
        self.assertEqual(len(requests), 1)

    def test_gateway_web_app_can_mount_feishu_and_telegram_services(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "telegram": {
                        "enabled": True,
                        "event_path": "/hooks/telegram",
                        "accounts": [
                            {
                                "account_id": "ops-telegram",
                                "env": {
                                    "bot_token": "ELEPHANT_TEST_TELEGRAM_BOT_TOKEN",
                                },
                            }
                        ],
                    }
                }
            )
        )
        app, _, _ = self._build()
        feishu_requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        telegram_requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_feishu_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            feishu_requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_multi_1"},
            }

        def fake_telegram_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            telegram_requests.append((method, url, payload, headers))
            self.assertTrue(url.endswith("/bottelegram-token/sendMessage"))
            return {
                "ok": True,
                "result": {"message_id": 1001},
            }

        feishu_service = FeishuGatewayService(
            app=app,
            http_requester=fake_feishu_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        telegram_service = TelegramGatewayService(
            app=app,
            http_requester=fake_telegram_request,
            environ={
                DEFAULT_TELEGRAM_BOT_TOKEN_ENV: "",
                "ELEPHANT_TEST_TELEGRAM_BOT_TOKEN": "telegram-token",
            },
        )
        web_app = create_gateway_web_app(
            {
                "feishu": feishu_service,
                "telegram": telegram_service,
            },
            app=app,
        )

        health_status, health_body = self._call_wsgi(
            web_app,
            method="GET",
            path="/healthz",
        )
        self.assertEqual(health_status, "200 OK")
        self.assertIn("feishu", health_body["services"])
        self.assertIn("telegram", health_body["services"])

        feishu_status, feishu_body = self._call_wsgi(
            web_app,
            method="POST",
            path="/hooks/feishu",
            payload={
                "schema": "2.0",
                "header": {
                    "event_id": "evt-web-multi-feishu",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_web_multi"},
                        "sender_type": "user",
                        "name": "Webhook Ada",
                    },
                    "message": {
                        "message_id": "om_web_multi_1",
                        "chat_id": "oc_web_multi_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from multi feishu"}),
                    },
                },
            },
        )
        self.assertEqual(feishu_status, "200 OK")
        self.assertEqual(feishu_body["delivery_outcome"], "delivered")

        telegram_status, telegram_body = self._call_wsgi(
            web_app,
            method="POST",
            path="/hooks/telegram",
            payload={
                "update_id": 9100,
                "message": {
                    "message_id": 91,
                    "chat": {"id": 88, "type": "private"},
                    "from": {"id": 11, "username": "multi_ada"},
                    "text": "hello from multi telegram",
                },
            },
        )
        self.assertEqual(telegram_status, "200 OK")
        self.assertEqual(telegram_body["delivery_outcome"], "delivered")
        self.assertEqual(telegram_body["delivery_request_path"], "/sendMessage")
        self.assertEqual(len(feishu_requests), 2)
        self.assertEqual(len(telegram_requests), 1)

    def test_feishu_gateway_service_starts_python_sdk_long_connection(self) -> None:
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_ws_1",
        )
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        captured: dict[str, object] = {}

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_ws_1"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(execution=SimpleNamespace(summary=f"cli-handled:{prompt}"))

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        class FakeSDKEvent:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

        class FakeEventHandler:
            def __init__(self, callback) -> None:
                self.message_handler = callback

        class FakeEventDispatcherBuilder:
            def __init__(self) -> None:
                self.callback = None

            def register_p2_im_message_receive_v1(self, callback):
                self.callback = callback
                return self

            def build(self):
                assert self.callback is not None
                return FakeEventHandler(self.callback)

        class FakeEventDispatcherHandler:
            @staticmethod
            def builder(encrypt_key: str, verification_token: str, level=None):
                captured["builder"] = {
                    "encrypt_key": encrypt_key,
                    "verification_token": verification_token,
                    "log_level": level,
                }
                return FakeEventDispatcherBuilder()

        class FakeJSON:
            @staticmethod
            def marshal(event: FakeSDKEvent) -> str:
                return json.dumps(event.payload)

        class FakeLogLevel:
            INFO = "INFO"

        class FakeWSClient:
            def __init__(self, app_id: str, app_secret: str, *, event_handler, log_level=None) -> None:
                captured["client"] = {
                    "app_id": app_id,
                    "app_secret": app_secret,
                    "log_level": log_level,
                }
                self.event_handler = event_handler

            def start(self) -> None:
                self.event_handler.message_handler(
                    FakeSDKEvent(
                        {
                            "schema": "2.0",
                            "header": {
                                "event_id": "evt-ws-1",
                                "event_type": "im.message.receive_v1",
                                "app_id": "cli_feishu_bot",
                                "tenant_key": "tenant-alpha",
                            },
                            "event": {
                                "sender": {
                                    "sender_id": {"open_id": "ou_ws"},
                                    "sender_type": "user",
                                    "name": "WS Ada",
                                },
                                "message": {
                                    "message_id": "om_ws_1",
                                    "chat_id": "oc_ws_1",
                                    "chat_type": "p2p",
                                    "message_type": "text",
                                    "content": json.dumps({"text": "hello from ws"}),
                                },
                            },
                        }
                    )
                )

        class FakeWS:
            Client = FakeWSClient

        class FakeLark:
            EventDispatcherHandler = FakeEventDispatcherHandler
            JSON = FakeJSON
            LogLevel = FakeLogLevel
            ws = FakeWS

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_ws_1",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        description = service.describe()
        self.assertEqual(description["implemented_transports"][0], "python-sdk-long-connection")
        self.assertEqual(description["control"]["runtime_status"], "ready")

        try:
            service.start_long_connection(account_id="ops-feishu", lark_module=FakeLark())

            self.assertEqual(captured["client"]["app_id"], "cli_feishu_bot")
            self.assertEqual(captured["client"]["app_secret"], "super-secret")
            self.assertEqual(captured["client"]["log_level"], "INFO")
            self._wait_until(
                lambda: len(shared_runtime_calls) == 1,
                message="expected async long-connection job to reach shared gateway runtime",
            )
            self._wait_until(
                lambda: len(requests) == 3,
                message="expected placeholder and final Feishu replies",
            )
            self.assertEqual(shared_runtime_calls[0]["session_id"], expected_session_id)
            self.assertEqual(shared_runtime_calls[0]["prompt"], "hello from ws")
        finally:
            service.shutdown_async_processing()

    def test_feishu_gateway_service_dedupes_duplicate_long_connection_control_events(self) -> None:
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_ws_dedupe_1",
        )
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_ws_dedupe_1"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(execution=SimpleNamespace(summary=f"cli-handled:{prompt}"))

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        class FakeSDKEvent:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

        class FakeEventHandler:
            def __init__(self, callback) -> None:
                self.message_handler = callback

        class FakeEventDispatcherBuilder:
            def __init__(self) -> None:
                self.callback = None

            def register_p2_im_message_receive_v1(self, callback):
                self.callback = callback
                return self

            def build(self):
                assert self.callback is not None
                return FakeEventHandler(self.callback)

        class FakeEventDispatcherHandler:
            @staticmethod
            def builder(encrypt_key: str, verification_token: str, level=None):
                return FakeEventDispatcherBuilder()

        class FakeJSON:
            @staticmethod
            def marshal(event: FakeSDKEvent) -> str:
                return json.dumps(event.payload)

        class FakeLogLevel:
            INFO = "INFO"

        class FakeWSClient:
            def __init__(self, app_id: str, app_secret: str, *, event_handler, log_level=None) -> None:
                self.event_handler = event_handler

            def start(self) -> None:
                payload = {
                    "schema": "2.0",
                    "header": {
                        "event_id": "evt-ws-dedupe-1",
                        "event_type": "im.message.receive_v1",
                        "app_id": "cli_feishu_bot",
                        "tenant_key": "tenant-alpha",
                    },
                    "event": {
                        "sender": {
                            "sender_id": {"open_id": "ou_ws_dedupe"},
                            "sender_type": "user",
                            "name": "WS Ada",
                        },
                        "message": {
                            "message_id": "om_ws_dedupe_1",
                            "chat_id": "oc_ws_dedupe_1",
                            "chat_type": "p2p",
                            "message_type": "text",
                            "content": json.dumps({"text": "hello from duplicated ws"}),
                        },
                    },
                }
                self.event_handler.message_handler(FakeSDKEvent(payload))
                self.event_handler.message_handler(FakeSDKEvent(payload))

        class FakeWS:
            Client = FakeWSClient

        class FakeLark:
            EventDispatcherHandler = FakeEventDispatcherHandler
            JSON = FakeJSON
            LogLevel = FakeLogLevel
            ws = FakeWS

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_ws_dedupe_1",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        try:
            service.start_long_connection(account_id="ops-feishu", lark_module=FakeLark())

            self._wait_until(
                lambda: len(shared_runtime_calls) == 1,
                message="expected duplicate long-connection event to execute once",
            )
            self._wait_until(
                lambda: len(requests) == 3,
                message="expected only one placeholder and one final reply for duplicate events",
            )
            self.assertEqual(shared_runtime_calls[0]["session_id"], expected_session_id)
            self.assertEqual(shared_runtime_calls[0]["prompt"], "hello from duplicated ws")
        finally:
            service.shutdown_async_processing()

    def test_feishu_long_connection_acknowledges_before_runtime_finishes(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        runtime_started = threading.Event()
        release_runtime = threading.Event()

        def block_shared_runtime(_inbound, _session_id: str) -> None:
            runtime_started.set()
            release_runtime.wait(timeout=45.0)

        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            on_call=block_shared_runtime,
        )

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_reply_async_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        class FakeSDKEvent:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

        class FakeEventHandler:
            def __init__(self, callback) -> None:
                self.message_handler = callback

        class FakeEventDispatcherBuilder:
            def __init__(self) -> None:
                self.callback = None

            def register_p2_im_message_receive_v1(self, callback):
                self.callback = callback
                return self

            def build(self):
                assert self.callback is not None
                return FakeEventHandler(self.callback)

        class FakeEventDispatcherHandler:
            @staticmethod
            def builder(encrypt_key: str, verification_token: str, level=None):
                return FakeEventDispatcherBuilder()

        class FakeJSON:
            @staticmethod
            def marshal(event: FakeSDKEvent) -> str:
                return json.dumps(event.payload)

        class FakeLogLevel:
            INFO = "INFO"

        blocked_payload = self._feishu_message_event(
            event_id="evt-blocked-1",
            message_id="om_blocked_1",
            chat_id="oc_blocked_1",
            text="please block for a while",
        )

        class FakeWSClient:
            def __init__(self, app_id: str, app_secret: str, *, event_handler, log_level=None) -> None:
                self.event_handler = event_handler

            def start(self) -> None:
                self.event_handler.message_handler(FakeSDKEvent(blocked_payload))

        class FakeWS:
            Client = FakeWSClient

        class FakeLark:
            EventDispatcherHandler = FakeEventDispatcherHandler
            JSON = FakeJSON
            LogLevel = FakeLogLevel
            ws = FakeWS

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_blocked_1",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        try:
            started_at = time.monotonic()
            service.start_long_connection(account_id="ops-feishu", lark_module=FakeLark())
            elapsed = time.monotonic() - started_at

            self.assertLess(elapsed, 0.5)
            self.assertTrue(runtime_started.wait(timeout=1.0))
            self._wait_until(
                lambda: len(requests) >= 2,
                message="expected placeholder reply before runtime is released",
            )

            release_runtime.set()
            self._wait_until(
                lambda: len(shared_runtime_calls) == 1 and len(requests) == 3,
                message="expected final reply after async runtime finishes",
            )
        finally:
            release_runtime.set()
            service.shutdown_async_processing()

    def test_feishu_long_connection_duplicate_statuses_are_stateful(self) -> None:
        app, _, _ = self._build()
        service = FeishuGatewayService(
            app=app,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        assert service.adapter is not None
        assert service.async_job_store is not None
        payload = self._feishu_message_event(
            event_id="evt-stateful-1",
            message_id="om_stateful_1",
            chat_id="oc_stateful_1",
            text="stateful duplicate",
        )
        inbound = service.adapter.normalize_event(
            payload,
            account_id="ops-feishu",
            transport="long-connection",
        )

        with mock.patch.object(FeishuGatewayService, "_ensure_async_workers"), mock.patch.object(
            FeishuGatewayService, "_schedule_async_job", return_value=False
        ):
            job_key, _, created = service.async_job_store.create_or_get(
                account_id=inbound.account_id,
                conversation_id=inbound.conversation_id,
                event_id="evt-stateful-1",
                message_id="om_stateful_1",
                payload=payload,
                transport="long-connection",
            )
            self.assertTrue(created)

            queued = service.accept_long_connection_event(payload, account_id="ops-feishu")
            self.assertTrue(queued.response_body["duplicate_event"])
            self.assertEqual(queued.response_body["async_job_status"], "queued")
            self.assertEqual(queued.response_body["duplicate_handling"], "queued")

            service.async_job_store.mark_running(job_key)
            running = service.accept_long_connection_event(payload, account_id="ops-feishu")
            self.assertEqual(running.response_body["async_job_status"], "running")
            self.assertEqual(running.response_body["delivery_outcome"], "processing")

            service.async_job_store.complete(
                job_key,
                response_body={
                    "ok": True,
                    "adapter_id": FEISHU_ADAPTER_ID,
                    "transport": "long-connection",
                    "account_id": inbound.account_id,
                    "conversation_id": inbound.conversation_id,
                    "delivery_outcome": "delivered",
                    "external_message_id": "om_done",
                },
                external_message_id="om_done",
            )
            completed = service.accept_long_connection_event(payload, account_id="ops-feishu")
            self.assertEqual(completed.response_body["delivery_outcome"], "deduplicated")
            self.assertTrue(completed.response_body["duplicate_event"])

            failed_payload = self._feishu_message_event(
                event_id="evt-stateful-2",
                message_id="om_stateful_2",
                chat_id="oc_stateful_2",
                text="stateful failure",
            )
            failed_inbound = service.adapter.normalize_event(
                failed_payload,
                account_id="ops-feishu",
                transport="long-connection",
            )
            failed_key, _, failed_created = service.async_job_store.create_or_get(
                account_id=failed_inbound.account_id,
                conversation_id=failed_inbound.conversation_id,
                event_id="evt-stateful-2",
                message_id="om_stateful_2",
                payload=failed_payload,
                transport="long-connection",
            )
            self.assertTrue(failed_created)
            service.async_job_store.fail(
                failed_key,
                failure_summary="simulated failure",
            )
            failed = service.accept_long_connection_event(failed_payload, account_id="ops-feishu")
            self.assertEqual(failed.response_body["async_job_status"], "failed")
            self.assertEqual(failed.response_body["duplicate_handling"], "failed")

    def test_feishu_async_long_connection_serializes_same_conversation(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        first_started = threading.Event()
        first_release = threading.Event()
        second_started = threading.Event()

        def track_shared_runtime(inbound, _session_id: str) -> None:
            prompt = inbound.body
            if prompt == "first message":
                first_started.set()
                first_release.wait(timeout=2.0)
            else:
                second_started.set()

        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            on_call=track_shared_runtime,
        )

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_serial_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[str] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
            async_worker_count=2,
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_serial",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        try:
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-serial-1",
                    message_id="om_serial_1",
                    chat_id="oc_serial",
                    text="first message",
                ),
                account_id="ops-feishu",
            )
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-serial-2",
                    message_id="om_serial_2",
                    chat_id="oc_serial",
                    text="second message",
                ),
                account_id="ops-feishu",
            )

            self.assertTrue(first_started.wait(timeout=1.0))
            time.sleep(0.15)
            self.assertFalse(second_started.is_set())
            first_release.set()
            self.assertTrue(second_started.wait(timeout=1.0))
            self._wait_until(
                lambda: len(shared_runtime_calls) == 2 and len(requests) == 5,
                message="expected serialized same-conversation jobs to finish with two placeholders and two replies",
            )
            self.assertEqual([call["prompt"] for call in shared_runtime_calls], ["first message", "second message"])
        finally:
            first_release.set()
            service.shutdown_async_processing()

    def test_feishu_async_long_connection_runs_different_conversations_in_parallel(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        first_started = threading.Event()
        second_started = threading.Event()
        release_runtime = threading.Event()

        def track_parallel_runtime(inbound, _session_id: str) -> None:
            if inbound.conversation_id == "oc_parallel_1":
                first_started.set()
            elif inbound.conversation_id == "oc_parallel_2":
                second_started.set()
            release_runtime.wait(timeout=2.0)

        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            on_call=track_parallel_runtime,
        )

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_parallel_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.ops_session = Episode(
                    episode_id="session-ops",
                    state_id="state:test",
                    personal_model_id="elephant:ops",
                    entry_surface="test",
                    elephant_id="ops",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[str] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(elephant_id="demo"),
                    SimpleNamespace(elephant_id="ops"),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_session
                if elephant_id == "ops":
                    return self.ops_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_session.episode_id:
                    return self.demo_session
                if session_id == self.ops_session.episode_id:
                    return self.ops_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
            async_worker_count=2,
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_parallel_1",
            elephant_id="demo",
            session_id="session-demo",
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_parallel_2",
            elephant_id="ops",
            session_id="session-ops",
        )

        try:
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-parallel-1",
                    message_id="om_parallel_1",
                    chat_id="oc_parallel_1",
                    text="parallel demo",
                ),
                account_id="ops-feishu",
            )
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-parallel-2",
                    message_id="om_parallel_2",
                    chat_id="oc_parallel_2",
                    text="parallel ops",
                ),
                account_id="ops-feishu",
            )

            self._wait_until(
                lambda: first_started.is_set() and second_started.is_set(),
                timeout=30.0,
                message="expected both parallel conversations to enter the shared runtime before release",
            )
            release_runtime.set()
            self._wait_until(
                lambda: len(shared_runtime_calls) == 2 and len(requests) == 5,
                message="expected both conversations to run in parallel and complete",
            )
            self.assertCountEqual(
                [call["prompt"] for call in shared_runtime_calls],
                ["parallel demo", "parallel ops"],
            )
        finally:
            release_runtime.set()
            service.shutdown_async_processing()

    def test_feishu_async_long_connection_failure_marks_job_and_surfaces_doctor_status(self) -> None:
        app, _, _ = self._build()

        def fail_shared_runtime(_inbound, _session_id: str) -> None:
            raise RuntimeError("simulated async crash")

        self._install_shared_runtime_stub(app, on_call=fail_shared_runtime)
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_failure_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: FakeCliRuntime(),
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_failure_1",
            elephant_id="demo",
            session_id="session-demo",
        )

        try:
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-failure-1",
                    message_id="om_failure_1",
                    chat_id="oc_failure_1",
                    text="please fail",
                ),
                account_id="ops-feishu",
            )

            self._wait_until(
                lambda: len(tuple(service.describe().get("recent_failures") or ())) == 1,
                message="expected async failure to be recorded",
            )
            self._wait_until(
                lambda: len(requests) == 3,
                message="expected placeholder and failure replies",
            )
            description = service.describe()
            self.assertTrue(description["async_delivery_enabled"])
            self.assertEqual(description["queue_depth"], 0)
            self.assertEqual(description["running_jobs"], 0)
            self.assertEqual(len(tuple(description["recent_failures"])), 1)

            doctor_lines = gateway_main._doctor_lines(
                service,
                SimpleNamespace(
                    profile_dir=str(self.profile_dir),
                    state_dir=str(self.state_dir),
                    cli_profile_dir=str(self.profile_dir),
                    cli_state_dir=str(self.state_dir),
                ),
            )
            self.assertIn("async_delivery_enabled: yes", doctor_lines)
            self.assertIn("recent_failures: 1", doctor_lines)
        finally:
            service.shutdown_async_processing()

    def test_feishu_async_long_connection_recovers_incomplete_jobs_on_startup(self) -> None:
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_recovered_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[str] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        seeded_service = FeishuGatewayService(
            app=app,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        assert seeded_service.adapter is not None
        assert seeded_service.async_job_store is not None
        seeded_payload = self._feishu_message_event(
            event_id="evt-recovery-1",
            message_id="om_recovery_1",
            chat_id="oc_recovery_1",
            text="recover me",
        )
        seeded_inbound = seeded_service.adapter.normalize_event(
            seeded_payload,
            account_id="ops-feishu",
            transport="long-connection",
        )
        seeded_key, _, seeded_created = seeded_service.async_job_store.create_or_get(
            account_id=seeded_inbound.account_id,
            conversation_id=seeded_inbound.conversation_id,
            event_id="evt-recovery-1",
            message_id="om_recovery_1",
            payload=seeded_payload,
            transport="long-connection",
        )
        self.assertTrue(seeded_created)
        seeded_service.async_job_store.mark_running(seeded_key)

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_recovery_1",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        try:
            service._ensure_async_workers()
            self._wait_until(
                lambda: len(shared_runtime_calls) == 1 and len(requests) == 3,
                message="expected recovered async job to resume on startup",
            )
            recovered_record = service.async_job_store.get(seeded_key)
            assert recovered_record is not None
            self.assertEqual(recovered_record.status, "completed")
            self.assertEqual([call["prompt"] for call in shared_runtime_calls], ["recover me"])
        finally:
            service.shutdown_async_processing()

    def test_feishu_control_defaults_to_local_cli_runtime_paths(self) -> None:
        gateway_state_dir = self.state_dir / "gateway"
        gateway_state_dir.mkdir()
        app, _, _ = build_gateway_app(
            provider_profile=self._provider_profile(),
            state_dir=gateway_state_dir,
            control_state_dir=self.state_dir,
        )

        class FakeCliRuntime:
            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)

            def latest_session_for_elephant(self, elephant_id: str):
                return None

            def create_elephant(self, *, elephant_id: str, profile_id=None, display_name=None, mode=None, session_id=None):
                raise AssertionError("create_elephant should not be called in describe path")

            def inspect_session(self, session_id: str):
                raise AssertionError("inspect_session should not be called in describe path")

            def prepare_session_surface(self, session_id: str):
                raise AssertionError("prepare_session_surface should not be called in describe path")

            def explain_next_step(
                self,
                *,
                session_id: str,
                prompt: str,
                state_query=None,
                tool_name=None,
                tool_arguments=None,
                delivery_payload=None,
            ):
                raise AssertionError("explain_next_step should not be called in describe path")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be called in describe path")

        service = FeishuGatewayService(
            app=app,
            cli_runtime_factory=lambda profile_dir, state_dir: FakeCliRuntime(),
            default_cli_state_dir=str(self.state_dir),
        )

        description = service.describe()
        control = description["control"]
        self.assertTrue(control["enabled"])
        self.assertEqual(control["state_dir"], str(self.state_dir))
        self.assertEqual(control["runtime_status"], "ready")
        self.assertEqual(control["known_elephants"], ("demo",))

    def test_feishu_control_bridge_binds_conversation_to_selected_elephant(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_control_1",
        )
        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            session_ids={"oc_control_1": expected_session_id},
        )

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_control_1"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.ops_session = Episode(
                    episode_id="session-ops",
                    state_id="state:test",
                    personal_model_id="elephant:ops",
                    entry_surface="test",
                    elephant_id="ops",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                    SimpleNamespace(
                        elephant_id="ops",
                        latest_session_id=self.ops_session.episode_id,
                        latest_status=self.ops_session.status,
                        updated_at=self.ops_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_session
                if elephant_id == "ops":
                    return self.ops_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_session.episode_id:
                    return self.demo_session
                if session_id == self.ops_session.episode_id:
                    return self.ops_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-bind",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_bind",
                        "chat_id": "oc_control_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertIsNone(bind_result.exchange)
        self.assertEqual(bind_result.response_body["control_mode"], "cli-runtime")
        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)
        self.assertEqual(shared_runtime_calls, [])

        follow_up = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-msg",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_msg",
                        "chat_id": "oc_control_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "keep coding"}),
                    },
                },
            }
        )

        self.assertEqual(follow_up.response_body["elephant_id"], "demo")
        self.assertEqual(follow_up.response_body["session_id"], expected_session_id)
        self.assertEqual(shared_runtime_calls, [{"session_id": expected_session_id, "prompt": "keep coding", "conversation_id": "oc_control_1"}])
        self.assertEqual(len(requests), 3)

    def test_feishu_control_bridge_can_list_and_report_current_elephant(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_control_elephant_status",
        )
        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            session_ids={"oc_control_elephant_status": expected_session_id},
        )

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_control_session"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_root_session = Episode(
                    episode_id="session-demo-root",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.demo_latest_session = Episode(
                    episode_id="session-demo-latest",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                    parent_episode_id=self.demo_root_session.episode_id,
                )
            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_latest_session.episode_id,
                        latest_status=self.demo_latest_session.status,
                        updated_at=self.demo_latest_session.updated_at,
                        session_count=2,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_latest_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_root_session.episode_id:
                    return self.demo_root_session
                if session_id == self.demo_latest_session.episode_id:
                    return self.demo_latest_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        list_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-elephant-list",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_elephant_list",
                        "chat_id": "oc_control_elephant_status",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant list"}),
                    },
                },
            }
        )

        assert list_result.delivery_request is not None
        rendered_listing = str(list_result.delivery_request["body"]["content"])
        self.assertIn("Available local Elephant Agent herd", rendered_listing)
        self.assertIn("demo", rendered_listing)
        self.assertIn("open", rendered_listing)
        self.assertIn("/elephant use <name>", rendered_listing)

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-use-elephant",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_use_elephant",
                        "chat_id": "oc_control_elephant_status",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)

        current_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-current-elephant",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_current_elephant",
                        "chat_id": "oc_control_elephant_status",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant current"}),
                    },
                },
            }
        )

        self.assertEqual(current_result.response_body["elephant_id"], "demo")
        self.assertEqual(current_result.response_body["session_id"], expected_session_id)
        assert current_result.delivery_request is not None
        rendered_current = str(current_result.delivery_request["body"]["content"])
        self.assertIn("Current elephant: `demo`", rendered_current)
        self.assertIn("route_status: `open`", rendered_current)

        follow_up = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-follow-up",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_follow_up",
                        "chat_id": "oc_control_elephant_status",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "stay on the active elephant"}),
                    },
                },
            }
        )

        self.assertEqual(follow_up.response_body["elephant_id"], "demo")
        self.assertEqual(follow_up.response_body["session_id"], expected_session_id)
        self.assertEqual(shared_runtime_calls, [{"session_id": expected_session_id, "prompt": "stay on the active elephant", "conversation_id": "oc_control_elephant_status"}])
        self.assertGreaterEqual(len(requests), 5)

    def test_feishu_control_bridge_accepts_post_command_wrapped_elephant_use(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_reply_post_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo-root",
                    state_id="state:test",
                    personal_model_id="elephant:leo",
                    entry_surface="test",
                    elephant_id="leo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="leo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "leo":
                    return self.demo_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_session.episode_id:
                    return self.demo_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("post command should bind, not forward to runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-use-elephant-post",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_use_elephant_post",
                        "chat_id": "oc_control_elephant_post",
                        "chat_type": "p2p",
                        "message_type": "post",
                        "content": json.dumps(
                            {
                                "title": "",
                                "content": [
                                    [
                                        {"tag": "text", "text": "- "},
                                        {"tag": "text", "text": "/elephant create leo", "style": ["bold"]},
                                    ]
                                ],
                            }
                        ),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["elephant_id"], "leo")
        self.assertEqual(
            bind_result.response_body["session_id"],
            self._gateway_route_session_id(
                adapter_id=FEISHU_ADAPTER_ID,
                account_id="ops-feishu",
                conversation_id="oc_control_elephant_post",
            ),
        )
        self.assertEqual(bind_result.response_body["summary"], "elephant shaped")
        self.assertGreaterEqual(len(requests), 2)

    def test_feishu_control_bridge_reuses_parent_binding_inside_topic_replies(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        parent_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_topic_chat",
        )
        child_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_topic_chat:om_topic_root",
        )

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_reply_topic_{len(requests)}"},
            }

        def on_shared_runtime_call(inbound, session_id: str) -> None:
            parent_identity = app.core.dependencies.identity_store.lookup(
                GatewayIdentityKey(
                    adapter_id=inbound.adapter_id,
                    account_id=inbound.account_id,
                    conversation_id=inbound.parent_conversation_id or inbound.conversation_id,
                )
            )
            assert parent_identity is not None
            app.core.bind_elephant(
                inbound,
                elephant_id=str(parent_identity.elephant_id),
                state_id=str(parent_identity.state_id),
            )

        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            session_ids={"oc_topic_chat:om_topic_root": child_session_id},
            on_call=on_shared_runtime_call,
        )

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_root_session = Episode(
                    episode_id="session-demo-root",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.demo_latest_session = Episode(
                    episode_id="session-demo-latest",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                    parent_episode_id=self.demo_root_session.episode_id,
                )
            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_latest_session.episode_id,
                        latest_status=self.demo_latest_session.status,
                        updated_at=self.demo_latest_session.updated_at,
                        session_count=2,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_latest_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_root_session.episode_id:
                    return self.demo_root_session
                if session_id == self.demo_latest_session.episode_id:
                    return self.demo_latest_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-topic-use-elephant",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_topic_use_elephant",
                        "chat_id": "oc_topic_chat",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["session_id"], parent_session_id)

        topic_follow_up = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-topic-follow-up",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_topic_follow_up",
                        "chat_id": "oc_topic_chat",
                        "chat_type": "p2p",
                        "root_id": "om_topic_root",
                        "parent_id": "om_topic_root",
                        "message_type": "text",
                        "content": json.dumps({"text": "继续这个 session"}),
                    },
                },
            }
        )

        self.assertEqual(topic_follow_up.response_body["elephant_id"], "demo")
        self.assertEqual(topic_follow_up.response_body["session_id"], child_session_id)
        self.assertEqual(shared_runtime_calls, [{"session_id": child_session_id, "prompt": "继续这个 session", "conversation_id": "oc_topic_chat:om_topic_root"}])
        self.assertGreaterEqual(len(requests), 3)

        thread_identity = app.core.dependencies.identity_store.lookup(
            GatewayIdentityKey(
                adapter_id=FEISHU_ADAPTER_ID,
                account_id="ops-feishu",
                conversation_id="oc_topic_chat:om_topic_root",
            )
        )
        self.assertIsNotNone(thread_identity)
        assert thread_identity is not None
        self.assertEqual(thread_identity.session_id, child_session_id)

    def test_feishu_control_bridge_requires_binding_before_plain_text_routes(self) -> None:
        app, _, _ = self._build()

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_control_hint"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.ops_session = Episode(
                    episode_id="session-ops",
                    state_id="state:test",
                    personal_model_id="elephant:ops",
                    entry_surface="test",
                    elephant_id="ops",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                    SimpleNamespace(
                        elephant_id="ops",
                        latest_session_id=self.ops_session.episode_id,
                        latest_status=self.ops_session.status,
                        updated_at=self.ops_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_session
                if elephant_id == "ops":
                    return self.ops_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_session.episode_id:
                    return self.demo_session
                if session_id == self.ops_session.episode_id:
                    return self.ops_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(
                    execution=SimpleNamespace(summary=f"cli-handled:{prompt}")
                )

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-unbound",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_unbound",
                        "chat_id": "oc_control_unbound",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello there"}),
                    },
                },
            }
        )

        self.assertIsNone(result.exchange)
        self.assertEqual(result.response_body["control_mode"], "cli-runtime")
        self.assertNotIn("elephant_id", result.response_body)
        self.assertNotIn("session_id", result.response_body)
        self.assertEqual(len(fake_runtime.explain_calls), 0)
        assert result.delivery_request is not None
        self.assertEqual(result.delivery_request["body"]["msg_type"], "interactive")
        rendered_post = json.loads(result.delivery_request["body"]["content"])
        self.assertEqual(rendered_post["schema"], "2.0")
        rendered_text = rendered_post["body"]["elements"][0]["content"]
        self.assertIn("This conversation is not pinned yet.", rendered_text)
        self.assertIn("/elephant list", rendered_text)
        self.assertIn("/elephant use <name>", rendered_text)

    def test_interruption_state_is_preserved_when_chat_resumes(self) -> None:
        app, chat_adapter, _ = self._build()

        first = chat_adapter.receive_text(
            conversation_id="chat-2",
            external_user_id="user-2",
            body="pause here",
            event_id="evt-3",
        )
        interrupted = app.interrupt_episode(
            first.route.session.session_id,
            interruption_state="awaiting-operator-reply",
        )

        self.assertEqual(interrupted.status, "interrupted")
        self.assertEqual(interrupted.interruption_state, "awaiting-operator-reply")

        restarted_app, restarted_chat, _ = self._build()
        resumed = restarted_chat.receive_text(
            conversation_id="chat-2",
            external_user_id="user-2",
            body="back again",
            event_id="evt-4",
        )

        self.assertFalse(resumed.route.is_new_session)
        self.assertEqual(resumed.route.session.status, "interrupted")
        self.assertEqual(
            resumed.route.session.interruption_state,
            "awaiting-operator-reply",
        )
        self.assertEqual(
            restarted_app.session_records()[0].interruption_state,
            "awaiting-operator-reply",
        )

    def test_telegram_private_update_reuses_identity_mapping_across_restart(self) -> None:
        app, _, _ = self._build()
        telegram = TelegramMessagingAdapter(app=app)

        first = telegram.receive_update(
            {
                "update_id": 9001,
                "message": {
                    "message_id": 42,
                    "chat": {"id": 55, "type": "private"},
                    "from": {"id": 7, "first_name": "Ada", "last_name": "Lovelace"},
                    "text": "hello from telegram",
                },
            },
        )
        self.assertTrue(first.route.is_new_session)
        self.assertEqual(first.delivery.outcome, "delivered")

        restarted_app, _, _ = self._build()
        restarted = TelegramMessagingAdapter(app=restarted_app)
        second = restarted.receive_update(
            {
                "update_id": 9002,
                "edited_message": {
                    "message_id": 43,
                    "chat": {"id": 55, "type": "private"},
                    "from": {"id": 7, "username": "ada"},
                    "text": "follow-up",
                },
            }
        )

        self.assertFalse(second.route.is_new_session)
        self.assertEqual(first.route.identity.mapping_id, second.route.identity.mapping_id)
        self.assertEqual(
            second.route.session.session_id,
            f"session:{TELEGRAM_ADAPTER_ID}:{DEFAULT_GATEWAY_ACCOUNT_ID}:55",
        )
        self.assertEqual(second.route.identity.display_name, "@ada")
        self.assertEqual(second.delivery.policy_result.decision, PolicyDecision.ALLOW)
        self.assertEqual(second.route.inbound.chat_type, "direct")
        self.assertEqual(len(restarted_app.identity_records()), 1)
        self.assertEqual(len(restarted_app.session_records()), 1)

    def test_telegram_group_update_defaults_to_review_and_tracks_thread(self) -> None:
        app, _, _ = self._build()
        telegram = TelegramMessagingAdapter(app=app)

        exchange = telegram.receive_update(
            {
                "update_id": 9003,
                "callback_query": {
                    "data": "approve",
                    "message": {
                        "message_id": 44,
                        "message_thread_id": 9,
                        "chat": {"id": -10012345, "type": "supergroup"},
                        "from": {"id": 8, "username": "grace"},
                        "caption": "Need an answer here.",
                        "photo": [
                            {"file_id": "photo-1"},
                            {"file_id": "photo-1"},
                        ],
                        "document": {"file_id": "doc-1"},
                    },
                },
            },
        )

        self.assertEqual(exchange.route.identity.key.adapter_id, TELEGRAM_ADAPTER_ID)
        self.assertEqual(exchange.route.identity.display_name, "@grace")
        self.assertEqual(exchange.route.inbound.conversation_id, "-10012345:9")
        self.assertEqual(
            exchange.route.session.session_id,
            f"session:{TELEGRAM_ADAPTER_ID}:{DEFAULT_GATEWAY_ACCOUNT_ID}:-10012345:9",
        )
        self.assertEqual(exchange.route.inbound.parent_conversation_id, "-10012345")
        self.assertEqual(exchange.route.inbound.thread_id, "9")
        self.assertEqual(exchange.route.inbound.chat_type, "group")
        self.assertEqual(exchange.route.inbound.attachments, ("photo-1", "doc-1"))
        self.assertEqual(exchange.route.inbound.metadata["update_kind"], "callback_query")
        self.assertEqual(exchange.route.inbound.metadata["message_thread_id"], "9")
        self.assertEqual(exchange.delivery.outcome, "blocked")
        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.REVIEW)
        self.assertIsNone(exchange.delivery.outbound)
        self.assertIn(
            "recipient-verification",
            exchange.delivery.policy_result.required_controls,
        )


if __name__ == "__main__":
    unittest.main()
