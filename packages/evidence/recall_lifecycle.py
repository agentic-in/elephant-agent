"""Recall policy metadata for newly written Personal Model claims.

This module does not try to understand arbitrary natural language. The primary
source is an explicit, simple `recall_policy` chosen by the foreground agent or
background learning agent while it still has the full writing context. When that
is absent, we apply conservative structural defaults from lens/kind/scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

__all__ = [
    "RecallLifecycleInference",
    "infer_recall_lifecycle_metadata",
]

_ALLOWED_POLICIES = frozenset({"stable", "current", "temporary", "review", "episode"})
_ALLOWED_LIFECYCLES = frozenset({"permanent", "preference", "current_state", "temporal", "review", "episode"})
_POLICY_TO_PRESET: Mapping[str, tuple[str, str, str, str]] = {
    # recall_policy -> (retention_lifecycle, time_sensitivity, verification, review_after_days)
    "stable": ("preference", "low", "on_challenge", ""),
    "current": ("current_state", "high", "on_challenge", "7"),
    "temporary": ("temporal", "high", "expires", "3"),
    "review": ("review", "high", "periodic", "14"),
    "episode": ("episode", "medium", "none", ""),
}
_LIFECYCLE_TO_POLICY: Mapping[str, str] = {
    "permanent": "stable",
    "preference": "stable",
    "current_state": "current",
    "temporal": "temporary",
    "review": "review",
    "episode": "episode",
}
_TIME_METADATA_KEYS = frozenset(
    {
        "effective_at",
        "expires_at",
        "last_verified_at",
        "verified_at",
        "review_after_days",
    }
)


@dataclass(frozen=True, slots=True)
class RecallLifecycleInference:
    metadata: dict[str, str]
    lifecycle: str
    reason: str
    inferred: bool


def _now_iso(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _clean(value: object) -> str:
    return str(value or "").strip().casefold()


def _explicit_policy(metadata: Mapping[str, object]) -> str:
    policy = _clean(metadata.get("recall_policy"))
    return policy if policy in _ALLOWED_POLICIES else ""


def _explicit_lifecycle(metadata: Mapping[str, object]) -> str:
    lifecycle = _clean(
        metadata.get("retention_lifecycle") or metadata.get("lifecycle") or metadata.get("staleness_policy")
    )
    return lifecycle if lifecycle in _ALLOWED_LIFECYCLES else ""


def _structural_policy(
    *,
    lens: str,
    kind: str,
    owner_scope: str,
    metadata: Mapping[str, object],
) -> tuple[str, str, str]:
    resolved_lens = _clean(lens or metadata.get("lens"))
    resolved_kind = _clean(kind or metadata.get("component_family") or metadata.get("component_kind"))
    resolved_scope = _clean(owner_scope)
    stability = _clean(metadata.get("stability"))
    signal_type = _clean(metadata.get("signal_type"))

    if resolved_scope == "episode" or resolved_kind == "episodic_index":
        return "episode", "structural_default", "episode_scope"
    if resolved_scope == "state":
        return "current", "structural_default", "state_scope"
    if _clean(metadata.get("source")) == "personal_model_evolution" and stability == "single_episode":
        return "current", "structural_default", "single_episode_learning_signal"
    if signal_type in {"explicit_preference", "correction_signal"}:
        return "stable", "structural_default", "explicit_preference_or_correction"
    if stability in {"stable_trait", "recurring_theme"}:
        return "stable", "structural_default", f"stability.{stability}"
    if resolved_lens == "chapter":
        return "current", "structural_default", "chapter_lens"
    if resolved_lens in {"trait", "rapport"}:
        return "stable", "structural_default", f"{resolved_lens}_lens"
    if resolved_kind in {"style", "relationship", "procedural"}:
        return "stable", "structural_default", f"{resolved_kind}_kind"
    return "stable", "structural_default", "default_personal_model_claim"


def infer_recall_lifecycle_metadata(
    *,
    lens: str = "",
    topic: str = "",
    text: str = "",
    source: str = "",
    kind: str = "",
    owner_scope: str = "personal_model",
    metadata: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> RecallLifecycleInference:
    del topic, text, source
    base = {str(k): str(v) for k, v in dict(metadata or {}).items() if v is not None}
    explicit_policy = _explicit_policy(base)
    explicit_lifecycle = _explicit_lifecycle(base)
    if explicit_policy:
        policy = explicit_policy
        policy_source = "explicit"
        reason = "explicit_policy"
        inferred = False
    elif explicit_lifecycle:
        policy = _LIFECYCLE_TO_POLICY[explicit_lifecycle]
        policy_source = "explicit_lifecycle"
        reason = "explicit_lifecycle"
        inferred = False
    else:
        policy, policy_source, reason = _structural_policy(
            lens=lens,
            kind=kind,
            owner_scope=owner_scope,
            metadata=base,
        )
        inferred = True

    lifecycle, time_sensitivity, verification, default_review_days = _POLICY_TO_PRESET[policy]
    if explicit_lifecycle:
        lifecycle = explicit_lifecycle
    stamp = _now_iso(now)
    base.setdefault("recall_policy", policy)
    base.setdefault("recall_policy_source", policy_source)
    base.setdefault("recall_policy_confidence", "high" if not inferred else "medium")
    base.setdefault("retention_lifecycle", lifecycle)
    base.setdefault("recall_time_sensitivity", time_sensitivity)
    base.setdefault("recall_verification", verification)
    base.setdefault("lifecycle_inferred", "true" if inferred else "false")
    base.setdefault("lifecycle_reason", reason)
    base.setdefault("effective_at", stamp)
    if policy in {"current", "temporary", "review"}:
        base.setdefault("last_verified_at", stamp)
    if default_review_days:
        base.setdefault("review_after_days", default_review_days)
    for key in _TIME_METADATA_KEYS:
        if key in base:
            base[key] = str(base[key])
    return RecallLifecycleInference(
        metadata=base,
        lifecycle=lifecycle,
        reason=reason,
        inferred=inferred,
    )
