from __future__ import annotations

import json
import io
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.gateway import FEISHU_ADAPTER_ID, build_gateway_app
from apps.provider_runtime import provider_profile_from_payload
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
from packages.runtime_config import (
    global_config_path_for_state_dir,
    load_global_config,
    save_provider_to_config,
    write_global_config,
)
from packages.security.runtime import PolicyDecision


class GatewayAdapterTestBase(unittest.TestCase):
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

    def _write_profile_manifest(self, payload: dict[str, object]) -> None:
        serialized = json.dumps(payload)
        (self.profile_dir / "profile.json").write_text(serialized, encoding="utf-8")
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

    def _update_manifest(self, mutator) -> None:
        manifest_path = self.profile_dir / "profile.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutator(payload)
        self._write_profile_manifest(payload)

    def _build(self):
        return build_gateway_app(
            provider_profile=self._provider_profile(),
            state_dir=self.state_dir,
            control_state_dir=self.state_dir,
        )

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
