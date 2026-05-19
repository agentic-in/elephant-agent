from __future__ import annotations

from pathlib import Path
import json
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import apps.provider_runtime_support as provider_runtime_support
import packages.embeddings.runtime as embedding_runtime
import packages.models.bootstrap as model_bootstrap


class ProviderSelectionPayloadTest(unittest.TestCase):
    def test_load_provider_profile_reads_provider_profile_from_config_yaml(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                json.dumps(
                    {
                        "runtime": {
                            "state_dir": str(state_dir),
                            "default_profile_id": "default",
                        },
                        "models": {
                            "default_provider_source": "config",
                            "provider": {
                                "profile_id": "provider-openrouter",
                                "provider_id": "openai-compatible",
                                "base_url": "https://openrouter.ai/api/v1",
                                "default_model": "openai/gpt-4o-mini",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            profile = provider_runtime_support.load_provider_profile(state_dir, config_path=config_path)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.profile_id, "provider-openrouter")
        self.assertEqual(profile.provider_id, "openai-compatible")


class EmbeddingRuntimeLoggingTest(unittest.TestCase):
    def test_sentence_transformer_version_warning_is_filtered(self) -> None:
        logger = logging.getLogger("sentence_transformers.SentenceTransformer")
        existing_filters = list(logger.filters)
        try:
            logger.filters.clear()
            embedding_runtime._SENTENCE_TRANSFORMERS_LOG_FILTER_INSTALLED = False
            embedding_runtime._suppress_sentence_transformers_version_warning()
            record = logger.makeRecord(
                logger.name,
                logging.WARNING,
                "SentenceTransformer.py",
                1,
                "You try to use a model that was created with version 5.3.0.dev0, however, your version is 3.4.1.",
                (),
                None,
            )

            self.assertFalse(logger.filter(record))
        finally:
            logger.filters[:] = existing_filters
            embedding_runtime._SENTENCE_TRANSFORMERS_LOG_FILTER_INSTALLED = False


class EmbeddingBootstrapStateTest(unittest.TestCase):
    def test_resolve_embedding_bootstrap_state_uses_ready_when_root_is_healthy(
        self,
    ) -> None:
        with mock.patch.object(model_bootstrap, "embedding_root_is_healthy", return_value=True):
            state = provider_runtime_support.resolve_embedding_bootstrap_state(
                Path("/tmp/elephant-bootstrap-state"),
                state_focus_mode="embedded",
            )

        self.assertEqual(state.status, "ready")
        self.assertEqual(state.state_focus_mode, "embedded")
        self.assertIsNone(state.background_pid)

    def test_resolve_embedding_bootstrap_state_uses_downloading_when_dependencies_exist(
        self,
    ) -> None:
        with (
            mock.patch.object(model_bootstrap, "embedding_root_is_healthy", return_value=False),
            mock.patch.object(
                model_bootstrap,
                "sentence_transformers_dependencies_ready",
                return_value=True,
            ),
        ):
            state = provider_runtime_support.resolve_embedding_bootstrap_state(
                Path("/tmp/elephant-bootstrap-state"),
                state_focus_mode="embedded",
            )

        self.assertEqual(state.status, "downloading")
        self.assertIn("background model acquisition", state.summary)

    def test_trigger_embedding_bootstrap_spawns_background_worker_for_pending_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            fake_process = mock.Mock(pid=43210)
            with (
                mock.patch.object(model_bootstrap, "embedding_root_is_healthy", return_value=False),
                mock.patch.object(
                    model_bootstrap,
                    "sentence_transformers_dependencies_ready",
                    return_value=False,
                ),
                mock.patch.object(model_bootstrap.subprocess, "Popen", return_value=fake_process) as popen,
            ):
                state = provider_runtime_support.trigger_embedding_bootstrap(
                    state_dir,
                    state_focus_mode="embedded",
                )

            self.assertEqual(state.status, "pending")
            self.assertEqual(state.background_pid, 43210)
            persisted = provider_runtime_support.load_embedding_bootstrap_state(state_dir)
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted.status, "pending")
            self.assertEqual(persisted.background_pid, 43210)
            command = popen.call_args.args[0]
            self.assertEqual(command[0], sys.executable)
            self.assertIn("run_embedding_bootstrap_worker", command[2])

    def test_trigger_embedding_bootstrap_reuses_active_background_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            provider_runtime_support.persist_embedding_bootstrap_state(
                state_dir,
                provider_runtime_support.EmbeddingBootstrapState(
                    status="pending",
                    summary="background bootstrap is already pending",
                    state_focus_mode="embedded",
                    updated_at="2026-04-17T00:00:00+00:00",
                    background_pid=os.getpid(),
                ),
            )
            with (
                mock.patch.object(model_bootstrap, "embedding_root_is_healthy", return_value=False),
                mock.patch.object(
                    model_bootstrap,
                    "sentence_transformers_dependencies_ready",
                    return_value=False,
                ),
                mock.patch.object(model_bootstrap.subprocess, "Popen") as popen,
            ):
                state = provider_runtime_support.trigger_embedding_bootstrap(
                    state_dir,
                    state_focus_mode="embedded",
                )

            self.assertEqual(state.status, "pending")
            self.assertEqual(state.background_pid, os.getpid())
            popen.assert_not_called()

    def test_trigger_embedding_bootstrap_surfaces_spawn_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            with (
                mock.patch.object(model_bootstrap, "embedding_root_is_healthy", return_value=False),
                mock.patch.object(
                    model_bootstrap,
                    "sentence_transformers_dependencies_ready",
                    return_value=False,
                ),
                mock.patch.object(
                    model_bootstrap.subprocess,
                    "Popen",
                    side_effect=OSError("spawn failed"),
                ),
            ):
                state = provider_runtime_support.trigger_embedding_bootstrap(
                    state_dir,
                    state_focus_mode="embedded",
                )

            self.assertEqual(state.status, "failed")
            self.assertEqual(state.failure_message, "spawn failed")
            persisted = provider_runtime_support.load_embedding_bootstrap_state(state_dir)
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted.status, "failed")
            self.assertEqual(persisted.failure_message, "spawn failed")

    def test_trigger_embedding_bootstrap_retries_after_previous_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            provider_runtime_support.persist_embedding_bootstrap_state(
                state_dir,
                provider_runtime_support.EmbeddingBootstrapState(
                    status="failed",
                    summary="local semantic-index bootstrap remains non-blocking after a failure: spawn failed",
                    state_focus_mode="embedded",
                    updated_at="2026-04-17T00:00:00+00:00",
                    failure_message="spawn failed",
                    background_pid=None,
                ),
            )
            fake_process = mock.Mock(pid=54321)
            with (
                mock.patch.object(model_bootstrap, "embedding_root_is_healthy", return_value=False),
                mock.patch.object(
                    model_bootstrap,
                    "sentence_transformers_dependencies_ready",
                    return_value=False,
                ),
                mock.patch.object(model_bootstrap.subprocess, "Popen", return_value=fake_process) as popen,
            ):
                state = provider_runtime_support.trigger_embedding_bootstrap(
                    state_dir,
                    state_focus_mode="embedded",
                )

            self.assertEqual(state.status, "pending")
            self.assertEqual(state.background_pid, 54321)
            self.assertIsNone(state.failure_message)
            popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
