from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from apps.cli.runtime import CliRuntime


class RuntimeCognitionTestBase(unittest.TestCase):
    def _runtime(
        self,
        *,
        profile_payload: dict[str, object] | None = None,
        seed_charter: bool = True,
    ) -> CliRuntime:
        """Build a CliRuntime with identity seeded into the DB.

        ``profile_payload`` is a dict that mirrors the legacy ``profile.json``
        shape. Identity flows through the DB now — not from a filesystem
        manifest — so we translate the payload into the equivalent runtime
        calls (``update_identity``, ``update_companion_settings``,
        ``update_identity_state``).
        """
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        state_dir = root / "state"
        payload = profile_payload or {
            "profile_id": "profile-companion",
            "display_name": "Elephant Agent",
            "mode": "companion",
        }
        runtime = CliRuntime.create(state_dir=state_dir)
        profile_id = str(payload["profile_id"])
        display_name = payload.get("display_name")
        mode = payload.get("mode")
        if display_name or mode:
            runtime.update_identity(
                profile_id=profile_id,
                display_name=str(display_name) if display_name else None,
                mode=str(mode) if mode else None,
            )
        companion_payload = payload.get("companion")
        if isinstance(companion_payload, dict):
            runtime.update_companion_settings(
                profile_id=profile_id,
                personality_preset=str(companion_payload.get("personality_preset") or "") or None,
                initiative=str(companion_payload.get("initiative") or "") or None,
                notes=tuple(companion_payload.get("notes") or ()) or None,
            )
        if seed_charter:
            runtime.update_identity_state(
                profile_id=profile_id,
                elephant_identity_text="Stay durable and grounded.",
            )
        return runtime

