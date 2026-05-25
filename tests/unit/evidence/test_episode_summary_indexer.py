"""Tests for the producer-side SemanticSummaryIndexer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any

from packages.contracts import Episode, Fact
from packages.evidence import (
    SemanticSummaryIndexer,
    build_episode_summary_text,
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
