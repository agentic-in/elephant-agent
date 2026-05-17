"""Gateway CLI main implementation assembled from wizard, runtime, and parser helpers."""

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
from apps.provider_runtime import load_runtime_local_secret_env
from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir
from packages.gateway_core import DEFAULT_GATEWAY_ACCOUNT_ID
from packages.runtime_config import save_extensions_to_config, global_config_path_for_state_dir, load_global_config, write_global_config

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


from .gateway_main_parser import *  # noqa: F401,F403
from .gateway_main_parser import _resolved_cli_account_id
from .gateway_main_runtime import *  # noqa: F401,F403
from .gateway_main_wizard import *  # noqa: F401,F403
from .gateway_main_wizard import (
    GATEWAY_WIZARD_BACK,
    _confirm_gateway_wizard_intro,
    _gateway_wizard_choice_prompt,
    _gateway_wizard_dialogs_supported,
    _gateway_wizard_secret_prompt,
    _gateway_wizard_text_prompt,
    _interactive_shell_supported,
    _print_gateway_dingding_wizard_intro,
    _print_gateway_discord_wizard_intro,
    _print_gateway_feishu_wizard_intro,
    _print_gateway_setup_paused,
    _print_gateway_wecom_wizard_intro,
    _print_gateway_weixin_wizard_intro,
    _run_interactive_dingding_wizard,
    _run_interactive_discord_wizard,
    _run_interactive_feishu_wizard,
    _run_interactive_wecom_wizard,
    _run_interactive_weixin_wizard,
    _shared_wizard_choice_prompt,
    _shared_wizard_text_prompt,
)

def _save_gateway_manifest(state_dir: Path, manifest: Mapping[str, Any]) -> Path:
    """Write gateway and extension data to config.yaml, return the config path."""
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    # Merge gateway payload into config gateway section
    gateway_payload = manifest.get("gateway")
    if isinstance(gateway_payload, Mapping):
        config["gateway"] = {**config.get("gateway", {}), **dict(gateway_payload)}
    else:
        config.pop("gateway", None)
    # Merge extension keys
    extension_keys = ("tool_manifests", "skill_manifests", "skill_overrides", "skill_packages")
    extensions = dict(config.get("extensions", {})) if isinstance(config.get("extensions"), Mapping) else {}
    for key in extension_keys:
        if key in manifest:
            extensions[key] = manifest[key]
        else:
            extensions.pop(key, None)
    config["extensions"] = extensions
    write_global_config(config_path, config)
    return config_path


