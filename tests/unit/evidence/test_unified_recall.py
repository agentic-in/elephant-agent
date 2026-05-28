from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from packages.contracts.layers import Step
from packages.evidence.unified_recall import UnifiedRecallRequest, unified_recall
from packages.storage import RuntimeStorageRepository


class UnifiedRecallFallbackTests(unittest.TestCase):
    def test_step_fallback_uses_bounded_state_scoped_query(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.step_calls: list[dict[str, object]] = []

            def list_steps(self, **kwargs: object) -> tuple[Step, ...]:
                self.step_calls.append(dict(kwargs))
                return (
                    Step(
                        step_id="step:bounded",
                        loop_id="loop:bounded",
                        episode_id="episode:bounded",
                        state_id="state:you",
                        personal_model_id="you",
                        phase="observation",
                        action="record_input",
                        status="completed",
                        sequence=1,
                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        summary="",
                        metadata={"user_query": "concise examples please"},
                    ),
                )

            def list_episodes(self, **_: object) -> tuple[object, ...]:
                return ()

            def list_semantic_index_entries(self, **_: object) -> tuple[object, ...]:
                return ()

        repository = Repository()

        hits = unified_recall(
            UnifiedRecallRequest(
                query="concise",
                scopes=("steps",),
                personal_model_id="you",
                state_id="state:you",
                limit=3,
            ),
            repository=repository,
            searcher=None,
        )

        self.assertTrue(hits)
        self.assertIn("concise", hits[0].content)
        self.assertEqual(
            repository.step_calls,
            [
                {
                    "state_id": "state:you",
                    "personal_model_id": "you",
                    "created_at_start": None,
                    "created_at_end": None,
                    "limit": 200,
                    "newest_first": True,
                }
            ],
        )

    def test_fallback_logs_bounded_repository_failures(self) -> None:
        class Repository:
            def list_episodes(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("episodes unavailable")

            def list_steps(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("steps unavailable")

            def list_semantic_index_entries(self, **_: object) -> tuple[object, ...]:
                return ()

        with self.assertLogs("packages.evidence.unified_recall", level="DEBUG") as logs:
            hits = unified_recall(
                UnifiedRecallRequest(
                    query="anything",
                    scopes=("episodes", "steps"),
                    personal_model_id="you",
                    state_id="state:you",
                    limit=3,
                ),
                repository=Repository(),
                searcher=None,
            )

        rendered_logs = "\n".join(logs.output)
        self.assertEqual(hits, ())
        self.assertIn("Failed to load episode recall documents using bounded query", rendered_logs)
        self.assertIn("Failed to load step recall documents using bounded query", rendered_logs)

    def test_fallback_logs_compatibility_repository_failures(self) -> None:
        class Repository:
            def list_episodes(self, **kwargs: object) -> tuple[object, ...]:
                if "limit" in kwargs:
                    raise TypeError("old repository signature")
                raise RuntimeError("compat episodes unavailable")

            def list_steps(self, **kwargs: object) -> tuple[object, ...]:
                if kwargs:
                    raise TypeError("old repository signature")
                raise RuntimeError("compat steps unavailable")

            def list_semantic_index_entries(self, **_: object) -> tuple[object, ...]:
                return ()

        with self.assertLogs("packages.evidence.unified_recall", level="DEBUG") as logs:
            hits = unified_recall(
                UnifiedRecallRequest(
                    query="anything",
                    scopes=("episodes", "steps"),
                    personal_model_id="you",
                    state_id="state:you",
                    limit=3,
                ),
                repository=Repository(),
                searcher=None,
            )

        rendered_logs = "\n".join(logs.output)
        self.assertEqual(hits, ())
        self.assertIn("Failed to load episode recall documents using compatibility query", rendered_logs)
        self.assertIn("Failed to load step recall documents using compatibility query", rendered_logs)

    def test_hybrid_logs_dimension_health_and_search_failures(self) -> None:
        class Repository:
            def list_semantic_index_entries(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("index unavailable")

            def list_steps(self, **_: object) -> tuple[object, ...]:
                return ()

            def list_episodes(self, **_: object) -> tuple[object, ...]:
                return ()

        class Searcher:
            def search(self, query: object) -> tuple[object, ...]:
                del query
                raise RuntimeError("search unavailable")

        with self.assertLogs("packages.evidence.unified_recall", level="DEBUG") as logs:
            hits = unified_recall(
                UnifiedRecallRequest(
                    query="query",
                    scopes=("steps",),
                    personal_model_id="you",
                    state_id="state:you",
                    limit=3,
                ),
                repository=Repository(),
                searcher=Searcher(),
                embedding_service=object(),
                embedding_health_callable=lambda: (_ for _ in ()).throw(RuntimeError("health unavailable")),
            )

        rendered_logs = "\n".join(logs.output)
        self.assertEqual(hits, ())
        self.assertIn("Failed to inspect embedding runtime health for unified recall", rendered_logs)
        self.assertIn("Failed to inspect indexed recall dimensions", rendered_logs)
        self.assertIn("Hybrid semantic recall search failed for scope steps", rendered_logs)

    def test_hybrid_logs_query_embedding_failure(self) -> None:
        class Repository:
            def list_semantic_index_entries(self, **_: object) -> tuple[object, ...]:
                return ()

            def list_steps(self, **_: object) -> tuple[object, ...]:
                return ()

            def list_episodes(self, **_: object) -> tuple[object, ...]:
                return ()

        class EmbeddingService:
            def embed_text(self, *_: object, **__: object) -> object:
                raise RuntimeError("embedding unavailable")

        class Searcher:
            def search(self, query: object) -> tuple[object, ...]:
                del query
                return ()

        with self.assertLogs("packages.evidence.unified_recall", level="DEBUG") as logs:
            hits = unified_recall(
                UnifiedRecallRequest(
                    query="query",
                    scopes=("steps",),
                    personal_model_id="you",
                    state_id="state:you",
                    limit=3,
                ),
                repository=Repository(),
                searcher=Searcher(),
                embedding_service=EmbeddingService(),
                embedding_health_callable=lambda: SimpleNamespace(
                    status="ready",
                    metadata={"runtime_state": "loaded"},
                ),
            )

        self.assertEqual(hits, ())
        self.assertIn("Failed to embed unified recall query", "\n".join(logs.output))

    def test_conversation_recall_includes_path_learning_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            path = repository.create_path(title="Strength learning")
            step = repository.create_path_step(
                path_id=path.path_id,
                title="Explain progressive overload",
            )
            repository.write_learning_summary(
                path_step_id=step.path_step_id,
                what_done="Explained progressive overload with a simple training loop.",
                knowledge="Progressive overload needs small measurable increments and recovery.",
                human_takeaway="Increase one lift only after the baseline feels stable.",
            )
            repository.create_path_step_run(
                path_step_id=step.path_step_id,
                status="running",
                progress_stage="working",
                progress_detail="progressive overload draft in progress",
            )

            hits = unified_recall(
                UnifiedRecallRequest(
                    query="progressive overload recovery",
                    scopes=("steps",),
                    personal_model_id="you",
                    state_id="state:you",
                    limit=3,
                ),
                repository=repository,
                searcher=None,
            )

        self.assertTrue(hits)
        self.assertEqual(hits[0].kind, "path:learning_summary")
        self.assertIn("Progressive overload", hits[0].content)
        self.assertEqual(hits[0].extra_metadata["recall_source"], "path_learning_summary")
        self.assertNotIn("path:step", {hit.kind for hit in hits})
        self.assertNotIn("path:run", {hit.kind for hit in hits})


if __name__ == "__main__":
    unittest.main()
