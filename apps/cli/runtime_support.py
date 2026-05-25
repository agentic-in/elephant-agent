"""Shared helpers and lightweight data models for the CLI runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from packages.continuity import RelationshipPolicy
from packages.contracts import Episode
from packages.contracts.runtime import (
    EvidenceRetrievalResult,
    RecallEvidence,
    PlanDraft,
    PersonalModelRuntimeState,
    ResumePacket,
)
from packages.kernel import KernelOutcome, WakeReconciliationReport
from packages.skills import SkillDefinition
from packages.state import (
    LoadedProfile,
    companion_display_name,
    render_default_elephant_identity,
)
from packages.state.governance import parse_elephant_identity_display_name
from .runtime_voice import VoiceInputResolution, VoiceTurnResult

_PLACEHOLDER_MODELS_BY_PROVIDER = {
    "openai-compatible": {"model-id", "Any OpenAI-compatible chat model"},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _restore_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9_]+", text.lower()) if token}


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
    except ValueError:
        return False
    return True


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


def _runtime_skill_metadata_flag(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    return default


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _normalized_profile_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _elephant_state_id(elephant_id: str) -> str:
    normalized = elephant_id.strip()
    if not normalized:
        raise ValueError("elephant id is required")
    return f"state:{normalized}"


def _current_elephant_identity_text(profile: LoadedProfile) -> str | None:
    return _normalized_profile_text(profile.elephant_identity_text)


def _default_elephant_identity_text(
    profile: LoadedProfile,
    *,
    display_name: str | None = None,
) -> str:
    return render_default_elephant_identity(
        display_name=display_name or profile.state.display_name
    ).strip()


def _default_elephant_identity_file_text(
    profile: LoadedProfile,
    *,
    elephant_id: str,
    display_name: str | None = None,
) -> str:
    """Write a fresh identity file (ELEPHANT.md) for a new elephant.

    The file is read by two audiences: the human operator (who edits
    it directly) and the model (injected at Episode start). The
    previous template catered to neither well — it opened with
    ``# Elephant Identity: Zoey`` and ``Elephant ID: zoey``, dumped metadata,
    and closed with an "Operating Contract" list containing
    ``Personal Model -> Elephant -> Episode -> Loop -> Step``. The model
    read that and started thinking of itself as a framework object.

    The new template is a first-person self-introduction. The human
    metadata (id) lives in an HTML comment so the human can
    still edit it but the model never sees it. Everything else reads
    like a note the person themselves wrote to describe who they are.
    """
    resolved_display_name = (
        display_name
        or parse_elephant_identity_display_name(_current_elephant_identity_text(profile))
        or elephant_id.replace("-", " ").replace("_", " ").title()
        or companion_display_name(profile)
    )
    charter = _default_elephant_identity_text(
        profile,
        display_name=resolved_display_name,
    )
    return "\n".join(
        (
            f"<!-- Internal metadata (not shown to the model). id: {elephant_id}. "
            f"Edit the paragraphs below to reshape how {resolved_display_name} introduces themselves. -->",
            "",
            charter,
        )
    ).strip()


def _elephant_identity_text_uses_default(profile: LoadedProfile) -> bool:
    current = _current_elephant_identity_text(profile)
    if current is None:
        return True
    return current == _default_elephant_identity_text(profile)


def _resolved_state_for_elephant(repository: Any, elephant_id: str):
    target = str(elephant_id or "").strip()
    if not target:
        return repository.current_state() if hasattr(repository, "current_state") else None
    if hasattr(repository, "load_state"):
        direct = repository.load_state(_elephant_state_id(target))
        if direct is not None:
            return direct
    if hasattr(repository, "list_states"):
        try:
            states = repository.list_states(elephant_id=target)
        except TypeError:
            states = repository.list_states()
        for state in states:
            if state.elephant_id == target or state.state_anchor in {target, f"elephant:{target}"}:
                return state
    return None


def _resolved_session_skills(
    repository: Any,
    profile_loader: Any,
    skill_runtime: Any,
    session: Episode,
    *,
    prompt_visible_only: bool = False,
) -> tuple[SkillDefinition, ...]:
    """Thin wrapper — delegates to the canonical surface-level resolver.

    Kept so CLI call sites don't have to import ``packages.skills.surface_runtime``
    directly. The resolver reads identity / mode from the State row, not
    ``profile.json``.
    """
    from packages.skills.surface_runtime import resolved_session_skills

    return resolved_session_skills(
        repository=repository,
        profile_loader=profile_loader,
        skill_runtime=skill_runtime,
        session=session,
        surface_kind="cli",
        prompt_visible_only=prompt_visible_only,
    )


def _seed_elephant_identity_text(
    profile: LoadedProfile,
    *,
    display_name: str | None = None,
) -> str:
    current = _current_elephant_identity_text(profile)
    if current is None or _elephant_identity_text_uses_default(profile):
        return _default_elephant_identity_text(
            profile,
            display_name=display_name,
        )
    return current


@dataclass(frozen=True, slots=True)
class CliPaths:
    home_dir: Path
    state_dir: Path
    skills_dir: Path
    builtin_skills_dir: Path
    installed_skills_dir: Path
    authored_skills_dir: Path
    skill_search_cache_dir: Path
    cron_dir: Path
    workspaces_dir: Path
    pairing_dir: Path

    @property
    def database_path(self) -> Path:
        return self.state_dir / "elephant.sqlite3"

    @property
    def snapshot_path(self) -> Path:
        return self.state_dir / "preview-snapshot.json"

    @property
    def cron_jobs_path(self) -> Path:
        return self.cron_dir / "jobs.json"

    @property
    def cron_output_dir(self) -> Path:
        return self.cron_dir / "output"

    @property
    def cron_lock_path(self) -> Path:
        return self.cron_dir / "cron.lock"

    @property
    def secret_key_path(self) -> Path:
        return self.state_dir / "provider-secrets.key"

    def elephant_file_path(self, elephant_id: str) -> Path:
        key = quote(elephant_id.strip(), safe="")
        if not key:
            raise ValueError("elephant id is required")
        return self.workspaces_dir / key


@dataclass(frozen=True, slots=True)
class WakeProgressionResult:
    profile: PersonalModelRuntimeState
    session: Episode
    wake_action: str
    wake_summary: str
    state_focus: str
    applied: bool
    plan: PlanDraft | None
    reconciliation: WakeReconciliationReport
    retrieval: EvidenceRetrievalResult | None = None
    resume_packet: ResumePacket | None = None


@dataclass(frozen=True, slots=True)
class CliVoiceTurnResult:
    input_resolution: VoiceInputResolution
    kernel_outcome: KernelOutcome | None
    voice_turn: VoiceTurnResult


@dataclass(frozen=True, slots=True)
class ContinuityStatus:
    profile: LoadedProfile
    session: Episode
    relationship_policy: RelationshipPolicy
    governance_summary: str
    proactive_summary: str
    initiative: str
    wake_action: str
    wake_summary: str
    wake_factors: tuple[str, ...]
    reengagement_style: str
    reengagement_prompt: str
    continuity_summary: str
    voice_status: str
    voice_identity_binding: str


@dataclass(frozen=True, slots=True)
class EggSummary:
    elephant_id: str
    latest_session_id: str
    latest_status: str
    updated_at: datetime
    session_count: int


@dataclass(frozen=True, slots=True)
class _PlanningRecallRecovery:
    recall_items: tuple[RecallEvidence, ...]
    query: str
    work_item_ids: tuple[str, ...]
    scope_episode_ids: tuple[str, ...]
    scope_reason: str
    retrieval: EvidenceRetrievalResult | None = None
    resume_packet: ResumePacket | None = None
