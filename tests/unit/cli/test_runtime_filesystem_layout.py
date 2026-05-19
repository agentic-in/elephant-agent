from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from apps.cli.runtime_impl import CliRuntime


class CliRuntimeFilesystemLayoutTest(unittest.TestCase):
    def test_create_elephant_creates_elephant_root_and_tools_write_there(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            profile_dir = root / "profile"
            profile_dir.mkdir(parents=True)
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
            result = runtime.tool_runtime.invoke(
                "tool.file.write",
                {"path": "notes/plan.txt", "content": "elephant scoped\n"},
                session_id=session.session_id,
            )

            elephant_root = runtime.paths.elephant_file_path("atlas")
            self.assertEqual(result.outcome, "success")
            self.assertTrue((elephant_root / "notes" / "plan.txt").exists())
            self.assertTrue((runtime.paths.builtin_skills_dir / ".manifest.json").exists())
            self.assertEqual(
                runtime.paths.cron_jobs_path.resolve(),
                (root / "cron" / "jobs.json").resolve(),
            )
            self.assertEqual(runtime.paths.pairing_dir.resolve(), (root / "pairing").resolve())


if __name__ == "__main__":
    unittest.main()
