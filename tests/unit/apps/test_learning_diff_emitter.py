from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

import apps as _apps_pkg

_SOURCE_APPS = Path(__file__).resolve().parents[3] / "apps"
if str(_SOURCE_APPS) not in _apps_pkg.__path__:
    _apps_pkg.__path__.insert(0, str(_SOURCE_APPS))

from apps.cli.runtime import CliRuntime
from apps.reflect.evidence import build_evidence
from apps.reflect.features import resolve_features
from packages.contracts import Fact


class LearningResultWriteTests(unittest.TestCase):
    def test_learning_context_packet_uses_basic_anchors_and_tool_directives(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.create_elephant(elephant_id="atlas")
            now = datetime.now(timezone.utc)
            runtime.repository.upsert_personal_model_fact(
                Fact(
                    fact_id="fact:name",
                    personal_model_id=session.personal_model_id,
                    lens="identity",
                    text="称呼：zoey。",
                    confidence=1.0,
                    committed_at=now,
                    source="user_explicit",
                    metadata={"topic": "identity.anchor.name.preferred"},
                )
            )
            runtime.repository.upsert_personal_model_fact(
                Fact(
                    fact_id="fact:language",
                    personal_model_id=session.personal_model_id,
                    lens="identity",
                    text="第一语言：中文。",
                    confidence=1.0,
                    committed_at=now,
                    source="user_explicit",
                    metadata={"topic": "identity.style.language.first"},
                )
            )
            runtime.repository.upsert_personal_model_fact(
                Fact(
                    fact_id="fact:full",
                    personal_model_id=session.personal_model_id,
                    lens="world",
                    text="This should be queried through tools, not preloaded.",
                    confidence=1.0,
                    committed_at=now,
                    source="user_explicit",
                    metadata={"topic": "world.project.private.detail"},
                )
            )
            job = runtime.schedule_learning_for_session(session_id=session.episode_id, trigger="manual", start_worker=False)

            packet = build_evidence(runtime, job, resolve_features("manual"))

            self.assertIn("## User anchors", packet)
            self.assertIn("preferred_name: 称呼：zoey。", packet)
            self.assertIn("first_language: 第一语言：中文。", packet)
            self.assertIn("features: pm, questions, skill_affinity", packet)
            self.assertNotIn("This should be queried through tools", packet)
            self.assertNotIn("## Active PM facts", packet)
            self.assertNotIn("## Open/asked questions", packet)
            self.assertNotIn("## Available prompt-visible skills", packet)

    def test_learning_result_tool_writes_result_json(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            (root / "profile.json").write_text(
                json.dumps({"profile_id": "profile-companion", "display_name": "Elephant Agent", "mode": "companion"}),
                encoding="utf-8",
            )
            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.create_elephant(elephant_id="atlas")
            job = runtime.schedule_learning_for_session(
                session_id=session.episode_id,
                trigger="manual",
                summary="unit learning",
                force_new=True,
                start_worker=False,
            )

            result = runtime.write_learning_result(
                session_id=session.episode_id,
                job_id=job.job_id,
                mode="manual",
                status="completed",
                summary="result written by governed tool",
                pm_facts={"created": ["fact:1"]},
                skill_affinities={"included": ["fact:skill"]},
                questions={"next_ask_candidates": ["question:1"]},
                context={"should_refresh_skill_index": True},
            )

            self.assertEqual(result["status"], "completed")
            loaded = runtime.repository.load_learning_job(job.job_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            payload = dict(loaded.result_json)
            self.assertEqual(payload["job_id"], job.job_id)
            self.assertEqual(payload["summary"], "result written by governed tool")
            self.assertEqual(payload["pm_facts"]["created_refs"], ["fact:1"])
            self.assertEqual(payload["skill_affinities"]["included_refs"], ["fact:skill"])
            self.assertEqual(payload["questions"]["next_ask_candidate_ids"], ["question:1"])
            self.assertTrue(payload["context"]["should_refresh_skill_index"])


if __name__ == "__main__":
    unittest.main()