def _run_add_discord(args: Namespace) -> int:
    _ensure_discord_sdk_available(reason="Discord setup")


    
    
    
    
    
    
    
    
    
    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    discord_payload = _mapping_payload(adapters_payload.get("discord"), path="gateway.adapters.discord")
    control_payload = _mapping_payload(discord_payload.get("control"), path="gateway.adapters.discord.control")

    account_id = _resolved_cli_account_id(args) or DEFAULT_GATEWAY_ACCOUNT_ID
    accounts_value = discord_payload.get("accounts")
    if accounts_value is None:
        existing_accounts: list[dict[str, object]] = []
    elif isinstance(accounts_value, list):
        existing_accounts = []
        for index, account in enumerate(accounts_value):
            if not isinstance(account, Mapping):
                raise SystemExit(
                    f"gateway.adapters.discord.accounts[{index}] must be a JSON object"
                )
            existing_accounts.append({str(key): value for key, value in account.items()})
    else:
        raise SystemExit("gateway.adapters.discord.accounts must be a JSON array")
    existing_account = _find_discord_account(existing_accounts, account_id=account_id)

    transport = (
        str(args.transport or "").strip()
        or str((existing_account or {}).get("surface") or "").strip()
        or str(discord_payload.get("surface") or "").strip()
        or "gateway"
    )
    bot_token_env_var = _resolved_discord_bot_token_env_var(
        explicit_env_var=args.bot_token_env_var,
        existing_account=existing_account,
        account_id=account_id,
    )
    allow_guild_ids = (
        list(dict.fromkeys(str(value).strip() for value in args.allow_guild_id if str(value).strip()))
        if args.allow_guild_id is not None
        else _payload_string_list((existing_account or {}).get("allow_guild_ids"))
    )
    allow_channel_ids = (
        list(dict.fromkeys(str(value).strip() for value in args.allow_channel_id if str(value).strip()))
        if args.allow_channel_id is not None
        else _payload_string_list((existing_account or {}).get("allow_channel_ids"))
    )
    enabled = bool(args.enabled) if args.enabled is not None else True
    account_enabled = (
        bool(args.account_enabled)
        if args.account_enabled is not None
        else bool((existing_account or {}).get("enabled") is not False)
    )
    allow_group_chats = bool(args.allow_group_chats) or bool(control_payload.get("allow_group_chats") is True)
    bot_token_value = str(args.bot_token or "").strip()
    use_wizard = bool(args.wizard) if args.wizard is not None else _interactive_shell_supported()
    if use_wizard:
        if not _print_gateway_discord_wizard_intro():
            _print_gateway_setup_paused("Discord")
            return 0
        wizard_state = _run_interactive_discord_wizard(
            account_id=account_id,
            transport=transport,
            bot_token_value=bot_token_value,
            enabled=enabled,
            account_enabled=account_enabled,
            allow_group_chats=allow_group_chats,
            allow_guild_ids=allow_guild_ids,
            allow_channel_ids=allow_channel_ids,
        )
        if wizard_state is None:
            _print_gateway_setup_paused("Discord")
            return 0
        account_id = wizard_state.account_id
        transport = wizard_state.transport
        bot_token_value = wizard_state.bot_token_value
        enabled = wizard_state.enabled
        account_enabled = wizard_state.account_enabled
        allow_group_chats = wizard_state.allow_group_chats
        allow_guild_ids = list(wizard_state.allow_guild_ids)
        allow_channel_ids = list(wizard_state.allow_channel_ids)

    auto_start = (bool(getattr(args, "auto_start", False)) or use_wizard) and not getattr(args, "no_start", False)
    args.account_id = account_id
    existing_account = _find_discord_account(existing_accounts, account_id=account_id)
    bot_token_env_var = _resolved_discord_bot_token_env_var(
        explicit_env_var=args.bot_token_env_var,
        existing_account=existing_account,
        account_id=account_id,
    )

    account_payload: dict[str, object] = {
        "account_id": account_id,
        "surface": transport,
        "enabled": account_enabled,
        "env": {"bot_token": bot_token_env_var},
    }
    existing_runtime = _mapping((existing_account or {}).get("runtime"))
    if existing_runtime:
        account_payload["runtime"] = dict(existing_runtime)
    if allow_guild_ids:
        account_payload["allow_guild_ids"] = allow_guild_ids
    if allow_channel_ids:
        account_payload["allow_channel_ids"] = allow_channel_ids

    local_secret_path = _persist_gateway_local_secret_env(
        args.state_dir,
        {bot_token_env_var: bot_token_value},
    )

    control_payload.pop("default_elephant_id", None)
    control_payload.pop("default_session_id", None)
    control_payload.pop("auto_create_elephant", None)
    if allow_group_chats:
        control_payload["allow_group_chats"] = True
    elif use_wizard:
        control_payload.pop("allow_group_chats", None)

    discord_payload["accounts"] = _upsert_discord_account(existing_accounts, account_payload)
    discord_payload["surface"] = transport
    discord_payload["enabled"] = enabled
    if control_payload:
        discord_payload["control"] = control_payload
    else:
        discord_payload.pop("control", None)
    adapters_payload["discord"] = discord_payload
    gateway_payload["adapters"] = adapters_payload
    manifest["gateway"] = gateway_payload

    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)

    service = _build_discord_service(args)
    print(f"Configured Discord IM in {manifest_path}")
    print(f"Discord account: {account_id}")
    print(f"Discord transport: {transport}")
    if local_secret_path is not None:
        print(f"Local IM secret file: {local_secret_path}")

        print("Raw Discord bot token was stored locally outside config.yaml.")
    if auto_start:
        print("Starting the configured Discord bridge in the background...")
        try:
            _start_discord_runtime_after_setup(args, transport=transport)
        except SystemExit as exc:
            print("Discord setup completed, but the bridge did not stay running in the background.")
            print(f"Reason: {exc}")
            print("Next steps:")
            for step in _discord_next_steps(service):
                print(f"- {step}")
            print("- Start it again with `elephant gateway discord start --detach`.")
            return 1
        print("Discord setup is complete.")
        print("Next steps:")
        print("- Check status with `elephant gateway discord status`.")
        print(f"- Follow logs with `elephant gateway discord logs {account_id} --follow`.")
        print(f"- Restart after changes with `elephant gateway discord restart {account_id}`.")
        return 0
    print("Discord account enabled for default runtime starts: " + ("yes" if account_enabled else "no"))
    print("next_steps:")
    for step in _discord_next_steps(service):
        print(f"- {step}")
    print("Discord developer portal checklist:")
    for step in _discord_portal_checklist():
        print(f"- {step}")
    print("- Start the configured bridge with `elephant gateway discord start`.")
    return 0

def _start_discord_runtime_after_setup(args: Namespace, *, transport: str) -> int:
    start_args = Namespace(**vars(args))
    start_args.runtime_target = transport or "configured"
    start_args.account_id = None
    start_args.detach = True
    start_args.timeout = float(getattr(start_args, "timeout", 10.0) or 10.0)
    start_args.force = bool(getattr(start_args, "force", False))
    from apps.gateway.gateway_main_impl import _start_via_daemon
    return _start_via_daemon(start_args)

