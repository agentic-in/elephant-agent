"""Credential discovery registries and secret-store adapters.

This module owns runtime credential discovery that can reuse local provider
sessions without baking provider-specific lookup rules into app surfaces.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Protocol, runtime_checkable

from .runtime import (
    LocalEncryptedSecretCipher,
    SecretReference,
    SecretStore,
    SecretValueResolution,
)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def _jwt_claims(token: str) -> Mapping[str, Any]:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items()}


def _jwt_token_is_expiring(token: str, *, skew_seconds: int = 0) -> bool:
    from datetime import datetime, timezone

    claims = _jwt_claims(token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= (datetime.now(timezone.utc).timestamp() + max(0, int(skew_seconds)))


def _timestamp_string_is_expiring(value: Any, *, skew_seconds: int = 0) -> bool:
    from datetime import datetime, timezone

    text = str(value or "").strip()
    if not text:
        return False
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        expires_at = datetime.fromisoformat(text)
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at.timestamp() <= (datetime.now(timezone.utc).timestamp() + max(0, int(skew_seconds)))


def _codex_auth_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if not codex_home:
        codex_home = str(Path.home() / ".codex")
    return Path(codex_home).expanduser() / "auth.json"


def _qwen_auth_path() -> Path:
    return Path.home() / ".qwen" / "oauth_creds.json"


def _claude_code_credentials_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def _read_codex_cli_resolution() -> SecretValueResolution | None:
    auth_path = _codex_auth_path()
    if not auth_path.is_file():
        return None
    payload = _read_json_object(auth_path)
    if payload is None:
        return None
    tokens = payload.get("tokens")
    if not isinstance(tokens, Mapping):
        return None
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()
    if not access_token or not refresh_token or _jwt_token_is_expiring(access_token):
        return None
    return SecretValueResolution(value=access_token, source=f"codex-cli:{auth_path}")


def _read_qwen_oauth_resolution() -> SecretValueResolution | None:
    auth_path = _qwen_auth_path()
    if not auth_path.is_file():
        return None
    payload = _read_json_object(auth_path)
    if payload is None:
        return None
    access_token = str(payload.get("access_token", "") or "").strip()
    if not access_token:
        return None
    try:
        from datetime import datetime, timezone

        expiry_ms = int(payload.get("expiry_date"))
        if expiry_ms and expiry_ms <= int(datetime.now(timezone.utc).timestamp() * 1000):
            return None
    except (TypeError, ValueError):
        pass
    return SecretValueResolution(value=access_token, source=f"qwen-cli:{auth_path}")


def _read_google_gemini_oauth_resolution() -> SecretValueResolution | None:
    return None


def _read_anthropic_token_from_payload(
    path: Path,
    payload: Mapping[str, Any],
    *,
    source: str,
) -> SecretValueResolution | None:
    claude_code_oauth = payload.get("claudeAiOauth")
    if isinstance(claude_code_oauth, Mapping):
        payload = {str(key): value for key, value in claude_code_oauth.items()}
    access_token = str(payload.get("accessToken") or payload.get("access_token") or payload.get("token") or "").strip()
    if not access_token:
        return None
    expires_at = payload.get("expiresAt") or payload.get("expires_at")
    if _timestamp_string_is_expiring(expires_at):
        return None
    return SecretValueResolution(value=access_token, source=f"{source}:{path}")


def _read_anthropic_oauth_resolution() -> SecretValueResolution | None:
    value = os.environ.get("ANTHROPIC_TOKEN")
    if value:
        return SecretValueResolution(value=value, source="env:ANTHROPIC_TOKEN")
    return None


def _read_claude_code_oauth_resolution() -> SecretValueResolution | None:
    path = _claude_code_credentials_path()
    if path.is_file():
        payload = _read_json_object(path)
        if payload is not None:
            resolution = _read_anthropic_token_from_payload(
                path,
                payload,
                source="claude-code-oauth",
            )
            if resolution is not None:
                return resolution
    value = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if value:
        return SecretValueResolution(value=value, source="env:CLAUDE_CODE_OAUTH_TOKEN")
    return None


def _read_copilot_resolution() -> SecretValueResolution | None:
    for env_name in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = str(os.environ.get(env_name) or "").strip()
        if value and not value.startswith("ghp_"):
            return SecretValueResolution(value=value, source=f"env:{env_name}")
    clean_env = {key: value for key, value in os.environ.items() if key not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env=clean_env,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    token = completed.stdout.strip()
    if not token or token.startswith("ghp_"):
        return None
    return SecretValueResolution(value=token, source="gh auth token")


def _normalize_env_name(candidate: str) -> str:
    return candidate.strip().replace("-", "_").replace(".", "_").upper()


@runtime_checkable
class CredentialDiscoveryProvider(Protocol):
    def supports(self, provider_id: str) -> bool:
        """Return whether the provider can discover this provider id."""

    def discover(
        self,
        reference: SecretReference,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> SecretValueResolution | None:
        """Return a discovered secret value or None when unavailable."""


class InMemoryCredentialDiscoveryRegistry:
    def __init__(self, providers: tuple[CredentialDiscoveryProvider, ...] = ()) -> None:
        self._providers: list[CredentialDiscoveryProvider] = list(providers)

    def register(self, provider: CredentialDiscoveryProvider) -> None:
        self._providers.append(provider)

    def providers(self) -> tuple[CredentialDiscoveryProvider, ...]:
        return tuple(self._providers)

    def discover(
        self,
        reference: SecretReference,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> SecretValueResolution | None:
        provider_id = reference.provider_id.strip().lower()
        for provider in self._providers:
            if not provider.supports(provider_id):
                continue
            resolution = provider.discover(reference, environ=environ)
            if resolution is not None:
                return resolution
        return None

    @classmethod
    def default(cls) -> "InMemoryCredentialDiscoveryRegistry":
        return cls(
            (
                _StaticCredentialDiscoveryProvider(
                    provider_ids=("anthropic",),
                    resolver=_read_anthropic_oauth_resolution,
                ),
                _StaticCredentialDiscoveryProvider(
                    provider_ids=("claude-code",),
                    resolver=_read_claude_code_oauth_resolution,
                ),
                _StaticCredentialDiscoveryProvider(
                    provider_ids=("openai-codex",),
                    resolver=_read_codex_cli_resolution,
                ),
                _StaticCredentialDiscoveryProvider(
                    provider_ids=("google-gemini-cli",),
                    resolver=_read_google_gemini_oauth_resolution,
                ),
                _StaticCredentialDiscoveryProvider(
                    provider_ids=("qwen-oauth",),
                    resolver=_read_qwen_oauth_resolution,
                ),
                _StaticCredentialDiscoveryProvider(
                    provider_ids=("copilot",),
                    resolver=_read_copilot_resolution,
                ),
            )
        )


class _StaticCredentialDiscoveryProvider:
    def __init__(
        self,
        *,
        provider_ids: tuple[str, ...],
        resolver,
    ) -> None:
        self.provider_ids = tuple(item.strip().lower() for item in provider_ids)
        self.resolver = resolver

    def supports(self, provider_id: str) -> bool:
        return provider_id.strip().lower() in self.provider_ids

    def discover(
        self,
        reference: SecretReference,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> SecretValueResolution | None:
        del reference, environ
        return self.resolver()


def default_credential_discovery_registry() -> InMemoryCredentialDiscoveryRegistry:
    return InMemoryCredentialDiscoveryRegistry.default()


class EnvironmentSecretStore(SecretStore):
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self.environ = environ

    def resolve(self, reference: SecretReference) -> SecretValueResolution:
        env = self.environ or os.environ
        candidates: list[str] = list(reference.env_var_candidates())
        seen = set(candidates)
        for candidate in (
            reference.secret_name,
            reference.secret_key,
            reference.reference_id,
        ):
            normalized = _normalize_env_name(candidate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)
        for candidate in candidates:
            value = env.get(candidate)
            if value is not None:
                return SecretValueResolution(value=value, source=f"env:{candidate}")
        raise LookupError(f"missing environment secret for reference: {reference.reference_id}")

    def read(self, reference: SecretReference) -> str:
        return self.resolve(reference).value


class EncryptedRepositorySecretStore(SecretStore):
    def __init__(
        self,
        repository: AuthSecretValueRepository,
        *,
        cipher: LocalEncryptedSecretCipher,
        discovery_registry: InMemoryCredentialDiscoveryRegistry | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.discovery_registry = discovery_registry or default_credential_discovery_registry()
        self.environ = environ

    def resolve(self, reference: SecretReference) -> SecretValueResolution:
        stored = self.repository.load_auth_secret_value(reference.reference_id)
        if stored is not None:
            return SecretValueResolution(
                value=self.cipher.decrypt(stored),
                source="encrypted-local-store",
            )
        env = self.environ or os.environ
        for env_name in reference.env_var_candidates():
            value = env.get(env_name)
            if value is not None:
                if reference.provider_id.strip().lower() == "copilot" and value.strip().startswith("ghp_"):
                    continue
                return SecretValueResolution(value=value, source=f"env:{env_name}")
        external = self.discovery_registry.discover(reference, environ=env)
        if external is not None:
            return external
        raise LookupError(f"missing stored secret for reference: {reference.reference_id}")

    def read(self, reference: SecretReference) -> str:
        return self.resolve(reference).value


__all__ = [
    "CredentialDiscoveryProvider",
    "EncryptedRepositorySecretStore",
    "EnvironmentSecretStore",
    "InMemoryCredentialDiscoveryRegistry",
    "default_credential_discovery_registry",
]
