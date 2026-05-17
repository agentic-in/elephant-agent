"""Support contracts and helpers for the API runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
import json
from typing import Any, Mapping

from packages.auth import AuthProfile
from packages.contracts import Episode, State
from packages.contracts.runtime import RecallEvidence, PersonalModelRuntimeState
from packages.growth import ProgressionProjection
from packages.kernel import KernelOutcome


def _now() -> datetime:
    return datetime.now(UTC)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return [_jsonable(item) for item in sorted(value, key=repr)]
    return value


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(_jsonable(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")


def _read_json_bytes(body: bytes | None) -> dict[str, Any]:
    if not body:
        return {}
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    return data


def _split_path(path: str) -> tuple[str, ...]:
    trimmed = path.strip("/")
    if not trimmed:
        return ()
    parts = tuple(part for part in trimmed.split("/") if part)
    if parts and parts[0] == "v1":
        return parts[1:]
    return parts


def _coerce_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        if not value.strip():
            return ()
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_datetime(value: Any) -> datetime | None:
    text = _optional_str(value)
    if text is None:
        return None
    return datetime.fromisoformat(text)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = _optional_str(value)
    if text is None:
        return None
    normalized = text.lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


@dataclass(frozen=True, slots=True)
class APIAppConfig:
    database_path: Path
    install_root: Path | None = None
    instruction_refs: tuple[str, ...] = ("apps/api",)
    total_tokens: int = 2048


@dataclass(frozen=True, slots=True)
class APILoopRecord:
    request: dict[str, Any]
    outcome: KernelOutcome
    recorded_at: datetime

    def to_record(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "outcome": self.outcome,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class APIEpisodeInspection:
    personal_model: PersonalModelRuntimeState
    state: State
    episode: Episode
    lineage: tuple[Episode, ...]
    recall_items: tuple[RecallEvidence, ...]
    latest_loop: APILoopRecord | None
    recall_count: int
    telemetry_count: int
    provider_profile: AuthProfile | None = None
    progression: ProgressionProjection | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "personal_model": self.personal_model,
            "state": self.state,
            "episode": self.episode,
            "lineage": self.lineage,
            "recall_items": self.recall_items,
            "latest_loop": self.latest_loop,
            "recall_count": self.recall_count,
            "telemetry_count": self.telemetry_count,
            "provider_profile": self.provider_profile,
            "progression": self.progression,
        }


@dataclass(frozen=True, slots=True)
class APIEpisodeCreationResult:
    personal_model: PersonalModelRuntimeState
    state: State
    episode: Episode

    def to_record(self) -> dict[str, Any]:
        return {
            "personal_model": self.personal_model,
            "state": self.state,
            "episode": self.episode,
        }


@dataclass(frozen=True, slots=True)
class APIEpisodeLifecycleResult:
    episode: Episode

    def to_record(self) -> dict[str, Any]:
        return {"episode": self.episode}


@dataclass(frozen=True, slots=True)
class APIEpisodeTransitionResult:
    parent_episode: Episode
    episode: Episode
    lineage: tuple[Episode, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "parent_episode": self.parent_episode,
            "episode": self.episode,
            "lineage": self.lineage,
        }


@dataclass(frozen=True, slots=True)
class APILoopResult:
    episode: Episode
    outcome: KernelOutcome
    latest_loop: APILoopRecord
    inspection: APIEpisodeInspection

    def to_record(self) -> dict[str, Any]:
        return {
            "episode": self.episode,
            "outcome": self.outcome,
            "latest_loop": self.latest_loop,
            "inspection": self.inspection,
        }


@dataclass(frozen=True, slots=True)
class APIResponse:
    status_code: int
    payload: Mapping[str, Any]
    headers: tuple[tuple[str, str], ...] = (("content-type", "application/json; charset=utf-8"),)