def _start_feishu_runtime_after_setup(args: Namespace, *, transport: str) -> int:
    start_args = Namespace(**vars(args))
    start_args.runtime_target = transport or "configured"
    if transport == "long-connection":
        start_args.account_id = None
    start_args.detach = True
    start_args.host = getattr(start_args, "host", "127.0.0.1")
    start_args.port = int(getattr(start_args, "port", 8788) or 8788)
    start_args.timeout = float(getattr(start_args, "timeout", 10.0) or 10.0)
    start_args.force = bool(getattr(start_args, "force", False))
    from apps.gateway.gateway_main_impl import _start_via_daemon
    return _start_via_daemon(start_args)

def _run_add_feishu(args: Namespace) -> int:
    _ensure_feishu_sdk_available(reason="Feishu setup")

    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    feishu_payload = _mapping_payload(adapters_payload.get("feishu"), path="gateway.adapters.feishu")
    control_payload = _mapping_payload(feishu_payload.get("control"), path="gateway.adapters.feishu.control")

    account_id = _resolved_cli_account_id(args) or DEFAULT_GATEWAY_ACCOUNT_ID
    accounts_value = feishu_payload.get("accounts")
    if accounts_value is None:
        existing_accounts: list[dict[str, object]] = []
    elif isinstance(accounts_value, list):
        existing_accounts = []
        for index, account in enumerate(accounts_value):
            if not isinstance(account, Mapping):
                raise SystemExit(
                    f"gateway.adapters.feishu.accounts[{index}] must be a JSON object"
                )
            existing_accounts.append({str(key): value for key, value in account.items()})
    else:
        raise SystemExit("gateway.adapters.feishu.accounts must be a JSON array")

    existing_account = _find_feishu_account(existing_accounts, account_id=account_id)
    transport = (
        str(args.transport)
        if args.transport is not None
        else str(
            (existing_account or {}).get("surface")
            or feishu_payload.get("surface")
            or "long-connection"
        )
    )
    event_path = (
        str(args.event_path)
        if args.event_path is not None
        else str(
            (existing_account or {}).get("event_path")
            or feishu_payload.get("event_path")
            or DEFAULT_FEISHU_EVENT_PATH
        )
    )
    app_id_env_var = _resolved_feishu_secret_env_var(
        explicit_env_var=args.app_id_env_var,
        existing_account=existing_account,
        account_id=account_id,
        secret_key="app_id",
    )
    app_secret_env_var = _resolved_feishu_secret_env_var(
        explicit_env_var=args.app_secret_env_var,
        existing_account=existing_account,
        account_id=account_id,
        secret_key="app_secret",
    )
    app_id_value = str(args.app_id or "").strip()
    app_secret_value = str(args.app_secret or "").strip()
    enabled = bool(args.enabled) if args.enabled is not None else True
    allow_group_chats = bool(args.allow_group_chats) or bool(control_payload.get("allow_group_chats") is True)

    use_wizard = bool(args.wizard) if args.wizard is not None else _interactive_shell_supported()
    if use_wizard:
        if not _print_gateway_feishu_wizard_intro():
            _print_gateway_setup_paused("Feishu")
            return 0
        wizard_state = _run_interactive_feishu_wizard(
            account_id=account_id,
            transport=transport,
            event_path=event_path,
            app_id_env_var=app_id_env_var,
            app_secret_env_var=app_secret_env_var,
            app_id_value=app_id_value,
            app_secret_value=app_secret_value,
            enabled=enabled,
            allow_group_chats=allow_group_chats,
        )
        if wizard_state is None:
            _print_gateway_setup_paused("Feishu")
            return 0
        account_id = wizard_state.account_id
        transport = wizard_state.transport
        event_path = wizard_state.event_path
        app_id_value = wizard_state.app_id_value
        app_secret_value = wizard_state.app_secret_value
        enabled = wizard_state.enabled
        allow_group_chats = wizard_state.allow_group_chats

    auto_start = (bool(getattr(args, "auto_start", False)) or use_wizard) and not getattr(args, "no_start", False)
    args.account_id = account_id
    existing_account = _find_feishu_account(existing_accounts, account_id=account_id)
    app_id_env_var = _resolved_feishu_secret_env_var(
        explicit_env_var=args.app_id_env_var,
        existing_account=existing_account,
        account_id=account_id,
        secret_key="app_id",
    )
    app_secret_env_var = _resolved_feishu_secret_env_var(
        explicit_env_var=args.app_secret_env_var,
        existing_account=existing_account,
        account_id=account_id,
        secret_key="app_secret",
    )

    account_payload = {
        "account_id": account_id,
        "surface": transport,
        "event_path": event_path,
        "secret_references": [
            _build_feishu_secret_reference(
                account_id=account_id,
                secret_key="app_id",
                env_var=app_id_env_var,
            ),
            _build_feishu_secret_reference(
                account_id=account_id,
                secret_key="app_secret",
                env_var=app_secret_env_var,
            ),
        ],
    }
    feishu_payload["accounts"] = _upsert_feishu_account(existing_accounts, account_payload)
    feishu_payload["surface"] = transport
    feishu_payload["event_path"] = event_path
    feishu_payload["enabled"] = enabled

    control_payload.pop("default_elephant_id", None)
    control_payload.pop("default_session_id", None)
    control_payload.pop("auto_create_elephant", None)
    if allow_group_chats:
        control_payload["allow_group_chats"] = True
    elif use_wizard:
        control_payload.pop("allow_group_chats", None)
    if control_payload:
        feishu_payload["control"] = control_payload
    else:
        feishu_payload.pop("control", None)

    adapters_payload["feishu"] = feishu_payload
    gateway_payload["adapters"] = adapters_payload
    manifest["gateway"] = gateway_payload
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)

    local_secret_path = _persist_gateway_local_secret_env(
        args.state_dir,
        {
            app_id_env_var: app_id_value,
            app_secret_env_var: app_secret_value,
        },
    )

    service = _build_feishu_service(args)
    print(f"Configured Feishu IM in {manifest_path}")
    print(f"Feishu account: {account_id}")
    print(f"Feishu transport: {transport}")
    if local_secret_path is not None:
        print(f"Local IM secret file: {local_secret_path}")

        print("Raw Feishu credentials were stored locally outside config.yaml.")
    if auto_start:
        print("Starting the configured Feishu bridge in the background...")
        try:
            _start_feishu_runtime_after_setup(args, transport=transport)
        except SystemExit as exc:
            print("Feishu setup completed, but the bridge did not stay running in the background.")
            print(f"Reason: {exc}")
            print("Next steps:")
            for step in _next_steps(service):
                print(f"- {step}")
            print("- Start it again with `elephant gateway feishu start --detach`.")
            return 1
        print("Feishu setup is complete.")
        print("Next steps:")
        print("- Check status with `elephant gateway feishu status`.")
        print(f"- Follow logs with `elephant gateway feishu logs {account_id} --follow`.")
        print(f"- Restart after changes with `elephant gateway feishu restart {account_id}`.")
        return 0
    print("next_steps:")
    for step in _next_steps(service):
        print(f"- {step}")
    print("- Start the configured bridge with `elephant gateway feishu start`.")
    return 0

