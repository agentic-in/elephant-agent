from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from packages.storage import RuntimeStorageRepository
from packages.tools.handlers_paths import run_path_action
from packages.tools.path_management import RepositoryPathManagementSurface
from packages.tools.runtime import ToolInvocation


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
                path_step_id=step.path_step_id,
                what_done="Turned the first week into a checkable loop.",
                why_it_matters="The user can review the concrete change.",
                how_it_was_done="Separated goal, cadence, and next action.",
                knowledge="Habit loops need small repeatable triggers.",
                human_takeaway="A plan is useful when it can be checked.",
            )
            check = surface.manage_paths(
                "session:path-tool",
                action="check_understanding",
                summary_id=summary["summary"]["summary_id"],
                status="understood",
            )

        self.assertEqual(created["outcome"], "success")
        self.assertIn("Healthy rhythm", created["summary"])
        self.assertEqual(moved["step"]["status"], "moving")
        self.assertEqual(summary["understanding_check"]["status"], "pending")
        self.assertEqual(check["understanding_check"]["status"], "understood")


if __name__ == "__main__":
    unittest.main()
