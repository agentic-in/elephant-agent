from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import json

from packages.contracts.runtime import PersonalModelRuntimeState
from packages.state import (
    CompanionSettings,
    ELEPHANT_IDENTITY_FILENAME,
    EXTENSIONS_MANIFEST_FILENAME,
    ProfileLoader,
    ensure_elephant_identity_file,
    profile_with_authored_elephant_identity,
    write_elephant_identity_file,
)
from packages.state.projection import build_loaded_profile_from_state


class ProfileFilesTest(unittest.TestCase):
    def test_profile_loader_reads_extension_manifest_and_ignores_identity(self) -> None:
        """ProfileLoader owns only operator extension configuration.

        Identity fields (``display_name``, ``mode``, ``companion``) on disk
        are intentionally ignored — identity flows from the DB State row
        via ``load_runtime_profile``. The loader returns a stub identity
        so callers that still grab ``.state`` don't blow up.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            profile_dir.mkdir()
            (profile_dir / EXTENSIONS_MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "display_name": "Ignored",
                        "mode": "ignored",
                        "skill_overrides": {"arxiv": {"enabled": True}},
                    }
                ),
                encoding="utf-8",
            )

            loaded = ProfileLoader(profile_dir).load()

            # Identity comes from the DB, not this file — loader returns a stub.
            self.assertEqual(loaded.state.profile_id, "you")
            self.assertEqual(loaded.state.display_name, "You")
            # Extension manifest is passed through so skill / tool consumers see it.
            self.assertEqual(
                loaded.manifest.get("skill_overrides"),
                {"arxiv": {"enabled": True}},
            )

    def test_elephant_identity_file_is_seeded_under_elephant_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            herd_dir = Path(tmpdir) / "herd" / "owen"

            path = ensure_elephant_identity_file(
                herd_dir,
                "# Elephant Identity: Owen\n\nDefault Elephant Identity:\nOwen carries continuity.",
            )

            self.assertEqual(path, herd_dir / ELEPHANT_IDENTITY_FILENAME)
            self.assertTrue(path.exists())
            self.assertIn("Elephant Identity: Owen", path.read_text(encoding="utf-8"))

    def test_authored_identity_parse_failure_is_logged_and_uses_folder_name(self) -> None:
        loaded = _loaded_profile(display_name="You")
        with tempfile.TemporaryDirectory() as tmpdir:
            elephant_root = Path(tmpdir) / "quiet-alex"
            write_elephant_identity_file(
                elephant_root,
                "File-authored identity without a machine-readable display name.",
            )

            with (
                patch(
                    "packages.state.governance.parse_elephant_identity_display_name",
                    side_effect=RuntimeError("parser unavailable"),
                ),
                self.assertLogs("packages.state.files", level="DEBUG") as logs,
            ):
                authored = profile_with_authored_elephant_identity(loaded, elephant_root)

        self.assertEqual(authored.state.display_name, "Quiet Alex")
        self.assertIn(
            "Failed to parse authored elephant identity display name",
            "\n".join(logs.output),
        )

    def test_legacy_default_identity_render_failure_is_logged_and_falls_back(self) -> None:
        loaded = _loaded_profile(display_name="You")
        legacy_text = "\n".join(
            (
                "# Elephant Identity: Jasper",
                "Display name: Jasper",
                "Mode: companion",
                "",
                "You are Jasper, this person's companion.",
                "How you show up: Steady, present, and continuity-first without losing boundaries.",
                "How you sound: steady, present, grounded.",
                "How you take initiative: gentle.",
                "Stay continuous without performing intimacy: use remembered context naturally, keep uncertainty visible, and let the person correct you.",
            )
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            elephant_root = Path(tmpdir) / "jasper"
            write_elephant_identity_file(elephant_root, legacy_text)

            with (
                patch(
                    "packages.state.governance.render_default_elephant_identity",
                    side_effect=RuntimeError("renderer unavailable"),
                ),
                self.assertLogs("packages.state.files", level="DEBUG") as logs,
            ):
                authored = profile_with_authored_elephant_identity(loaded, elephant_root)
            refreshed = (elephant_root / ELEPHANT_IDENTITY_FILENAME).read_text(encoding="utf-8")

        self.assertIn("You are Jasper, this person's companion.", authored.elephant_identity_text or "")
        self.assertIn("Be useful without performing intimacy", refreshed)
        self.assertIn(
            "Failed to render refreshed default elephant identity",
            "\n".join(logs.output),
        )


def _loaded_profile(*, display_name: str):
    runtime_state = PersonalModelRuntimeState(
        profile_id="you",
        display_name=display_name,
        mode="companion",
    )
    companion = CompanionSettings(personality_preset="companion")
    return build_loaded_profile_from_state(
        runtime_state,
        manifest={},
        companion=companion,
        profile_dir="",
        manifest_path=None,
        elephant_identity_text="State cache says stay quiet and stale.",
        user_profile_text=None,
    )


if __name__ == "__main__":
    unittest.main()