def _run_remove_discord(args: Namespace) -> int:
    account_id = _resolved_cli_account_id(args)
    if account_id is None:
        raise SystemExit("remove requires <account-id>")

    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    discord_payload = _mapping_payload(adapters_payload.get("discord"), path="gateway.adapters.discord")
    accounts_value = discord_payload.get("accounts")
    if not isinstance(accounts_value, list):
        raise SystemExit("gateway.adapters.discord.accounts must be a JSON array")
    remaining_accounts, removed_account = _remove_account_payload(accounts_value, account_id=account_id)
    secret_path = _delete_gateway_local_secret_env(
        args.state_dir,
        _discord_account_secret_env_vars(removed_account),
    )
    if remaining_accounts:
        discord_payload["accounts"] = remaining_accounts
        discord_payload["enabled"] = True
        adapters_payload["discord"] = discord_payload
    else:
        adapters_payload.pop("discord", None)
    if adapters_payload:
        gateway_payload["adapters"] = adapters_payload
        manifest["gateway"] = gateway_payload
    else:
        manifest.pop("gateway", None)
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)
    print(f"Removed Discord account: {account_id}")
    print(f"Updated manifest: {manifest_path}")
    if secret_path is not None:
        print(f"Updated local IM secret file: {secret_path}")
    return 0

def _run_remove_feishu(args: Namespace) -> int:
    account_id = _resolved_cli_account_id(args)
    if account_id is None:
        raise SystemExit("remove requires <account-id>")

    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    feishu_payload = _mapping_payload(adapters_payload.get("feishu"), path="gateway.adapters.feishu")
    accounts_value = feishu_payload.get("accounts")
    if not isinstance(accounts_value, list):
        raise SystemExit("gateway.adapters.feishu.accounts must be a JSON array")
    remaining_accounts, removed_account = _remove_account_payload(accounts_value, account_id=account_id)
    secret_path = _delete_gateway_local_secret_env(
        args.state_dir,
        _feishu_account_secret_env_vars(removed_account),
    )
    if remaining_accounts:
        feishu_payload["accounts"] = remaining_accounts
        feishu_payload["enabled"] = True
        adapters_payload["feishu"] = feishu_payload
    else:
        adapters_payload.pop("feishu", None)
    if adapters_payload:
        gateway_payload["adapters"] = adapters_payload
        manifest["gateway"] = gateway_payload
    else:
        manifest.pop("gateway", None)
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)
    print(f"Removed Feishu account: {account_id}")
    print(f"Updated manifest: {manifest_path}")
    if secret_path is not None:
        print(f"Updated local IM secret file: {secret_path}")
    return 0

