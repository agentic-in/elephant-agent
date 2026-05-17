from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import apps.cli.cli_main_impl as cli_main_impl
from apps.cli.runtime import CliRuntime


class CliRuntimeLearningTest(unittest.TestCase):
    def test_schedule_learning_for_session_enqueues_job_and_surfaces_status(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_dir = root / "state"
            profile_dir = root / "profiles" / "default"
            state_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )

            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.create_elephant(
                elephant_id="atlas",
                display_name="Atlas",
                mode="companion",
            )

            with mock.patch("apps.learning_worker_runtime.ensure_learning_worker_running", return_value=True) as ensure_worker:
                job = runtime.schedule_learning_for_session(
                    session_id=session.episode_id,
                    trigger="clear",
                    summary="fresh loop requested",
                    metadata={"source": "unit-test"},
                )

            ensure_worker.assert_called_once()
            self.assertEqual(job.status, "queued")
            status = runtime.learning_runtime_status(session_id=session.episode_id)
            self.assertTrue(status["active"])
            self.assertEqual(status["queued_count"], 1)
            self.assertEqual(status["running_count"], 0)
            self.assertEqual(status["jobs"][0]["trigger"], "clear")
            self.assertEqual(status["jobs"][0]["status"], "queued")

    def test_cli_elephant_list_hides_synthetic_learning_elephants(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.create_elephant(elephant_id="atlas")
            runtime.create_elephant(elephant_id="learn-live-noop-20260509140344")

            herd = runtime.list_herd(limit=12)

            self.assertEqual({elephant.elephant_id for elephant in herd}, {"atlas"})

    def test_learn_cli_run_list_and_kill(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_dir = root / "state"
            profile_dir = root / "profiles" / "default"
            state_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )
            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.create_elephant(elephant_id="atlas")

            with mock.patch("apps.learning_worker_runtime.ensure_learning_worker_running", return_value=True) as ensure_worker:
                run_exit = cli_main_impl._run_learn(
                    runtime,
                    SimpleNamespace(learn_command="run", elephant_id="atlas", limit=12, wait=False),
                )
            list_exit = cli_main_impl._run_learn(
                runtime,
                SimpleNamespace(learn_command="list", elephant_id="atlas", limit=12),
            )
            with mock.patch("apps.learning_worker_runtime.stop_learning_worker", return_value={"status": "stopped", "stopped_pid": None, "signal_sent": False}) as stop_worker:
                kill_exit = cli_main_impl._run_learn(
                    runtime,
                    SimpleNamespace(learn_command="kill", elephant_id=None, limit=12),
                )

            self.assertEqual(run_exit, 0)
            self.assertEqual(list_exit, 0)
            self.assertEqual(kill_exit, 0)
            ensure_worker.assert_called_once()
            stop_worker.assert_called_once_with(state_dir=runtime.paths.state_dir, reason="operator requested learn kill")
            jobs = runtime.repository.list_learning_jobs(episode_id=session.episode_id)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].trigger, "manual")

    def test_learn_run_wait_uses_subprocess_once_without_starting_background_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.create_elephant(elephant_id="atlas")

            completed = SimpleNamespace(returncode=0)
            with mock.patch("apps.learning_worker_runtime.ensure_learning_worker_running", return_value=True) as ensure_worker:
                with mock.patch.object(cli_main_impl.subprocess, "run", return_value=completed) as run_worker:
                    exit_code = cli_main_impl._run_learn(
                        runtime,
                        SimpleNamespace(learn_command="run", elephant_id="atlas", limit=12, wait=True),
                    )

            self.assertEqual(exit_code, 0)
            ensure_worker.assert_not_called()
            run_worker.assert_called_once()
            command = run_worker.call_args.args[0]
            self.assertEqual(command[:3], (cli_main_impl.sys.executable, "-m", "apps.learning_worker_command"))
            self.assertIn("--once", command)
            self.assertIn(str(runtime.paths.state_dir), command)

    def test_learn_run_marks_job_failed_when_subprocess_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.create_elephant(elephant_id="atlas")
            completed = SimpleNamespace(returncode=139)

            with mock.patch.object(cli_main_impl.subprocess, "run", return_value=completed):
                with mock.patch("apps.learning_worker_runtime.mark_learning_job_terminal_failure") as mark_failed:
                    exit_code = cli_main_impl._run_learn(
                        runtime,
                        SimpleNamespace(learn_command="run", elephant_id="atlas", limit=12, wait=True),
                    )

            self.assertEqual(exit_code, 139)
            mark_failed.assert_called_once()
            _, kwargs = mark_failed.call_args
            self.assertEqual(kwargs["worker_id"], "cli.reflect.run")
            self.assertIn("139", kwargs["error"])

    def test_normal_wake_turn_does_not_start_old_queued_learning_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.create_elephant(elephant_id="atlas")
            runtime.schedule_learning_for_session(
                session_id=session.episode_id,
                trigger="manual",
                start_worker=False,
            )

            with mock.patch("apps.learning_worker_runtime.ensure_learning_worker_running") as ensure_worker:
                runtime.explain_next_step(session_id=session.episode_id, prompt="hi")

            ensure_worker.assert_not_called()

    def test_learning_sub_agent_child_episode_history_is_preserved_after_job_completion(self) -> None:
        from apps.learning_worker_runtime import run_learning_job

        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.create_elephant(elephant_id="atlas")
            child = runtime.open_next_episode(
                session.episode_id,
                reason="learning_child",
                summary="learning child Episode opened",
            ).episode
            job = runtime.schedule_learning_for_session(session_id=session.episode_id, trigger="manual", start_worker=False)
            agent_result = SimpleNamespace(
                status="completed",
                summary="done",
                result_source_id="",
                child_episode_id=child.episode_id,
            )

            with mock.patch("apps.learning_agents.run_background_learning_agent", return_value=agent_result):
                run_learning_job(runtime, job, worker_id="worker:test")

            self.assertIsNotNone(runtime.repository.load_episode(child.episode_id))
            self.assertIsNotNone(runtime.repository.load_episode(session.episode_id))
            self.assertEqual(runtime.repository.load_learning_job(job.job_id).status, "completed")

    def test_background_learning_agent_writes_result_from_summary(self) -> None:
        from apps.learning_agents import run_background_learning_agent

        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.create_elephant(elephant_id="atlas")
            job = runtime.schedule_learning_for_session(
                session_id=session.episode_id,
                trigger="manual",
                summary="unit learning",
                force_new=True,
                start_worker=False,
            )
            with mock.patch.object(
                type(runtime),
                "run_sub_agent",
                return_value={
                    "status": "completed",
                    "summary": "No durable facts found, nothing to write.",
                    "session_id": "episode:learning-child",
                    "side_effects": (),
                },
            ):
                result = run_background_learning_agent(runtime, job)
            loaded = runtime.repository.load_learning_job(job.job_id)

            self.assertEqual(result.status, "no_op")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.result_json["status"], "no_op")
            self.assertIn("No durable facts found", str(loaded.result_json["summary"]))

    def test_once_learning_worker_processes_only_one_queued_job(self) -> None:
        from apps.learning_worker_runtime import run_learning_worker

        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            runtime = CliRuntime.create(state_dir=state_dir)
            first = runtime.create_elephant(elephant_id="atlas")
            second = runtime.create_elephant(elephant_id="nova")
            runtime.schedule_learning_for_session(session_id=first.episode_id, trigger="manual", start_worker=False)
            runtime.schedule_learning_for_session(session_id=second.episode_id, trigger="manual", start_worker=False)

            def complete_one(worker_runtime, job, *, worker_id: str) -> None:
                worker_runtime.repository.complete_learning_job(
                    job.job_id,
                    worker_id=worker_id,
                    progress_detail="test completed one job",
                )

            with mock.patch("apps.learning_worker_runtime.run_learning_job", side_effect=complete_one):
                exit_code = run_learning_worker(state_dir=state_dir, once=True)

            self.assertEqual(exit_code, 0)
            jobs = runtime.repository.list_learning_jobs(statuses=("queued", "completed"))
            statuses = sorted(job.status for job in jobs)
            self.assertEqual(statuses, ["completed", "queued"])


if __name__ == "__main__":
    unittest.main()
