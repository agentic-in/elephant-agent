from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from apps.rtk_command import command_main
from packages.runtime_config import global_config_path_for_state_dir, load_global_config, load_rtk_from_config


def _fake_rtk(path: Path) -> Path:
    script = path / "fake-rtk"
    script.write_text(
        """#!/usr/bin/env python3
import sys

if len(sys.argv) > 1 and sys.argv[1] == "--version":
    print("rtk 0.40.0")
    raise SystemExit(0)
if len(sys.argv) > 2 and sys.argv[1] == "rewrite":
    print("rtk " + sys.argv[2])
    raise SystemExit(3)
raise SystemExit(64)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


class RtkCommandTest(unittest.TestCase):
    def test_start_and_stop_toggle_rtk_config(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_dir = root / "state"
            binary = _fake_rtk(root)

            with redirect_stdout(io.StringIO()):
                started = command_main(["start", "--binary", str(binary)], default_state_dir=state_dir)
            config_path = global_config_path_for_state_dir(state_dir)
            started_config = load_global_config(config_path, state_dir=state_dir)
            started_rtk = load_rtk_from_config(started_config)

            with redirect_stdout(io.StringIO()):
                stopped = command_main(["stop"], default_state_dir=state_dir)
            stopped_config = load_global_config(config_path, state_dir=state_dir)
            stopped_rtk = load_rtk_from_config(stopped_config)

        self.assertEqual(started, 0)
        self.assertTrue(started_rtk["enabled"])
        self.assertEqual(started_rtk["binary"], str(binary))
        self.assertEqual(stopped, 0)
        self.assertFalse(stopped_rtk["enabled"])
        self.assertEqual(stopped_rtk["binary"], str(binary))

    def test_start_fails_without_rtk_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "state"
            with redirect_stdout(io.StringIO()):
                exit_code = command_main(["start", "--binary", str(Path(tempdir) / "missing")], default_state_dir=state_dir)
            config = load_global_config(global_config_path_for_state_dir(state_dir), state_dir=state_dir)

        self.assertEqual(exit_code, 1)
        self.assertFalse(load_rtk_from_config(config)["enabled"])

    def test_doctor_reports_disabled_missing_binary_as_non_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            with redirect_stdout(io.StringIO()):
                exit_code = command_main(["doctor"], default_state_dir=Path(tempdir) / "state")

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