def _start_dingding_runtime_after_setup(args: Namespace, *, transport: str) -> int:
    start_args = Namespace(**vars(args))
    start_args.runtime_target = transport or "configured"
    start_args.account_id = None
    start_args.detach = True
    start_args.timeout = float(getattr(start_args, "timeout", 10.0) or 10.0)
    start_args.force = bool(getattr(start_args, "force", False))
    from apps.gateway.gateway_main_impl import _start_via_daemon
    return _start_via_daemon(start_args)

def _run_add_dingding(args: Namespace) -> int:
    _ensure_dingding_sdk_available(reason="DingDing setup")

    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    dingding_payload = _mapping_payload(adapters_payload.get("dingding"), path="gateway.adapters.dingding")
    control_payload = _mapping_payload(dingding_payload.get("control"), path="gateway.adapters.dingding.control")
    account_id = _resolved_cli_account_id(args) or DEFAULT_GATEWAY_ACCOUNT_ID
    accounts_value = dingding_payload.get("accounts")
    if accounts_value is None:
        existing_accounts: list[dict[str, object]] = []
    elif isinstance(accounts_value, list):
        existing_accounts = [{str(k): v for k, v in a.items()} for a in accounts_value if isinstance(a, Mapping)]
    else:
        raise SystemExit("gateway.adapters.dingding.accounts must be a JSON array")
    existing_account = _find_dingding_account(existing_accounts, account_id=account_id)
    transport = str(args.transport or "").strip() or str((existing_account or {}).get("surface") or "").strip() or str(dingding_payload.get("surface") or "").strip() or "stream"
    client_id_env_var = _resolved_dingding_secret_env_var(explicit_env_var=args.client_id_env_var, existing_account=existing_account, account_id=account_id, secret_key="client_id")
    client_secret_env_var = _resolved_dingding_secret_env_var(explicit_env_var=args.client_secret_env_var, existing_account=existing_account, account_id=account_id, secret_key="client_secret")
    robot_code_env_var = _resolved_dingding_secret_env_var(explicit_env_var=args.robot_code_env_var, existing_account=existing_account, account_id=account_id, secret_key="robot_code")
    client_id_value = str(args.client_id or "").strip()
    client_secret_value = str(args.client_secret or "").strip()
    robot_code_value = str(args.robot_code or "").strip()
    enabled = bool(args.enabled) if args.enabled is not None else True
    allow_group_chats = bool(args.allow_group_chats) or bool(control_payload.get("allow_group_chats") is True)
    use_wizard = bool(args.wizard) if args.wizard is not None else _interactive_shell_supported()
    if use_wizard:
        if not _print_gateway_dingding_wizard_intro():
            _print_gateway_setup_paused("DingDing"); return 0
        ws = _run_interactive_dingding_wizard(account_id=account_id, transport=transport, client_id_value=client_id_value, client_secret_value=client_secret_value, robot_code_value=robot_code_value, enabled=enabled, allow_group_chats=allow_group_chats)
        if ws is None:
            _print_gateway_setup_paused("DingDing"); return 0
        account_id, transport, client_id_value, client_secret_value, robot_code_value = ws.account_id, ws.transport, ws.client_id_value, ws.client_secret_value, ws.robot_code_value
        enabled, allow_group_chats = ws.enabled, ws.allow_group_chats
    auto_start = (bool(getattr(args, "auto_start", False)) or use_wizard) and not getattr(args, "no_start", False)
    args.account_id = account_id
    existing_account = _find_dingding_account(existing_accounts, account_id=account_id)
    client_id_env_var = _resolved_dingding_secret_env_var(explicit_env_var=args.client_id_env_var, existing_account=existing_account, account_id=account_id, secret_key="client_id")
    client_secret_env_var = _resolved_dingding_secret_env_var(explicit_env_var=args.client_secret_env_var, existing_account=existing_account, account_id=account_id, secret_key="client_secret")
    robot_code_env_var = _resolved_dingding_secret_env_var(explicit_env_var=args.robot_code_env_var, existing_account=existing_account, account_id=account_id, secret_key="robot_code")
    account_payload: dict[str, object] = {"account_id": account_id, "surface": transport, "enabled": True, "env": {"client_id": client_id_env_var, "client_secret": client_secret_env_var, "robot_code": robot_code_env_var}}
    local_secrets = {}
    if client_id_value: local_secrets[client_id_env_var] = client_id_value
    if client_secret_value: local_secrets[client_secret_env_var] = client_secret_value
    if robot_code_value: local_secrets[robot_code_env_var] = robot_code_value
    control_payload.pop("default_elephant_id", None)
    control_payload.pop("default_session_id", None)
    control_payload.pop("auto_create_elephant", None)
    if allow_group_chats: control_payload["allow_group_chats"] = True
    elif use_wizard: control_payload.pop("allow_group_chats", None)
    dingding_payload["accounts"] = _upsert_dingding_account(existing_accounts, account_payload)
    dingding_payload["surface"] = transport
    dingding_payload["enabled"] = enabled
    if control_payload: dingding_payload["control"] = control_payload
    else: dingding_payload.pop("control", None)
    adapters_payload["dingding"] = dingding_payload
    gateway_payload["adapters"] = adapters_payload
    manifest["gateway"] = gateway_payload
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)
    local_secret_path = _persist_gateway_local_secret_env(args.state_dir, local_secrets) if local_secrets else None
    print(f"Configured DingDing IM in {manifest_path}")
    print(f"DingDing account: {account_id}")
    print(f"DingDing transport: {transport}")
    if local_secret_path is not None: print(f"Local IM secret file: {local_secret_path}")
    if auto_start:
        print("Starting the configured DingDing bridge in the background...")
        try: _start_dingding_runtime_after_setup(args, transport=transport)
        except SystemExit: print("- Start it again with `elephant gateway dingding start --detach`."); return 1
        print("DingDing setup is complete."); return 0
    print("- Start the configured bridge with `elephant gateway dingding start`.")
    return 0

