"""Secret-reference, provider profile, and credential-resolution primitives."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
from typing import Any, Mapping, Protocol, runtime_checkable

from packages.capabilities.runtime import CapabilityDescriptor
from packages.models.provider_catalog import default_provider_definitions

_ENV_ALIAS_METADATA_KEYS = ("env_var", "env", "environment_variable")
_SENSITIVE_MAPPING_KEYS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "private_key",
    "secret",
    "token",
)
_SENSITIVE_HEADER_NAMES = {
    "api-key",
    "apikey",
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}\b"),
    re.compile(r"\bsk(?:-[a-zA-Z0-9_-]{6,}|_proj-[a-zA-Z0-9_-]{6,})\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _normalize_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return normalized.lower()


def _normalize_env_name(value: str) -> str:
    return _normalize_name(value).upper()


def _looks_like_secret_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) is not None for pattern in _SECRET_VALUE_PATTERNS)


def _validate_identifier(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")


def _validate_mapping_without_inline_secrets(
    mapping: Mapping[str, str],
    *,
    label: str,
    allow_env_aliases: bool = False,
) -> None:
    for key, value in mapping.items():
        _validate_identifier(f"{label} key", key)
        normalized_key = _normalize_name(key)
        if allow_env_aliases and normalized_key in {_normalize_name(item) for item in _ENV_ALIAS_METADATA_KEYS}:
            if not _normalize_env_name(value):
                raise ValueError(f"{label} entry '{key}' must name a non-empty environment variable")
            continue
        if normalized_key in _SENSITIVE_MAPPING_KEYS:
            raise ValueError(f"{label} entry '{key}' must reference a secret source, not inline secret material")
        if _looks_like_secret_value(value):
            raise ValueError(f"{label} entry '{key}' must not contain inline secret material")


def _validate_extra_headers(extra_headers: Mapping[str, str]) -> None:
    for key, value in extra_headers.items():
        _validate_identifier("extra_headers key", key)
        normalized_key = _normalize_name(key)
        if normalized_key in {_normalize_name(item) for item in _SENSITIVE_HEADER_NAMES}:
            raise ValueError(
                f"extra_headers entry '{key}' must not carry provider credentials; use secret references instead"
            )
        if _looks_like_secret_value(value):
            raise ValueError(f"extra_headers entry '{key}' must not contain inline secret material")


@dataclass(frozen=True, slots=True)
class SecretReference:
    reference_id: str
    provider_id: str
    secret_name: str
    secret_key: str
    source: str = "elephant"
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier("reference_id", self.reference_id)
        _validate_identifier("provider_id", self.provider_id)
        _validate_identifier("secret_name", self.secret_name)
        _validate_identifier("secret_key", self.secret_key)
        _validate_mapping_without_inline_secrets(
            self.metadata,
            label="secret reference metadata",
            allow_env_aliases=True,
        )

    def env_var_candidates(self) -> tuple[str, ...]:
        candidates: list[str] = []
        seen: set[str] = set()
        for key in _ENV_ALIAS_METADATA_KEYS:
            value = self.metadata.get(key)
            if not value:
                continue
            normalized = _normalize_env_name(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(normalized)
        return tuple(candidates)

    def runtime_resolution_hint(self) -> str:
        return (
            f"store the provider key for '{self.provider_id}' key '{self.secret_key}' "
            "through 'elephant init' or '/providers', then rerun 'elephant status'"
        )


@dataclass(frozen=True, slots=True)
class SecretValueResolution:
    value: str
    source: str = "unknown"


@dataclass(frozen=True, slots=True)
class AuthProfile:
    profile_id: str
    provider_id: str
    transport_id: str = "openai-compatible"
    base_url: str | None = None
    default_model: str | None = None
    auth_method: str = "api_key"
    provider_kind: str = "first_party"
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    secret_references: tuple[SecretReference, ...] = ()
    priority: int = 0
    session_pin: str | None = None
    cooldown_until: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier("profile_id", self.profile_id)
        _validate_identifier("provider_id", self.provider_id)
        _validate_identifier("transport_id", self.transport_id)
        _validate_identifier("auth_method", self.auth_method)
        _validate_identifier("provider_kind", self.provider_kind)
        _validate_extra_headers(self.extra_headers)
        _validate_mapping_without_inline_secrets(self.metadata, label="auth profile metadata")
        seen_reference_ids: set[str] = set()
        seen_secret_keys: set[str] = set()
        for reference in self.secret_references:
            if reference.provider_id != self.provider_id:
                raise ValueError(
                    "secret reference provider_id must match auth profile provider_id: "
                    f"{reference.provider_id} != {self.provider_id}"
                )
            if reference.reference_id in seen_reference_ids:
                raise ValueError(f"duplicate secret reference id in auth profile: {reference.reference_id}")
            if reference.secret_key in seen_secret_keys:
                raise ValueError(f"duplicate secret key in auth profile: {reference.secret_key}")
            seen_reference_ids.add(reference.reference_id)
            seen_secret_keys.add(reference.secret_key)


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    provider_id: str
    display_label: str
    transport_id: str
    base_url: str | None
    default_model: str | None
    auth_method: str = "api_key"
    auth_type: str = "api_key"
    provider_kind: str = "first_party"
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    required_secret_keys: tuple[str, ...] = ()
    env_var_names: tuple[str, ...] = ()
    base_url_env_var: str | None = None
    runtime_enabled: bool = True
    model_hints: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderProfileInput:
    profile_id: str
    provider_id: str
    secret_references: tuple[SecretReference, ...] = ()
    priority: int = 0
    session_pin: str | None = None
    cooldown_until: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


class ProviderCatalog:
    def __init__(self, manifests: tuple[ProviderManifest, ...] = ()) -> None:
        self._manifests: dict[str, ProviderManifest] = {}
        for manifest in manifests:
            self.register(manifest)

    @classmethod
    def with_defaults(cls) -> "ProviderCatalog":
        return cls(
            tuple(
                ProviderManifest(
                    provider_id=definition.provider_id,
                    display_label=definition.display_name,
                    transport_id=definition.transport_id,
                    base_url=definition.default_base_url,
                    default_model=definition.default_model_id,
                    auth_method=definition.auth_method,
                    auth_type=definition.auth_type,
                    provider_kind=definition.provider_kind,
                    extra_headers=dict(definition.extra_headers),
                    required_secret_keys=definition.required_secret_keys,
                    env_var_names=definition.env_var_names,
                    base_url_env_var=definition.base_url_env_var,
                    runtime_enabled=definition.runtime_enabled,
                    model_hints=definition.model_hints,
                    metadata=dict(definition.metadata),
                )
                for definition in default_provider_definitions(include_discovery_only=True)
            )
        )

    def register(self, manifest: ProviderManifest) -> None:
        self._manifests[manifest.provider_id] = manifest

    def get(self, provider_id: str) -> ProviderManifest | None:
        return self._manifests.get(provider_id)

    def list(self) -> tuple[ProviderManifest, ...]:
        return tuple(self._manifests.values())


class ProviderProfileFactory:
    def __init__(self, catalog: ProviderCatalog | None = None) -> None:
        self.catalog = catalog or ProviderCatalog.with_defaults()

    def from_provider_defaults(
        self,
        provider_id: str,
        *,
        profile_id: str,
        secret_references: tuple[SecretReference, ...] = (),
        priority: int = 0,
        session_pin: str | None = None,
        cooldown_until: datetime | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> AuthProfile:
        manifest = self.catalog.get(provider_id)
        if manifest is None:
            raise LookupError(f"unknown provider manifest: {provider_id}")
        return AuthProfile(
            profile_id=profile_id,
            provider_id=provider_id,
            transport_id=manifest.transport_id,
            base_url=manifest.base_url,
            default_model=manifest.default_model,
            auth_method=manifest.auth_method,
            provider_kind=manifest.provider_kind,
            extra_headers=dict(manifest.extra_headers),
            secret_references=secret_references,
            priority=priority,
            session_pin=session_pin,
            cooldown_until=cooldown_until,
            metadata=dict(metadata or {}),
        )

    def from_compatible_endpoint(
        self,
        *,
        profile_id: str,
        provider_id: str,
        base_url: str,
        default_model: str,
        secret_references: tuple[SecretReference, ...] = (),
        transport_id: str = "openai-compatible",
        auth_method: str = "api_key",
        provider_kind: str = "custom",
        extra_headers: Mapping[str, str] | None = None,
        priority: int = 0,
        session_pin: str | None = None,
        cooldown_until: datetime | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> AuthProfile:
        return AuthProfile(
            profile_id=profile_id,
            provider_id=provider_id,
            transport_id=transport_id,
            base_url=base_url,
            default_model=default_model,
            auth_method=auth_method,
            provider_kind=provider_kind,
            extra_headers=dict(extra_headers or {}),
            secret_references=secret_references,
            priority=priority,
            session_pin=session_pin,
            cooldown_until=cooldown_until,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class CredentialBundle:
    profile_id: str
    provider_id: str
    values: Mapping[str, str] = field(default_factory=dict)
    value_sources: Mapping[str, str] = field(default_factory=dict)
    source_reference_ids: tuple[str, ...] = ()
    resolved_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, str]:
        return dict(self.values)

    def redacted_mapping(self) -> dict[str, str]:
        return {key: "***" for key in self.values}

    def __repr__(self) -> str:  # pragma: no cover - exercised indirectly
        return (
            "CredentialBundle("
            f"profile_id={self.profile_id!r}, provider_id={self.provider_id!r}, "
            f"values={self.redacted_mapping()!r}, value_sources={dict(self.value_sources)!r}, "
            f"source_reference_ids={self.source_reference_ids!r})"
        )


@dataclass(frozen=True, slots=True)
class EncryptedSecretValue:
    reference_id: str
    key_id: str
    nonce_b64: str
    ciphertext_b64: str
    mac_hex: str


@dataclass(frozen=True, slots=True)
class ProviderAuthState:
    provider_id: str
    auth_type: str
    status: str
    source: str
    profile_id: str | None = None
    transport_id: str | None = None
    provider_kind: str = "first_party"
    base_url: str | None = None
    default_model: str | None = None
    runtime_enabled: bool = True
    summary: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    discovered_at: datetime | None = None
    updated_at: datetime | None = None


class LocalEncryptedSecretCipher:
    """Small local-only encrypt-then-MAC helper for persisted provider secrets."""

    def __init__(self, master_key: bytes, *, key_id: str = "local-v1") -> None:
        if len(master_key) < 32:
            raise ValueError("master_key must be at least 32 bytes")
        self.master_key = bytes(master_key)
        self.key_id = key_id
        self._enc_key = hmac.new(self.master_key, b"elephant:secret-store:enc", hashlib.sha256).digest()
        self._mac_key = hmac.new(self.master_key, b"elephant:secret-store:mac", hashlib.sha256).digest()

    @classmethod
    def from_path(cls, path: str | Path, *, key_id: str = "local-v1") -> "LocalEncryptedSecretCipher":
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if resolved.exists():
            material = resolved.read_bytes()
        else:
            material = secrets.token_bytes(32)
            resolved.write_bytes(material)
            os.chmod(resolved, 0o600)
        return cls(material, key_id=key_id)

    def encrypt(self, *, reference_id: str, value: str) -> EncryptedSecretValue:
        plaintext = value.encode("utf-8")
        nonce = secrets.token_bytes(16)
        ciphertext = self._xor_with_keystream(plaintext, nonce)
        mac = self._mac(reference_id=reference_id, nonce=nonce, ciphertext=ciphertext)
        return EncryptedSecretValue(
            reference_id=reference_id,
            key_id=self.key_id,
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
            ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
            mac_hex=mac.hex(),
        )

    def decrypt(self, value: EncryptedSecretValue) -> str:
        if value.key_id != self.key_id:
            raise LookupError(f"unsupported secret key id: {value.key_id}")
        nonce = base64.b64decode(value.nonce_b64.encode("ascii"))
        ciphertext = base64.b64decode(value.ciphertext_b64.encode("ascii"))
        expected_mac = self._mac(reference_id=value.reference_id, nonce=nonce, ciphertext=ciphertext).hex()
        if not hmac.compare_digest(expected_mac, value.mac_hex):
            raise LookupError(f"stored secret integrity check failed for reference: {value.reference_id}")
        plaintext = self._xor_with_keystream(ciphertext, nonce)
        return plaintext.decode("utf-8")

    def _mac(self, *, reference_id: str, nonce: bytes, ciphertext: bytes) -> bytes:
        payload = reference_id.encode("utf-8") + b"\0" + nonce + ciphertext
        return hmac.new(self._mac_key, payload, hashlib.sha256).digest()

    def _xor_with_keystream(self, payload: bytes, nonce: bytes) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < len(payload):
            block = hmac.new(
                self._enc_key,
                nonce + counter.to_bytes(8, "big"),
                hashlib.sha256,
            ).digest()
            output.extend(block)
            counter += 1
        keystream = bytes(output[: len(payload)])
        return bytes(left ^ right for left, right in zip(payload, keystream, strict=True))


@runtime_checkable
class SecretStore(Protocol):
    def resolve(self, reference: SecretReference) -> SecretValueResolution:
        """Return secret material plus provenance for a reference."""

    def read(self, reference: SecretReference) -> str:
        """Return the raw secret material for a reference."""


@runtime_checkable
class AuthProfileStore(Protocol):
    def register(self, profile: AuthProfile) -> None:
        """Register or replace an auth profile."""

    def get(self, profile_id: str) -> AuthProfile | None:
        """Return a profile by id."""

    def list(self, provider_id: str | None = None) -> tuple[AuthProfile, ...]:
        """Return profiles, optionally filtered by provider."""

    def select(self, provider_id: str) -> AuthProfile:
        """Return the best matching profile for a provider."""


@runtime_checkable
class CredentialResolver(Protocol):
    def resolve(self, profile: AuthProfile) -> CredentialBundle:
        """Resolve a credential bundle for an auth profile."""


class InMemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def put(self, reference_id: str, value: str) -> None:
        self._values[reference_id] = value

    def resolve(self, reference: SecretReference) -> SecretValueResolution:
        return SecretValueResolution(
            value=self.read(reference),
            source=f"memory:{reference.reference_id}",
        )

    def read(self, reference: SecretReference) -> str:
        try:
            return self._values[reference.reference_id]
        except KeyError as exc:
            raise LookupError(f"missing secret reference: {reference.reference_id}") from exc


class InMemoryAuthProfileStore:
    def __init__(self, profiles: tuple[AuthProfile, ...] = ()) -> None:
        self._profiles: dict[str, AuthProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: AuthProfile) -> None:
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> AuthProfile | None:
        return self._profiles.get(profile_id)

    def list(self, provider_id: str | None = None) -> tuple[AuthProfile, ...]:
        profiles = tuple(self._profiles.values())
        if provider_id is None:
            return profiles
        return tuple(profile for profile in profiles if profile.provider_id == provider_id)

    def select(self, provider_id: str) -> AuthProfile:
        matches = sorted(
            self.list(provider_id),
            key=lambda profile: (-profile.priority, profile.profile_id),
        )
        if not matches:
            raise LookupError(f"no auth profile registered for provider: {provider_id}")
        return matches[0]


class PersistentAuthProfileStore:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def register(self, profile: AuthProfile) -> None:
        self.repository.upsert_auth_profile(profile)

    def get(self, profile_id: str) -> AuthProfile | None:
        return self.repository.load_auth_profile(profile_id)

    def list(self, provider_id: str | None = None) -> tuple[AuthProfile, ...]:
        return self.repository.list_auth_profiles(provider_id)

    def select(self, provider_id: str) -> AuthProfile:
        return self.repository.select_auth_profile(provider_id)


class ProfileCredentialResolver:
    def __init__(self, secret_store: SecretStore) -> None:
        self.secret_store = secret_store

    def resolve(self, profile: AuthProfile) -> CredentialBundle:
        values: dict[str, str] = {}
        value_sources: dict[str, str] = {}
        source_reference_ids: list[str] = []
        for reference in profile.secret_references:
            try:
                resolution = self.secret_store.resolve(reference)
            except LookupError as exc:
                raise LookupError(
                    f"missing runtime secret for provider '{profile.provider_id}' key '{reference.secret_key}'; "
                    f"{reference.runtime_resolution_hint()}"
                ) from exc
            resolved = resolution.value
            if not resolved.strip():
                env_vars = reference.env_var_candidates()
                location = env_vars[0] if env_vars else reference.reference_id
                raise LookupError(
                    f"runtime secret for provider '{profile.provider_id}' key '{reference.secret_key}' "
                    f"is empty at '{location}'; update the value and rerun 'elephant status'"
                )
            values[reference.secret_key] = resolved
            value_sources[reference.secret_key] = resolution.source
            source_reference_ids.append(reference.reference_id)
        return CredentialBundle(
            profile_id=profile.profile_id,
            provider_id=profile.provider_id,
            values=values,
            value_sources=value_sources,
            source_reference_ids=tuple(source_reference_ids),
            resolved_at=datetime.now(timezone.utc),
            metadata=dict(profile.metadata),
        )


def profile_from_input(
    profile_input: ProviderProfileInput,
    *,
    catalog: ProviderCatalog | None = None,
    base_url: str | None = None,
    default_model: str | None = None,
    transport_id: str | None = None,
    auth_method: str | None = None,
    provider_kind: str | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> AuthProfile:
    factory = ProviderProfileFactory(catalog=catalog)
    if any(
        value is not None
        for value in (
            base_url,
            default_model,
            transport_id,
            auth_method,
            provider_kind,
            extra_headers,
        )
    ):
        return factory.from_compatible_endpoint(
            profile_id=profile_input.profile_id,
            provider_id=profile_input.provider_id,
            base_url=base_url or "",
            default_model=default_model or "",
            transport_id=transport_id or "openai-compatible",
            auth_method=auth_method or "api_key",
            provider_kind=provider_kind or "custom",
            extra_headers=extra_headers,
            secret_references=profile_input.secret_references,
            priority=profile_input.priority,
            session_pin=profile_input.session_pin,
            cooldown_until=profile_input.cooldown_until,
            metadata=profile_input.metadata,
        )
    return factory.from_provider_defaults(
        profile_input.provider_id,
        profile_id=profile_input.profile_id,
        secret_references=profile_input.secret_references,
        priority=profile_input.priority,
        session_pin=profile_input.session_pin,
        cooldown_until=profile_input.cooldown_until,
        metadata=profile_input.metadata,
    )


class PreviewAuthProviderCapability:
    """Resolve provider credentials for the preview runtime."""

    def __init__(
        self,
        *,
        profile_store: AuthProfileStore,
        resolver: CredentialResolver,
        capability_id: str = "auth.preview",
    ) -> None:
        self.profile_store = profile_store
        self.resolver = resolver
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            kind="auth_provider",
            version="1.0.0",
        )

    def resolve(self, provider_id: str) -> Mapping[str, str]:
        profile = self.profile_store.select(provider_id)
        return self.resolver.resolve(profile).as_mapping()

    def resolve_bundle(self, provider_id: str) -> CredentialBundle:
        profile = self.profile_store.select(provider_id)
        return self.resolver.resolve(profile)
