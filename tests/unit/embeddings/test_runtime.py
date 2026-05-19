from __future__ import annotations

import logging
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.embeddings import (  # noqa: E402
    ELEPHANT_EMBED_MODEL_ID,
    ELEPHANT_EMBED_DEFAULT_DIMENSIONS,
    ELEPHANT_EMBED_ONLINE_DIMENSIONS,
    ELEPHANT_EMBED_PROVIDER_ID,
    ELEPHANT_EMBED_PROVIDER_KIND,
    DefaultEmbeddingService,
    EmbeddingPreloadEntry,
    EmbeddingRequest,
    InMemoryEmbeddingModelRegistry,
    LocalElephantEmbeddingProvider,
    OPENAI_COMPATIBLE_EMBED_DEFAULT_SECRET_ENV_VAR,
    OPENAI_COMPATIBLE_EMBED_PROFILE_ID,
    OPENAI_COMPATIBLE_EMBED_PROVIDER_ID,
    OPENAI_COMPATIBLE_EMBED_PROVIDER_KIND,
    OPENAI_COMPATIBLE_EMBED_SECRET_REFERENCE_ID,
    SentenceTransformerEmbeddingProvider,
    build_default_embedding_service,
    cosine_similarity,
    default_local_embedding_provider_config,
    embedding_mode_for_latency,
    embedding_model_root_path,
    embedding_root_is_healthy,
    resolve_embedding_dimensions,
)
import packages.embeddings.runtime as embedding_runtime  # noqa: E402


def _unit_vector(dimensions: int, *, index: int = 0, weight: float = 1.0) -> tuple[float, ...]:
    values = [0.0] * dimensions
    values[index] = weight
    return tuple(values)


