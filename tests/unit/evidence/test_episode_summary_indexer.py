"""Tests for the producer-side SemanticSummaryIndexer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any

from packages.contracts import Episode, Fact, PersonalModel, State, Step
from packages.contracts.paths import LearningSummaryRecord, PathRecord, PathStepRecord
from packages.evidence import (
    SemanticSummaryIndexer,
    backfill_existing_semantic_summaries,
    build_episode_summary_text,
    build_learning_summary_recall_text,
    build_personal_model_claim_text,
)


@dataclass
class _StubEmbeddingVector:
    values: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4)
    dimensions: int = 4


@dataclass
class _StubEmbeddingService:
    calls: list[dict[str, Any]] = field(default_factory=list)
    raise_on_embed: bool = False

    def embed_text(self, text: str, **kwargs: Any) -> _StubEmbeddingVector:
        if self.raise_on_embed:
            raise RuntimeError("embedding down")
        self.calls.append({"text": text, "kwargs": dict(kwargs)})
        return _StubEmbeddingVector()


@dataclass
class _StubSemanticIndex:
    documents: list[Any] = field(default_factory=list)
    raise_on_index: bool = False

    def index_document(self, document: Any) -> Any:
        if self.raise_on_index:
            raise RuntimeError("index down")
        self.documents.append(document)
        return document


def _episode(**kwargs: Any) -> Episode:
    defaults: dict[str, Any] = dict(
        episode_id="session:1",
        state_id="state:1",
        personal_model_id="pm:1",
        entry_surface="cli",
        status="closed",
        started_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        exit_summary="We finished reviewing the deploy script and found two issues.",
    )
    defaults.update(kwargs)
    return Episode(**defaults)


def _fact(**kwargs: Any) -> Fact:
    defaults: dict[str, Any] = dict(
        fact_id="fact:pm:1",
        personal_model_id="pm:1",
        lens="identity",
        text="I prefer concise answers over long explanations.",
        confidence=0.82,
        committed_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        source="pm_agent_promote",
        metadata={"topic": "identity.communication.verbosity"},
    )
    defaults.update(kwargs)
    return Fact(**defaults)


def _path(**kwargs: Any) -> PathRecord:
    defaults: dict[str, Any] = dict(
        path_id="path:learn",
        personal_model_id="pm:1",
        title="Research operating loop",
    )
    defaults.update(kwargs)
    return PathRecord(**defaults)


def _path_step(**kwargs: Any) -> PathStepRecord:
    defaults: dict[str, Any] = dict(
        path_step_id="path-step:summary",
        path_id="path:learn",
        personal_model_id="pm:1",
        title="Extract the core lesson",
        description="Keep the durable user takeaway small.",
    )
    defaults.update(kwargs)
    return PathStepRecord(**defaults)


def _learning_summary(**kwargs: Any) -> LearningSummaryRecord:
    defaults: dict[str, Any] = dict(
        summary_id="learning-summary:1",
        path_step_id="path-step:summary",
        path_id="path:learn",
        run_id="run:1",
        what_done="Condensed the raw run into a durable study note.",
        why_it_matters="The user can recall the useful lesson without reading logs.",
        how_it_was_done="Kept plan details out and preserved the takeaway.",
        knowledge="Path runs should be summarized before they become memory.",
        human_takeaway="Index the core essence, not every progress event.",
    )
    defaults.update(kwargs)
    return LearningSummaryRecord(**defaults)


def _step(**kwargs: Any) -> Step:
    defaults: dict[str, Any] = dict(
        step_id="step:1",
        loop_id="loop:1",
        episode_id="session:1",
        state_id="state:1",
        personal_model_id="pm:1",
        phase="observation",
        action="record_input",
        status="completed",
        sequence=1,
        created_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        metadata={"user_query": "Remember that I care about semantic recall."},
    )
    defaults.update(kwargs)
    return Step(**defaults)


def test_build_episode_summary_joins_entry_exit_and_metadata() -> None:
    ep = _episode(
        entry_surface="cli",
        exit_summary="Fixed the deploy bug and shipped the patch.",
        metadata={"topic": "deploy.release.success", "note": "success"},
    )
    text = build_episode_summary_text(ep)
    assert "exit: Fixed the deploy bug" in text
    assert "entry: cli" in text
    assert "topic: deploy" in text
    assert "note: success" in text


def test_build_personal_model_claim_text_collects_lens_topic_claim() -> None:
    r = _fact()
    text = build_personal_model_claim_text(r)
    assert "lens: identity" in text
    assert "topic: identity.communication.verbosity" in text
    assert "I prefer concise answers" in text


def test_build_learning_summary_recall_text_prioritizes_takeaway_and_knowledge() -> None:
    text = build_learning_summary_recall_text(
        _learning_summary(),
        path_step=_path_step(),
        path=_path(),
    )
    assert "Research operating loop" in text
    assert "Extract the core lesson" in text
    assert "Index the core essence" in text
    assert "Path runs should be summarized" in text


def test_indexer_noop_without_semantic_index_or_embedding() -> None:
    indexer = SemanticSummaryIndexer()
    assert indexer.index_episode_exit(_episode()) is None
    assert indexer.index_personal_model_claim(_fact()) is None


def test_indexer_writes_one_document_per_episode_exit() -> None:
    emb = _StubEmbeddingService()
    idx = _StubSemanticIndex()
    indexer = SemanticSummaryIndexer(
        semantic_index=idx,
        embedding_service=emb,
        provider_id="stub-provider",
        model_id="stub-model",
    )
    indexer.index_episode_exit(_episode())
    assert len(idx.documents) == 1
    doc = idx.documents[0]
    assert doc.owner_scope == "state"
    assert doc.source_id == "episode:session:1"
    assert doc.dimensions == 4
    assert "deploy script" in doc.text
    # No record ids leak into the indexed text.
    assert "record:" not in doc.text


def test_indexer_writes_document_for_committed_personal_model_claim() -> None:
    emb = _StubEmbeddingService()
    idx = _StubSemanticIndex()
    indexer = SemanticSummaryIndexer(
        semantic_index=idx,
        embedding_service=emb,
        provider_id="stub-provider",
        model_id="stub-model",
    )
    indexer.index_personal_model_claim(_fact())
    assert len(idx.documents) == 1
    doc = idx.documents[0]
    assert doc.owner_scope == "personal_model"
    assert doc.personal_model_id == "pm:1"
    assert doc.source_id == "fact:pm:1"


def test_indexer_writes_document_for_path_learning_summary() -> None:
    emb = _StubEmbeddingService()
    idx = _StubSemanticIndex()
    indexer = SemanticSummaryIndexer(
        semantic_index=idx,
        embedding_service=emb,
        provider_id="stub-provider",
        model_id="stub-model",
    )
    indexer.index_learning_summary(
        _learning_summary(),
        path_step=_path_step(),
        path=_path(),
    )
    assert len(idx.documents) == 1
    doc = idx.documents[0]
    assert doc.owner_scope == "personal_model"
    assert doc.personal_model_id == "pm:1"
    assert doc.state_id is None
    assert doc.source_id == "path:learning_summary:learning-summary:1"
    assert doc.metadata["kind"] == "path_learning_summary"
    assert "core essence" in doc.text


def test_backfill_existing_semantic_summaries_indexes_missing_records() -> None:
    emb = _StubEmbeddingService()
    idx = _StubSemanticIndex()
    indexer = SemanticSummaryIndexer(
        semantic_index=idx,
        embedding_service=emb,
        provider_id="stub-provider",
        model_id="stub-model",
    )

    class _Repository:
        def list_semantic_index_entries(self):
            return ()

        def list_personal_models(self):
            return (PersonalModel(personal_model_id="pm:1"),)

        def current_state(self):
            return State(state_id="state:1", personal_model_id="pm:1", state_anchor="qa")

        def list_personal_model_facts(self, **_kwargs: Any):
            return (_fact(),)

        def list_episodes(self, **_kwargs: Any):
            return (_episode(),)

        def list_steps(self, **_kwargs: Any):
            return (_step(), _step(step_id="step:tool", action="call_tool", metadata={"tool_name": "noop"}))

        def list_learning_summaries(self, **_kwargs: Any):
            return (_learning_summary(),)

        def load_path_step(self, path_step_id: str):
            return _path_step(path_step_id=path_step_id)

        def load_path(self, path_id: str):
            return _path(path_id=path_id)

    result = backfill_existing_semantic_summaries(repository=_Repository(), indexer=indexer)

    assert result.facts_indexed == 1
    assert result.episodes_indexed == 1
    assert result.steps_indexed == 1
    assert result.learning_summaries_indexed == 1
    assert result.total_indexed == 4
    assert [doc.source_id for doc in idx.documents] == [
        "fact:pm:1",
        "episode:session:1",
        "step:step:1",
        "path:learning_summary:learning-summary:1",
    ]


def test_backfill_existing_semantic_summaries_skips_existing_source_ids() -> None:
    emb = _StubEmbeddingService()
    idx = _StubSemanticIndex()
    indexer = SemanticSummaryIndexer(
        semantic_index=idx,
        embedding_service=emb,
        provider_id="stub-provider",
        model_id="stub-model",
    )

    class _Repository:
        def list_semantic_index_entries(self):
            return (
                type("Entry", (), {"source_id": "fact:pm:1", "status": "indexed"})(),
                type("Entry", (), {"source_id": "episode:session:1", "status": "indexed"})(),
            )

        def list_personal_models(self):
            return (PersonalModel(personal_model_id="pm:1"),)

        def list_personal_model_facts(self, **_kwargs: Any):
            return (_fact(),)

        def list_episodes(self, **_kwargs: Any):
            return (_episode(),)

        def list_steps(self, **_kwargs: Any):
            return (_step(),)

    result = backfill_existing_semantic_summaries(repository=_Repository(), indexer=indexer)

    assert result.facts_indexed == 0
    assert result.episodes_indexed == 0
    assert result.steps_indexed == 1
    assert [doc.source_id for doc in idx.documents] == ["step:step:1"]


def test_indexer_swallows_embedding_exception(caplog) -> None:
    emb = _StubEmbeddingService(raise_on_embed=True)
    idx = _StubSemanticIndex()
    indexer = SemanticSummaryIndexer(
        semantic_index=idx,
        embedding_service=emb,
        provider_id="stub-provider",
        model_id="stub-model",
    )
    with caplog.at_level(logging.DEBUG, logger="packages.evidence.episode_summary_indexer"):
        assert indexer.index_episode_exit(_episode()) is None
    assert idx.documents == []
    assert "Semantic summary embedding failed" in caplog.text
    assert "embedding down" in caplog.text


def test_indexer_swallows_semantic_index_exception(caplog) -> None:
    emb = _StubEmbeddingService()
    idx = _StubSemanticIndex(raise_on_index=True)
    indexer = SemanticSummaryIndexer(
        semantic_index=idx,
        embedding_service=emb,
        provider_id="stub-provider",
        model_id="stub-model",
    )
    with caplog.at_level(logging.DEBUG, logger="packages.evidence.episode_summary_indexer"):
        assert indexer.index_personal_model_claim(_fact()) is None
    assert "Semantic summary indexing failed" in caplog.text
    assert "index down" in caplog.text


def test_indexer_skips_when_text_is_empty() -> None:
    # Exercise the early-return in `_index` by passing text that collapses to
    # empty after truncation. We hit this via a blank fact.
    emb = _StubEmbeddingService()
    idx = _StubSemanticIndex()
    indexer = SemanticSummaryIndexer(
        semantic_index=idx,
        embedding_service=emb,
        provider_id="stub-provider",
        model_id="stub-model",
    )
    try:
        blank = _fact(text="", metadata={})
        result = indexer.index_personal_model_claim(blank)
    except ValueError:
        result = None
    assert result is None
    assert idx.documents == []
