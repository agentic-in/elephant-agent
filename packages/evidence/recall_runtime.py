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

from .runtime import DefaultEvidenceRetriever, build_embedding_index_policy, build_resume_packet
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

    def _steps_for_episode(self, episode_id: str | None, *, episode_ids: tuple[str, ...] | None = None) -> tuple[object, ...]:
        repository = self.repository
        list_steps = getattr(repository, "list_steps", None)
        if not callable(list_steps):
            return ()
        if episode_ids is not None:
            # Fast path: push filtering down to SQL via episode_ids parameter.
            try:
                return tuple(list_steps(episode_ids=episode_ids))
            except TypeError:
                # Fallback if the repository doesn't support episode_ids kwarg.
                steps = tuple(list_steps())
                id_set = set(episode_ids)
                return tuple(step for step in steps if getattr(step, "episode_id", None) in id_set)
        if episode_id is None:
            return tuple(list_steps())
        try:
            return tuple(list_steps(episode_id=episode_id))
        except TypeError:
            steps = tuple(list_steps())
        return tuple(step for step in steps if getattr(step, "episode_id", None) == episode_id)

    def get_by_evidence_id(self, evidence_id: str) -> RecallEvidence | None:
        if evidence_id.startswith("step:"):
            return self.get(evidence_id)
        return None

    def list(self, episode_id: str | None = None, *, include_inactive: bool = False, episode_ids: tuple[str, ...] | None = None) -> tuple[RecallEvidence, ...]:
        del include_inactive
        return tuple(self._step_to_evidence(step) for step in self._steps_for_episode(episode_id, episode_ids=episode_ids))

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

    def _episode_scope(self, episode_id: str) -> tuple[str, str | None]:
        repository = self.repository
        personal_model_id = "you"
        state_id: str | None = None
        if repository is None:
            return personal_model_id, state_id

        episode = None
        for loader_name in ("load_episode", "load_episode_state"):
            loader = getattr(repository, loader_name, None)
            if not callable(loader):
                continue
            try:
                episode = loader(episode_id)
            except Exception:
                episode = None
            if episode is not None:
                break

        if episode is None:
            return personal_model_id, state_id
        resolved_personal_model_id = str(getattr(episode, "personal_model_id", "") or "").strip()
        resolved_state_id = str(getattr(episode, "state_id", "") or "").strip()
        return resolved_personal_model_id or personal_model_id, resolved_state_id or None

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
        personal_model_id, state_id = self._episode_scope(episode_id)
        semantic_bundle = getattr(self.evidence_retriever, "semantic_bundle", None)
        searcher = getattr(semantic_bundle, "searcher", None)
        embedding_service = getattr(self.evidence_retriever, "embedding_service", None)
        embedding_health = getattr(embedding_service, "health", None)
        hits = unified_recall(
            UnifiedRecallRequest(
                query=query,
                personal_model_id=personal_model_id,
                state_id=state_id,
                scopes=("steps", "episodes"),
                limit=limit,
            ),
            repository=self.repository,
            searcher=searcher,
            embedding_service=embedding_service,
            embedding_health_callable=embedding_health if callable(embedding_health) else None,
        )
        candidates = tuple(
            RecallRetrievalCandidate(
                evidence=RecallEvidence(
                    evidence_id=f"recall:{index}",
                    episode_id=str(hit.extra_metadata.get("episode_id") or episode_id),
                    kind=hit.kind,
                    content=hit.content,
                    source_id=str(
                        hit.extra_metadata.get("source_id")
                        or hit.extra_metadata.get("step_id")
                        or hit.extra_metadata.get("document_id")
                        or hit.extra_metadata.get("episode_id")
                        or ""
                    ),
                    source_kind=str(hit.extra_metadata.get("recall_source") or hit.extra_metadata.get("owner_scope") or "semantic_index"),
                    step_id=str(hit.extra_metadata.get("step_id") or "") or None,
                    loop_id=str(hit.extra_metadata.get("loop_id") or "") or None,
                    created_at=hit.when_datetime,
                    metadata=dict(hit.extra_metadata),
                ),
                score=hit.score,
                reasons=tuple(str(reason) for reason in str(hit.extra_metadata.get("semantic_reasons") or "").split(",") if reason),
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
