"""Gateway parser, account, and status helpers."""

from __future__ import annotations
import asyncio
from argparse import SUPPRESS, ArgumentParser, Namespace
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import getpass
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

import packages.operator.wizard as cli_wizard
from packages.operator.shell_stack import Align, Console, Group, Panel, RICH_AVAILABLE, Table, Text
from packages.operator.shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_LIGHT,
    BRAND_MUTED,
    resolve_elephant_version as _resolve_elephant_version,
    render_elephant_mark,
)
from apps.provider_runtime import load_runtime_local_secret_env
from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir
from packages.gateway_core import DEFAULT_GATEWAY_ACCOUNT_ID

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

def _secret_reference_id(*, account_id: str, secret_key: str) -> str:
    normalized_account = re.sub(r"[^a-z0-9]+", "-", account_id.strip().lower()).strip("-") or "default"
    normalized_key = secret_key.replace("_", "-")
    return f"secret-feishu-{normalized_account}-{normalized_key}"

def _default_feishu_secret_env_var(*, account_id: str, secret_key: str) -> str:
    if account_id == DEFAULT_GATEWAY_ACCOUNT_ID:
        if secret_key == "app_id":
            return DEFAULT_FEISHU_APP_ID_ENV
        if secret_key == "app_secret":
            return DEFAULT_FEISHU_APP_SECRET_ENV
    normalized_account = re.sub(r"[^A-Za-z0-9]+", "_", account_id.strip()).strip("_").upper() or "DEFAULT"
    suffix = "APP_ID" if secret_key == "app_id" else "APP_SECRET"
    return f"ELEPHANT_FEISHU_{normalized_account}_{suffix}"

def _build_feishu_secret_reference(
    *,
    account_id: str,
    secret_key: str,
    env_var: str,
) -> dict[str, object]:
    return {
        "reference_id": _secret_reference_id(account_id=account_id, secret_key=secret_key),
        "provider_id": FEISHU_ADAPTER_ID,
        "secret_name": secret_key,
        "secret_key": secret_key,
        "metadata": {"env_var": env_var},
    }

def _find_feishu_account(
    accounts: Sequence[Mapping[str, object]],
    *,
    account_id: str,
) -> Mapping[str, object] | None:
    for account in accounts:
        current_account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if current_account_id == account_id:
            return account
    return None

def _account_secret_env_var(
    account_payload: Mapping[str, object] | None,
    *,
    secret_key: str,
) -> str | None:
    if account_payload is None:
        return None
    env_payload = _mapping(account_payload.get("env")) or {}
    direct = env_payload.get(secret_key)
    if direct is not None:
        text = str(direct).strip()
        if text:
            return text
    secret_refs = account_payload.get("secret_references")
    if not isinstance(secret_refs, list):
        return None
    for item in secret_refs:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("secret_key") or "") != secret_key:
            continue
        metadata = _mapping(item.get("metadata")) or {}
        for key in ("env_var", "env", "environment_variable"):
            candidate = metadata.get(key)
            if candidate is None:
                continue
            text = str(candidate).strip()
            if text:
                return text
    return None

def _payload_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise SystemExit("allowlist fields must be JSON arrays when already present in gateway config")
    resolved: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            resolved.append(text)
    return list(dict.fromkeys(resolved))

def _resolved_cli_account_id(args: Namespace) -> str | None:
    raw_account_id = getattr(args, "account_id", None)
    direct = _optional_text(raw_account_id) if isinstance(raw_account_id, str) else None
    if direct is not None:
        return direct
    raw_account_id_flag = getattr(args, "account_id_flag", None)
    if not isinstance(raw_account_id_flag, str):
        return None
    return _optional_text(raw_account_id_flag)

def _default_dingding_secret_env_var(*, account_id: str, secret_key: str) -> str:
    defaults = {
        ("default", "client_id"): DEFAULT_DINGDING_CLIENT_ID_ENV,
        ("default", "client_secret"): DEFAULT_DINGDING_CLIENT_SECRET_ENV,
        ("default", "robot_code"): DEFAULT_DINGDING_ROBOT_CODE_ENV,
    }
    key = (DEFAULT_GATEWAY_ACCOUNT_ID if account_id == "default" else account_id, secret_key)
    if key in defaults:
        return defaults[key]
    normalized_account = re.sub(r"[^A-Za-z0-9]+", "_", account_id.strip()).strip("_").upper() or "DEFAULT"
    suffix = secret_key.upper()
    return f"ELEPHANT_DINGDING_{normalized_account}_{suffix}"