def _run_remove_dingding(args: Namespace) -> int:
    account_id = _resolved_cli_account_id(args)
    if account_id is None: raise SystemExit("remove requires <account-id>")

    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    dingding_payload = _mapping_payload(adapters_payload.get("dingding"), path="gateway.adapters.dingding")
    accounts_value = dingding_payload.get("accounts")
    if not isinstance(accounts_value, list): raise SystemExit("gateway.adapters.dingding.accounts must be a JSON array")
    remaining_accounts, removed_account = _remove_account_payload(accounts_value, account_id=account_id)
    secret_path = _delete_gateway_local_secret_env(args.state_dir, _dingding_account_secret_env_vars(removed_account))
    if remaining_accounts: dingding_payload["accounts"] = remaining_accounts; dingding_payload["enabled"] = True; adapters_payload["dingding"] = dingding_payload
    else: adapters_payload.pop("dingding", None)
    if adapters_payload: gateway_payload["adapters"] = adapters_payload; manifest["gateway"] = gateway_payload
    else: manifest.pop("gateway", None)
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)
    print(f"Removed DingDing account: {account_id}")
    print(f"Updated manifest: {manifest_path}")
    if secret_path is not None: print(f"Updated local IM secret file: {secret_path}")
    return 0

def _start_weixin_runtime_after_setup(args: Namespace, *, transport: str) -> int:
    start_args = Namespace(**vars(args))
    start_args.runtime_target = transport or "configured"
    start_args.account_id = None
    start_args.detach = True
    start_args.timeout = float(getattr(start_args, "timeout", 10.0) or 10.0)
    start_args.force = bool(getattr(start_args, "force", False))
    from apps.gateway.gateway_main_impl import _start_via_daemon
    return _start_via_daemon(start_args)

def _run_add_weixin(args: Namespace) -> int:
    from .weixin_support import check_weixin_requirements, qr_login, ILINK_BASE_URL
    if not check_weixin_requirements():
        _ensure_weixin_sdk_available(reason="WeChat setup")
        if not check_weixin_requirements():
            print("Failed to install WeChat dependencies. Run: pip install aiohttp cryptography")
            return 1


    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    weixin_payload = _mapping_payload(adapters_payload.get("weixin"), path="gateway.adapters.weixin")
    control_payload = _mapping_payload(weixin_payload.get("control"), path="gateway.adapters.weixin.control")
    account_id = _resolved_cli_account_id(args) or DEFAULT_GATEWAY_ACCOUNT_ID
    accounts_value = weixin_payload.get("accounts")
    if accounts_value is None:
        existing_accounts: list[dict[str, object]] = []
    elif isinstance(accounts_value, list):
        existing_accounts = [{str(k): v for k, v in a.items()} for a in accounts_value if isinstance(a, Mapping)]
    else:
        raise SystemExit("gateway.adapters.weixin.accounts must be a JSON array")

    # Run iLink QR login flow
    state_dir = str(args.state_dir) if args.state_dir else str(default_gateway_state_dir())
    print("Starting WeChat QR login...")
    credentials = asyncio.run(qr_login(state_dir))
    if credentials is None:
        print("WeChat QR login failed or timed out.")
        return 1

    resolved_account_id = credentials["account_id"]
    resolved_token = credentials["token"]
    resolved_base_url = credentials.get("base_url", ILINK_BASE_URL)
    resolved_user_id = credentials.get("user_id", "")

    enabled = bool(args.enabled) if args.enabled is not None else True
    allow_group_chats = bool(args.allow_group_chats) or bool(control_payload.get("allow_group_chats") is True)
    use_wizard = bool(args.wizard) if args.wizard is not None else _interactive_shell_supported()

    auto_start = (bool(getattr(args, "auto_start", False)) or use_wizard) and not getattr(args, "no_start", False)
    control_payload.pop("default_elephant_id", None)
    control_payload.pop("default_session_id", None)
    control_payload.pop("auto_create_elephant", None)
    if allow_group_chats: control_payload["allow_group_chats"] = True
    elif use_wizard: control_payload.pop("allow_group_chats", None)
    account_payload: dict[str, object] = {
        "account_id": resolved_account_id,
        "token": resolved_token,
        "base_url": resolved_base_url,
        "surface": "ilink",
        "enabled": True,
    }
    weixin_payload["accounts"] = _upsert_weixin_account(existing_accounts, account_payload)
    weixin_payload["surface"] = "ilink"
    weixin_payload["enabled"] = enabled
    if control_payload: weixin_payload["control"] = control_payload
    else: weixin_payload.pop("control", None)
    adapters_payload["weixin"] = weixin_payload
    gateway_payload["adapters"] = adapters_payload
    manifest["gateway"] = gateway_payload
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)
    print(f"Configured WeChat IM in {manifest_path}")
    print(f"WeChat account: {resolved_account_id}")
    print(f"WeChat transport: ilink")
    if auto_start:
        print("Starting the configured WeChat bridge in the background...")
        try: _start_weixin_runtime_after_setup(args, transport="ilink")
        except SystemExit: print("- Start it again with `elephant gateway weixin start --detach`."); return 1
        print("WeChat setup is complete."); return 0
    print("- Start the configured bridge with `elephant gateway weixin start`.")
    return 0

