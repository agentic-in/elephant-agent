from __future__ import annotations

from pathlib import Path
import unittest

from packages.runtime_layout import (
    default_builtin_skills_dir,
    default_cron_dir,
    default_pairing_dir,
    default_workspaces_dir,
    elephant_file_path,
)


class RuntimeLayoutTest(unittest.TestCase):
    def test_top_level_runtime_dirs_default_under_elephant_home(self) -> None:
        environ = {"ELEPHANT_HOME": "/tmp/elephant-home"}

        self.assertEqual(default_cron_dir(environ=environ), Path("/tmp/elephant-home/cron"))
        self.assertEqual(
            default_workspaces_dir(environ=environ),
            Path("/tmp/elephant-home/workspaces"),
        )
        self.assertEqual(default_pairing_dir(environ=environ), Path("/tmp/elephant-home/pairing"))
        self.assertEqual(
            default_builtin_skills_dir(environ=environ),
            Path("/tmp/elephant-home/skills/builtin"),
        )

    def test_workspace_path_escapes_path_characters(self) -> None:
        path = elephant_file_path("team/atlas", environ={"ELEPHANT_HOME": "/tmp/elephant-home"})

        self.assertEqual(path, Path("/tmp/elephant-home/workspaces/team%2Fatlas"))


if __name__ == "__main__":
    unittest.main()
