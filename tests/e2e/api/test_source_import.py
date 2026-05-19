from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api import create_app


class SourceImportE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.app = create_app(
            database_path=self.root / "api.sqlite3",
            install_root=self.root,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_source_import_creates_evidence_without_direct_personal_model_truth(self) -> None:
        source_root = self.root / "sample-project"
        (source_root / "src").mkdir(parents=True)
        (source_root / "node_modules" / "pkg").mkdir(parents=True)
        (source_root / "README.md").write_text("# Launch Plan\n\nShip a mac-first desktop shell.\n", encoding="utf-8")
        (source_root / "src" / "app.py").write_text("def main():\n    return 'context in minutes'\n", encoding="utf-8")
        (source_root / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
        (source_root / "node_modules" / "pkg" / "ignored.js").write_text("ignored()", encoding="utf-8")

        created = self.app.dispatch(
            "POST",
            "/v1/herd",
            body=self._body({"display_name": "Atlas", "elephant_id": "atlas"}),
        )
        self.assertEqual(created.status_code, 201)

        with patch("apps.learning_worker_runtime.ensure_learning_worker_running") as worker:
            response = self.app.dispatch(
                "POST",
                "/v1/sources/import",
                body=self._body(
                    {
                        "paths": [str(source_root)],
                        "elephant_id": "atlas",
                        "mode": "profile_builder",
                    }
                ),
            )

        self.assertEqual(response.status_code, 201)
        payload = response.payload
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["admitted_count"], 2)
        self.assertEqual(payload["skipped_reasons"]["secret_like"], 1)
        self.assertIsNotNone(payload["episode_id"])
        self.assertIsNotNone(payload["job_id"])
        worker.assert_called_once()

        status = self.app.dispatch("GET", f"/v1/sources/imports/{payload['import_id']}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.payload["import_id"], payload["import_id"])
        self.assertEqual(status.payload["progress"], 100)

        episode = self.app.repository.load_episode(str(payload["episode_id"]))
        self.assertIsNotNone(episode)
        self.assertEqual(episode.status, "closed")
        loops = self.app.repository.list_loops(episode_id=str(payload["episode_id"]))
        self.assertEqual(len(loops), 1)
        steps = self.app.repository.list_steps(loop_id=loops[0].loop_id)
        self.assertEqual(len(steps), 2)
        self.assertTrue(all(step.action == "source_import" for step in steps))
        self.assertTrue(any("README.md" in step.summary for step in steps))

        semantic_entries = self.app.repository.list_semantic_index_entries(state_id=episode.state_id)
        self.assertEqual(len(semantic_entries), 2)
        jobs = self.app.repository.list_learning_jobs(episode_id=episode.episode_id)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].trigger, "init_profile")

        facts = self.app.repository.list_personal_model_facts(
            personal_model_id=episode.personal_model_id,
            status=("active", "inactive", "disputed", "deleted"),
        )
        self.assertEqual(facts, ())

    @staticmethod
    def _body(payload: dict[str, object]) -> bytes:
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
