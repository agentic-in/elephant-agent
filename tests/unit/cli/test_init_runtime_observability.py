from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from apps.cli import cli_main_init_runtime as init_runtime


class InitRuntimeObservabilityTests(unittest.TestCase):
    def test_persist_question_config_failure_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(paths=SimpleNamespace(state_dir=Path(tmpdir)))
            with (
                mock.patch("packages.runtime_config.write_global_config", side_effect=RuntimeError("write failed")),
                self.assertLogs("apps.cli.cli_main_init_runtime", level="DEBUG") as logs,
            ):
                init_runtime._persist_init_question_config(
                    runtime,
                    first_language="en",
                    learning_intensity="medium",
                )

        self.assertIn("Failed to persist init Personal Model question config", "\n".join(logs.output))

    def test_bootstrap_user_profile_failure_is_logged(self) -> None:
        class Runtime:
            def update_user_state(self, **_: object) -> None:
                raise RuntimeError("profile unavailable")

        bootstrap_state = SimpleNamespace(
            first_language="en",
            preferred_name="Bit",
            occupation="building agents",
        )

        with self.assertLogs("apps.cli.cli_main_init_runtime", level="DEBUG") as logs:
            init_runtime._bootstrap_user_profile_from_init(
                Runtime(),
                personal_model_id="you",
                bootstrap_state=bootstrap_state,
            )

        self.assertIn("Failed to persist init user profile fields", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
