"""Gateway parser, account, and status helpers."""

from __future__ import annotations
import asyncio
from argparse import SUPPRESS, ArgumentParser, Namespace
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import getpass
import apps.cli.wizard as cli_wizard
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from wsgiref.simple_server import make_server

from apps.cli.runtime import CliRuntime
from apps.cli.shell import (
    Align,
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_LIGHT,
    BRAND_MUTED,
    Console,
    Group,
    Panel,
    RICH_AVAILABLE,
    Table,
    Text,
    _resolve_elephant_version,
    render_elephant_mark,
)
from apps.provider_runtime import load_provider_profile, load_runtime_local_secret_env
from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir
from packages.runtime_config import global_config_path_for_state_dir

from . import (
    DEFAULT_DINGDING_CLIENT_ID_ENV,
    DEFAULT_DINGDING_CLIENT_SECRET_ENV,
    DEFAULT_DINGDING_ROBOT_CODE_ENV,
    DEFAULT_DISCORD_BOT_TOKEN_ENV,
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    DEFAULT_FEISHU_EVENT_PATH,
    DEFAULT_WECOM_BOT_ID_ENV,
    DEFAULT_WECOM_SECRET_ENV,
    DINGDING_ADAPTER_ID,
    FEISHU_ADAPTER_ID,
    GatewayHttpService,
    GatewayManagedRuntime,
    GatewayManagedService,
    SUPPORTED_DINGDING_TRANSPORTS,
    SUPPORTED_DISCORD_TRANSPORTS,
    SUPPORTED_FEISHU_TRANSPORTS,
    SUPPORTED_WECOM_TRANSPORTS,
    SUPPORTED_WEIXIN_TRANSPORTS,
    WECOM_ADAPTER_ID,
    WEIXIN_ADAPTER_ID,
    build_gateway_app,
    build_gateway_plugin_registry,
    create_gateway_web_app,
)
from .dingding import DINGTALK_STREAM_PIP_SPEC, DingdingGatewayService
from .discord import DISCORD_PY_PIP_SPEC, DiscordGatewayService
from .feishu import FEISHU_SDK_PIP_SPEC, FeishuGatewayService
from .wecom import WecomGatewayService
from .weixin import WeixinGatewayService

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings as PromptKeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.shortcuts import input_dialog
    from prompt_toolkit.styles import Style as PromptStyle

    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional wizard polish
    Application = None
    PromptKeyBindings = None
    HSplit = None
    Window = None
    FormattedTextControl = None
    Layout = None
    input_dialog = None
    PromptStyle = None
    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = False


from .gateway_main_runtime import *  # noqa: F401,F403
from .gateway_main_wizard import *  # noqa: F401,F403

from .gateway_main_parser_state import *  # noqa: F401,F403
from .gateway_main_parser_state import __all__ as _STATE_ALL
from .gateway_main_parser_providers import *  # noqa: F401,F403
from .gateway_main_parser_providers import __all__ as _PROVIDER_ALL
from .gateway_main_parser_doctor import *  # noqa: F401,F403
from .gateway_main_parser_doctor import __all__ as _DOCTOR_ALL

def _build_registry():
    return build_gateway_plugin_registry()

def _gateway_provider_profile_for(args: Namespace):
    """Load provider profile from the canonical CLI control runtime config.
    
    Always uses cli_state_dir to ensure consistent configuration across all IM components.
    """
    cli_state_dir = getattr(args, "cli_state_dir", None)
    if cli_state_dir is None:
        cli_state_dir = default_cli_state_dir()
    if cli_state_dir is None:
        return None
    
    state_dir = Path(cli_state_dir)
    config_path = global_config_path_for_state_dir(state_dir)
    return load_provider_profile(state_dir, config_path=config_path)


def _build_app(args: Namespace, *, registry=None):
    args.state_dir.mkdir(parents=True, exist_ok=True)
    app, _, _ = build_gateway_app(
        provider_profile=_gateway_provider_profile_for(args),
        state_dir=str(args.state_dir),
        control_state_dir=str(args.cli_state_dir) if args.cli_state_dir else None,
        runtime_environ=_gateway_runtime_environ(
            args.state_dir,
            cli_state_dir=args.cli_state_dir,
        ),
        plugin_registry=registry,
    )
    return app

