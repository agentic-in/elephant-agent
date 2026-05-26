from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from typer.testing import CliRunner

import apps.cli.cli_main_impl as cli_main_impl


class ReflectCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.app = cli_main_impl.build_typer_app()

    def test_reflect_run_help_mentions_trigger_and_skill_evolution(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            result = self.runner.invoke(
                self.app,
                ["--state-dir", tempdir, "reflect", "run", "--help"],
            )

        rendered = result.output

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--preset", rendered)
        self.assertIn("skill-evolution", rendered)
        self.assertIn("--trigger", rendered)
        self.assertIn("skill_review", rendered)
        self.assertIn("skill_affinity", rendered)
        self.assertIn("skill_evolution", rendered)

    def test_reflect_run_accepts_skill_review_trigger_and_feature_override(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            fake_runtime = SimpleNamespace(paths=SimpleNamespace(state_dir=Path(tempdir)))
            fake_job = SimpleNamespace(job_id="job-skill-review")
            with (
                mock.patch.object(cli_main_impl, "_cli_runtime", return_value=fake_runtime),
                mock.patch.object(cli_main_impl, "_queue_learning_job", return_value=fake_job) as queue_job,
                mock.patch.object(cli_main_impl, "_print_cli_card"),
            ):
                result = self.runner.invoke(
                    self.app,
                    [
                        "--state-dir",
                        tempdir,
                        "reflect",
                        "run",
                        "--trigger",
                        "skill_review",
                        "--features",
                        "skill_optimization",
                    ],
                )

        self.assertEqual(result.exit_code, 0)
        _, kwargs = queue_job.call_args
        self.assertEqual(kwargs["trigger"], "skill_review")
        self.assertEqual(kwargs["extra_metadata"], {"features": "skill_optimization"})
        self.assertTrue(kwargs["force_new"])
        self.assertTrue(kwargs["start_worker"])

    def test_reflect_run_accepts_skill_evolution_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            fake_runtime = SimpleNamespace(paths=SimpleNamespace(state_dir=Path(tempdir)))
            fake_job = SimpleNamespace(job_id="job-skill-evolution")
            with (
                mock.patch.object(cli_main_impl, "_cli_runtime", return_value=fake_runtime),
                mock.patch.object(cli_main_impl, "_queue_learning_job", return_value=fake_job) as queue_job,
                mock.patch.object(cli_main_impl, "_print_cli_card"),
            ):
                result = self.runner.invoke(
                    self.app,
                    [
                        "--state-dir",
                        tempdir,
                        "reflect",
                        "run",
                        "--preset",
                        "skill-evolution",
                    ],
                )

        self.assertEqual(result.exit_code, 0)
        _, kwargs = queue_job.call_args
        self.assertEqual(kwargs["trigger"], "skill_review")
        self.assertIsNone(kwargs["extra_metadata"])

    def test_reflect_run_rejects_preset_with_feature_override(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            fake_runtime = SimpleNamespace(paths=SimpleNamespace(state_dir=Path(tempdir)))
            with (
                mock.patch.object(cli_main_impl, "_cli_runtime", return_value=fake_runtime),
                mock.patch.object(cli_main_impl, "_print_cli_card"),
            ):
                result = self.runner.invoke(
                    self.app,
                    [
                        "--state-dir",
                        tempdir,
                        "reflect",
                        "run",
                        "--preset",
                        "dream",
                        "--features",
                        "diary",
                    ],
                )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--preset cannot be combined", result.output)

    def test_reflect_run_dream_trigger_without_features_sets_target_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            fake_runtime = SimpleNamespace(paths=SimpleNamespace(state_dir=Path(tempdir)))
            fake_job = SimpleNamespace(job_id="job-dream")
            with (
                mock.patch.object(cli_main_impl, "_cli_runtime", return_value=fake_runtime),
                mock.patch.object(cli_main_impl, "_queue_learning_job", return_value=fake_job) as queue_job,
                mock.patch.object(cli_main_impl, "_print_cli_card"),
            ):
                result = self.runner.invoke(
                    self.app,
                    [
                        "--state-dir",
                        tempdir,
                        "reflect",
                        "run",
                        "--trigger",
                        "dream",
                        "--date",
                        "2026-05-19",
                    ],
                )

        self.assertEqual(result.exit_code, 0)
        _, kwargs = queue_job.call_args
        self.assertEqual(kwargs["trigger"], "dream")
        self.assertEqual(
            kwargs["extra_metadata"],
            {
                "target_date": "2026-05-19",
                "diary_target_date": "2026-05-19",
            },
        )

    def test_reflect_run_rejects_invalid_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            fake_runtime = SimpleNamespace(paths=SimpleNamespace(state_dir=Path(tempdir)))
            with (
                mock.patch.object(cli_main_impl, "_cli_runtime", return_value=fake_runtime),
                mock.patch.object(cli_main_impl, "_print_cli_card"),
            ):
                result = self.runner.invoke(
                    self.app,
                    ["--state-dir", tempdir, "reflect", "run", "--trigger", "not-a-trigger"],
                )

        rendered = result.output

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--trigger must be one of", rendered)


if __name__ == "__main__":
    unittest.main()
