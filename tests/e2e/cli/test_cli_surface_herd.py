from __future__ import annotations

import json
import sqlite3

from apps.cli.runtime import CliRuntime
from packages.storage import RuntimeStorageRepository
from tests.e2e.cli.cli_surface_test_base import CliSurfaceE2ETestBase


class CliSurfaceHerdE2ETest(CliSurfaceE2ETestBase):
    def test_non_interactive_elephant_creates_state_without_activity_command(
        self,
    ) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        created = self._run(
            "herd",
            "new",
            "mission",
        )
        self.assertIn("state_id · state:mission", created.stdout)
        self.assertIn("personal_model_id · you", created.stdout)
        self.assertNotIn("active_goal", created.stdout)

    def test_elephant_name_is_required_and_elephants_delete_clears_named_or_all_elephants(
        self,
    ) -> None:
        missing_name = self._run("herd", "new", check=False)
        self.assertEqual(missing_name.returncode, 1)
        self.assertIn("Elephant blocked", missing_name.stdout)
        self.assertIn("elephant init", missing_name.stdout)

        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "alpha")
        self._run("herd", "new", "beta")
        prompted_elephant = self._run_in_tty(
            "Nova\n",
            "herd",
            "new",
            followup_text="/exit\n",
        )
        self.assertIn("Let's bring another elephant online.", prompted_elephant)
        self.assertIn("Elephant Agent", prompted_elephant)
        self.assertIn("Nova", prompted_elephant)

        herd = self._run("herd")
        self.assertIn("Elephant Agent herd", herd.stdout)
        self.assertIn("Available herd", herd.stdout)
        self.assertIn("alpha · latest", herd.stdout)
        self.assertIn("beta · latest", herd.stdout)
        self.assertIn("nova · current · latest", herd.stdout)
        self.assertIn("elephant herd use <name>", herd.stdout)
        self.assertIn("elephant herd delete <name>", herd.stdout)

        retired = self._run("herd", "delete", "alpha")
        self.assertIn("Elephant retired", retired.stdout)
        self.assertIn("Retired now", retired.stdout)
        self.assertIn("elephant_id · alpha", retired.stdout)

        herd_after_one = self._run("herd")
        self.assertNotIn("alpha · latest", herd_after_one.stdout)
        self.assertIn("beta · latest", herd_after_one.stdout)

        retired_all = self._run("herd", "delete", "--all")
        self.assertIn("All herd retired", retired_all.stdout)
        self.assertIn("deleted_elephants · 3", retired_all.stdout)

        herd_after_all = self._run("herd")
        self.assertIn("Current state", herd_after_all.stdout)
        self.assertIn("No herd yet.", herd_after_all.stdout)

    def test_elephants_use_selects_current_elephant_for_bare_wake(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "atlas")

        runtime = CliRuntime.create(state_dir=self.state_dir)
        latest = runtime.latest_session_for_elephant("atlas")
        assert latest is not None
        selected = self._run("herd", "use", "atlas")
        self.assertIn("Elephant selected", selected.stdout)
        self.assertIn("elephant_id · atlas", selected.stdout)
        self.assertIn("state_id · state:atlas", selected.stdout)

        current_state = runtime.repository.current_state()
        self.assertIsNotNone(current_state)
        self.assertEqual(current_state.elephant_id, "atlas")

        current = self._run("herd", "current")
        self.assertIn("Current elephant", current.stdout)
        self.assertIn("elephant_id · atlas", current.stdout)
        self.assertIn("state_id · state:atlas", current.stdout)

        self._run("wake", "--message", "Who are you?")

        current_after_wake = self._run("herd", "current")
        self.assertIn("elephant_id · atlas", current_after_wake.stdout)

    def test_elephant_message_provider_failure_renders_recovery_card(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self.stub.fail_chat = True

        failed = self._run(
            "herd",
            "new",
            "provider-fail",
            "--message",
            "hello from the failure path",
            check=False,
        )

        self.assertEqual(failed.returncode, 1)
        self.assertIn("Elephant Agent elephant", failed.stdout)
        self.assertIn("state_id · state:provider-fail", failed.stdout)
        self.assertIn("personal_model_id · you", failed.stdout)
        self.assertIn("A new elephant is ready.", failed.stdout)
        self.assertIn("elephant wake --elephant-id provider-fail", failed.stdout)
        self.assertNotIn("Traceback", failed.stderr)

    def test_elephant_create_persists_canonical_state_under_default_personal_model(
        self,
    ) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        created = self._run("herd", "new", "atlas")
        self.assertIn("state_id · state:atlas", created.stdout)
        self.assertIn("personal_model_id · you", created.stdout)

        runtime = CliRuntime.create(state_dir=self.state_dir)
        elephant_state = runtime.repository.load_state("state:atlas")
        self.assertIsNotNone(elephant_state)
        self.assertEqual(elephant_state.elephant_id, "atlas")
        self.assertEqual(elephant_state.personal_model_id, "you")

    def test_elephant_create_uses_canonical_episode_storage_only(self) -> None:
        state_dir = self.root / "canonical-state"
        profile_dir = self.root / "canonical-profile"
        profile_dir.mkdir()
        (profile_dir / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "preferences": ["tone:steady"],
                    "enabled_capabilities": ["cli.primary"],
                }
            ),
            encoding="utf-8",
        )
        database_path = state_dir / "elephant.sqlite3"
        RuntimeStorageRepository(database_path).bootstrap()

        runtime = CliRuntime.create(state_dir=state_dir)
        session = runtime.create_elephant(
            elephant_id="atlas", session_id="session-atlas"
        )

        self.assertEqual(session.elephant_id, "atlas")
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                "SELECT state_id, personal_model_id FROM episodes WHERE episode_id = ?",
                ("session-atlas",),
            ).fetchone()
            table_names = {
                str(table_row[0])
                for table_row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        self.assertNotIn("sessions", table_names)
        self.assertIsNotNone(row)
        self.assertEqual(tuple(row), ("state:atlas", "you"))

    def test_elephant_delete_removes_elephant_state_and_preserves_personal_model(
        self,
    ) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "atlas")

        runtime = CliRuntime.create(state_dir=self.state_dir)
        self.assertIsNotNone(runtime.repository.load_state("state:atlas"))

        retired = self._run("herd", "delete", "atlas")
        self.assertIn("Elephant retired", retired.stdout)
        self.assertIn("personal_model_facts · preserved", retired.stdout)

        refreshed = CliRuntime.create(state_dir=self.state_dir)
        self.assertIsNone(refreshed.repository.load_state("state:atlas"))
        self.assertIsNotNone(refreshed.repository.load_personal_model("you"))


if __name__ == "__main__":
    import unittest

    unittest.main()
