"""Kernel-facing recall runtime.

The kernel consumes recall as Step / Episode / SemanticIndex evidence retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from packages.contracts.runtime import (
    EvidenceRetrievalRequest,
    EvidenceRetrievalResult,
    RecallEvidence,
)

from .runtime import (
    DefaultEvidenceRetriever,
    build_embedding_index_policy,
)
from .state_focus_support import build_resume_packet
from .unified_recall import UnifiedRecallRequest, unified_recall


class StepEvidenceStore:
    """Read-only view over canonical Step/Episode evidence."""

    def __init__(self, repository: object | None = None) -> None:
        self.repository = repository

    def upsert(self, evidence: RecallEvidence) -> None:
        del evidence
        raise RuntimeError("RecallEvidence persistence was removed; write Step records or Facts instead")

    def get(self, evidence_ref: str) -> RecallEvidence | None:
        repository = self.repository
        load_step = getattr(repository, "load_step", None)
        if not callable(load_step):
            return None
        step_id = evidence_ref.removeprefix("step:")
        step = load_step(step_id)
        if step is None:
            return None
        return self._step_to_evidence(step)

    def _step_to_evidence(self, step: object) -> RecallEvidence:
        metadata = dict(getattr(step, "metadata", {}) or {})
        metadata.setdefault("status", str(getattr(step, "status", "") or ""))
        metadata.setdefault("phase", str(getattr(step, "phase", "") or ""))
        metadata.setdefault("sequence", str(getattr(step, "sequence", "") or ""))
        content_parts = tuple(
            part
            for part in (
                str(getattr(step, "summary", "") or "").strip(),
                str(getattr(step, "outcome", "") or "").strip(),
            )
            if part
        )
        content = "\n".join(content_parts) or str(getattr(step, "action", "") or "").strip()
        step_id = str(getattr(step, "step_id", "") or "")
        return RecallEvidence(
            evidence_id=f"step:{step_id}",
            episode_id=str(getattr(step, "episode_id", "") or ""),
            kind=str(getattr(step, "action", "") or "step"),
            content=content,
            source_id=step_id,
            source_kind="step",
            step_id=step_id,
            loop_id=str(getattr(step, "loop_id", "") or "") or None,
            created_at=getattr(step, "created_at", None),
            metadata=metadata,
        )

    def _steps_for_episode(self, episode_id: str | None) -> tuple[object, ...]:
        repository = self.repository
        list_steps = getattr(repository, "list_steps", None)
        if not callable(list_steps):
            return ()
        steps = tuple(list_steps())
        if episode_id is None:
            return steps
        return tuple(step for step in steps if getattr(step, "episode_id", None) == episode_id)

    def get_by_evidence_id(self, evidence_id: str) -> RecallEvidence | None:
        if evidence_id.startswith("step:"):
            return self.get(evidence_id)
        return None

    def list(self, episode_id: str | None = None, *, include_inactive: bool = False) -> tuple[RecallEvidence, ...]:
        del include_inactive
        return tuple(self._step_to_evidence(step) for step in self._steps_for_episode(episode_id))

    def state(self, evidence_ref: str) -> Mapping[str, object]:
        evidence = self.get_by_evidence_id(evidence_ref)
        if evidence is None:
            return {}
        return {
            "status": str(evidence.metadata.get("status") or "active"),
            "source_kind": evidence.source_kind,
        }

    def lineage(self, evidence_ref: str) -> tuple[str, ...]:
        evidence = self.get_by_evidence_id(evidence_ref)
        if evidence is None:
            return ()
        refs = [f"episode:{evidence.episode_id}"]
        if evidence.loop_id:
            refs.append(f"loop:{evidence.loop_id}")
        if evidence.step_id:
            refs.append(f"step:{evidence.step_id}")
        return tuple(refs)


@dataclass(frozen=True, slots=True)
class RecallRetrievalCandidate:
    evidence: RecallEvidence
    score: float = 0.0
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecallRetrievalResult:
    candidates: tuple[RecallRetrievalCandidate, ...] = ()
    scope_reason: str = ""


class _RetrieverFacade:
    def __init__(self, evidence_retriever: DefaultEvidenceRetriever) -> None:
        self.evidence_retriever = evidence_retriever


class RecallRuntime:
    def __init__(
        self,
        *,
        repository: object | None = None,
        evidence_retriever: DefaultEvidenceRetriever,
    ) -> None:
        self.repository = repository
        self.store = StepEvidenceStore(repository)
        self.evidence_retriever = evidence_retriever
        self.retriever = _RetrieverFacade(evidence_retriever)

    @classmethod
    def from_repository(
        cls,
        repository: object,
        *,
        semantic_index_bundle: object | None = None,
        semantic_bundle: object | None = None,
        retriever: object | None = None,
    ) -> "RecallRuntime":
        evidence_retriever = getattr(retriever, "evidence_retriever", None)
        if evidence_retriever is None:
            store = StepEvidenceStore(repository)
            evidence_retriever = DefaultEvidenceRetriever(
                store,
                repository=repository,
                semantic_bundle=semantic_index_bundle or semantic_bundle,
            )
        return cls(repository=repository, evidence_retriever=evidence_retriever)

    def append_event(self, event: object) -> None:
        del event
        return None

    def retrieve(
        self,
        episode_id: str,
        query: str,
        *,
        work_item_ids: tuple[str, ...] = (),
        scope_episode_ids: tuple[str, ...] = (),
        scope_reason: str = "",
        limit: int = 5,
    ) -> RecallRetrievalResult:
        del work_item_ids, scope_episode_ids
        if self.repository is None:
            return RecallRetrievalResult(scope_reason=scope_reason)
        hits = unified_recall(
            UnifiedRecallRequest(
                query=query,
                personal_model_id="you",
                state_id=None,
                episode_id=episode_id,
                scopes=("steps", "episodes"),
                limit=limit,
            ),
            repository=self.repository,
        )
        candidates = tuple(
            RecallRetrievalCandidate(
                evidence=RecallEvidence(
                    evidence_id=f"recall:{index}",
                    episode_id=episode_id,
                    kind=hit.kind,
                    content=hit.content,
                    created_at=hit.when_datetime,
                    metadata=dict(hit.extra_metadata),
                ),
                score=hit.score,
            )
            for index, hit in enumerate(hits)
        )
        return RecallRetrievalResult(candidates=candidates, scope_reason=scope_reason)

    def retrieve_evidence(self, request: EvidenceRetrievalRequest) -> EvidenceRetrievalResult:
        return self.evidence_retriever.retrieve(request)

    def build_resume_packet(
        self,
        request: EvidenceRetrievalRequest,
        retrieval: EvidenceRetrievalResult,
        **kwargs: object,
    ):
        return build_resume_packet(request, retrieval, **kwargs)

    def index_policy(self):
        return build_embedding_index_policy(tracked_evidence_count=0)
