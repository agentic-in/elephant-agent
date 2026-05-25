from __future__ import annotations

from datetime import datetime, timezone
import unittest

from packages.contracts.runtime import EvidenceCandidate, EvidenceRetrievalRequest, RecallEvidence
from packages.evidence.recall_runtime import RecallRuntime, StepEvidenceStore
from packages.evidence.runtime import DefaultEvidenceRetriever


class RecallRuntimeTests(unittest.TestCase):
    def test_step_evidence_store_uses_episode_scoped_step_query(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def list_steps(self, **kwargs: object) -> tuple[object, ...]:
                self.calls.append(dict(kwargs))
                return (_step("step:1", episode_id="episode:1"),)

        repository = Repository()
        store = StepEvidenceStore(repository)

        records = store.list(episode_id="episode:1")

        self.assertEqual(repository.calls, [{"episode_id": "episode:1"}])
        self.assertEqual(tuple(record.evidence_id for record in records), ("step:step:1",))

    def test_default_retriever_does_not_scan_global_store_for_scoped_episode(self) -> None:
        class Store:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def list(
                self,
                episode_id: str | None = None,
                *,
                include_inactive: bool = False,
            ) -> tuple[RecallEvidence, ...]:
                self.calls.append(
                    {
                        "episode_id": episode_id,
                        "include_inactive": include_inactive,
                    }
                )
                if episode_id != "episode:1":
                    return ()
                return (
                    RecallEvidence(
                        evidence_id="evidence:1",
                        episode_id="episode:1",
                        kind="note",
                        content="concise examples",
                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    ),
                )

        store = Store()
        retriever = DefaultEvidenceRetriever(store, embedding_service=object())  # type: ignore[arg-type]

        result = retriever.retrieve(
            EvidenceRetrievalRequest(
                episode_id="episode:1",
                personal_model_id="you",
                query="concise",
                allow_embeddings=False,
            )
        )

        self.assertEqual(
            store.calls,
            [{"episode_id": "episode:1", "include_inactive": False}],
        )
        self.assertEqual(tuple(candidate.evidence.evidence_id for candidate in result.candidates), ("evidence:1",))
        self.assertEqual(result.index_policy.tracked_evidence_count, 1)

    def test_elephant_scope_uses_bounded_episode_queries(self) -> None:
        class Store:
            def __init__(self) -> None:
                self.calls: list[str | None] = []

            def list(
                self,
                episode_id: str | None = None,
                *,
                include_inactive: bool = False,
            ) -> tuple[RecallEvidence, ...]:
                del include_inactive
                self.calls.append(episode_id)
                return (
                    RecallEvidence(
                        evidence_id=f"evidence:{episode_id}",
                        episode_id=str(episode_id),
                        kind="note",
                        content="scope bounded",
                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    ),
                )

        class Repository:
            def __init__(self) -> None:
                self.episode_calls: list[dict[str, object]] = []
                self.state_calls: list[dict[str, object]] = []
                self.load_state_calls: list[str] = []

            def list_episodes(self, **kwargs: object) -> tuple[object, ...]:
                self.episode_calls.append(dict(kwargs))
                if kwargs.get("elephant_id") == "elephant-alpha":
                    return (_episode("episode:alpha-new", elephant_id="elephant-alpha"),)
                if kwargs.get("state_id") == "state:alpha":
                    return (_episode("episode:alpha-old", elephant_id=""),)
                return ()

            def list_states(self, **kwargs: object) -> tuple[object, ...]:
                self.state_calls.append(dict(kwargs))
                return (_state("state:alpha", elephant_id="elephant-alpha"),)

            def load_state(self, state_id: str) -> object | None:
                self.load_state_calls.append(state_id)
                return _state(state_id, elephant_id="elephant-alpha")

        store = Store()
        repository = Repository()
        retriever = DefaultEvidenceRetriever(
            store,  # type: ignore[arg-type]
            repository,  # type: ignore[arg-type]
            embedding_service=object(),  # type: ignore[arg-type]
        )

        result = retriever.retrieve(
            EvidenceRetrievalRequest(
                episode_id="episode:current",
                personal_model_id="you",
                elephant_id="elephant-alpha",
                scopes=("episode", "elephant"),
                query="bounded",
                allow_embeddings=False,
            )
        )

        self.assertEqual(
            repository.episode_calls,
            [
                {"elephant_id": "elephant-alpha", "newest_first": True},
                {"state_id": "state:alpha", "newest_first": True},
            ],
        )
        self.assertEqual(
            repository.state_calls,
            [{"personal_model_id": None, "elephant_id": "elephant-alpha"}],
        )
        self.assertEqual(repository.load_state_calls, ["state:alpha"])
        self.assertEqual(
            store.calls,
            ["episode:current", "episode:alpha-old", "episode:alpha-new"],
        )
        self.assertEqual(len(result.scope_episode_ids), 3)

    def test_recall_runtime_index_policy_is_lightweight_without_store_scan(self) -> None:
        runtime = RecallRuntime.from_repository(object())

        policy = runtime.index_policy()

        self.assertFalse(policy.rebuild_required)
        self.assertEqual(policy.tracked_evidence_count, 0)

    def test_embedding_health_failure_is_logged_and_uses_lexical_recall(self) -> None:
        class Store:
            def list(self, episode_id: str | None = None, *, include_inactive: bool = False):
                del episode_id, include_inactive
                return (
                    RecallEvidence(
                        evidence_id="evidence:1",
                        episode_id="episode:1",
                        kind="note",
                        content="concise examples",
                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    ),
                )

        class EmbeddingService:
            def health(self):
                raise RuntimeError("health unavailable")

        retriever = DefaultEvidenceRetriever(
            Store(),  # type: ignore[arg-type]
            embedding_service=EmbeddingService(),  # type: ignore[arg-type]
        )

        with self.assertLogs("packages.evidence.runtime", level="DEBUG") as logs:
            result = retriever.retrieve(
                EvidenceRetrievalRequest(
                    episode_id="episode:1",
                    personal_model_id="you",
                    query="concise",
                    allow_embeddings=True,
                )
            )

        self.assertEqual(tuple(candidate.evidence_id for candidate in result.candidates), ("evidence:1",))
        self.assertIn("Failed to inspect evidence embedding runtime health", "\n".join(logs.output))

    def test_query_vector_cache_failures_are_logged(self) -> None:
        class EmbeddingService:
            def cached_vector(self, **_: object):
                raise RuntimeError("cache unavailable")

            def pending_vector(self, **_: object) -> bool:
                raise RuntimeError("pending unavailable")

            def queue_backfill(self, **_: object) -> None:
                raise RuntimeError("queue unavailable")

        retriever = DefaultEvidenceRetriever(
            object(),  # type: ignore[arg-type]
            embedding_service=EmbeddingService(),  # type: ignore[arg-type]
        )

        with self.assertLogs("packages.evidence.runtime", level="DEBUG") as logs:
            vector, status = retriever._resolve_query_vector(
                EvidenceRetrievalRequest(
                    episode_id="episode:1",
                    personal_model_id="you",
                    query="concise examples",
                ),
                dims=256,
            )

        rendered_logs = "\n".join(logs.output)
        self.assertEqual(vector, ())
        self.assertEqual(status, "miss-backfilled")
        self.assertIn("Failed to read cached evidence query vector", rendered_logs)
        self.assertIn("Failed to inspect pending evidence query vector", rendered_logs)
        self.assertIn("Failed to queue evidence query vector backfill", rendered_logs)

    def test_candidate_backfill_failure_is_logged(self) -> None:
        class EmbeddingService:
            def queue_backfill(self, **_: object) -> None:
                raise RuntimeError("queue unavailable")

        retriever = DefaultEvidenceRetriever(
            object(),  # type: ignore[arg-type]
            embedding_service=EmbeddingService(),  # type: ignore[arg-type]
        )
        evidence = RecallEvidence(
            evidence_id="evidence:1",
            episode_id="episode:1",
            kind="note",
            content="concise examples",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        with self.assertLogs("packages.evidence.runtime", level="DEBUG") as logs:
            retriever._queue_candidate_backfill(
                request=EvidenceRetrievalRequest(
                    episode_id="episode:1",
                    personal_model_id="you",
                    query="concise",
                ),
                candidates=(EvidenceCandidate(evidence_id="evidence:1", evidence=evidence, score=1.0),),
                query_vector=(),
            )

        self.assertIn("Failed to queue evidence candidate vector backfill", "\n".join(logs.output))

    def test_lineage_failure_is_logged_and_uses_active_episode(self) -> None:
        class Repository:
            def lineage(self, episode_id: str):
                del episode_id
                raise RuntimeError("lineage unavailable")

        retriever = DefaultEvidenceRetriever(
            object(),  # type: ignore[arg-type]
            Repository(),  # type: ignore[arg-type]
            embedding_service=object(),  # type: ignore[arg-type]
        )

        with self.assertLogs("packages.evidence.runtime", level="DEBUG") as logs:
            self.assertEqual(retriever._lineage_episode_ids("episode:1"), ("episode:1",))

        self.assertIn("Failed to load evidence recall lineage", "\n".join(logs.output))

    def test_semantic_search_failure_is_logged(self) -> None:
        class Searcher:
            def search(self, query: object):
                del query
                raise RuntimeError("semantic search unavailable")

        retriever = DefaultEvidenceRetriever(object(), embedding_service=object())  # type: ignore[arg-type]

        with self.assertLogs("packages.evidence.runtime", level="DEBUG") as logs:
            candidates = retriever._semantic_scope_candidates(
                EvidenceRetrievalRequest(
                    episode_id="episode:1",
                    personal_model_id="you",
                    query="concise",
                ),
                owner_scope="personal_model",
                state_scope_id="state:1",
                personal_model_id="you",
                recall_evidence_by_source_id={},
                dims=256,
                query_vector=(),
                searcher=Searcher(),  # type: ignore[arg-type]
            )

        self.assertEqual(candidates, ())
        self.assertIn("Semantic evidence search failed for owner scope personal_model", "\n".join(logs.output))


def _step(step_id: str, *, episode_id: str) -> object:
    return type(
        "StepStub",
        (),
        {
            "step_id": step_id,
            "loop_id": "loop:1",
            "episode_id": episode_id,
            "action": "record_input",
            "status": "completed",
            "phase": "observation",
            "sequence": 1,
            "summary": "concise examples",
            "outcome": "",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "metadata": {},
        },
    )()


def _episode(episode_id: str, *, elephant_id: str) -> object:
    return type(
        "EpisodeStub",
        (),
        {
            "episode_id": episode_id,
            "state_id": "state:alpha",
            "personal_model_id": "you",
            "elephant_id": elephant_id,
            "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "ended_at": None,
            "metadata": {},
        },
    )()


def _state(state_id: str, *, elephant_id: str) -> object:
    return type(
        "StateStub",
        (),
        {
            "state_id": state_id,
            "personal_model_id": "you",
            "elephant_id": elephant_id,
        },
    )()


if __name__ == "__main__":
    unittest.main()
