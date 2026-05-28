from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from packages.storage import RuntimeStorageRepository
from packages.context.epoch_store import FileEpochStore
from packages.tools.handlers_paths import run_path_action
from packages.tools.path_management import RepositoryPathManagementSurface
from packages.tools.runtime import ToolInvocation


class _StubSummaryIndexer:
    def __init__(self) -> None:
        self.calls = []

    def index_learning_summary(self, summary, *, path_step=None, path=None):
        self.calls.append((summary, path_step, path))
        return summary


class PathManagementToolTest(unittest.TestCase):
    def test_path_management_tool_runs_full_learning_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            surface = RepositoryPathManagementSurface(repository)

            created = run_path_action(
                ToolInvocation(
                    invocation_id="tool-call:create-path",
                    tool_id="tool.paths.manage",
                    session_id="session:path-tool",
                    arguments={
                        "action": "create_path",
                        "title": "Healthy rhythm",
                        "review_mode": "trusted",
                        "steps": [{"title": "Draft week one", "assignee_elephant_id": "baby-coach"}],
                    },
                ),
                surface=surface,
            )
            path = repository.list_paths()[0]
            step = repository.list_path_steps(path_id=path.path_id)[0]

            moved = surface.manage_paths(
                "session:path-tool",
                action="move_step",
                path_step_id=step.path_step_id,
                status="moving",
            )
            summary = surface.manage_paths(
                "session:path-tool",
                action="write_summary",
                path_id=path.path_id,
                what_done="Turned the first week into a checkable loop.",
                why_it_matters="The user can review the concrete change.",
                how_it_was_done="Separated goal, cadence, and next action.",
                knowledge="Habit loops need small repeatable triggers.",
                human_takeaway="A plan is useful when it can be checked.",
            )
            checking_step = repository.load_path_step(step.path_step_id)
            check = surface.manage_paths(
                "session:path-tool",
                action="check_understanding",
                summary_id=summary["summary"]["summary_id"],
                status="understood",
            )
            understood_step = repository.load_path_step(step.path_step_id)

        self.assertEqual(created["outcome"], "success")
        self.assertIn("Healthy rhythm", created["summary"])
        self.assertEqual(moved["step"]["status"], "moving")
        self.assertEqual(summary["understanding_check"]["status"], "pending")
        self.assertEqual(check["understanding_check"]["status"], "understood")
        self.assertIsNotNone(checking_step)
        self.assertIsNotNone(understood_step)
        assert checking_step is not None
        assert understood_step is not None
        self.assertEqual(checking_step.status, "checking")
        self.assertEqual(understood_step.status, "done")

    def test_write_summary_can_infer_step_from_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            indexer = _StubSummaryIndexer()
            surface = RepositoryPathManagementSurface(repository, semantic_summary_indexer=indexer)

            created = surface.manage_paths(
                "session:path-tool",
                action="create_path",
                title="Tool repair",
                steps=[{"title": "Fix macOS tool fallback"}],
            )
            step_id = created["path"]["steps"][0]["path_step_id"]
            run = surface.manage_paths(
                "session:path-tool",
                action="create_run",
                path_step_id=step_id,
                run_id="run:tool:macos",
            )
            summary = surface.manage_paths(
                "session:path-tool",
                action="write_summary",
                run_id=run["run"]["run_id"],
                what_done="Made the tool resilient to macOS runtime differences.",
            )

        self.assertEqual(summary["summary"]["path_step_id"], step_id)
        self.assertEqual(summary["understanding_check"]["status"], "pending")
        self.assertEqual(len(indexer.calls), 1)
        self.assertEqual(indexer.calls[0][0].summary_id, summary["summary"]["summary_id"])
        self.assertEqual(indexer.calls[0][1].path_step_id, step_id)

    def test_write_comment_projects_to_session_epoch_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            surface = RepositoryPathManagementSurface(repository)

            created = surface.manage_paths(
                "session:path-tool",
                action="create_path",
                title="Comment projection",
                steps=[{"title": "Keep history ordered"}],
            )
            step_id = created["path"]["steps"][0]["path_step_id"]
            surface.manage_paths(
                "session:path-tool",
                action="write_comment",
                path_step_id=step_id,
                body="First assistant result.",
                author_kind="elephant",
                comment_id="comment:assistant:1",
            )
            surface.manage_paths(
                "session:path-tool",
                action="write_comment",
                path_step_id=step_id,
                body="Follow-up user instruction.",
                author_kind="user",
                comment_id="comment:user:2",
            )
            surface.manage_paths(
                "session:path-tool",
                action="write_comment",
                path_step_id=step_id,
                body="Second assistant result.",
                author_kind="elephant",
                comment_id="comment:assistant:3",
            )
            epoch = FileEpochStore(repository.database_path.parent).load("session:path-tool")

        self.assertIsNotNone(epoch)
        assert epoch is not None
        self.assertEqual([message.role for message in epoch.history_messages], ["assistant", "user", "assistant"])
        self.assertEqual([message.content for message in epoch.history_messages], [
            "First assistant result.",
            "Follow-up user instruction.",
            "Second assistant result.",
        ])

    def test_path_management_tool_controls_runs_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            surface = RepositoryPathManagementSurface(repository)

            created = surface.manage_paths(
                "session:path-tool",
                action="create_path",
                title="Elephant agent path",
                steps=[{"title": "Wire durable run state", "assignee_elephant_id": "baby:codex"}],
            )
            step_id = created["path"]["steps"][0]["path_step_id"]
            run_created = surface.manage_paths(
                "session:path-tool",
                action="create_run",
                path_step_id=step_id,
                run_id="run:tool:first",
                max_attempts=2,
            )
            run_running = surface.manage_paths(
                "session:path-tool",
                action="update_run",
                run_id="run:tool:first",
                status="running",
                progress_stage="build",
                progress_detail="Adding controls",
                progress_current=1,
                progress_total=2,
            )
            run_failed = surface.manage_paths(
                "session:path-tool",
                action="update_run",
                run_id="run:tool:first",
                status="failed",
                failure_reason="timeout",
            )
            run_retry = surface.manage_paths(
                "session:path-tool",
                action="retry_run",
                run_id="run:tool:first",
                reason="timeout",
            )
            summary = surface.manage_paths(
                "session:path-tool",
                action="write_summary",
                path_step_id=step_id,
                run_id=run_retry["run"]["run_id"],
                what_done="Added durable run state.",
                knowledge="Run state and card state are separate control loops.",
            )
            step = repository.load_path_step(step_id)

        self.assertEqual(run_created["run"]["status"], "queued")
        self.assertEqual(run_created["step"]["active_run"]["run_id"], "run:tool:first")
        self.assertEqual(run_running["run"]["progress_stage"], "build")
        self.assertEqual(run_running["run"]["progress_current"], 1)
        self.assertEqual(run_failed["run"]["failure_reason"], "timeout")
        self.assertEqual(run_failed["step"]["status"], "stuck")
        self.assertEqual(run_retry["run"]["attempt"], 2)
        self.assertEqual(run_retry["run"]["metadata"]["retry_of"], "run:tool:first")
        self.assertEqual(summary["understanding_check"]["status"], "pending")
        self.assertIsNotNone(step)
        assert step is not None
        self.assertEqual(step.status, "checking")

    def test_tool_can_create_baby_and_delete_path_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            surface = RepositoryPathManagementSurface(repository)

            baby = surface.manage_paths(
                "session:path-tool",
                action="create_baby",
                display_name="Research baby elephant",
                role_title="research",
                role_prompt="Investigate context before Mother plans.",
                provider_id="openai",
                provider_model="gpt-5.4",
                engine_id="codex",
                tool_ids=["tool.paths.manage", "tool.memory.search"],
                skill_ids=["research"],
            )
            created = surface.manage_paths(
                "session:path-tool",
                action="create_path",
                title="Research path",
                steps=[{"title": "Read source material"}],
            )
            step_id = created["path"]["steps"][0]["path_step_id"]
            deleted_step = surface.manage_paths(
                "session:path-tool",
                action="delete_step",
                path_step_id=step_id,
            )
            deleted_path = surface.manage_paths(
                "session:path-tool",
                action="delete_path",
                path_id=created["path"]["path_id"],
            )

        self.assertEqual(baby["baby"]["herd_kind"], "baby")
        self.assertEqual(baby["baby"]["role_title"], "research")
        self.assertEqual(baby["baby"]["backend"], "provider")
        self.assertEqual(baby["baby"]["provider_model"], "gpt-5.4")
        self.assertEqual(baby["baby"]["engine_id"], "codex")
        self.assertEqual(baby["baby"]["tool_ids"], "tool.paths.manage, tool.memory.search")
        self.assertEqual(baby["baby"]["skill_ids"], "research")
        self.assertTrue(deleted_step["deleted"])
        self.assertEqual(deleted_step["path_step_id"], step_id)
        self.assertTrue(deleted_path["deleted"])

    def test_tool_create_baby_uses_runtime_id_for_local_cli_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            surface = RepositoryPathManagementSurface(repository)

            baby = surface.manage_paths(
                "session:path-tool",
                action="create_baby",
                display_name="Codex baby elephant",
                role_title="implementation",
                runtime_id="local-agent:codex:test",
                engine_id="codex",
            )

        self.assertEqual(baby["baby"]["backend"], "local_cli")
        self.assertEqual(baby["baby"]["runtime_id"], "local-agent:codex:test")
        self.assertEqual(baby["baby"]["engine_id"], "codex")


if __name__ == "__main__":
    unittest.main()
