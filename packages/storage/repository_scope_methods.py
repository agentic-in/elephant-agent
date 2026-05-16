"""Scoped memory and semantic-index repository methods."""

from __future__ import annotations

from datetime import datetime
import json
from packages.auth import AuthProfile, EncryptedSecretValue, SecretReference
from packages.contracts import SemanticIndexEntry

from .repository_support import (
    _iso,
    _json_mapping,
    _parse_datetime,
    _semantic_index_entry_from_row,
    canonical_personal_model_id,
    canonical_personal_model_ref,
)


def upsert_semantic_index_entry(self, entry: SemanticIndexEntry) -> None:
    canonical_id = canonical_personal_model_ref(entry.personal_model_id)
    created_at = _iso(entry.created_at)
    updated_at = _iso(entry.updated_at)
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO semantic_index_entries (
                semantic_index_entry_id, owner_scope, source_id, provider_id,
                model_id, dimensions, content_hash, personal_model_id, state_id,
                backend, vector_ref, status, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(semantic_index_entry_id) DO UPDATE SET
                owner_scope = excluded.owner_scope,
                source_id = excluded.source_id,
                provider_id = excluded.provider_id,
                model_id = excluded.model_id,
                dimensions = excluded.dimensions,
                content_hash = excluded.content_hash,
                personal_model_id = excluded.personal_model_id,
                state_id = excluded.state_id,
                backend = excluded.backend,
                vector_ref = excluded.vector_ref,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                entry.semantic_index_entry_id,
                entry.owner_scope,
                entry.source_id,
                entry.provider_id,
                entry.model_id,
                entry.dimensions,
                entry.content_hash,
                canonical_id,
                entry.state_id,
                entry.backend,
                entry.vector_ref,
                entry.status,
                _json_mapping(dict(entry.metadata)),
                created_at,
                updated_at,
            ),
        )
        connection.commit()


def load_semantic_index_entry(self, entry_id: str) -> SemanticIndexEntry | None:
    with self.connection() as connection:
        row = connection.execute(
            "SELECT * FROM semantic_index_entries WHERE semantic_index_entry_id = ?",
            (entry_id,),
        ).fetchone()
    return None if row is None else _semantic_index_entry_from_row(row)


def list_semantic_index_entries(
    self,
    *,
    owner_scope: str | None = None,
    state_id: str | None = None,
    personal_model_id: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> tuple[SemanticIndexEntry, ...]:
    clauses, parameters = _owner_clauses(
        owner_scope=owner_scope,
        state_id=state_id,
        personal_model_id=personal_model_id,
    )
    if provider_id is not None:
        clauses.append("provider_id = ?")
        parameters.append(provider_id)
    if model_id is not None:
        clauses.append("model_id = ?")
        parameters.append(model_id)
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    with self.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM semantic_index_entries"
            + (" " + where_sql if where_sql else "")
            + " ORDER BY created_at ASC, semantic_index_entry_id ASC",
            tuple(parameters),
        ).fetchall()
    return tuple(_semantic_index_entry_from_row(row) for row in rows)


def delete_semantic_index_entries(
    self,
    *,
    state_id: str | None = None,
    personal_model_id: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> int:
    clauses, parameters = _owner_clauses(
        owner_scope=None,
        state_id=state_id,
        personal_model_id=personal_model_id,
    )
    if provider_id is not None:
        clauses.append("provider_id = ?")
        parameters.append(provider_id)
    if model_id is not None:
        clauses.append("model_id = ?")
        parameters.append(model_id)
    if not clauses:
        raise ValueError("semantic index deletion requires at least one filter")
    with self.connection() as connection:
        cursor = connection.execute(
            "DELETE FROM semantic_index_entries WHERE " + " AND ".join(clauses),
            tuple(parameters),
        )
        connection.commit()
    return int(cursor.rowcount)


def _owner_clauses(
    *,
    owner_scope: str | None,
    state_id: str | None,
    personal_model_id: str | None,
) -> tuple[list[str], list[str]]:
    clauses: list[str] = []
    parameters: list[str] = []
    if owner_scope is not None:
        clauses.append("owner_scope = ?")
        parameters.append(owner_scope)
    if state_id is not None:
        clauses.append("state_id = ?")
        parameters.append(state_id)
    if personal_model_id is not None:
        clauses.append("personal_model_id = ?")
        parameters.append(canonical_personal_model_id(personal_model_id))
    return clauses, parameters


def _grounding_ids(connection, table_name: str, owner_column: str, owner_id: str) -> tuple[str, ...]:
    rows = connection.execute(
        f"""
        SELECT grounding_id
        FROM {table_name}
        WHERE {owner_column} = ?
        ORDER BY grounding_order ASC
        """,
        (owner_id,),
    ).fetchall()
    return tuple(str(row["grounding_id"]) for row in rows)


def upsert_auth_profile(self, profile: AuthProfile) -> None:
    payload = _read_auth_profiles_payload(self)
    payload[profile.profile_id] = _auth_profile_payload(profile)
    _write_auth_profiles_payload(self, payload)


def load_auth_profile(self, profile_id: str) -> AuthProfile | None:
    payload = _read_auth_profiles_payload(self)
    item = payload.get(profile_id)
    if not isinstance(item, dict):
        return None
    return _auth_profile_from_payload(item)


def list_auth_profiles(self, provider_id: str | None = None) -> tuple[AuthProfile, ...]:
    payload = _read_auth_profiles_payload(self)
    profiles = tuple(
        _auth_profile_from_payload(item)
        for _, item in sorted(payload.items())
        if isinstance(item, dict)
    )
    if provider_id is None:
        return profiles
    return tuple(profile for profile in profiles if profile.provider_id == provider_id)


def select_auth_profile(self, provider_id: str) -> AuthProfile:
    matches = sorted(
        self.list_auth_profiles(provider_id),
        key=lambda profile: (-profile.priority, profile.profile_id),
    )
    if not matches:
        raise LookupError(f"no auth profile registered for provider: {provider_id}")
    return matches[0]


def upsert_auth_secret_value(self, secret: EncryptedSecretValue) -> None:
    payload = _read_auth_secret_values_payload(self)
    payload[secret.reference_id] = _encrypted_secret_payload(secret)
    _write_auth_secret_values_payload(self, payload)


def load_auth_secret_value(self, reference_id: str) -> EncryptedSecretValue | None:
    payload = _read_auth_secret_values_payload(self)
    item = payload.get(reference_id)
    if not isinstance(item, dict):
        return None
    return _encrypted_secret_from_payload(item)


def has_auth_secret_value(self, reference_id: str) -> bool:
    payload = _read_auth_secret_values_payload(self)
    return reference_id in payload


def delete_auth_secret_value(self, reference_id: str) -> None:
    payload = _read_auth_secret_values_payload(self)
    if reference_id not in payload:
        return
    payload.pop(reference_id, None)
    _write_auth_secret_values_payload(self, payload)


def _auth_profiles_path(self) -> str:
    return str(self.database_path.with_name(f"{self.database_path.stem}.auth-profiles.json"))


def _read_auth_profiles_payload(self) -> dict[str, dict[str, object]]:
    path = _auth_profiles_path(self)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def _write_auth_profiles_payload(self, payload: dict[str, dict[str, object]]) -> None:
    path = _auth_profiles_path(self)
    self.database_path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)