def _service_kwargs_for(service_key: str, args: Namespace) -> dict[str, object]:
    if service_key == "discord":
        return {
            "default_cli_state_dir": (
                None if args.cli_state_dir is None else str(args.cli_state_dir)
            ),
            "environ": _gateway_runtime_environ(
                args.state_dir,
                cli_state_dir=args.cli_state_dir,
            ),
            "runtime_dependency_ensurer": _ensure_discord_sdk_available,
            "runtime_state_dir": Path(args.state_dir),
        }
    if service_key == "feishu":
        return {
            "default_cli_state_dir": (
                None if args.cli_state_dir is None else str(args.cli_state_dir)
            ),
            "environ": _gateway_runtime_environ(
                args.state_dir,
                cli_state_dir=args.cli_state_dir,
            ),
            "runtime_dependency_ensurer": _ensure_feishu_sdk_available,
        }
    if service_key == "dingding":
        return {
            "default_cli_state_dir": (
                None if args.cli_state_dir is None else str(args.cli_state_dir)
            ),
            "environ": _gateway_runtime_environ(
                args.state_dir,
                cli_state_dir=args.cli_state_dir,
            ),
            "runtime_dependency_ensurer": _ensure_dingding_sdk_available,
            "runtime_state_dir": Path(args.state_dir),
        }
    if service_key == "weixin":
        return {
            "default_cli_state_dir": (
                None if args.cli_state_dir is None else str(args.cli_state_dir)
            ),
            "environ": _gateway_runtime_environ(
                args.state_dir,
                cli_state_dir=args.cli_state_dir,
            ),
            "runtime_dependency_ensurer": _ensure_weixin_sdk_available,
            "runtime_state_dir": Path(args.state_dir),
        }
    if service_key == "wecom":
        return {
            "default_cli_state_dir": (
                None if args.cli_state_dir is None else str(args.cli_state_dir)
            ),
            "environ": _gateway_runtime_environ(
                args.state_dir,
                cli_state_dir=args.cli_state_dir,
            ),
            "runtime_dependency_ensurer": _ensure_wecom_sdk_available,
            "runtime_state_dir": Path(args.state_dir),
        }
    return {}

def _build_services(
    args: Namespace,
    *,
    service_keys: Iterable[str] | None = None,
):
    registry = _build_registry()
    app = _build_app(args, registry=registry)
    manifest = app.loaded_profile.manifest if app.loaded_profile is not None else None
    resolved_keys = (
        tuple(service_keys)
        if service_keys is not None
        else registry.configured_service_keys(manifest)
    )
    services = {
        key: registry.create_service(
            key,
            app=app,
            **_service_kwargs_for(key, args),
        )
        for key in resolved_keys
    }
    return app, services

def _build_service(
    args: Namespace,
    *,
    service_key: str,
    respect_enabled: bool = False,
):
    registry = _build_registry()
    app = _build_app(args, registry=registry)
    service = registry.create_service(
        service_key,
        app=app,
        respect_enabled=respect_enabled,
        **_service_kwargs_for(service_key, args),
    )
    return service

def _build_feishu_service(args: Namespace) -> FeishuGatewayService:
    service = _build_service(args, service_key="feishu", respect_enabled=False)
    if not isinstance(service, FeishuGatewayService):
        raise TypeError("gateway service plugin 'feishu' must build FeishuGatewayService")
    return service

def _build_discord_service(args: Namespace) -> DiscordGatewayService:
    service = _build_service(args, service_key="discord", respect_enabled=False)
    if not isinstance(service, DiscordGatewayService):
        raise TypeError("gateway service plugin 'discord' must build DiscordGatewayService")
    return service


def _build_dingding_service(args: Namespace) -> DingdingGatewayService:
    service = _build_service(args, service_key="dingding", respect_enabled=False)
    if not isinstance(service, DingdingGatewayService):
        raise TypeError("gateway service plugin 'dingding' must build DingdingGatewayService")
    return service


