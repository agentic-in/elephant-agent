from __future__ import annotations

from datetime import date as date_type, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.api.api_runtime_internal_methods import _learning_job_runtime_contract
from apps.api.api_runtime_internal_triggers import trigger_reflect_job


class _RepositoryStub:
    database_path = Path("/tmp/elephant/state.db")

    def __init__(self) -> None:
        self.enqueued_metadata: dict[str, str] | None = None
        self.enqueued_summary = ""

    def ensure_default_personal_model(self) -> SimpleNamespace:
        return SimpleNamespace(personal_model_id="pm")

    def list_states(self, *, personal_model_id: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(state_id=f"state:{personal_model_id}")]

    def list_episodes(self, *, state_id: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(episode_id=f"episode:{state_id}")]

    def enqueue_learning_job(self, **kwargs: object) -> SimpleNamespace:
        self.enqueued_metadata = dict(kwargs["metadata"])  # type: ignore[arg-type]
        self.enqueued_summary = str(kwargs.get("summary") or "")
        return SimpleNamespace(job_id="job:reflect")


class InternalReflectTriggerTest(unittest.TestCase):
    def test_reflect_dream_diary_features_get_separate_target_dates(self) -> None:
        repository = _RepositoryStub()
        app = SimpleNamespace(repository=repository)

        with patch("apps.learning_worker_runtime.ensure_learning_worker_running", lambda **_: None):
            result = trigger_reflect_job(app, trigger="manual", features="dream,diary")

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["features"], "dream,diary")
        self.assertIsNotNone(repository.enqueued_metadata)
        metadata = repository.enqueued_metadata or {}
        self.assertEqual(metadata["features"], "dream,diary")
        self.assertEqual(metadata["target_date"], date_type.today().isoformat())
        self.assertEqual(metadata["diary_target_date"], (date_type.today() - timedelta(days=1)).isoformat())

    def test_reflect_diary_feature_defaults_to_yesterday(self) -> None:
        repository = _RepositoryStub()
        app = SimpleNamespace(repository=repository)

        with patch("apps.learning_worker_runtime.ensure_learning_worker_running", lambda **_: None):
            trigger_reflect_job(app, trigger="manual", features="diary")

        metadata = repository.enqueued_metadata or {}
        self.assertEqual(metadata["target_date"], (date_type.today() - timedelta(days=1)).isoformat())
        self.assertNotIn("diary_target_date", metadata)

    def test_reflect_init_profile_summary_uses_resolved_features(self) -> None:
        repository = _RepositoryStub()
        app = SimpleNamespace(repository=repository)

        with patch("apps.learning_worker_runtime.ensure_learning_worker_running", lambda **_: None):
            result = trigger_reflect_job(app, trigger="init_profile", features=None)

        self.assertEqual(result["features"], "pm,questions,skills,init_links")
        self.assertEqual(repository.enqueued_summary, "reflect job (features=pm,questions,skills,init_links)")

    def test_reflect_onboarding_letter_sets_letter_metadata(self) -> None:
        repository = _RepositoryStub()
        app = SimpleNamespace(repository=repository)

        with patch("apps.learning_worker_runtime.ensure_learning_worker_running", lambda **_: None):
            result = trigger_reflect_job(app, trigger="onboarding_letter", features=None)

        self.assertEqual(result["features"], "onboarding_letter")
        metadata = repository.enqueued_metadata or {}
        self.assertEqual(metadata["source"], "onboarding_letter")
        self.assertEqual(metadata["letter_kind"], "onboarding_letter")
        self.assertEqual(metadata["target_date"], date_type.today().isoformat())
        self.assertEqual(repository.enqueued_summary, "reflect job (features=onboarding_letter)")

    def test_learning_job_runtime_contract_exposes_init_tools(self) -> None:
        features, tools = _learning_job_runtime_contract("init_profile", metadata={})

        self.assertEqual(features, ("pm", "questions", "skills", "init_links"))
        self.assertIn("tool.personal_model.update", tools)
        self.assertIn("tool.skill.list", tools)
        self.assertIn("tool.web.read", tools)

    def test_learning_job_runtime_contract_exposes_onboarding_letter_tools(self) -> None:
        features, tools = _learning_job_runtime_contract("onboarding_letter", metadata={})

        self.assertEqual(features, ("onboarding_letter",))
        self.assertIn("tool.diary.write", tools)
        self.assertIn("tool.personal_model.search", tools)


if __name__ == "__main__":
    unittest.main()
