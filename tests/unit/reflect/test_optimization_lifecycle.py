from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from packages.reflect import (
    apply_approved_optimization,
    find_candidate_by_ref,
    find_candidate_by_topic,
    mark_candidate_review_status,
    optimization_candidate_topic,
    persist_optimization_candidate,
    write_optimization_candidate,
)
from packages.reflect.types import SkillOptimizationCandidate
from packages.skills.authoring import write_skill_package
from packages.skills.runtime import SkillManifestLoadRecord, load_skill_package_definition
from packages.storage import RuntimeStorageRepository
from packages.understanding import PersonalModelUnderstandingSurface


class _SkillSurface:
    def __init__(self, root: Path, *, source_kind: str) -> None:
        self._root = root / source_kind
        self._source_kind = source_kind
        self.skill_dir = write_skill_package(
            self._root,
            skill_id="python-development",
            display_name="Python Development",
            summary="Python workflow help",
            instruction_text="Use tool.terminal.exec before tool.file.read.",
            overwrite=True,
            source_kind=source_kind,
        )
        self.update_calls = 0

    def inspect_skill(self, skill_id: str, *, session_id: str | None = None):
        del session_id
        definition = load_skill_package_definition(self.skill_dir)
        metadata = dict(definition.metadata)
        metadata.update(
            {
                "source_kind": self._source_kind,
                "source_id": self._source_kind,
                "hub_reference": f"{self._source_kind}:{skill_id}",
            }
        )
        return replace(definition, metadata=metadata)

    def update_authored_skill(
        self,
        skill_id: str,
        *,
        display_name: str | None = None,
        summary: str | None = None,
        instruction_text: str | None = None,
        category: str | None = None,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        del category, profile_id, session_id
        self.update_calls += 1
        if self._source_kind != "elephant-authored":
            raise AssertionError("non-authored skill should never be updated")
        current = self.inspect_skill(skill_id)
        write_skill_package(
            self._root,
            skill_id=skill_id,
            display_name=display_name or current.display_name,
            summary=summary or current.summary,
            instruction_text=instruction_text or current.instruction_text,
            overwrite=True,
            source_kind=self._source_kind,
        )
        return SkillManifestLoadRecord(
            source_path=str(self.skill_dir),
            skill_ids=(skill_id,),
            loaded_at=datetime.now(timezone.utc),
            status="loaded",
        )

    def list_skills(self):
        return (self.inspect_skill("python-development"),)


def _candidate(*, occurrence_count: int = 5, confidence: float = 0.82) -> SkillOptimizationCandidate:
    return SkillOptimizationCandidate(
        candidate_id="cand_skillopt_python",
        target_skill_id="python-development",
        target_index_id="python_development",
        optimization_type="update_procedure",
        supporting_signals=("sig-1",),
        confidence=confidence,
        summary="tool.terminal.exec -> tool.file.read recurred across closed episodes",
        suggested_action="Update python-development to encode the repeated tool sequence tool.terminal.exec -> tool.file.read.",
        candidate_key="update_procedure_ab12cd34",
        metadata={
            "signal_type": "recurring_sequence",
            "occurrence_count": str(occurrence_count),
            "confidence": f"{confidence:.2f}",
        },
    )


class OptimizationLifecycleTest(unittest.TestCase):
    def test_write_optimization_candidate_persists_review_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-skill", elephant_name="Skill")
            surface = PersonalModelUnderstandingSurface(repository=repository)

            result = write_optimization_candidate(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                candidate=_candidate(),
            )
            stored = find_candidate_by_topic(
                repository,
                personal_model_id=state.personal_model_id,
                topic=optimization_candidate_topic(_candidate()),
                fact_status="active",
            )

        self.assertEqual(result["claim"]["topic"], "world.skills.optimization.python_development.update_procedure_ab12cd34")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.review_status, "pending")
        self.assertEqual(stored.recall_policy, "review")
        self.assertEqual(stored.retention_lifecycle, "draft")
        self.assertEqual(stored.metadata["projection_policy"], "skill_optimization_candidate")

    def test_persist_optimization_candidate_corrects_materially_stronger_pending_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-skill", elephant_name="Skill")
            surface = PersonalModelUnderstandingSurface(repository=repository)

            first = persist_optimization_candidate(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                candidate=_candidate(occurrence_count=3, confidence=0.72),
            )
            updated = persist_optimization_candidate(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                candidate=_candidate(occurrence_count=5, confidence=0.86),
            )
            active = find_candidate_by_topic(
                repository,
                personal_model_id=state.personal_model_id,
                topic=optimization_candidate_topic(_candidate()),
                fact_status="active",
            )
            retired = find_candidate_by_ref(
                repository,
                personal_model_id=state.personal_model_id,
                ref=first["claim"]["ref"],
                fact_status="retired",
            )

        self.assertNotEqual(first["claim"]["ref"], updated["claim"]["ref"])
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.occurrence_count, 5)
        self.assertEqual(active.review_status, "pending")
        self.assertIsNotNone(retired)

    def test_mark_candidate_review_status_requires_exact_ref_and_valid_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-skill", elephant_name="Skill")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            created = write_optimization_candidate(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                candidate=_candidate(),
            )

            with self.assertRaises(ValueError):
                mark_candidate_review_status(
                    surface,
                    "session-skill",
                    personal_model_id=state.personal_model_id,
                    ref="",
                    review_status="approved",
                )

            approved = mark_candidate_review_status(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                ref=created["claim"]["ref"],
                review_status="approved",
            )

            with self.assertRaises(ValueError):
                mark_candidate_review_status(
                    surface,
                    "session-skill",
                    personal_model_id=state.personal_model_id,
                    ref=approved["claim"]["ref"],
                    review_status="rejected",
                )

        self.assertEqual(approved["claim"]["topic"], "world.skills.optimization.python_development.update_procedure_ab12cd34")

    def test_apply_approved_optimization_updates_authored_skill_and_marks_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-skill", elephant_name="Skill")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            skill_surface = _SkillSurface(Path(tmpdir) / "skills", source_kind="elephant-authored")
            created = write_optimization_candidate(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                candidate=_candidate(),
            )
            approved = mark_candidate_review_status(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                ref=created["claim"]["ref"],
                review_status="approved",
            )

            applied = apply_approved_optimization(
                surface,
                skill_surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                ref=approved["claim"]["ref"],
            )
            active = find_candidate_by_ref(
                repository,
                personal_model_id=state.personal_model_id,
                ref=applied["ref"],
                fact_status="active",
            )
            skill_text = load_skill_package_definition(skill_surface.skill_dir).instruction_text

        self.assertTrue(applied["applied"])
        self.assertEqual(skill_surface.update_calls, 1)
        self.assertIn("Reviewed optimization", skill_text)
        self.assertIn("skill-optimization:update_procedure_ab12cd34", skill_text)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.review_status, "applied")

    def test_apply_approved_optimization_keeps_non_authored_skill_as_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-skill", elephant_name="Skill")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            skill_surface = _SkillSurface(Path(tmpdir) / "skills", source_kind="builtin")
            created = write_optimization_candidate(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                candidate=_candidate(),
            )
            approved = mark_candidate_review_status(
                surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                ref=created["claim"]["ref"],
                review_status="approved",
            )

            result = apply_approved_optimization(
                surface,
                skill_surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                ref=approved["claim"]["ref"],
            )
            active = find_candidate_by_ref(
                repository,
                personal_model_id=state.personal_model_id,
                ref=approved["claim"]["ref"],
                fact_status="active",
            )

        self.assertFalse(result["applied"])
        self.assertEqual(result["status"], "approved")
        self.assertEqual(skill_surface.update_calls, 0)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.review_status, "approved")


if __name__ == "__main__":
    unittest.main()