def _find_dingding_account(
    accounts: Sequence[Mapping[str, object]],
    *,
    account_id: str,
) -> Mapping[str, object] | None:
    for account in accounts:
        current_account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if current_account_id == account_id:
            return account
    return None


def _resolved_dingding_secret_env_var(
    *,
    explicit_env_var: object,
    existing_account: Mapping[str, object] | None,
    account_id: str,
    secret_key: str,
) -> str:
    if explicit_env_var is not None:
        text = str(explicit_env_var).strip()
        if text:
            return text
    if existing_account is not None:
        env_payload = _mapping(existing_account.get("env"))
        if env_payload is not None:
            candidate = env_payload.get(secret_key)
            if candidate is not None:
                text = str(candidate).strip()
                if text:
                    return text
    return _default_dingding_secret_env_var(account_id=account_id, secret_key=secret_key)


def _upsert_dingding_account(
    accounts: Sequence[Mapping[str, object]],
    account_payload: Mapping[str, object],
) -> list[dict[str, object]]:
    target_account_id = str(account_payload.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
    resolved = [dict(account) for account in accounts]
    for index, account in enumerate(resolved):
        account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if account_id == target_account_id:
            resolved[index] = dict(account_payload)
            return resolved
    resolved.append(dict(account_payload))
    return resolved


def _dingding_account_secret_env_vars(account_payload: Mapping[str, object]) -> tuple[str, ...]:
    env_payload = _mapping(account_payload.get("env")) or {}
    env_vars: list[str] = []
    for key in ("client_id", "client_secret", "robot_code"):
        env_var = _optional_text(env_payload.get(key))
        if env_var is not None:
            env_vars.append(env_var)
    return tuple(dict.fromkeys(env_vars))


def _default_discord_bot_token_env_var(*, account_id: str) -> str:
    if account_id == DEFAULT_GATEWAY_ACCOUNT_ID:
        return DEFAULT_DISCORD_BOT_TOKEN_ENV
    normalized_account = re.sub(r"[^A-Za-z0-9]+", "_", account_id.strip()).strip("_").upper() or "DEFAULT"
    return f"ELEPHANT_DISCORD_{normalized_account}_BOT_TOKEN"

def _find_discord_account(
    accounts: Sequence[Mapping[str, object]],
    *,
    account_id: str,
) -> Mapping[str, object] | None:
    for account in accounts:
        current_account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if current_account_id == account_id:
            return account
    return None

def _resolved_discord_bot_token_env_var(
    *,
    explicit_env_var: object,
    existing_account: Mapping[str, object] | None,
    account_id: str,
) -> str:
    if explicit_env_var is not None:
        text = str(explicit_env_var).strip()
        if text:
            return text
    env_payload = _mapping(existing_account.get("env")) if existing_account is not None else None
    if env_payload is not None:
        candidate = env_payload.get("bot_token")
        if candidate is not None:
            text = str(candidate).strip()
            if text:
                return text
    return _default_discord_bot_token_env_var(account_id=account_id)

def _is_unconfigured_default_discord_account(
    account_payload: Mapping[str, object],
    *,
    state_dir: Path,
    cli_state_dir: Path | None = None,
) -> bool:
    account_id = str(account_payload.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
    if account_id != DEFAULT_GATEWAY_ACCOUNT_ID:
        return False
    env_var = _account_secret_env_var(account_payload, secret_key="bot_token")
    if env_var is None or env_var != DEFAULT_DISCORD_BOT_TOKEN_ENV:
        return False
    if _payload_string_list(account_payload.get("allow_guild_ids")):
        return False
    if _payload_string_list(account_payload.get("allow_channel_ids")):
        return False
    runtime_payload = _mapping(account_payload.get("runtime")) or {}
    if runtime_payload:
        return False
    runtime_environ = _gateway_runtime_environ(state_dir, cli_state_dir=cli_state_dir)
    if str(runtime_environ.get(DEFAULT_DISCORD_BOT_TOKEN_ENV) or "").strip():
        return False
    if str(runtime_environ.get(LEGACY_DISCORD_BOT_TOKEN_ENV) or "").strip():
        return False
    return True

def _upsert_discord_account(
    accounts: Sequence[Mapping[str, object]],
    account_payload: Mapping[str, object],
    *,
    state_dir: Path | None = None,
    cli_state_dir: Path | None = None,
) -> list[dict[str, object]]:
    target_account_id = str(account_payload.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
    if (
        target_account_id != DEFAULT_GATEWAY_ACCOUNT_ID
        and state_dir is not None
        and len(accounts) == 1
        and _is_unconfigured_default_discord_account(
            accounts[0],
            state_dir=state_dir,
            cli_state_dir=cli_state_dir,
        )
    ):
        return [{str(key): value for key, value in account_payload.items()}]
    updated: list[dict[str, object]] = []
    replaced = False
    for account in accounts:
        current_account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if current_account_id == target_account_id:
            updated.append({str(key): value for key, value in account_payload.items()})
            replaced = True
        else:
            updated.append({str(key): value for key, value in account.items()})
    if not replaced:
        updated.append({str(key): value for key, value in account_payload.items()})
    return updated

def _resolved_feishu_secret_env_var(
    *,
    explicit_env_var: object,
    existing_account: Mapping[str, object] | None,
    account_id: str,
    secret_key: str,
) -> str:
    if explicit_env_var is not None:
        text = str(explicit_env_var).strip()
        if text:
            return text
    return _account_secret_env_var(existing_account, secret_key=secret_key) or _default_feishu_secret_env_var(
        account_id=account_id,
        secret_key=secret_key,
    )

def _upsert_feishu_account(
    accounts: Sequence[Mapping[str, object]],
    account_payload: Mapping[str, object],
) -> list[dict[str, object]]:
    target_account_id = str(account_payload.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
    resolved = [dict(account) for account in accounts]
    for index, account in enumerate(resolved):
        account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if account_id == target_account_id:
            resolved[index] = dict(account_payload)
            return resolved
    resolved.append(dict(account_payload))
    return resolved

def _remove_account_payload(
    accounts: Sequence[Mapping[str, object]],
    *,
    account_id: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    updated: list[dict[str, object]] = []
    removed: dict[str, object] | None = None
    for account in accounts:
        current_account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if current_account_id == account_id:
            removed = {str(key): value for key, value in account.items()}
            continue
        updated.append({str(key): value for key, value in account.items()})
    if removed is None:
        raise SystemExit(f"unknown gateway account: {account_id}")
    return updated, removed

def _discord_account_secret_env_vars(account_payload: Mapping[str, object]) -> tuple[str, ...]:
    env_payload = _mapping(account_payload.get("env")) or {}
    env_var = _optional_text(env_payload.get("bot_token"))
    return (env_var,) if env_var is not None else ()

def _feishu_account_secret_env_vars(account_payload: Mapping[str, object]) -> tuple[str, ...]:
    env_vars: list[str] = []
    env_payload = _mapping(account_payload.get("env")) or {}
    for key in ("app_id", "app_secret"):
        env_var = _optional_text(env_payload.get(key))
        if env_var is not None:
            env_vars.append(env_var)
    secret_refs = account_payload.get("secret_references")
    if isinstance(secret_refs, list):
        for item in secret_refs:
            if not isinstance(item, Mapping):
                continue
            metadata = _mapping(item.get("metadata")) or {}
            env_var = _optional_text(
                metadata.get("env_var") or metadata.get("env") or metadata.get("environment_variable")
            )
            if env_var is not None:
                env_vars.append(env_var)
    return tuple(dict.fromkeys(env_vars))


def _find_weixin_account(
    accounts: Sequence[Mapping[str, object]],
    *,
    account_id: str,
) -> Mapping[str, object] | None:
    for account in accounts:
        current_account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if current_account_id == account_id:
            return account
    return None


def _upsert_weixin_account(
    accounts: Sequence[Mapping[str, object]],
    account_payload: Mapping[str, object],
) -> list[dict[str, object]]:
    target_account_id = str(account_payload.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
    resolved = [dict(account) for account in accounts]
    for index, account in enumerate(resolved):
        account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if account_id == target_account_id:
            resolved[index] = dict(account_payload)
            return resolved
    resolved.append(dict(account_payload))
    return resolved


def _weixin_account_secret_env_vars(account_payload: Mapping[str, object]) -> tuple[str, ...]:
    return ()


def _find_wecom_account(
    accounts: Sequence[Mapping[str, object]],
    *,
    account_id: str,
) -> Mapping[str, object] | None:
    for account in accounts:
        current_account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if current_account_id == account_id:
            return account
    return None


def _upsert_wecom_account(
    accounts: Sequence[Mapping[str, object]],
    account_payload: Mapping[str, object],
) -> list[dict[str, object]]:
    target_account_id = str(account_payload.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
    resolved = [dict(account) for account in accounts]
    for index, account in enumerate(resolved):
        account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        if account_id == target_account_id:
            resolved[index] = dict(account_payload)
            return resolved
    resolved.append(dict(account_payload))
    return resolved


def _wecom_account_secret_env_vars(account_payload: Mapping[str, object]) -> tuple[str, ...]:
    env_payload = _mapping(account_payload.get("env")) or {}
    env_vars: list[str] = []
    for key in ("bot_id", "secret"):
        env_var = _optional_text(env_payload.get(key))
        if env_var is not None:
            env_vars.append(env_var)
    return tuple(dict.fromkeys(env_vars))


def _default_wecom_secret_env_var(*, account_id: str, secret_key: str) -> str:
    if account_id == DEFAULT_GATEWAY_ACCOUNT_ID:
        if secret_key == "bot_id":
            return DEFAULT_WECOM_BOT_ID_ENV
        if secret_key == "secret":
            return DEFAULT_WECOM_SECRET_ENV
    normalized_account = re.sub(r"[^A-Za-z0-9]+", "_", account_id.strip()).strip("_").upper() or "DEFAULT"
    suffix = secret_key.upper()
    return f"ELEPHANT_WECOM_{normalized_account}_{suffix}"


def _resolved_wecom_secret_env_var(
    *,
    explicit_env_var: object,
    existing_account: Mapping[str, object] | None,
    account_id: str,
    secret_key: str,
) -> str:
    if explicit_env_var is not None:
        text = str(explicit_env_var).strip()
        if text:
            return text
    if existing_account is not None:
        env_payload = _mapping(existing_account.get("env"))
        if env_payload is not None:
            candidate = env_payload.get(secret_key)
            if candidate is not None:
                text = str(candidate).strip()
                if text:
                    return text
    return _default_wecom_secret_env_var(account_id=account_id, secret_key=secret_key)

def _resolved_defaults(
    *,
    default_state_dir_override: Path | None = None,
    default_control_state_dir_override: Path | None = None,
) -> dict[str, Path]:
    return {
        "state_dir": default_state_dir_override or default_gateway_state_dir(),
        "cli_state_dir": default_control_state_dir_override or default_cli_state_dir(),
    }

def _add_common_gateway_options(parser: ArgumentParser, *, defaults: dict[str, Path]) -> None:
    parser.add_argument("--state-dir", type=Path, default=defaults["state_dir"])
    parser.add_argument("--cli-state-dir", type=Path, default=defaults["cli_state_dir"])

def _add_http_server_options(parser: ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)

def _add_optional_account_argument(parser: ArgumentParser, *, help_text: str) -> None:
    parser.add_argument("account_id", nargs="?", help=help_text)

def _add_required_account_argument(parser: ArgumentParser, *, help_text: str) -> None:
    parser.add_argument("account_id", nargs="?", help=help_text)


__all__ = ['_secret_reference_id', '_default_feishu_secret_env_var', '_build_feishu_secret_reference', '_find_feishu_account', '_account_secret_env_var', '_payload_string_list', '_resolved_cli_account_id', '_default_dingding_secret_env_var', '_find_dingding_account', '_resolved_dingding_secret_env_var', '_upsert_dingding_account', '_dingding_account_secret_env_vars', '_default_discord_bot_token_env_var', '_find_discord_account', '_resolved_discord_bot_token_env_var', '_is_unconfigured_default_discord_account', '_upsert_discord_account', '_resolved_feishu_secret_env_var', '_upsert_feishu_account', '_remove_account_payload', '_discord_account_secret_env_vars', '_feishu_account_secret_env_vars', '_find_weixin_account', '_upsert_weixin_account', '_weixin_account_secret_env_vars', '_find_wecom_account', '_upsert_wecom_account', '_wecom_account_secret_env_vars', '_default_wecom_secret_env_var', '_resolved_wecom_secret_env_var', '_resolved_defaults', '_add_common_gateway_options', '_add_http_server_options', '_add_optional_account_argument', '_add_required_account_argument']