def _run_remove_weixin(args: Namespace) -> int:
    account_id = _resolved_cli_account_id(args)
    if account_id is None: raise SystemExit("remove requires <account-id>")

    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    weixin_payload = _mapping_payload(adapters_payload.get("weixin"), path="gateway.adapters.weixin")
    accounts_value = weixin_payload.get("accounts")
    if not isinstance(accounts_value, list): raise SystemExit("gateway.adapters.weixin.accounts must be a JSON array")
    remaining_accounts, removed_account = _remove_account_payload(accounts_value, account_id=account_id)
    secret_path = _delete_gateway_local_secret_env(args.state_dir, _weixin_account_secret_env_vars(removed_account))
    if remaining_accounts: weixin_payload["accounts"] = remaining_accounts; weixin_payload["enabled"] = True; adapters_payload["weixin"] = weixin_payload
    else: adapters_payload.pop("weixin", None)
    if adapters_payload: gateway_payload["adapters"] = adapters_payload; manifest["gateway"] = gateway_payload
    else: manifest.pop("gateway", None)
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)
    print(f"Removed WeChat account: {account_id}")
    print(f"Updated manifest: {manifest_path}")
    if secret_path is not None: print(f"Updated local IM secret file: {secret_path}")
    return 0

def _run_add_wecom(args: Namespace) -> int:
    _ensure_wecom_sdk_available(reason="WeCom setup")

    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    wecom_payload = _mapping_payload(adapters_payload.get("wecom"), path="gateway.adapters.wecom")
    control_payload = _mapping_payload(wecom_payload.get("control"), path="gateway.adapters.wecom.control")
    account_id = _resolved_cli_account_id(args) or DEFAULT_GATEWAY_ACCOUNT_ID
    accounts_value = wecom_payload.get("accounts")
    if accounts_value is None:
        existing_accounts: list[dict[str, object]] = []
    elif isinstance(accounts_value, list):
        existing_accounts = [{str(k): v for k, v in a.items()} for a in accounts_value if isinstance(a, Mapping)]
    else:
        raise SystemExit("gateway.adapters.wecom.accounts must be a JSON array")
    existing_account = _find_wecom_account(existing_accounts, account_id=account_id)
    transport = str(args.transport or "").strip() or str((existing_account or {}).get("surface") or "").strip() or str(wecom_payload.get("surface") or "").strip() or "websocket"
    bot_id_env_var = _resolved_wecom_secret_env_var(explicit_env_var=args.bot_id_env_var, existing_account=existing_account, account_id=account_id, secret_key="bot_id")
    secret_env_var = _resolved_wecom_secret_env_var(explicit_env_var=args.secret_env_var, existing_account=existing_account, account_id=account_id, secret_key="secret")
    bot_id_value = str(args.bot_id or "").strip()
    secret_value = str(args.secret or "").strip()
    enabled = bool(args.enabled) if args.enabled is not None else True
    allow_group_chats = bool(args.allow_group_chats) or bool(control_payload.get("allow_group_chats") is True)
    use_wizard = bool(args.wizard) if args.wizard is not None else _interactive_shell_supported()
    if use_wizard:
        if not _print_gateway_wecom_wizard_intro():
            _print_gateway_setup_paused("WeCom"); return 0
        ws = _run_interactive_wecom_wizard(account_id=account_id, transport=transport, bot_id_value=bot_id_value, secret_value=secret_value, enabled=enabled, allow_group_chats=allow_group_chats)
        if ws is None:
            _print_gateway_setup_paused("WeCom"); return 0
        account_id, transport, bot_id_value, secret_value = ws.account_id, ws.transport, ws.bot_id_value, ws.secret_value
        enabled, allow_group_chats = ws.enabled, ws.allow_group_chats
    auto_start = (bool(getattr(args, "auto_start", False)) or use_wizard) and not getattr(args, "no_start", False)
    args.account_id = account_id
    existing_account = _find_wecom_account(existing_accounts, account_id=account_id)
    bot_id_env_var = _resolved_wecom_secret_env_var(explicit_env_var=args.bot_id_env_var, existing_account=existing_account, account_id=account_id, secret_key="bot_id")
    secret_env_var = _resolved_wecom_secret_env_var(explicit_env_var=args.secret_env_var, existing_account=existing_account, account_id=account_id, secret_key="secret")
    account_payload: dict[str, object] = {"account_id": account_id, "surface": transport, "enabled": True, "env": {"bot_id": bot_id_env_var, "secret": secret_env_var}}
    local_secrets = {}
    if bot_id_value: local_secrets[bot_id_env_var] = bot_id_value
    if secret_value: local_secrets[secret_env_var] = secret_value
    control_payload.pop("default_elephant_id", None)
    control_payload.pop("default_session_id", None)
    control_payload.pop("auto_create_elephant", None)
    if allow_group_chats: control_payload["allow_group_chats"] = True
    elif use_wizard: control_payload.pop("allow_group_chats", None)
    wecom_payload["accounts"] = _upsert_wecom_account(existing_accounts, account_payload)
    wecom_payload["surface"] = transport
    wecom_payload["enabled"] = enabled
    if control_payload: wecom_payload["control"] = control_payload
    else: wecom_payload.pop("control", None)
    adapters_payload["wecom"] = wecom_payload
    gateway_payload["adapters"] = adapters_payload
    manifest["gateway"] = gateway_payload
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)
    local_secret_path = _persist_gateway_local_secret_env(args.state_dir, local_secrets) if local_secrets else None
    print(f"Configured WeCom IM in {manifest_path}")
    print(f"WeCom account: {account_id}")
    print(f"WeCom transport: {transport}")
    if local_secret_path is not None: print(f"Local IM secret file: {local_secret_path}")
    if auto_start:
        print("Starting the configured WeCom bridge in the background...")
        try: _start_wecom_runtime_after_setup(args, transport=transport)
        except SystemExit: print("- Start it again with `elephant gateway wecom start --detach`."); return 1
        print("WeCom setup is complete."); return 0
    print("- Start the configured bridge with `elephant gateway wecom start`.")
    return 0