def _auth_secret_values_path(self) -> str:
    return str(self.database_path.with_name(f"{self.database_path.stem}.auth-secrets.json"))


def _read_auth_secret_values_payload(self) -> dict[str, dict[str, object]]:
    path = _auth_secret_values_path(self)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def _write_auth_secret_values_payload(self, payload: dict[str, dict[str, object]]) -> None:
    path = _auth_secret_values_path(self)
    self.database_path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)


def _secret_reference_payload(reference: SecretReference) -> dict[str, object]:
    return {
        "reference_id": reference.reference_id,
        "provider_id": reference.provider_id,
        "secret_name": reference.secret_name,
        "secret_key": reference.secret_key,
        "source": reference.source,
        "metadata": dict(reference.metadata),
    }


def _secret_reference_from_payload(payload: dict[str, object]) -> SecretReference:
    metadata = payload.get("metadata")
    return SecretReference(
        reference_id=str(payload["reference_id"]),
        provider_id=str(payload["provider_id"]),
        secret_name=str(payload["secret_name"]),
        secret_key=str(payload["secret_key"]),
        source=str(payload.get("source") or "elephant"),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def _encrypted_secret_payload(secret: EncryptedSecretValue) -> dict[str, object]:
    return {
        "reference_id": secret.reference_id,
        "key_id": secret.key_id,
        "nonce_b64": secret.nonce_b64,
        "ciphertext_b64": secret.ciphertext_b64,
        "mac_hex": secret.mac_hex,
    }


def _encrypted_secret_from_payload(payload: dict[str, object]) -> EncryptedSecretValue:
    return EncryptedSecretValue(
        reference_id=str(payload["reference_id"]),
        key_id=str(payload["key_id"]),
        nonce_b64=str(payload["nonce_b64"]),
        ciphertext_b64=str(payload["ciphertext_b64"]),
        mac_hex=str(payload["mac_hex"]),
    )


def _auth_profile_payload(profile: AuthProfile) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "provider_id": profile.provider_id,
        "transport_id": profile.transport_id,
        "base_url": profile.base_url,
        "default_model": profile.default_model,
        "auth_method": profile.auth_method,
        "provider_kind": profile.provider_kind,
        "extra_headers": dict(profile.extra_headers),
        "secret_references": [_secret_reference_payload(reference) for reference in profile.secret_references],
        "priority": profile.priority,
        "session_pin": profile.session_pin,
        "cooldown_until": profile.cooldown_until.isoformat() if profile.cooldown_until is not None else None,
        "metadata": dict(profile.metadata),
    }


def _auth_profile_from_payload(payload: dict[str, object]) -> AuthProfile:
    cooldown_until = payload.get("cooldown_until")
    return AuthProfile(
        profile_id=str(payload["profile_id"]),
        provider_id=str(payload["provider_id"]),
        transport_id=str(payload.get("transport_id") or "openai-compatible"),
        base_url=str(payload["base_url"]) if payload.get("base_url") is not None else None,
        default_model=(
            str(payload["default_model"]) if payload.get("default_model") is not None else None
        ),
        auth_method=str(payload.get("auth_method") or "api_key"),
        provider_kind=str(payload.get("provider_kind") or "first_party"),
        extra_headers=(
            dict(payload["extra_headers"]) if isinstance(payload.get("extra_headers"), dict) else {}
        ),
        secret_references=tuple(
            _secret_reference_from_payload(item)
            for item in payload.get("secret_references", ())
            if isinstance(item, dict)
        ),
        priority=int(payload.get("priority") or 0),
        session_pin=str(payload["session_pin"]) if payload.get("session_pin") is not None else None,
        cooldown_until=(
            _parse_datetime(str(cooldown_until)) if cooldown_until is not None else None
        ),
        metadata=dict(payload["metadata"]) if isinstance(payload.get("metadata"), dict) else {},
    )
