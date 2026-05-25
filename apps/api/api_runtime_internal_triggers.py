"""Trigger functions for internal dashboard operations."""

from __future__ import annotations

import logging
from typing import Any


LOGGER = logging.getLogger(__name__)


def _latest_default_episode_context(self) -> tuple[object, object, object] | tuple[None, None, None]:
    pm = self.repository.ensure_default_personal_model()
    states = self.repository.list_states(personal_model_id=pm.personal_model_id)
    if not states:
        return pm, None, None
    state = states[0]
    try:
        episodes = self.repository.list_episodes(
            state_id=state.state_id,
            limit=1,
            newest_first=True,
        )
        episode = episodes[0] if episodes else None
    except TypeError:
        episodes = self.repository.list_episodes(state_id=state.state_id)
        episode = episodes[-1] if episodes else None
    return pm, state, episode


def trigger_diary_write(self, *, target_date: str) -> dict[str, Any]:
    """Enqueue a diary write job from the dashboard."""
    from apps.learning_worker_runtime import ensure_learning_worker_running

    pm, state, episode = _latest_default_episode_context(self)
    if state is None:
        return {"status": "error", "detail": "no states available"}
    if episode is None:
        return {"status": "error", "detail": "no episodes available"}
    metadata: dict[str, str] = {"source": "dashboard.diary"}
    try:
        # Attempt to enqueue journal job
        from datetime import datetime
        target = datetime.strptime(target_date.strip()[:10], "%Y-%m-%d").date()
        metadata["target_date"] = target.isoformat()
    except (ValueError, AttributeError):
        pass
    job = self.repository.enqueue_learning_job(
        job_type="episode_boundary_learning",
        trigger="diary",
        personal_model_id=pm.personal_model_id,
        state_id=state.state_id,
        episode_id=episode.episode_id,
        loop_id=None,
        summary="diary job",
        metadata=metadata,
        force_new=True,
    )
    try:
        ensure_learning_worker_running(state_dir=self.repository.database_path.parent)
    except Exception:
        LOGGER.warning("failed to start learning worker for diary trigger", exc_info=True)
        pass
    return {"status": "queued", "job_id": job.job_id, "target_date": target_date}


def delete_diary_entry(self, *, entry_date: str) -> dict[str, Any]:
    """Delete one diary entry from the dashboard."""
    from datetime import datetime

    try:
        target = datetime.strptime(entry_date.strip()[:10], "%Y-%m-%d").date().isoformat()
    except (ValueError, AttributeError) as error:
        raise ValueError("entry_date must be YYYY-MM-DD") from error
    pm = self.repository.ensure_default_personal_model()
    deleted = self.repository.delete_diary_entry(
        personal_model_id=pm.personal_model_id,
        entry_date=target,
    )
    return {"status": "deleted" if deleted else "not_found", "entry_date": target, "deleted": deleted}


def trigger_reflect_job(self, *, trigger: str, features: str | None = None) -> dict[str, Any]:
    """Enqueue a reflect job from the dashboard."""
    from apps.learning_worker_runtime import ensure_learning_worker_running

    resolved_trigger = trigger or "manual"
    pm, state, episode = _latest_default_episode_context(self)
    if state is None:
        return {"status": "error", "detail": "no states available"}
    if episode is None:
        return {"status": "error", "detail": "no episodes available"}
    metadata: dict[str, str] = {"source": "dashboard.reflect"}
    normalized_trigger = resolved_trigger.strip().lower()
    if features:
        metadata["features"] = features
        from datetime import date as date_type, timedelta

        feature_set = {item.strip() for item in features.split(",") if item.strip()}
        if "dream" in feature_set:
            metadata["target_date"] = date_type.today().isoformat()
        if "diary" in feature_set:
            diary_target_date = (date_type.today() - timedelta(days=1)).isoformat()
            if "dream" in feature_set:
                metadata["diary_target_date"] = diary_target_date
            else:
                metadata["target_date"] = diary_target_date
    if normalized_trigger == "onboarding_letter":
        from datetime import date as date_type

        metadata["target_date"] = date_type.today().isoformat()
        metadata["letter_kind"] = "onboarding_letter"
        metadata["source"] = "onboarding_letter"
    summary_features = _resolved_feature_summary(resolved_trigger, features=features)
    job = self.repository.enqueue_learning_job(
        job_type="episode_boundary_learning",
        trigger=resolved_trigger,
        personal_model_id=pm.personal_model_id,
        state_id=state.state_id,
        episode_id=episode.episode_id,
        loop_id=None,
        summary=f"reflect job (features={summary_features})",
        metadata=metadata,
        force_new=True,
    )
    try:
        ensure_learning_worker_running(state_dir=self.repository.database_path.parent)
    except Exception:
        LOGGER.warning("failed to start learning worker for reflect trigger", exc_info=True)
        pass
    return {"status": "queued", "job_id": job.job_id, "trigger": resolved_trigger, "features": summary_features}


def _resolved_feature_summary(trigger: str, *, features: str | None) -> str:
    explicit = tuple(item.strip() for item in (features or "").split(",") if item.strip())
    try:
        from packages.reflect.features import resolve_features

        resolved = resolve_features(trigger.strip().lower(), explicit_features=explicit or None)
    except Exception:
        LOGGER.warning(
            "failed to resolve reflect feature summary for internal trigger",
            extra={"trigger": trigger, "features": features},
            exc_info=True,
        )
        return features.strip() if features and features.strip() else "default"
    return ",".join(feature.feature_id for feature in resolved) or "default"


__all__ = ["delete_diary_entry", "trigger_diary_write", "trigger_reflect_job"]
