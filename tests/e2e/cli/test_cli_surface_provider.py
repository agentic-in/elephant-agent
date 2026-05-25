from __future__ import annotations

import json

from apps.cli.runtime import CliRuntime
from apps.provider_runtime import runtime_local_secret_env_path
from packages.runtime_config import global_config_path_for_state_dir, load_global_config
from tests.e2e.cli.cli_surface_test_base import (
    EMBEDDING_BOOTSTRAP_READY_PATTERN,
    EMBEDDING_BOOTSTRAP_STATUS_PATTERN,
    EMBEDDING_BOOTSTRAP_STATUSES,
    CliSurfaceE2ETestBase,
)


class CliSurfaceProviderE2ETest(CliSurfaceE2ETestBase):
    def test_born_persists_runtime_secret_file_for_future_surfaces(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "demo",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--secret-env-var",
            "ELEPHANT_OPENROUTER_API_KEY",
        )

        secret_path = runtime_local_secret_env_path(self.state_dir)
        self.assertTrue(secret_path.exists())
        payload = json.loads(secret_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["ELEPHANT_OPENROUTER_API_KEY"], "sk-cli-test-123")

    def test_init_surfaces_embedding_bootstrap_without_exposing_state_focus_mode(
        self,
    ) -> None:
        setup = self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "demo",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self.assertRegex(
            setup.stdout,
            rf"embedding_bootstrap_status · {EMBEDDING_BOOTSTRAP_STATUS_PATTERN}",
        )
        self.assertRegex(
            setup.stdout,
            rf"embedding_bootstrap_ready · {EMBEDDING_BOOTSTRAP_READY_PATTERN}",
        )
        self.assertNotIn("state_focus_mode", setup.stdout)

        config = load_global_config(
            global_config_path_for_state_dir(self.state_dir), state_dir=self.state_dir
        )
        self.assertEqual(
            config["models"]["provider"]["default_model"], "openai/gpt-4o-mini"
        )

        health = self._run("status")
        self.assertRegex(
            health.stdout,
            rf"active_provider_embedding_bootstrap · {EMBEDDING_BOOTSTRAP_STATUS_PATTERN}",
        )
        self.assertNotIn("state_focus_mode", health.stdout)

    def test_provider_embeddings_switch_between_local_default_and_configured_override(
        self,
    ) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "demo",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        initial = self._run("provider", "embeddings", "status")
        self.assertIn("Embedding provider status", initial.stdout)
        self.assertIn("source · local-default", initial.stdout)

        configured = self._run(
            "provider",
            "embeddings",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model",
            "text-embedding-3-large",
            "--dimensions",
            "1536",
            "--api-key",
            "sk-cli-test-123",
        )
        self.assertIn("Embedding provider updated", configured.stdout)
        self.assertIn("source · configured", configured.stdout)
        self.assertIn("provider_id · openai-compatible-embed", configured.stdout)

        runtime = CliRuntime.create(state_dir=self.state_dir)
        summary = dict(runtime.embedding_provider_summary())
        self.assertEqual(summary["source"], "configured")
        self.assertEqual(summary["model_id"], "text-embedding-3-large")
        self.assertEqual(summary["dimensions"], 1536)
        self.assertEqual(summary["secret_status"], "stored")

        reverted = self._run("provider", "embeddings", "local")
        self.assertIn("Embedding provider updated", reverted.stdout)
        self.assertIn("source · local-default", reverted.stdout)
        self.assertRegex(
            reverted.stdout,
            rf"embedding_bootstrap_status · {EMBEDDING_BOOTSTRAP_STATUS_PATTERN}",
        )
        self.assertRegex(
            reverted.stdout,
            rf"embedding_bootstrap_ready · {EMBEDDING_BOOTSTRAP_READY_PATTERN}",
        )

        refreshed = CliRuntime.create(state_dir=self.state_dir)
        refreshed_summary = dict(refreshed.embedding_provider_summary())
        self.assertEqual(refreshed_summary["source"], "local-default")
        self.assertIn(
            refreshed_summary["embedding_bootstrap_status"],
            EMBEDDING_BOOTSTRAP_STATUSES,
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