def _run_remove_wecom(args: Namespace) -> int:
    account_id = _resolved_cli_account_id(args)
    if account_id is None: raise SystemExit("remove requires <account-id>")

    manifest = _load_profile_manifest(args.cli_state_dir)
    gateway_payload = _mapping_payload(manifest.get("gateway"), path="gateway")
    adapters_payload = _mapping_payload(gateway_payload.get("adapters"), path="gateway.adapters")
    wecom_payload = _mapping_payload(adapters_payload.get("wecom"), path="gateway.adapters.wecom")
    accounts_value = wecom_payload.get("accounts")
    if not isinstance(accounts_value, list): raise SystemExit("gateway.adapters.wecom.accounts must be a JSON array")
    remaining_accounts, removed_account = _remove_account_payload(accounts_value, account_id=account_id)
    secret_path = _delete_gateway_local_secret_env(args.state_dir, _wecom_account_secret_env_vars(removed_account))
    if remaining_accounts: wecom_payload["accounts"] = remaining_accounts; wecom_payload["enabled"] = True; adapters_payload["wecom"] = wecom_payload
    else: adapters_payload.pop("wecom", None)
    if adapters_payload: gateway_payload["adapters"] = adapters_payload; manifest["gateway"] = gateway_payload
    else: manifest.pop("gateway", None)
    manifest_path = _save_gateway_manifest(args.cli_state_dir, manifest)
    print(f"Removed WeCom account: {account_id}")
    print(f"Updated manifest: {manifest_path}")
    if secret_path is not None: print(f"Updated local IM secret file: {secret_path}")
    return 0


__all__ = ['_run_add_discord', '_start_discord_runtime_after_setup', '_start_feishu_runtime_after_setup', '_run_add_feishu', '_run_remove_discord', '_run_remove_feishu', '_start_dingding_runtime_after_setup', '_run_add_dingding', '_run_remove_dingding', '_start_weixin_runtime_after_setup', '_run_add_weixin', '_run_remove_weixin', '_run_add_wecom', '_run_remove_wecom']
