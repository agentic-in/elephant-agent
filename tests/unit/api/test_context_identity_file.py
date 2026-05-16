from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from apps.api.api_runtime_impl import ElephantAPIApp
from apps.api.api_runtime_support import APIAppConfig
from packages.contracts.layers import Episode
from packages.runtime_layout import elephant_file_path
from packages.state import write_elephant_identity_file


class APIContextIdentityFileTest(unittest.TestCase):
    def test_api_context_reads_authored_elephant_file_before_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_root = Path(tmpdir)
            app = ElephantAPIApp(
                APIAppConfig(
                    database_path=install_root / "herd" / "runtime.sqlite",
                    install_root=install_root,
                )
            )
            created = app.dispatch(
                "POST",
                "/v1/herd",
                body=b'{"elephant_id":"atlas","display_name":"Atlas","elephant_identity_text":"State cache is stale."}',
            )
            self.assertEqual(created.status_code, 201)
            write_elephant_identity_file(
                elephant_file_path("atlas", install_root=install_root),
                "<!-- hidden metadata -->\n\nAtlas is playful, precise, and alive.",
            )
            session = Episode(
                episode_id="episode:api",
                state_id="state:atlas",
                personal_model_id="you",
                entry_surface="api",
                elephant_id="",
                status="open",
                started_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
            )

            bundle = app.context.assemble(session, (), ())

        rendered = bundle.prompt_envelope.frozen_prefix
        self.assertIn("Atlas is playful, precise, and alive.", rendered)
        self.assertNotIn("State cache is stale.", rendered)
        self.assertNotIn("hidden metadata", rendered)


if __name__ == "__main__":
    unittest.main()
