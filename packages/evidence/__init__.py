"""Evidence retrieval, semantic recall, and wake-recovery helpers."""

from .inventory import EVIDENCE_SURFACES
from .recall_runtime import RecallRuntime
from .episode_summary_indexer import (
    SemanticSummaryBackfillResult,
    SemanticSummaryIndexer,
    backfill_existing_semantic_summaries,
    build_diary_entry_recall_text,
    build_episode_summary_text,
    build_learning_summary_recall_text,
    build_personal_model_claim_text,
    build_step_recall_text,
)
from .recall_support import (
    RecallCandidate,
    RecallHit,
    rank_recall_candidates,
    render_recall_hit,
)
from .recall_lifecycle import RecallLifecycleInference, infer_recall_lifecycle_metadata
from .recall_planning import RecallQueryPlan, normalize_recall_query, plan_recall_query
from .recall_rerank import (
    RecallRankedHit,
    rerank_recall_hits,
    score_recall_hit,
)
from .runtime import (
    DefaultEvidenceRetriever,
    build_embedding_index_policy,
    build_embedding_index_rebuild_plan,
    build_resume_packet,
    parse_step_replay_record,
)
from .semantic_index_factory import (
    SemanticIndexBundle,
    build_semantic_index_bundle,
    default_semantic_index_path,
)
from .unified_recall import (
    CONVERSATION_RECALL_SCOPES,
    CONVERSATION_SEARCH_SCOPES,
    RecallDocument,
    RecallTimeRange,
    UnifiedRecallRepository,
    UnifiedRecallRequest,
    candidates_from_episodes,
    candidates_from_steps,
    conversation_scopes_for_view,
    recall_time_range_from_payload,
    recall_timeline,
    summarize_recall_hits,
    unified_recall,
)
from .locator_match import (
    find_entry_by_locator,
    normalize_locator,
)

__all__ = [
    "CONVERSATION_RECALL_SCOPES",
    "CONVERSATION_SEARCH_SCOPES",
    "DefaultEvidenceRetriever",
    "EVIDENCE_SURFACES",
    "RecallRuntime",
    "RecallCandidate",
    "RecallDocument",
    "RecallHit",
    "RecallLifecycleInference",
    "RecallTimeRange",
    "RecallQueryPlan",
    "RecallRankedHit",
    "SemanticSummaryBackfillResult",
    "SemanticSummaryIndexer",
    "SemanticIndexBundle",
    "UnifiedRecallRepository",
    "UnifiedRecallRequest",
    "backfill_existing_semantic_summaries",
    "build_diary_entry_recall_text",
    "build_embedding_index_policy",
    "build_episode_summary_text",
    "build_learning_summary_recall_text",
    "build_personal_model_claim_text",
    "build_resume_packet",
    "build_step_recall_text",
    "build_semantic_index_bundle",
    "parse_step_replay_record",
    "conversation_scopes_for_view",
    "candidates_from_episodes",
    "candidates_from_steps",
    "default_semantic_index_path",
    "infer_recall_lifecycle_metadata",
    "normalize_recall_query",
    "plan_recall_query",
    "recall_time_range_from_payload",
    "recall_timeline",
    "rank_recall_candidates",
    "rerank_recall_hits",
    "render_recall_hit",
    "score_recall_hit",
    "find_entry_by_locator",
    "normalize_locator",
    "summarize_recall_hits",
    "unified_recall",
]
