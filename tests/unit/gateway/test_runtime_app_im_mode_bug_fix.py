"""Gateway + CLI prompt parity for bound herd (regression test for IM identity bug).

Earlier bug: in IM mode the ``### Who you are`` section rendered the default
"Elephant Agent" name while ``### Where things stand`` correctly rendered the elephant name
(e.g., "Zoey"). The two disagreed because they read from different sources —
the prompt contract read ``profile.json``, the dynamic system-layer read the
State row.

With the reset:

- Identity name/mode flows from State.
- The authored voice paragraph comes from ``ELEPHANT.md`` when present, with
  State as the cache/fallback.
- Gateway and CLI share the same DB, file layout, and ``load_runtime_profile``
  resolver plus authored-file overlay.
- Both surfaces therefore produce a byte-identical ``### Who you are`` /
  ``### Your own voice`` for the same ``(personal_model_id, elephant_id)`` pair.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from packages.runtime_layout import elephant_file_path
from packages.state import (
    build_prompt_contract,
    load_runtime_profile,
    profile_with_authored_elephant_identity,
    write_elephant_identity_file,
)
from packages.storage import RuntimeStorageRepository


class GatewayCliPromptParityTest(unittest.TestCase):
    def _repository(self, tmpdir: Path) -> RuntimeStorageRepository:
        db_path = tmpdir / "elephant.sqlite3"
        repository = RuntimeStorageRepository(db_path)
        repository.bootstrap()
        return repository

    def test_prompt_contract_reads_canonical_state_identity(self) -> None:
        """The ``### Who you are`` name comes from ``State.elephant_name``."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository = self._repository(root)
            repository.ensure_default_personal_model()
            repository.create_state(
                state_id="state:zoey",
                personal_model_id="you",
                elephant_id="zoey",
                state_anchor="elephant:zoey",
                elephant_name="Zoey",
                identity_mode="companion",
                initiative="gentle",
                working_style="companion",
                surface_bindings=("cli",),
                elephant_identity_text="Hi — I'm Zoey. I stay curious and grounded.",
                summary="",
                metadata={"profile_id": "you"},
            )

            loaded = load_runtime_profile(
                repository,
                personal_model_id="you",
                elephant_id="zoey",
            )

        self.assertEqual(loaded.state.display_name, "Zoey")
        contract = build_prompt_contract(loaded, prompt_mode="full")
        rendered = "\n".join(contract.stable_prefix_refs)
        self.assertIn(
            "- You are Zoey, the companion this person keeps coming back to.",
            rendered,
        )
        # Without an authored file overlay, "Your own voice" uses the State cache.
        self.assertIn("Hi — I'm Zoey.", rendered)
        # Legacy default must NOT leak in.
        self.assertNotIn("You are Elephant Agent,", rendered)

    def test_cli_and_gateway_render_the_same_identity_block(self) -> None:
        """Same elephant file + State pair → byte-identical identity block."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository = self._repository(root)
            repository.ensure_default_personal_model()
            repository.create_state(
                state_id="state:hazel",
                personal_model_id="you",
                elephant_id="hazel",
                state_anchor="elephant:hazel",
                elephant_name="Hazel",
                identity_mode="companion",
                initiative="proactive",
                working_style="companion",
                surface_bindings=("cli", "messaging.weixin"),
                elephant_identity_text="Hi — I'm Hazel. Steady, exact, steady.",
                summary="",
                metadata={"profile_id": "you"},
            )
            write_elephant_identity_file(
                elephant_file_path("hazel", install_root=root),
                "<!-- hidden metadata -->\n\nHi, I'm Hazel from the authored file. I am playful and exact.",
            )

            cli_profile = profile_with_authored_elephant_identity(
                load_runtime_profile(
                    repository,
                    personal_model_id="you",
                    elephant_id="hazel",
                ),
                elephant_file_path("hazel", install_root=root),
            )
            gateway_profile = profile_with_authored_elephant_identity(
                load_runtime_profile(
                    repository,
                    personal_model_id="you",
                    elephant_id="hazel",
                ),
                elephant_file_path("hazel", install_root=root),
            )

        cli_contract = build_prompt_contract(cli_profile, prompt_mode="full")
        gateway_contract = build_prompt_contract(gateway_profile, prompt_mode="full")
        self.assertEqual(cli_contract.stable_prefix_refs, gateway_contract.stable_prefix_refs)
        rendered = "\n".join(cli_contract.stable_prefix_refs)
        self.assertIn("You are Hazel,", rendered)
        self.assertIn("Hi, I'm Hazel from the authored file.", rendered)
        self.assertNotIn("Hi — I'm Hazel. Steady, exact, steady.", rendered)


if __name__ == "__main__":
    unittest.main()
