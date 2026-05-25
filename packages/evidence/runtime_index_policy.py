"""Embedding index policy helpers for evidence retrieval."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from packages.contracts.runtime import (
    EmbeddingIndexInvalidation,
    EmbeddingIndexPolicy,
    EmbeddingIndexRebuildPlan,
    RecallEvidence,
)
from packages.embeddings import ELEPHANT_EMBED_MODEL_ID, ELEPHANT_EMBED_ONLINE_DIMENSIONS

from .runtime_replay import _evidence_preload_entry

if TYPE_CHECKING:
    from .recall_runtime import StepEvidenceStore


_LEXICAL_INDEX_VERSION = "fts5-evidence-v1"
_EMBEDDING_INDEX_VERSION = f"{ELEPHANT_EMBED_MODEL_ID}@2026-04"


def _evidence_sort_key(record: RecallEvidence) -> tuple[datetime, str]:
    return (
        record.created_at or datetime.min.replace(tzinfo=timezone.utc),
        record.evidence_id,
    )


def _index_refresh_action(*, lifecycle_state: str, replacement_evidence_id: str | None) -> str:
    if lifecycle_state in {"superseded", "consolidated"} and replacement_evidence_id:
        return "replace"
    if lifecycle_state == "deleted":
        return "drop"
    return "refresh"


def _index_invalidation_reason(*, lifecycle_state: str, replacement_evidence_id: str | None) -> str:
    if lifecycle_state == "superseded" and replacement_evidence_id:
        return f"superseded evidence must be replaced by {replacement_evidence_id} before lexical and vector views are trusted"
    if lifecycle_state == "consolidated" and replacement_evidence_id:
        return f"consolidated evidence must be replaced by summary {replacement_evidence_id} before lexical and vector views are trusted"
    if lifecycle_state == "deleted":
        return "deleted evidence must be removed from lexical and vector views"
    return f"{lifecycle_state} evidence must refresh derived lexical and vector views from canonical rows"


def _embedding_index_invalidations(store: "StepEvidenceStore") -> tuple[EmbeddingIndexInvalidation, ...]:
    invalidations: list[EmbeddingIndexInvalidation] = []
    ordered_records = tuple(sorted(store.list(include_inactive=True), key=_evidence_sort_key))
    for record in ordered_records:
        state_payload = store.state(record.evidence_id)
        lifecycle_state = str(state_payload.get("status") or "active")
        if lifecycle_state in {None, "active"}:
            continue
        replacement_evidence_id = None
        preload_entry = _evidence_preload_entry(record)
        invalidations.append(
            EmbeddingIndexInvalidation(
                evidence_id=record.evidence_id,
                lifecycle_state=lifecycle_state,
                stale_cache_key=preload_entry.cache_key,
                replacement_evidence_id=replacement_evidence_id,
                refresh_action=_index_refresh_action(
                    lifecycle_state=lifecycle_state,
                    replacement_evidence_id=replacement_evidence_id,
                ),
                reason=_index_invalidation_reason(
                    lifecycle_state=lifecycle_state,
                    replacement_evidence_id=replacement_evidence_id,
                ),
            )
        )
    return tuple(invalidations)


def build_embedding_index_rebuild_plan(store: "StepEvidenceStore") -> EmbeddingIndexRebuildPlan:
    ordered_records = tuple(sorted(store.list(include_inactive=True), key=_evidence_sort_key))
    active_records = tuple(
        record
        for record in ordered_records
        if str(store.state(record.evidence_id).get("status") or "active") == "active"
    )
    invalidations = _embedding_index_invalidations(store)
    active_entries = tuple(_evidence_preload_entry(record) for record in active_records)
    replacement_evidence_ids = tuple(
        dict.fromkeys(
            invalidation.replacement_evidence_id
            for invalidation in invalidations
            if invalidation.replacement_evidence_id is not None
        )
    )
    if not invalidations:
        return EmbeddingIndexRebuildPlan(
            target="evidence",
            refresh_scope="noop",
            active_evidence_ids=tuple(record.evidence_id for record in active_records),
            active_cache_keys=tuple(entry.cache_key for entry in active_entries),
            stale_cache_keys=(),
            replacement_evidence_ids=(),
            dimensions=ELEPHANT_EMBED_ONLINE_DIMENSIONS,
            steps=(
                "no rebuild is required while canonical evidence rows, lexical views, and shared vector projections stay aligned",
            ),
            summary="derived lexical and vector views already match the active canonical evidence rows",
        )
    stale_cache_keys = tuple(invalidation.stale_cache_key for invalidation in invalidations)
    steps = [
        f"drop {len(stale_cache_keys)} stale vector cache entr{'y' if len(stale_cache_keys) == 1 else 'ies'} for inactive evidence rows",
        f"rebuild lexical evidence views from {len(active_records)} active canonical row(s)",
        (
            f"reseed shared {ELEPHANT_EMBED_MODEL_ID} candidate vectors for {len(active_entries)} active evidence row(s) "
            f"at dimensions {', '.join(str(value) for value in ELEPHANT_EMBED_ONLINE_DIMENSIONS)}"
        ),
    ]
    if replacement_evidence_ids:
        steps.insert(
            1,
            f"promote lineage replacements before rebuild: {', '.join(replacement_evidence_ids)}",
        )
    return EmbeddingIndexRebuildPlan(
        target="evidence",
        refresh_scope="full",
        active_evidence_ids=tuple(record.evidence_id for record in active_records),
        active_cache_keys=tuple(entry.cache_key for entry in active_entries),
        stale_cache_keys=stale_cache_keys,
        replacement_evidence_ids=replacement_evidence_ids,
        dimensions=ELEPHANT_EMBED_ONLINE_DIMENSIONS,
        steps=tuple(steps),
        summary=(
            f"refresh the evidence index from {len(active_records)} active canonical row(s) after "
            f"invalidating {len(invalidations)} stale derived entr{'y' if len(invalidations) == 1 else 'ies'}"
        ),
    )


def _aligned_embedding_index_policy(*, tracked_evidence_count: int) -> EmbeddingIndexPolicy:
    rebuild_plan = EmbeddingIndexRebuildPlan(
        target="evidence",
        refresh_scope="noop",
        active_evidence_ids=(),
        active_cache_keys=(),
        stale_cache_keys=(),
        replacement_evidence_ids=(),
        dimensions=ELEPHANT_EMBED_ONLINE_DIMENSIONS,
        steps=(
            "hot-path retrieval does not rebuild evidence indexes; producer-side indexing owns durable refresh",
        ),
        summary="derived lexical and vector views are read as-is on the retrieval hot path",
    )
    return EmbeddingIndexPolicy(
        model_id=ELEPHANT_EMBED_MODEL_ID,
        lexical_index_version=_LEXICAL_INDEX_VERSION,
        embedding_index_version=_EMBEDDING_INDEX_VERSION,
        active_dimensions=ELEPHANT_EMBED_ONLINE_DIMENSIONS,
        tracked_evidence_count=max(0, int(tracked_evidence_count)),
        rebuild_required=False,
        invalidated_evidence_ids=(),
        invalidation_reason="derived lexical and vector views are aligned with the active canonical evidence rows",
        invalidations=(),
        rebuild_plan=rebuild_plan,
    )


def build_embedding_index_policy(
    store: "StepEvidenceStore | None" = None,
    *,
    tracked_evidence_count: int | None = None,
) -> EmbeddingIndexPolicy:
    if store is None:
        return _aligned_embedding_index_policy(
            tracked_evidence_count=0 if tracked_evidence_count is None else tracked_evidence_count,
        )
    invalidations = _embedding_index_invalidations(store)
    rebuild_plan = build_embedding_index_rebuild_plan(store)
    invalidation_reason = (
        "superseded, consolidated, and deleted evidence must invalidate derived lexical and vector views"
        if invalidations
        else "derived lexical and vector views are aligned with the active canonical evidence rows"
    )
    return EmbeddingIndexPolicy(
        model_id=ELEPHANT_EMBED_MODEL_ID,
        lexical_index_version=_LEXICAL_INDEX_VERSION,
        embedding_index_version=_EMBEDDING_INDEX_VERSION,
        active_dimensions=ELEPHANT_EMBED_ONLINE_DIMENSIONS,
        tracked_evidence_count=len(rebuild_plan.active_evidence_ids),
        rebuild_required=bool(invalidations),
        invalidated_evidence_ids=tuple(invalidation.evidence_id for invalidation in invalidations),
        invalidation_reason=invalidation_reason,
        invalidations=invalidations,
        rebuild_plan=rebuild_plan,
    )