def _build_weixin_service(args: Namespace) -> WeixinGatewayService:
    service = _build_service(args, service_key="weixin", respect_enabled=False)
    if not isinstance(service, WeixinGatewayService):
        raise TypeError("gateway service plugin 'weixin' must build WeixinGatewayService")
    return service


def _build_wecom_service(args: Namespace) -> WecomGatewayService:
    service = _build_service(args, service_key="wecom", respect_enabled=False)
    if not isinstance(service, WecomGatewayService):
        raise TypeError("gateway service plugin 'wecom' must build WecomGatewayService")
    return service

def _build_managed_service(args: Namespace, *, service_key: str) -> GatewayManagedService:
    service = _build_service(args, service_key=service_key, respect_enabled=False)
    if not isinstance(service, GatewayManagedService):
        raise TypeError(
            f"gateway service plugin '{service_key}' must build a managed gateway service"
        )
    return service

def _describe_payload(service_key: str, service) -> dict[str, object]:
    return {
        "gateway": dict(service.app.setup_summary()),
        service_key: dict(service.describe()),
    }

def _describe_services_payload(
    app,
    services: Mapping[str, object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "gateway": dict(app.setup_summary()),
        "services": {
            key: dict(service.describe())
            for key, service in services.items()
            if hasattr(service, "describe")
        },
    }
    for key, service in services.items():
        if hasattr(service, "describe"):
            payload[key] = dict(service.describe())
    return payload

def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _run_status_all(args: Namespace) -> int:
    app, services = _build_services(args)
    print("Elephant Agent Gateway status")
    print(f"im_gateway_dir: {args.state_dir}")

    # Show daemon status if running
    try:
        from apps.daemon_command import daemon_is_running
        from apps.daemon_command import _read_pid, _daemon_pid_path
        state_dir_path = Path(args.state_dir)
        daemon_pid = _read_pid(_daemon_pid_path(state_dir_path))
        if daemon_is_running(state_dir_path):
            print(f"daemon_status: running (pid {daemon_pid})")
            print("note: all adapters are managed by the unified daemon")
        else:
            print("daemon_status: stopped")
    except Exception:
        pass

    if not services:
        print("configured_services: <none>")
        print("next_steps:")
        print("- Run `elephant gateway setup` to configure your first IM account.")
        return 0
    print("configured_services: " + ", ".join(services.keys()))
    for service_key, service in services.items():
        description = service.describe() if hasattr(service, "describe") else {}
        runtime_status, runtime_error = _service_runtime_status_summary(service, args)
        configured_transport = description.get("configured_transport") or "<unset>"
        print(f"service[{service_key}].configured_transport: {configured_transport}")
        print(f"service[{service_key}].runtime_status: {runtime_status}")
        if runtime_error is not None:
            print(f"service[{service_key}].runtime_error: {runtime_error}")
        for account in tuple(description.get("accounts") or ()):
            if not isinstance(account, Mapping):
                continue
            if service_key == "discord":
                print(_render_discord_account_line(account, prefix=f"service[{service_key}].account"))
            elif service_key == "feishu":
                print(_render_feishu_account_line(account, prefix=f"service[{service_key}].account"))
            elif service_key == "dingding":
                print(_render_dingding_account_line(account, prefix=f"service[{service_key}].account"))
            elif service_key == "weixin":
                print(_render_weixin_account_line(account, prefix=f"service[{service_key}].account"))
            elif service_key == "wecom":
                print(_render_wecom_account_line(account, prefix=f"service[{service_key}].account"))
    return 0


__all__ = [*_STATE_ALL, *_PROVIDER_ALL, *_DOCTOR_ALL, *['_build_registry', '_build_app', '_service_kwargs_for', '_build_services', '_build_service', '_build_feishu_service', '_build_discord_service', '_build_dingding_service', '_build_weixin_service', '_build_wecom_service', '_build_managed_service', '_describe_payload', '_describe_services_payload', '_print_json', '_run_status_all']]
