"""Account discovery and credential resolution for the Feishu gateway."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import os
from typing import Any

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
)

from apps.provider_runtime import secret_reference_from_payload
from packages.auth import (
    AuthProfile,
    EnvironmentSecretStore,
    ProfileCredentialResolver,
    SecretReference,
)

from .runtime import FEISHU_ADAPTER_ID, GatewayApp

DEFAULT_FEISHU_APP_ID_ENV = "ELEPHANT_FEISHU_APP_ID"
DEFAULT_FEISHU_APP_SECRET_ENV = "ELEPHANT_FEISHU_APP_SECRET"
LEGACY_FEISHU_APP_ID_ENV = "FEISHU_APP_ID"
LEGACY_FEISHU_APP_SECRET_ENV = "FEISHU_APP_SECRET"
DEFAULT_FEISHU_BASE_URL = "https://open.feishu.cn"
DEFAULT_FEISHU_EVENT_PATH = "/feishu/events"
DEFAULT_FEISHU_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
SUPPORTED_FEISHU_TRANSPORTS = ("long-connection",)
FEISHU_SDK_PIP_SPEC = "lark-oapi>=1.5.3,<2"
DEFAULT_FEISHU_INBOUND_EVENT_RETENTION_SECONDS = 60 * 60 * 24 * 3
DEFAULT_FEISHU_INBOUND_EVENT_MAX_RECORDS = 4096
DEFAULT_FEISHU_ASYNC_JOB_RETENTION_SECONDS = DEFAULT_FEISHU_INBOUND_EVENT_RETENTION_SECONDS
DEFAULT_FEISHU_ASYNC_JOB_MAX_RECORDS = DEFAULT_FEISHU_INBOUND_EVENT_MAX_RECORDS
DEFAULT_FEISHU_ASYNC_WORKER_COUNT = 2
DEFAULT_FEISHU_ASYNC_FAILURE_HISTORY = 5
DEFAULT_FEISHU_PLACEHOLDER_BODY = "已收到，正在处理中..."
DEFAULT_FEISHU_FAILURE_BODY = "处理失败，请稍后重试。"

HttpJsonRequester = Callable[[str, str, Mapping[str, object], Mapping[str, str]], Mapping[str, object]]
FeishuWSClientFactory = Callable[[Any, str, str, object, object | None], object]

LOGGER = logging.getLogger(__name__)

from .feishu_support import *  # noqa: F401,F403


def _feishu_event_identifiers(
    payload: Mapping[str, object],
) -> tuple[str | None, str | None]:
    header = _mapping(payload.get("header")) or {}
    event = _mapping(payload.get("event")) or {}
    message = _mapping(event.get("message")) or {}
    return (
        _optional_text(header.get("event_id")),
        _optional_text(message.get("message_id")),
    )


def _feishu_secret_reference_from_payload(
    payload: Mapping[str, object],
    *,
    account_id: str,
) -> SecretReference:
    normalized_payload = dict(payload)
    secret_key = str(normalized_payload.get("secret_key") or "")
    if not secret_key:
        raise ValueError(f"feishu account '{account_id}' secret_references entries must declare secret_key")
    normalized_payload.setdefault("provider_id", FEISHU_ADAPTER_ID)
    normalized_payload.setdefault("secret_name", secret_key)
    reference = secret_reference_from_payload(normalized_payload)
    if reference.provider_id != FEISHU_ADAPTER_ID:
        raise ValueError(f"feishu account '{account_id}' secret reference provider_id must be {FEISHU_ADAPTER_ID}")
    return reference


def _secret_reference_env_alias(
    references: tuple[SecretReference, ...],
    secret_key: str,
) -> str | None:
    for reference in references:
        if reference.secret_key != secret_key:
            continue
        candidates = reference.env_var_candidates()
        if candidates:
            return candidates[0]
    return None


def _credential_env_vars(config: FeishuGatewayAccountConfig) -> tuple[str, ...]:
    if config.secret_references:
        return tuple(
            dict.fromkeys(
                env_var for reference in config.secret_references for env_var in reference.env_var_candidates()
            )
        )
    env_vars = [config.app_id_env_var, config.app_secret_env_var]
    return tuple(dict.fromkeys(value for value in env_vars if value))


def _feishu_account_profile(config: FeishuGatewayAccountConfig) -> AuthProfile:
    return AuthProfile(
        profile_id=f"gateway.feishu.{config.account_id}",
        provider_id=FEISHU_ADAPTER_ID,
        transport_id="gateway-feishu",
        auth_method="secret_reference",
        provider_kind="service",
        secret_references=config.secret_references,
        metadata={
            "surface": "gateway.feishu",
            "account_id": config.account_id,
        },
    )


def load_feishu_gateway_accounts(
    app: GatewayApp,
    *,
    respect_enabled: bool = True,
) -> tuple[FeishuGatewayAccountConfig, ...]:
    manifest = app.loaded_profile.manifest if app.loaded_profile is not None else {}
    gateway_payload = _mapping(manifest.get("gateway")) or {}
    adapters_payload = _mapping(gateway_payload.get("adapters")) or {}
    feishu_payload = _mapping(adapters_payload.get("feishu"))
    if respect_enabled and feishu_payload is not None and feishu_payload.get("enabled") is False:
        return ()

    default_surface = _normalize_configured_transport((feishu_payload or {}).get("surface"))
    default_event_path = _normalize_path((feishu_payload or {}).get("event_path"))
    default_base_url = str((feishu_payload or {}).get("base_url") or DEFAULT_FEISHU_BASE_URL)
    default_token_path = _normalize_path((feishu_payload or {}).get("token_path") or DEFAULT_FEISHU_TOKEN_PATH)
    accounts_payload = (feishu_payload or {}).get("accounts")
    if isinstance(accounts_payload, list) and accounts_payload:
        resolved: list[FeishuGatewayAccountConfig] = []
        for index, account_payload in enumerate(accounts_payload):
            account_mapping = _mapping(account_payload)
            if account_mapping is None:
                raise ValueError("gateway.adapters.feishu.accounts entries must be JSON objects")
            account_id = str(account_mapping.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
            env_payload = _mapping(account_mapping.get("env")) or {}
            secret_references_payload = account_mapping.get("secret_references")
            if secret_references_payload is None:
                secret_references = ()
            elif isinstance(secret_references_payload, list):
                secret_references = tuple(
                    _feishu_secret_reference_from_payload(item, account_id=account_id)
                    for item in secret_references_payload
                    if isinstance(item, Mapping)
                )
                if len(secret_references) != len(secret_references_payload):
                    raise ValueError(f"feishu account '{account_id}' secret_references entries must be JSON objects")
            else:
                raise ValueError(f"feishu account '{account_id}' secret_references must be a JSON array")
            app_id_env_var = str(
                env_payload.get("app_id")
                or _secret_reference_env_alias(secret_references, "app_id")
                or ("" if secret_references else DEFAULT_FEISHU_APP_ID_ENV)
            )
            app_secret_env_var = str(
                env_payload.get("app_secret")
                or _secret_reference_env_alias(secret_references, "app_secret")
                or ("" if secret_references else DEFAULT_FEISHU_APP_SECRET_ENV)
            )
            resolved.append(
                FeishuGatewayAccountConfig(
                    account_id=account_id,
                    app_id_env_var=app_id_env_var,
                    app_secret_env_var=app_secret_env_var,
                    secret_references=secret_references,
                    surface=str(account_mapping.get("surface") or default_surface),
                    event_path=_normalize_path(account_mapping.get("event_path") or default_event_path),
                    base_url=str(account_mapping.get("base_url") or default_base_url),
                    token_path=_normalize_path(account_mapping.get("token_path") or default_token_path),
                    metadata={"manifest_index": index},
                )
            )
        return tuple(resolved)

    return (
        FeishuGatewayAccountConfig(
            event_path=default_event_path,
            surface=default_surface,
            base_url=default_base_url,
            token_path=default_token_path,
        ),
    )


def resolve_feishu_account(
    config: FeishuGatewayAccountConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> FeishuResolvedAccount:
    env = environ or os.environ
    if config.secret_references:
        credentials = (
            ProfileCredentialResolver(EnvironmentSecretStore(env)).resolve(_feishu_account_profile(config)).as_mapping()
        )
        app_id = str(credentials.get("app_id") or "")
        app_secret = str(credentials.get("app_secret") or "")
        if not app_id or not app_secret:
            raise LookupError(
                f"feishu account '{config.account_id}' secret references must resolve app_id and app_secret"
            )
        return FeishuResolvedAccount(
            account_id=config.account_id,
            app_id=app_id,
            app_secret=app_secret,
            config=config,
        )

    app_id = str(env.get(config.app_id_env_var) or "")
    app_secret = str(env.get(config.app_secret_env_var) or "")
    if not app_id and config.app_id_env_var == DEFAULT_FEISHU_APP_ID_ENV:
        app_id = str(env.get(LEGACY_FEISHU_APP_ID_ENV) or "")
    if not app_secret and config.app_secret_env_var == DEFAULT_FEISHU_APP_SECRET_ENV:
        app_secret = str(env.get(LEGACY_FEISHU_APP_SECRET_ENV) or "")
    if not app_id or not app_secret:
        raise LookupError(
            f"feishu account '{config.account_id}' requires {config.app_id_env_var} and {config.app_secret_env_var}"
        )
    return FeishuResolvedAccount(
        account_id=config.account_id,
        app_id=app_id,
        app_secret=app_secret,
        config=config,
    )


__all__ = [
    "DEFAULT_FEISHU_APP_ID_ENV",
    "DEFAULT_FEISHU_APP_SECRET_ENV",
    "LEGACY_FEISHU_APP_ID_ENV",
    "LEGACY_FEISHU_APP_SECRET_ENV",
    "DEFAULT_FEISHU_BASE_URL",
    "DEFAULT_FEISHU_EVENT_PATH",
    "DEFAULT_FEISHU_TOKEN_PATH",
    "SUPPORTED_FEISHU_TRANSPORTS",
    "FEISHU_SDK_PIP_SPEC",
    "DEFAULT_FEISHU_INBOUND_EVENT_RETENTION_SECONDS",
    "DEFAULT_FEISHU_INBOUND_EVENT_MAX_RECORDS",
    "DEFAULT_FEISHU_ASYNC_JOB_RETENTION_SECONDS",
    "DEFAULT_FEISHU_ASYNC_JOB_MAX_RECORDS",
    "DEFAULT_FEISHU_ASYNC_WORKER_COUNT",
    "DEFAULT_FEISHU_ASYNC_FAILURE_HISTORY",
    "DEFAULT_FEISHU_PLACEHOLDER_BODY",
    "DEFAULT_FEISHU_FAILURE_BODY",
    "HttpJsonRequester",
    "FeishuWSClientFactory",
    "LOGGER",
    "_feishu_event_identifiers",
    "_feishu_secret_reference_from_payload",
    "_secret_reference_env_alias",
    "_credential_env_vars",
    "_feishu_account_profile",
    "load_feishu_gateway_accounts",
    "resolve_feishu_account",
]
