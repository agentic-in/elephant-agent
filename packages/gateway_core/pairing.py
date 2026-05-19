"""Filesystem-backed pairing approvals for gateway surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import tempfile
from typing import Any

from packages.runtime_layout import default_pairing_dir


PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_CODE_LENGTH = 8
PAIRING_TTL = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class PairingRequest:
    platform: str
    code: str
    external_user_id: str
    display_name: str
    created_at: datetime
    expires_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PairingApproval:
    platform: str
    external_user_id: str
    display_name: str
    approved_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class FileGatewayPairingStore:
    """Store pending pairing codes and approved gateway users as JSON files."""

    def __init__(self, root: Path | None = None, *, clock=None) -> None:
        self.root = (root or default_pairing_dir()).expanduser()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.root.mkdir(parents=True, exist_ok=True)

    def create_request(
        self,
        *,
        platform: str,
        external_user_id: str,
        display_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PairingRequest:
        now = self._clock()
        request = PairingRequest(
            platform=_platform_key(platform),
            code=_new_code(),
            external_user_id=external_user_id.strip(),
            display_name=display_name.strip(),
            created_at=now,
            expires_at=now + PAIRING_TTL,
            metadata=dict(metadata or {}),
        )
        pending = {
            code: payload
            for code, payload in self._load_mapping(self._pending_path(request.platform)).items()
            if not _request_expired(payload, now)
        }
        pending[request.code] = _request_payload(request)
        self._write_mapping(self._pending_path(request.platform), pending)
        return request

    def approve(self, *, platform: str, code: str) -> PairingApproval | None:
        platform_key = _platform_key(platform)
        normalized_code = code.strip().upper()
        now = self._clock()
        pending_path = self._pending_path(platform_key)
        pending = self._load_mapping(pending_path)
        payload = pending.get(normalized_code)
        if payload is None or _request_expired(payload, now):
            if normalized_code in pending:
                pending.pop(normalized_code, None)
                self._write_mapping(pending_path, pending)
            return None
        pending.pop(normalized_code, None)
        self._write_mapping(pending_path, pending)
        approval = PairingApproval(
            platform=platform_key,
            external_user_id=str(payload.get("external_user_id") or ""),
            display_name=str(payload.get("display_name") or ""),
            approved_at=now,
            metadata=dict(payload.get("metadata") or {}),
        )
        approved = self._load_mapping(self._approved_path(platform_key))
        approved[approval.external_user_id] = _approval_payload(approval)
        self._write_mapping(self._approved_path(platform_key), approved)
        return approval

    def is_approved(self, *, platform: str, external_user_id: str) -> bool:
        approved = self._load_mapping(self._approved_path(_platform_key(platform)))
        return external_user_id in approved

    def revoke(self, *, platform: str, external_user_id: str) -> bool:
        platform_key = _platform_key(platform)
        path = self._approved_path(platform_key)
        approved = self._load_mapping(path)
        if external_user_id not in approved:
            return False
        approved.pop(external_user_id, None)
        self._write_mapping(path, approved)
        return True

    def pending_requests(self, *, platform: str) -> tuple[PairingRequest, ...]:
        platform_key = _platform_key(platform)
        now = self._clock()
        pending = self._load_mapping(self._pending_path(platform_key))
        active = tuple(
            _request_from_payload(platform_key, code, payload)
            for code, payload in sorted(pending.items())
            if not _request_expired(payload, now)
        )
        if len(active) != len(pending):
            self._write_mapping(
                self._pending_path(platform_key),
                {item.code: _request_payload(item) for item in active},
            )
        return active

    def _pending_path(self, platform: str) -> Path:
        return self.root / f"{platform}-pending.json"

    def _approved_path(self, platform: str) -> Path:
        return self.root / f"{platform}-approved.json"

    def _load_mapping(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return dict(payload) if isinstance(payload, dict) else {}

    def _write_mapping(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(path)


def _platform_key(value: str) -> str:
    key = value.strip().lower()
    if not key:
        raise ValueError("platform is required")
    if not all(character.isalnum() or character in {"-", "_"} for character in key):
        raise ValueError(f"invalid platform key: {value}")
    return key


def _new_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))


def _request_payload(request: PairingRequest) -> dict[str, Any]:
    return {
        "external_user_id": request.external_user_id,
        "display_name": request.display_name,
        "created_at": request.created_at.isoformat(),
        "expires_at": request.expires_at.isoformat(),
        "metadata": dict(request.metadata),
    }


def _approval_payload(approval: PairingApproval) -> dict[str, Any]:
    return {
        "external_user_id": approval.external_user_id,
        "display_name": approval.display_name,
        "approved_at": approval.approved_at.isoformat(),
        "metadata": dict(approval.metadata),
    }


def _request_from_payload(platform: str, code: str, payload: dict[str, Any]) -> PairingRequest:
    return PairingRequest(
        platform=platform,
        code=code,
        external_user_id=str(payload.get("external_user_id") or ""),
        display_name=str(payload.get("display_name") or ""),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        expires_at=datetime.fromisoformat(str(payload["expires_at"])),
        metadata=dict(payload.get("metadata") or {}),
    )


def _request_expired(payload: dict[str, Any], now: datetime) -> bool:
    try:
        expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    except (KeyError, ValueError):
        return True
    return expires_at <= now


__all__ = [
    "FileGatewayPairingStore",
    "PAIRING_CODE_LENGTH",
    "PairingApproval",
    "PairingRequest",
]
