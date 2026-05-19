"""Discord gateway bootstrap, service description, and delivery wiring."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


LOGGER = logging.getLogger(__name__)

from packages.gateway_core import (
    GatewayExchange,
)

from .runtime import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayApp,
)

DEFAULT_DISCORD_BOT_TOKEN_ENV = "ELEPHANT_DISCORD_BOT_TOKEN"
LEGACY_DISCORD_BOT_TOKEN_ENV = "DISCORD_BOT_TOKEN"
SUPPORTED_DISCORD_TRANSPORTS = ("gateway",)
REQUIRED_DISCORD_INTENTS = ("guilds", "messages", "message_content")
PRIVILEGED_DISCORD_INTENTS = ("message_content",)
DISCORD_PY_PIP_SPEC = "discord.py>=2.6,<3"
DISCORD_MESSAGE_CONTENT_LIMIT = 2000
DISCORD_FENCE_SPLIT_RESERVE = 32
DISCORD_ATTACHMENT_FALLBACK_THRESHOLD = 8000
DISCORD_ATTACHMENT_FALLBACK_FILENAME = "reply.md"

DiscordClientFactory = Callable[[Any, object], object]
DiscordDeliveryTransportFactory = Callable[[object, Any], "DiscordDeliveryTransport"]


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _normalize_transport(value: str | None) -> str:
    normalized = str(value or "gateway").strip().lower().replace("_", "-")
    if normalized in {"gateway", "discord-gateway"}:
        return "gateway"
    raise ValueError(f"discord transport must be one of {', '.join(SUPPORTED_DISCORD_TRANSPORTS)}")


def _string_list(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a JSON array")
    resolved: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            resolved.append(text)
    return tuple(dict.fromkeys(resolved))


def _discord_py_dependency_status() -> str:
    return "installed" if importlib.util.find_spec("discord") is not None else "missing_optional_dependency"


def _load_discord_sdk(discord_module: Any | None = None) -> Any:
    if discord_module is not None:
        return discord_module
    try:
        import discord  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised by runtime preflight
        raise RuntimeError(
            "Discord gateway transport requires the bundled dependency "
            "'discord.py'. Reinstall Elephant Agent or add the package to your environment if it is missing."
        ) from exc
    return discord


def _default_discord_client_factory(discord_module: Any, intents: object) -> object:
    client_type = getattr(discord_module, "Client", None)
    if client_type is None:
        raise RuntimeError("discord.py Client is unavailable")
    return client_type(intents=intents)


def _default_discord_delivery_transport_factory(
    client: object,
    discord_module: Any,
) -> "DiscordPyDeliveryTransport":
    from .discord_transport import DiscordPyDeliveryTransport

    return DiscordPyDeliveryTransport(client=client, discord_module=discord_module)


def _snowflake(value: object) -> int | str:
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return text


def _discord_intents(discord_module: Any) -> object:
    intents_type = getattr(discord_module, "Intents", None)
    if intents_type is None or not hasattr(intents_type, "none"):
        raise RuntimeError("discord.py Intents.none() is unavailable")
    intents = intents_type.none()
    for field_name in REQUIRED_DISCORD_INTENTS:
        if not hasattr(intents, field_name):
            raise RuntimeError(f"discord.py intents object is missing '{field_name}'")
        setattr(intents, field_name, True)
    return intents


async def _maybe_await(result: object) -> object:
    if inspect.isawaitable(result):
        return await result
    return result


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _split_discord_message_content(
    content: str,
    *,
    limit: int = DISCORD_MESSAGE_CONTENT_LIMIT,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("discord message content limit must be positive")
    if len(content) <= limit:
        return (content,)
    chunks: list[str] = []
    remaining = content
    preferred_split_floor = max(1, limit // 2)
    while len(remaining) > limit:
        boundary = remaining.rfind("\n", 0, limit)
        if boundary < preferred_split_floor:
            boundary = remaining.rfind(" ", 0, limit)
        cut = limit if boundary < preferred_split_floor else boundary + 1
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining or not chunks:
        chunks.append(remaining)
    return tuple(chunks)


def _discord_fence_state(content: str) -> str | None:
    open_fence: str | None = None
    for raw_line in content.split("\n"):
        stripped = raw_line.strip()
        if not stripped.startswith("```"):
            continue
        if open_fence is None:
            open_fence = stripped
        else:
            open_fence = None
    return open_fence


def _rebalance_discord_fenced_chunks(
    chunks: tuple[str, ...],
    *,
    limit: int = DISCORD_MESSAGE_CONTENT_LIMIT,
) -> tuple[str, ...]:
    if len(chunks) <= 1 or not any("```" in chunk for chunk in chunks):
        return chunks
    balanced: list[str] = []
    reopened_fence: str | None = None
    for index, original_chunk in enumerate(chunks):
        chunk = original_chunk if reopened_fence is None else f"{reopened_fence}\n{original_chunk}"
        reopened_fence = _discord_fence_state(chunk)
        if reopened_fence is not None and index < len(chunks) - 1:
            chunk = f"{chunk}\n```"
        if len(chunk) > limit:
            raise RuntimeError("discord fenced content chunk exceeds message content limit")
        balanced.append(chunk)
    if reopened_fence is not None and balanced:
        final_chunk = f"{balanced[-1]}\n```"
        if len(final_chunk) > limit:
            raise RuntimeError("discord fenced content chunk exceeds message content limit")
        balanced[-1] = final_chunk
    return tuple(balanced)


def _read_runtime_record(path: Path) -> Mapping[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_is_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _managed_runtime_state(*, pid_path: Path, record_path: Path) -> Mapping[str, object]:
    record = dict(_read_runtime_record(record_path) or {})
    pid_from_file = _read_pid(pid_path)
    pid_from_record = _coerce_int(record.get("pid"))
    pid = pid_from_file if pid_from_file is not None else pid_from_record
    pid_active = _pid_is_running(pid)
    record_status = _optional_text(record.get("status")) or "stopped"
    if pid_active:
        runtime_status = "running"
    elif record_status == "failed":
        runtime_status = "failed"
    else:
        runtime_status = "stopped"
    return {
        "record": record,
        "pid": pid,
        "pid_active": pid_active,
        "stale_pid": pid_from_file is not None and not pid_active,
        "runtime_status": runtime_status,
        "recorded_status": record_status,
    }


@dataclass(frozen=True, slots=True)
class DiscordGatewayAccountConfig:
    account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID
    bot_token_env_var: str = DEFAULT_DISCORD_BOT_TOKEN_ENV
    surface: str = "gateway"
    enabled: bool = True
    allow_guild_ids: tuple[str, ...] = ()
    allow_channel_ids: tuple[str, ...] = ()
    runtime_metadata: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscordResolvedAccount:
    account_id: str
    bot_token: str
    config: DiscordGatewayAccountConfig


@dataclass(frozen=True, slots=True)
class DiscordGatewayEventResult:
    exchange: GatewayExchange | None
    response_body: Mapping[str, object]
    delivery_request: Mapping[str, object] | None = None
    delivery_response: Mapping[str, object] | None = None


@runtime_checkable
class DiscordDeliveryTransport(Protocol):
    async def send_request(
        self,
        request: Mapping[str, object],
        *,
        account: DiscordResolvedAccount,
    ) -> Mapping[str, object]:
        """Send one normalized Discord outbound request."""


def load_discord_gateway_accounts(
    app: GatewayApp,
    *,
    respect_enabled: bool = True,
    include_disabled: bool = False,
) -> tuple[DiscordGatewayAccountConfig, ...]:
    manifest = app.loaded_profile.manifest if app.loaded_profile is not None else {}
    gateway_payload = _mapping(manifest.get("gateway")) or {}
    adapters_payload = _mapping(gateway_payload.get("adapters")) or {}
    discord_payload = _mapping(adapters_payload.get("discord"))
    if respect_enabled and discord_payload is not None and discord_payload.get("enabled") is False:
        return ()

    default_surface = _normalize_transport((discord_payload or {}).get("surface"))
    accounts_payload = (discord_payload or {}).get("accounts")
    if isinstance(accounts_payload, list) and accounts_payload:
        resolved: list[DiscordGatewayAccountConfig] = []
        for index, account_payload in enumerate(accounts_payload):
            account_mapping = _mapping(account_payload)
            if account_mapping is None:
                raise ValueError("gateway.adapters.discord.accounts entries must be JSON objects")
            account_enabled = _coerce_bool(account_mapping.get("enabled"), default=True)
            if not include_disabled and not account_enabled:
                continue
            env_payload = _mapping(account_mapping.get("env")) or {}
            runtime_payload = _mapping(account_mapping.get("runtime")) or {}
            resolved.append(
                DiscordGatewayAccountConfig(
                    account_id=str(account_mapping.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
                    bot_token_env_var=str(env_payload.get("bot_token") or DEFAULT_DISCORD_BOT_TOKEN_ENV),
                    surface=str(account_mapping.get("surface") or default_surface),
                    enabled=account_enabled,
                    allow_guild_ids=_string_list(
                        account_mapping.get("allow_guild_ids"),
                        field_name="gateway.adapters.discord.accounts[].allow_guild_ids",
                    ),
                    allow_channel_ids=_string_list(
                        account_mapping.get("allow_channel_ids"),
                        field_name="gateway.adapters.discord.accounts[].allow_channel_ids",
                    ),
                    runtime_metadata=dict(runtime_payload),
                    metadata={"manifest_index": index},
                )
            )
        return tuple(resolved)

    return (DiscordGatewayAccountConfig(surface=default_surface),)


def resolve_discord_account(
    config: DiscordGatewayAccountConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> DiscordResolvedAccount:
    env = environ or os.environ
    bot_token = str(env.get(config.bot_token_env_var) or "").strip()
    if not bot_token and config.bot_token_env_var == DEFAULT_DISCORD_BOT_TOKEN_ENV:
        bot_token = str(env.get(LEGACY_DISCORD_BOT_TOKEN_ENV) or "").strip()
    if not bot_token:
        raise LookupError(f"discord account '{config.account_id}' requires {config.bot_token_env_var}")
    return DiscordResolvedAccount(
        account_id=config.account_id,
        bot_token=bot_token,
        config=config,
    )


__all__ = [name for name in globals() if not name.startswith("__")]