class EmbeddingRuntimeTest(unittest.TestCase):
    def test_provider_health_reflects_local_runtime_state(self) -> None:
        provider = SentenceTransformerEmbeddingProvider(model_root="/tmp/elephant-embed")

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=False,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=False,
            ),
        ):
            self.assertEqual(provider.health().status, "pending")

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=False,
            ),
        ):
            self.assertEqual(provider.health().status, "downloading")

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
        ):
            health = provider.health()

        self.assertEqual(health.status, "ready")
        self.assertIn("local embedding root is available", health.summary)

    def test_provider_health_reports_runtime_steady_state_metadata(self) -> None:
        provider = SentenceTransformerEmbeddingProvider(model_root="/tmp/elephant-embed")
        steadying_thread = mock.Mock()
        steadying_thread.is_alive.return_value = True
        provider._steady_thread = steadying_thread

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
        ):
            steadying = provider.health()

        self.assertEqual(steadying.metadata["runtime_state"], "steadying")
        self.assertIn("steadyup is in progress", steadying.summary)

        provider._model = object()
        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
        ):
            loaded = provider.health()

        self.assertEqual(loaded.metadata["runtime_state"], "loaded")
        self.assertIn("already steady in memory", loaded.summary)

    def test_default_service_uses_canonical_provider(self) -> None:
        provider = SentenceTransformerEmbeddingProvider()
        service = DefaultEmbeddingService(registry=InMemoryEmbeddingModelRegistry((provider,)))

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
            mock.patch.object(provider, "_encode_texts", return_value=(_unit_vector(64),)),
        ):
            vector = service.embed_text(
                "resume the release State",
                request_id="embedding:single",
                latency_mode="fast",
            )
            health = service.health()

        self.assertEqual(vector.provider_id, ELEPHANT_EMBED_PROVIDER_ID)
        self.assertEqual(vector.model_id, ELEPHANT_EMBED_MODEL_ID)
        self.assertEqual(vector.dimensions, 64)
        self.assertEqual(len(vector.values), 64)
        self.assertEqual(health.provider_id, ELEPHANT_EMBED_PROVIDER_ID)
        self.assertEqual(health.model_id, ELEPHANT_EMBED_MODEL_ID)
        self.assertEqual(health.status, "ready")

    def test_build_default_service_uses_local_elephant_provider(self) -> None:
        service = build_default_embedding_service()
        provider = service.registry.default()
        config = default_local_embedding_provider_config()

        self.assertIsInstance(provider, LocalElephantEmbeddingProvider)
        self.assertEqual(provider.provider_id, ELEPHANT_EMBED_PROVIDER_ID)
        self.assertEqual(provider.model_id, ELEPHANT_EMBED_MODEL_ID)
        self.assertEqual(config["provider_id"], ELEPHANT_EMBED_PROVIDER_ID)
        self.assertEqual(config["provider_kind"], ELEPHANT_EMBED_PROVIDER_KIND)
        self.assertEqual(config["dimensions"], ELEPHANT_EMBED_DEFAULT_DIMENSIONS)
        self.assertEqual(config["metadata"]["default"], "true")

    def test_openai_compatible_embedding_profile_constants_are_stable(self) -> None:
        self.assertEqual(OPENAI_COMPATIBLE_EMBED_PROFILE_ID, "provider-embedding-openai-compatible")
        self.assertEqual(OPENAI_COMPATIBLE_EMBED_PROVIDER_ID, "openai-compatible-embed")
        self.assertEqual(OPENAI_COMPATIBLE_EMBED_PROVIDER_KIND, "openai-compatible")
        self.assertEqual(
            OPENAI_COMPATIBLE_EMBED_SECRET_REFERENCE_ID,
            "secret-embedding-provider-openai-compatible-active-api-key",
        )
        self.assertEqual(OPENAI_COMPATIBLE_EMBED_DEFAULT_SECRET_ENV_VAR, "OPENAI_API_KEY")

    def test_registry_selects_registered_provider(self) -> None:
        provider = SentenceTransformerEmbeddingProvider()
        registry = InMemoryEmbeddingModelRegistry((provider,))
        service = DefaultEmbeddingService(registry=registry)

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
            mock.patch.object(
                provider,
                "_encode_texts",
                return_value=(_unit_vector(256, index=0), _unit_vector(256, index=1)),
            ),
        ):
            batch = service.embed(
                EmbeddingRequest(
                    request_id="embedding:batch",
                    texts=("release gate", "provider doctor"),
                    latency_mode="balanced",
                )
            )

        self.assertEqual(batch.provider_id, ELEPHANT_EMBED_PROVIDER_ID)
        self.assertEqual(batch.model_id, ELEPHANT_EMBED_MODEL_ID)
        self.assertEqual(batch.dimensions, 256)
        self.assertEqual(len(batch.vectors), 2)

    def test_provider_rejects_unsupported_dimensions(self) -> None:
        provider = SentenceTransformerEmbeddingProvider()

        with self.assertRaises(ValueError):
            provider.embed(
                EmbeddingRequest(
                    request_id="embedding:bad-dims",
                    texts=("hello",),
                    dimensions=32,
                )
            )

    def test_dimension_resolution_and_similarity_stay_explicit(self) -> None:
        self.assertEqual(resolve_embedding_dimensions("fast"), 64)
        self.assertEqual(resolve_embedding_dimensions("balanced"), 256)
        self.assertEqual(resolve_embedding_dimensions("offline"), 768)
        self.assertEqual(embedding_mode_for_latency("deep"), f"{ELEPHANT_EMBED_MODEL_ID}:768d")
        self.assertEqual(ELEPHANT_EMBED_ONLINE_DIMENSIONS, (64, 256, 768))

        left = _unit_vector(256, index=0)
        right = _unit_vector(256, index=0)
        other = _unit_vector(256, index=1)

        self.assertAlmostEqual(cosine_similarity(left, right), 1.0, places=6)
        self.assertEqual(cosine_similarity(left, other), 0.0)

    def test_embedding_root_health_requires_sentence_transformer_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "elephant-embed"
            root.mkdir()

            self.assertEqual(embedding_model_root_path(str(root)), root)
            self.assertFalse(embedding_root_is_healthy(str(root)))

            (root / "modules.json").write_text("[]", encoding="utf-8")
            self.assertTrue(embedding_root_is_healthy(str(root)))

    def test_local_embedding_loader_passes_tokenizer_regex_fix(self) -> None:
        provider = SentenceTransformerEmbeddingProvider(model_root="/tmp/elephant-embed")
        sentence_transformer = mock.Mock(return_value=object())
        fake_module = types.SimpleNamespace(SentenceTransformer=sentence_transformer)

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
            mock.patch.dict(sys.modules, {"sentence_transformers": fake_module}),
        ):
            provider._load_model()

        sentence_transformer.assert_called_once_with(
            "/tmp/elephant-embed",
            local_files_only=True,
            processor_kwargs={"fix_mistral_regex": True},
        )

    def test_local_embedding_loader_suppresses_known_tokenizer_regex_warning(
        self,
    ) -> None:
        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        records: list[logging.LogRecord] = []
        logger = logging.getLogger("transformers.tokenization_utils_tokenizers")
        handler = _CaptureHandler()
        original_level = logger.level
        original_propagate = logger.propagate

        model_root = "/tmp/elephant-embed-regex-warning"
        known_warning = (
            f"The tokenizer you are loading from '{model_root}' with an incorrect regex pattern. "
            "This warning is emitted by transformers for the local embedding tokenizer."
        )
        other_warning = (
            "The tokenizer you are loading from '/tmp/other-model' with an incorrect regex pattern. "
            "This warning should still be visible."
        )

        try:
            logger.addHandler(handler)
            logger.setLevel(logging.WARNING)
            logger.propagate = False
            embedding_runtime._suppress_local_embedding_load_warnings(model_root)

            logger.warning(known_warning)
            logger.warning(other_warning)
            logger.warning("plain tokenizer warning")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original_level)
            logger.propagate = original_propagate

        self.assertEqual(
            [record.getMessage() for record in records],
            [other_warning, "plain tokenizer warning"],
        )

    def test_preload_and_background_backfill_fill_the_shared_cache(self) -> None:
        provider = SentenceTransformerEmbeddingProvider()
        preload_entries = (
            EmbeddingPreloadEntry(cache_key="memory-1", text="release evidence summary"),
            EmbeddingPreloadEntry(cache_key="memory-2", text="release checklist"),
        )
        backfill_entries = (EmbeddingPreloadEntry(cache_key="projection-1", text="projection anchor summary"),)

        def _encode(texts: tuple[str, ...], *, dimensions: int) -> tuple[tuple[float, ...], ...]:
            return tuple(_unit_vector(dimensions, index=index) for index, _text in enumerate(texts))

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
            mock.patch.object(provider, "_encode_texts", side_effect=_encode),
        ):
            preload_state = provider.preload(
                target="evidence",
                entries=preload_entries,
                latency_mode="balanced",
            )
            self.assertEqual(preload_state.status, "ready")
            cached = provider.cached_vector(target="evidence", cache_key="memory-1", dimensions=256)
            self.assertIsNotNone(cached)
            assert cached is not None
            self.assertEqual(cached.dimensions, 256)

            steadying_state = provider.queue_backfill(
                target="projection-history",
                entries=backfill_entries,
                latency_mode="fast",
            )
            self.assertIn(steadying_state.status, {"steadying", "ready"})
            deadline = time.time() + 1.0
            projection_cached = None
            while projection_cached is None and time.time() < deadline:
                projection_cached = provider.cached_vector(
                    target="projection-history",
                    cache_key="projection-1",
                    dimensions=64,
                )
                if projection_cached is None:
                    time.sleep(0.01)
            self.assertIsNotNone(projection_cached)

    def test_queue_backfill_skips_cached_entries_when_a_higher_dimension_vector_exists(
        self,
    ) -> None:
        provider = SentenceTransformerEmbeddingProvider()
        entry = EmbeddingPreloadEntry(cache_key="memory-1", text="release evidence summary")

        def _encode(texts: tuple[str, ...], *, dimensions: int) -> tuple[tuple[float, ...], ...]:
            return tuple(_unit_vector(dimensions, index=index) for index, _text in enumerate(texts))

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
            mock.patch.object(provider, "_encode_texts", side_effect=_encode),
        ):
            provider.preload(
                target="evidence",
                entries=(entry,),
                latency_mode="balanced",
            )
            with mock.patch.object(provider, "_spawn_backfill_worker") as spawn:
                state = provider.queue_backfill(
                    target="evidence",
                    entries=(entry,),
                    latency_mode="fast",
                )

        self.assertEqual(state.status, "ready")
        spawn.assert_not_called()
        self.assertIsNotNone(provider.cached_vector(target="evidence", cache_key="memory-1", dimensions=64))

    def test_pending_vector_reports_queued_backfill_without_embedding(self) -> None:
        provider = SentenceTransformerEmbeddingProvider()
        entry = EmbeddingPreloadEntry(cache_key="memory-1", text="release evidence summary")

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
            mock.patch.object(provider, "_spawn_backfill_worker") as spawn,
        ):
            state = provider.queue_backfill(
                target="evidence",
                entries=(entry,),
                latency_mode="fast",
            )

        self.assertEqual(state.status, "steadying")
        spawn.assert_called_once()
        self.assertTrue(provider.pending_vector(target="evidence", cache_key="memory-1", dimensions=64))
        self.assertFalse(provider.pending_vector(target="evidence", cache_key="memory-2", dimensions=64))

    def test_queue_backfill_respects_failure_cooldown_after_worker_errors(self) -> None:
        provider = SentenceTransformerEmbeddingProvider()
        entry = EmbeddingPreloadEntry(cache_key="memory-1", text="release evidence summary")

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
            mock.patch.object(provider, "_encode_texts", side_effect=RuntimeError("boom")),
        ):
            provider.queue_backfill(
                target="evidence",
                entries=(entry,),
                latency_mode="fast",
            )
            deadline = time.time() + 1.0
            state = provider.preload_state()
            while state.status != "failed" and time.time() < deadline:
                time.sleep(0.01)
                state = provider.preload_state()

            self.assertEqual(state.status, "failed")
            self.assertIn("cooldown", state.summary)

            with mock.patch.object(provider, "_spawn_backfill_worker") as spawn:
                repeated = provider.queue_backfill(
                    target="evidence",
                    entries=(entry,),
                    latency_mode="fast",
                )

        self.assertEqual(repeated.status, "failed")
        spawn.assert_not_called()

    def test_steady_async_loads_the_local_model_only_once(self) -> None:
        provider = SentenceTransformerEmbeddingProvider()
        loaded: list[str] = []

        def _load_model() -> object:
            loaded.append("loaded")
            time.sleep(0.05)
            return object()

        with (
            mock.patch(
                "packages.embeddings.runtime.sentence_transformers_dependencies_ready",
                return_value=True,
            ),
            mock.patch(
                "packages.embeddings.runtime.embedding_root_is_healthy",
                return_value=True,
            ),
            mock.patch.object(provider, "_load_model", side_effect=_load_model),
        ):
            self.assertTrue(provider.steady_async())
            self.assertFalse(provider.steady_async())
            deadline = time.time() + 1.0
            while len(loaded) < 1 and time.time() < deadline:
                time.sleep(0.01)

        self.assertEqual(loaded, ["loaded"])


if __name__ == "__main__":
    unittest.main()
