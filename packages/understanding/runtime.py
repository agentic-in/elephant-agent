"""Personal Model Understanding runtime surface.
This module is the clean foreground write/read boundary for Elephant Agent's
understanding system.  The model-facing contract is intentionally small:
active four-lens claims, evidence summaries, and question rows. Free-form
notes are evidence, not a Personal Model write surface.
"""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import unicodedata
from typing import Any
from packages.contracts import ALLOWED_LENSES, Fact
from packages.evidence import UnifiedRecallRequest, conversation_scopes_for_view, infer_recall_lifecycle_metadata, recall_time_range_from_payload, recall_timeline, render_recall_hit, unified_recall
from packages.curiosity.question_tool_surface import CuriosityQuestionManagementSurface
from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID, canonical_personal_model_id
from .semantic_search_support import fallback_pm_search, keyword_boost, rank_facts_by_semantic_queries
from .temporal_policy import freshness_score
from .personal_model_governance import (
    claim_payload,
    ensure_valid_topic_key,
    inheritable_recall_metadata,
    is_protected_topic,
    is_single_active_topic,
    personal_model_health_report,
    protected_topic_metadata,
    narrowing_suggestions,
    related_claims_for_selection,
    valid_topic_key,
    similar_topic_payloads,
    topic_rows,
    topic_tree,
)
_ALLOWED_ACTIONS = frozenset({"remember", "correct", "forget", "dispute", "restore"})
_ALLOWED_SOURCES = frozenset({"user_said", "user_corrected", "learned"})
_ALLOWED_SEARCH_STATUSES = frozenset({"active", "retired", "disputed", "all"})
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
def _clean(value: object) -> str:
    return str(value or "").strip()
def _rerank_by_freshness(facts: list[Fact], *, now: datetime) -> list[Fact]:
    """Apply volatility freshness as a small penalty without overriding relevance rank."""
    scored: list[tuple[float, int, Fact]] = []
    for rank, fact in enumerate(facts):
        volatility = (fact.metadata or {}).get("volatility", "situational")
        penalty = freshness_score(
            volatility,
            fact.committed_at,
            fact.last_accessed_at,
            fact.access_count,
            now,
        )
        # `penalty` is in [-1.0, 0.0]. It should only break near-ties; a
        # frequently accessed but weakly matched claim must not jump ahead of a
        # stronger semantic/lexical hit for the current query.
        freshness_offset = min(max(0.0, -penalty), 0.49)
        scored.append((float(rank) + freshness_offset, rank, fact))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [fact for _, _, fact in scored]
def _normalized_lens(value: object) -> str:
    lens = _clean(value).lower()
    if lens not in ALLOWED_LENSES:
        raise ValueError(f"lens must be one of {sorted(ALLOWED_LENSES)}")
    return lens
def _normalized_action(value: object) -> str:
    action = _clean(value).lower()
    if action not in _ALLOWED_ACTIONS:
        raise ValueError(f"action must be one of {sorted(_ALLOWED_ACTIONS)}")
    return action
def _normalized_source(value: object) -> str:
    source = _clean(value).lower() or "user_said"
    if source not in _ALLOWED_SOURCES:
        raise ValueError(f"source must be one of {sorted(_ALLOWED_SOURCES)}")
    return source
def _normalized_search_status(value: object) -> str:
    status = _clean(value).lower() or "active"
    if status not in _ALLOWED_SEARCH_STATUSES:
        raise ValueError(f"status must be one of {sorted(_ALLOWED_SEARCH_STATUSES)}")
    return status
def _status_filter(status: str) -> str | tuple[str, ...]:
    if status == "all":
        return ("active", "retired", "disputed")
    return status
def _fact_ref(personal_model_id: str, lens: str, topic: str, text: str) -> str:
    digest = hashlib.sha256(
        f"{personal_model_id}|{lens}|{topic}|{text}".encode("utf-8")
    ).hexdigest()[:18]
    return f"claim:{digest}"
def _topic_matches(fact: Fact, *, topic: str, ref: str = "") -> bool:
    if ref and fact.fact_id == ref:
        return True
    return _clean((fact.metadata or {}).get("topic")) == topic


def _topic_matches_filter(fact: Fact, topic_filter: str) -> bool:
    """Match fact topic by exact match or prefix (for 2-segment topics like pulse.mood)."""
    fact_topic = _clean((fact.metadata or {}).get("topic"))
    if fact_topic == topic_filter:
        return True
    return fact_topic.startswith(f"{topic_filter}.")


_QUERY_ALIASES: Mapping[str, tuple[str, ...]] = {}
def _normalized_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
def _search_tokens(value: object) -> tuple[str, ...]:
    normalized = _normalized_text(value)
    tokens: list[str] = []
    current: list[str] = []
    for ch in normalized:
        if unicodedata.category(ch)[0] in {"L", "N"} or ch in "_./:-":
            current.append(ch)
            continue
        if current:
            tokens.extend(_token_variants("".join(current)))
            current = []
    if current:
        tokens.extend(_token_variants("".join(current)))
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(_normalized_text(alias) for alias in _QUERY_ALIASES.get(token, ()))
    return tuple(token for token in dict.fromkeys(expanded) if token)
def _token_variants(token: str) -> tuple[str, ...]:
    if not token:
        return ()
    variants: list[str] = [token]
    if _has_cjk(token):
        variants.extend(_char_ngrams(token, widths=(1, 2)))
    return tuple(variants)
def _has_cjk(text: str) -> bool:
    return any(
        "CJK" in unicodedata.name(ch, "")
        or "HIRAGANA" in unicodedata.name(ch, "")
        or "KATAKANA" in unicodedata.name(ch, "")
        for ch in text
    )
def _compact_search_text(value: object) -> str:
    normalized = _normalized_text(value)
    return "".join(ch for ch in normalized if unicodedata.category(ch)[0] in {"L", "N"})
def _char_ngrams(value: object, *, widths: tuple[int, ...] = (2, 3)) -> set[str]:
    text = _compact_search_text(value)
    if not text:
        return set()
    grams: set[str] = set()
    for width in widths:
        if len(text) <= width:
            grams.add(text)
        else:
            grams.update(text[index : index + width] for index in range(0, len(text) - width + 1))
    return grams
def _safe_query_variants(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw_values = (values,)
    elif isinstance(values, (list, tuple)):
        raw_values = tuple(str(item) for item in values)
    else:
        raw_values = (str(values),)
    cleaned: list[str] = []
    for value in raw_values:
        item = _clean(value)
        if not item:
            continue
        cleaned.append(item[:160])
        if len(cleaned) >= 5:
            break
    return tuple(dict.fromkeys(cleaned))
def _low_information_query(query: str) -> bool:
    normalized = _normalized_text(query).strip()
    if not normalized:
        return True
    if not any(unicodedata.category(ch)[0] in {"L", "N"} for ch in normalized):
        return True
    tokens = tuple(token for token in _search_tokens(normalized) if token)
    if not tokens:
        return True
    ascii_tokens = [token for token in tokens if token.isascii()]
    if len(tokens) == 1 and ascii_tokens and len(ascii_tokens[0]) <= 1:
        return True
    if len(ascii_tokens) >= 4 and all(len(token) <= 1 for token in ascii_tokens):
        return True
    return False
def _question_topic(lens: str, sub_lens: str) -> str:
    def segment(value: str, fallback: str) -> str:
        normalized = _normalized_text(value).replace(".", "_").replace("-", "_").replace("/", "_").replace(":", "_")
        chars = [ch if ch.isascii() and (ch.isalnum() or ch == "_") else "_" for ch in normalized]
        resolved = "_".join(part for part in "".join(chars).strip("_").split("_") if part)
        if not resolved:
            resolved = fallback
        if not resolved[0].isalpha():
            resolved = f"{fallback}_{resolved}"
        return resolved
    resolved_lens = _normalized_lens(lens)
    raw = _clean(sub_lens) or "answer"
    try:
        return ensure_valid_topic_key(raw)
    except ValueError:
        return f"{resolved_lens}.question.{segment(raw, 'answer')}"
class PersonalModelUnderstandingSurface:
    """Small four-lens Personal Model surface used by foreground tools."""
    def __init__(
        self,
        *,
        repository: Any,
        semantic_summary_indexer: Any = None,
        semantic_searcher: Any = None,
        embedding_service: Any = None,
    ) -> None:
        self.repository = repository
        self.semantic_summary_indexer = semantic_summary_indexer
        self.semantic_searcher = semantic_searcher
        self.embedding_service = embedding_service or getattr(
            semantic_summary_indexer,
            "embedding_service",
            None,
        )
        self._questions = CuriosityQuestionManagementSurface(repository=repository)
    def _personal_model_id(self, session_id: str, explicit: str = "") -> str:
        pm_id = _clean(explicit)
        if not pm_id:
            load_episode = getattr(self.repository, "load_episode_state", None)
            episode = load_episode(session_id) if callable(load_episode) else None
            pm_id = _clean(getattr(episode, "personal_model_id", ""))
        pm_id = canonical_personal_model_id(pm_id or DEFAULT_PERSONAL_MODEL_ID)
        ensure = getattr(self.repository, "ensure_default_personal_model", None)
        if callable(ensure):
            ensure(personal_model_id=pm_id)
        return pm_id
    def _episode_id(self, session_id: str) -> str:
        load_episode = getattr(self.repository, "load_episode_state", None)
        episode = load_episode(session_id) if callable(load_episode) else None
        return _clean(getattr(episode, "episode_id", "")) or session_id
    def _index_claim(self, fact: Fact) -> None:
        index_claim = getattr(self.semantic_summary_indexer, "index_personal_model_claim", None)
        if callable(index_claim):
            try:
                index_claim(fact)
            except Exception:
                return
    def _deactivate_claim_index(
        self,
        *,
        personal_model_id: str,
        fact_id: str,
        status: str,
    ) -> None:
        list_entries = getattr(self.repository, "list_semantic_index_entries", None)
        upsert_entry = getattr(self.repository, "upsert_semantic_index_entry", None)
        if not callable(list_entries) or not callable(upsert_entry):
            return
        try:
            entries = list_entries(
                personal_model_id=personal_model_id,
                owner_scope="personal_model",
            )
        except Exception:
            return
        now = _utc_now()
        for entry in entries:
            if getattr(entry, "source_id", "") != fact_id:
                continue
            try:
                upsert_entry(
                    replace(
                        entry,
                        status="deleted",
                        updated_at=now,
                        metadata={
                            **dict(getattr(entry, "metadata", {}) or {}),
                            "claim_status": status,
                            "deactivated_by": "tool.personal_model.update",
                        },
                    )
                )
            except Exception:
                continue
    def _indexed_query_dimensions(
        self,
        *,
        owner_scope: str,
        personal_model_id: str = "",
        state_id: str = "",
    ) -> int | None:
        list_entries = getattr(self.repository, "list_semantic_index_entries", None)
        if not callable(list_entries):
            return None
        try:
            entries = list_entries(
                owner_scope=owner_scope,
                personal_model_id=personal_model_id or None,
                state_id=state_id or None,
            )
        except Exception:
            return None
        counts: dict[int, int] = {}
        for entry in entries:
            if str(getattr(entry, "status", "") or "") == "deleted":
                continue
            dimensions = int(getattr(entry, "dimensions", 0) or 0)
            if dimensions <= 0:
                continue
            counts[dimensions] = counts.get(dimensions, 0) + 1
        if not counts:
            return None
        return max(counts, key=lambda item: (counts[item], item))

    def _query_vector(self, query: str, *, dimensions: int | None = None) -> tuple[tuple[float, ...], int | None]:
        service = self.embedding_service
        if service is None or not query.strip():
            return (), None
        try:
            vector = service.embed_text(
                query,
                request_id="personal-model-search-query",
                task="query",
                latency_mode="balanced",
                dimensions=dimensions,
            )
            values = tuple(getattr(vector, "values", ()) or ())
            dimensions = int(getattr(vector, "dimensions", 0) or 0) or None
        except Exception:
            return (), None
        if not values or dimensions is None:
            return (), None
        return values, dimensions
    def search_personal_model(
        self,
        session_id: str,
        *,
        query: str = "",
        lens: str = "",
        topic: str = "",
        query_variants: object = (),
        include_diagnostics: bool = False,
        limit: int = 12,
        status: str = "active",
        ref: str = "",
        personal_model_id: str = "",
        mode: str = "auto",
    ) -> Mapping[str, Any]:
        pm_id = self._personal_model_id(session_id, personal_model_id)
        resolved_lens = _normalized_lens(lens) if _clean(lens) else None
        resolved_status = _normalized_search_status(status)
        resolved_ref = _clean(ref)
        resolved_topic = _clean(topic)
        if resolved_topic:
            # For search, accept partial topic prefixes (2+ segments) as well as full keys
            valid = valid_topic_key(resolved_topic)
            if valid:
                resolved_topic = valid
            else:
                # Allow 2-segment prefix for search (e.g. "pulse.mood")
                parts = tuple(p for p in resolved_topic.split(".") if p)
                if len(parts) >= 2:
                    resolved_topic = ".".join(parts)
                else:
                    resolved_topic = ""
        facts = tuple(
            self.repository.list_personal_model_facts(
                personal_model_id=pm_id,
                lens=resolved_lens,
                status=_status_filter(resolved_status),
            )
        )
        capped = max(1, min(int(limit or 12), 30))
        primary_query = _clean(query)
        list_all = _normalized_text(primary_query) in {"all", "*", "list"}
        variants = _safe_query_variants(query_variants)
        search_queries = tuple(
            item for item in dict.fromkeys((primary_query, *variants)) if item and item not in {"all", "*", "list"}
        )
        # --- Fast paths (no scoring needed) ---
        if resolved_ref:
            selected = tuple(fact for fact in facts if fact.fact_id == resolved_ref)[:capped]
            match_status = "strong_match" if selected else "no_match"
        elif list_all and not resolved_topic:
            selected = facts[:capped]
            match_status = "strong_match" if selected else "no_match"
        elif resolved_topic and not search_queries:
            # Topic-only filter: return all facts matching this topic (exact or prefix)
            selected = tuple(
                fact for fact in facts
                if _topic_matches_filter(fact, resolved_topic)
            )[:capped]
            match_status = "strong_match" if selected else "no_match"
        elif not search_queries:
            selected = ()
            match_status = "no_match"
        elif all(_low_information_query(item) for item in search_queries):
            selected = ()
            match_status = "no_match"
        else:
            # --- Main search path: HybridSemanticSearcher ---
            selected, match_status = self._hybrid_pm_search(
                search_queries, pm_id=pm_id, facts=facts, topic=resolved_topic, limit=capped,
            )

        claims = []
        for fact in selected:
            claims.append(claim_payload(fact))

        # Track access for temporal policy (non-blocking side effect)
        if selected:
            touch = getattr(self.repository, "touch_fact_access", None)
            if callable(touch):
                try:
                    touch(tuple(fact.fact_id for fact in selected))
                except Exception:
                    pass

        result: dict[str, Any] = {
            "personal_model_id": pm_id,
            "match_status": match_status,
            "claims": tuple(claims),
        }
        suggestions = narrowing_suggestions(
            selected,
            mode="balanced",
            lens=resolved_lens,
            topic=resolved_topic,
            limit=capped,
        )
        if suggestions:
            result["narrowing_suggestions"] = suggestions
            result["search_tip"] = "broad match set; use narrowing_suggestions before editing or verifying one claim"
        if include_diagnostics:
            related_claims = related_claims_for_selection(facts, selected)
            if related_claims:
                result["related_active_claims"] = related_claims
                result["similar_topics"] = tuple({item["topic"] for item in related_claims})
        return result

    def _hybrid_pm_search(
        self,
        queries: tuple[str, ...],
        *,
        pm_id: str,
        facts: tuple[Fact, ...],
        topic: str,
        limit: int,
    ) -> tuple[tuple[Fact, ...], str]:
        """Search PM facts via HybridSemanticSearcher with topic boost."""
        facts_by_ref = {fact.fact_id: fact for fact in facts}
        # Topic pre-filter: if a topic is specified, narrow candidates first
        if topic:
            topic_matched = tuple(
                fact for fact in facts
                if _clean((fact.metadata or {}).get("topic")) == topic
                or _clean((fact.metadata or {}).get("topic")).startswith(f"{topic}.")
            )
            # If topic matches exist and no semantic searcher, return them directly
            if topic_matched and self.semantic_searcher is None:
                return topic_matched[:limit], "strong_match"
        # Use HybridSemanticSearcher if available. Run every translated/paraphrased
        # query variant through the semantic path, then fuse by claim ref so cross-
        # language variants are not limited to keyword fallback only.
        if self.semantic_searcher is not None:
            query_dimensions = self._indexed_query_dimensions(
                owner_scope="personal_model",
                personal_model_id=pm_id,
            )
            ranked_facts = rank_facts_by_semantic_queries(
                self.semantic_searcher,
                queries,
                pm_id=pm_id,
                facts_by_ref=facts_by_ref,
                query_vector=lambda search_text: self._query_vector(
                    search_text,
                    dimensions=query_dimensions,
                ),
                limit=limit,
            )
            seen_refs: set[str] = {fact.fact_id for fact in ranked_facts}

            # Keyword fallback: also find facts matching query_variants via token overlap.
            # This catches multi-keyword queries (e.g. compound terms) that vector search misses.
            if len(ranked_facts) < limit:
                keyword_hits = keyword_boost(queries, facts=facts, exclude_refs=seen_refs)
                for fact in keyword_hits:
                    if fact.fact_id not in seen_refs:
                        ranked_facts.append(fact)
                        seen_refs.add(fact.fact_id)

            # If topic specified, boost topic-matched results to front
            if topic and ranked_facts:
                topic_hits = [f for f in ranked_facts if _topic_matches_filter(f, topic)]
                non_topic = [f for f in ranked_facts if f not in topic_hits]
                ranked_facts = topic_hits + non_topic

            # Apply freshness re-ranking (demote stale chapter/knowledge facts)
            if ranked_facts:
                now = _utc_now()
                ranked_facts = _rerank_by_freshness(ranked_facts, now=now)
                selected = tuple(ranked_facts[:limit])
                return selected, "strong_match" if len(selected) >= 1 else "no_match"

        # Fallback: token matching when no semantic searcher — uses all query variants
        return fallback_pm_search(queries, facts=facts, topic=topic, limit=limit)

    def search_conversation(
        self,
        session_id: str,
        *,
        query: str = "",
        time_range: object = None,
        mode: str = "recall",
        bucket: str = "auto",
        preview: str = "anchors",
        view: str = "conversation",
        limit: int = 8,
        personal_model_id: str = "",
        include_current_episode: bool = False,
    ) -> Mapping[str, Any]:
        pm_id = self._personal_model_id(session_id, personal_model_id)
        load_episode = getattr(self.repository, "load_episode_state", None)
        episode = load_episode(session_id) if callable(load_episode) else None
        current_episode_id = _clean(getattr(episode, "episode_id", "")) or _clean(session_id)
        state_id = _clean(getattr(episode, "state_id", ""))
        if not state_id:
            current_state = getattr(self.repository, "current_state", None)
            state = current_state() if callable(current_state) else None
            state_id = _clean(getattr(state, "state_id", ""))
        resolved_mode = "discover" if _clean(mode).lower() == "discover" else "recall"
        resolved_view = "debug" if _clean(view).lower() == "debug" else "conversation"
        capped = max(1, min(int(limit or 8), 30))
        now = _utc_now()
        resolved_time_range = recall_time_range_from_payload(time_range, now=now)
        request = UnifiedRecallRequest(
            query=_clean(query),
            scopes=conversation_scopes_for_view(resolved_view),
            personal_model_id=pm_id,
            state_id=state_id or None,
            limit=capped,
            time_range=resolved_time_range,
            now=now,
            view=resolved_view,
            exclude_episode_ids=() if include_current_episode else (current_episode_id,),
        )
        if resolved_mode == "discover" and resolved_time_range is None:
            return {
                "personal_model_id": pm_id,
                "scope": "conversation",
                "mode": resolved_mode,
                "view": resolved_view,
                "query": _clean(query),
                "resolved_time_range": {},
                "ranges": (),
                "requires_time_range": True,
                "guidance": "mode=discover requires top-level expr or explicit start_at/end_at; when the user mentions time, patiently map it to expr such as last_night, yesterday, last:3d, or an ISO interval before searching.",
            }
        if resolved_mode == "discover":
            result = recall_timeline(
                request,
                repository=self.repository,
                bucket=bucket,
                preview=preview,
                limit=capped,
            )
            return {"personal_model_id": pm_id, "scope": "conversation", "mode": resolved_mode, **dict(result)}
        ranked = unified_recall(
            request,
            repository=self.repository,
            searcher=self.semantic_searcher,
            embedding_service=self.embedding_service,
        )
        rendered_hits = tuple(render_recall_hit(hit) for hit in ranked)
        return {
            "personal_model_id": pm_id,
            "scope": "conversation",
            "mode": resolved_mode,
            "view": resolved_view,
            "query": _clean(query),
            "resolved_time_range": resolved_time_range.payload() if resolved_time_range is not None else {},
            "hits": rendered_hits[:capped],
        }

    def recall_personal_model(
        self,
        session_id: str,
        *,
        query: str = "",
        time_range: object = None,
        limit: int = 5,
        personal_model_id: str = "",
    ) -> Mapping[str, Any]:
        return self.search_conversation(
            session_id,
            query=query,
            time_range=time_range,
            mode="recall",
            limit=limit,
            personal_model_id=personal_model_id,
        )

    def timeline_personal_model(
        self,
        session_id: str,
        *,
        time_range: object = None,
        bucket: str = "hour",
        include_examples: bool = True,
        limit: int = 24,
        personal_model_id: str = "",
    ) -> Mapping[str, Any]:
        return self.search_conversation(
            session_id,
            time_range=time_range,
            mode="discover",
            bucket=bucket,
            preview="anchors" if include_examples else "none",
            limit=limit,
            personal_model_id=personal_model_id,
        )
    def inspect_personal_model(
        self,
        session_id: str,
        *,
        ref: str = "",
        topic: str = "",
        query: str = "",
        personal_model_id: str = "",
        limit: int = 5,
    ) -> Mapping[str, Any]:
        pm_id = self._personal_model_id(session_id, personal_model_id)
        resolved_ref = _clean(ref)
        resolved_topic = ensure_valid_topic_key(topic) if _clean(topic) else ""
        facts = tuple(
            self.repository.list_personal_model_facts(
                personal_model_id=pm_id,
                status=("active", "retired", "disputed"),
            )
        )
        selected = tuple(
            fact for fact in facts
            if (resolved_ref and fact.fact_id == resolved_ref)
            or (resolved_topic and _clean((fact.metadata or {}).get("topic")) == resolved_topic)
        )
        claim = claim_payload(selected[0]) if selected else None
        if selected and not resolved_topic:
            resolved_topic = _clean((selected[0].metadata or {}).get("topic"))
        supersedes_refs: list[str] = []
        for fact in selected[: max(1, min(int(limit or 5), 10))]:
            if fact.supersedes_fact_id:
                supersedes_refs.append(fact.supersedes_fact_id)
            metadata = dict(fact.metadata or {})
            supersedes_refs.extend(
                item.strip()
                for item in str(metadata.get("supersedes_fact_ids") or "").split(",")
                if item.strip()
            )
        chain = tuple(
            claim_payload(fact)
            for ref_id in dict.fromkeys(supersedes_refs)
            for fact in facts
            if fact.fact_id == ref_id
        )
        recall_query = _clean(query) or _clean((claim or {}).get("text") if isinstance(claim, Mapping) else "") or resolved_topic
        history = ()
        if recall_query:
            history_result = self.recall_personal_model(
                session_id,
                query=recall_query,
                limit=limit,
                personal_model_id=pm_id,
            )
            history = tuple(history_result.get("hits") or ())
        return {
            "personal_model_id": pm_id,
            "ref": resolved_ref,
            "topic": resolved_topic,
            "claim": claim,
            "claims": tuple(claim_payload(fact) for fact in selected[: max(1, min(int(limit or 5), 10))]),
            "history": history,
            "supersedes_chain": chain,
        }
    def audit_personal_model(
        self,
        session_id: str,
        *,
        action: str = "health",
        lens: str = "",
        personal_model_id: str = "",
        limit: int = 30,
    ) -> Mapping[str, Any]:
        resolved_action = _clean(action).lower() or "health"
        if resolved_action not in {"health", "topics", "conflicts", "stale"}:
            raise ValueError("audit action must be one of health, topics, conflicts, stale")
        pm_id = self._personal_model_id(session_id, personal_model_id)
        resolved_lens = _normalized_lens(lens) if _clean(lens) else None
        facts = tuple(
            self.repository.list_personal_model_facts(
                personal_model_id=pm_id,
                lens=resolved_lens,
                status=("active", "retired", "disputed"),
            )
        )
        health = personal_model_health_report(facts)
        result: dict[str, Any] = {"personal_model_id": pm_id, "action": resolved_action}
        if resolved_action in {"health", "conflicts", "stale"}:
            result["health_report"] = health
        if resolved_action in {"health", "topics"}:
            result["topic_tree"] = topic_tree(tuple(fact for fact in facts if fact.status == "active"))
        if resolved_action == "topics":
            result["topics"] = topic_rows(tuple(fact for fact in facts if fact.status == "active"), limit=max(1, min(int(limit or 30), 100)))
        if resolved_action == "conflicts":
            result["conflicts"] = tuple(health.get("conflicting_claim_candidates") or ())
        if resolved_action == "stale":
            result["review_claims_overdue"] = tuple(health.get("review_claims_overdue") or ())
            result["current_claims_stale"] = tuple(health.get("current_claims_stale") or ())
        return result
    def update_personal_model(
        self,
        session_id: str,
        *,
        action: str,
        lens: str,
        topic: str,
        text: str = "",
        ref: str = "",
        reason: str = "",
        source: str = "user_said",
        recall_policy: str = "",
        personal_model_id: str = "",
        metadata: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        resolved_action = _normalized_action(action)
        resolved_lens = _normalized_lens(lens)
        resolved_topic = _clean(topic)
        if not resolved_topic:
            raise ValueError("topic is required")
        resolved_topic = ensure_valid_topic_key(resolved_topic)
        resolved_source = _normalized_source(source)
        resolved_recall_policy = _clean(recall_policy).lower()
        if resolved_recall_policy not in {"", "stable", "current", "temporary", "review"}:
            raise ValueError("recall_policy must be one of stable, current, temporary, review when provided")
        pm_id = self._personal_model_id(session_id, personal_model_id)
        now = _utc_now()
        active = tuple(
            self.repository.list_personal_model_facts(
                personal_model_id=pm_id,
                lens=resolved_lens,
                status="active",
            )
        )
        resolved_ref = _clean(ref)
        targets = tuple(
            fact for fact in active if _topic_matches(fact, topic=resolved_topic, ref=resolved_ref)
        )
        if resolved_action == "remember" and not resolved_ref and is_single_active_topic(resolved_topic):
            targets = tuple(fact for fact in active if _topic_matches(fact, topic=resolved_topic))
        if resolved_action == "restore":
            if not resolved_ref:
                return {
                    "action": resolved_action,
                    "personal_model_id": pm_id,
                    "lens": resolved_lens,
                    "topic": resolved_topic,
                    "retired": (),
                    "status": "ambiguous",
                    "no_match_hint": "restore requires a claim ref from search(status=all) to avoid reviving the wrong claim",
                }
            all_facts = tuple(
                self.repository.list_personal_model_facts(
                    personal_model_id=pm_id,
                    lens=resolved_lens,
                    status=("active", "retired", "disputed"),
                )
            )
            target = next((fact for fact in all_facts if fact.fact_id == resolved_ref and _topic_matches(fact, topic=resolved_topic, ref=resolved_ref)), None)
            if target is None:
                return {
                    "action": resolved_action,
                    "personal_model_id": pm_id,
                    "lens": resolved_lens,
                    "topic": resolved_topic,
                    "retired": (),
                    "status": "no_match",
                    "no_match_hint": "no claim matched ref/topic; search with status=all and retry with the exact ref",
                }
            retired_refs = []
            for fact in active:
                if fact.fact_id == target.fact_id or not _topic_matches(fact, topic=resolved_topic):
                    continue
                self.repository.upsert_personal_model_fact(
                    replace(
                        fact,
                        status="retired",
                        metadata={
                            **dict(fact.metadata or {}),
                            "retired_by": "tool.personal_model.update",
                            "retired_action": "restore_superseded",
                            "retired_reason": _clean(reason),
                            "retired_at": now.isoformat(),
                            "understanding_status": "retired",
                        },
                    )
                )
                self._deactivate_claim_index(personal_model_id=pm_id, fact_id=fact.fact_id, status="retired")
                retired_refs.append(fact.fact_id)
            restored = replace(
                target,
                status="active",
                metadata={
                    **dict(target.metadata or {}),
                    "restored_by": "tool.personal_model.update",
                    "restored_reason": _clean(reason),
                    "restored_at": now.isoformat(),
                    "understanding_status": "active",
                },
            )
            self.repository.upsert_personal_model_fact(restored)
            self._index_claim(restored)
            return {
                "action": resolved_action,
                "personal_model_id": pm_id,
                "claim": claim_payload(restored),
                "retired": tuple(retired_refs),
                "status": "active",
            }
        related_candidates = similar_topic_payloads(
            active,
            lens=resolved_lens,
            topic=resolved_topic,
            text=_clean(text),
            exclude_refs=tuple(fact.fact_id for fact in targets),
        )
        protected_targets = tuple(fact for fact in targets if is_protected_topic(resolved_topic, dict(fact.metadata or {})))
        if resolved_action == "forget" and protected_targets:
            return {
                "action": resolved_action,
                "personal_model_id": pm_id,
                "lens": resolved_lens,
                "topic": resolved_topic,
                "retired": (),
                "status": "protected",
                "no_match_hint": "protected core topic cannot be forgotten by agent tools; correct the content or unprotect it in the dashboard first",
                "protected_refs": tuple(fact.fact_id for fact in protected_targets),
            }
        if resolved_action in {"forget", "dispute"} and not resolved_ref and (len(targets) > 1 or (not targets and related_candidates)):
            return {
                "action": resolved_action,
                "personal_model_id": pm_id,
                "lens": resolved_lens,
                "topic": resolved_topic,
                "retired": (),
                "status": "ambiguous",
                "no_match_hint": "ambiguous or missing target; search first and retry with ref before forget/dispute",
                "related_active_claims": related_candidates,
                "similar_topics": tuple({item["topic"] for item in related_candidates}),
            }
        retired_refs: list[str] = []
        retirement_status = "disputed" if resolved_action == "dispute" else "retired"
        for fact in targets:
            self.repository.upsert_personal_model_fact(
                replace(
                    fact,
                    status=retirement_status,
                    metadata={
                        **dict(fact.metadata or {}),
                        "retired_by": "tool.personal_model.update",
                        "retired_action": resolved_action,
                        "retired_reason": _clean(reason),
                        "retired_at": now.isoformat(),
                        "understanding_status": retirement_status,
                    },
                )
            )
            self._deactivate_claim_index(
                personal_model_id=pm_id,
                fact_id=fact.fact_id,
                status=retirement_status,
            )
            retired_refs.append(fact.fact_id)
        no_match_hint = ""
        if not targets and resolved_action in {"correct", "forget", "dispute"}:
            no_match_hint = "no matching active claim; search first and retry with ref when topic is uncertain"
        if resolved_action in {"forget", "dispute"}:
            return {
                "action": resolved_action,
                "personal_model_id": pm_id,
                "lens": resolved_lens,
                "topic": resolved_topic,
                "retired": tuple(retired_refs),
                "status": retirement_status if retired_refs else "no_match",
                **({"no_match_hint": no_match_hint} if no_match_hint else {}),
            }
        resolved_text = _clean(text)
        if not resolved_text:
            raise ValueError("text is required for remember/correct")
        fact_source = "pm_agent_promote" if resolved_source == "learned" else "user_explicit"
        inherited_recall_metadata = (
            inheritable_recall_metadata(targets)
            if resolved_action == "correct" and not resolved_recall_policy
            else {}
        )
        caller_metadata = {str(key): str(value) for key, value in dict(metadata or {}).items() if str(value).strip()}
        protection_metadata = protected_topic_metadata(resolved_topic, caller_metadata)
        base_metadata = {
            **inherited_recall_metadata,
            **caller_metadata,
            **protection_metadata,
            "topic": resolved_topic,
            "source_kind": resolved_source,
            "action": resolved_action,
            "reason": _clean(reason),
            "surface": "tool.personal_model.update",
            "supersedes_fact_ids": ",".join(retired_refs),
            **({"recall_policy": resolved_recall_policy} if resolved_recall_policy else {}),
        }
        lifecycle_metadata = infer_recall_lifecycle_metadata(
            lens=resolved_lens,
            topic=resolved_topic,
            text=resolved_text,
            source=resolved_source,
            kind="personal_model_claim",
            owner_scope="personal_model",
            metadata=base_metadata,
            now=now,
        ).metadata
        fact = Fact(
            fact_id=_fact_ref(pm_id, resolved_lens, resolved_topic, resolved_text),
            personal_model_id=pm_id,
            lens=resolved_lens,
            text=resolved_text,
            confidence=0.72 if resolved_source == "learned" else 1.0,
            committed_at=now,
            source=fact_source,
            source_episode_ids=(self._episode_id(session_id),),
            status="active",
            supersedes_fact_id=retired_refs[0] if retired_refs else None,
            metadata=lifecycle_metadata,
        )
        self.repository.upsert_personal_model_fact(fact)
        self._index_claim(fact)
        related_claims = similar_topic_payloads(
            active,
            lens=resolved_lens,
            topic=resolved_topic,
            text=resolved_text,
            exclude_refs=(*retired_refs, fact.fact_id),
        )
        return {
            "action": resolved_action,
            "personal_model_id": pm_id,
            "claim": claim_payload(fact),
            "retired": tuple(retired_refs),
            "related_active_claims": related_claims,
            "similar_topics": tuple({item["topic"] for item in related_claims}),
            "status": "active",
            **({"no_match_hint": no_match_hint} if no_match_hint else {}),
        }
    def manage_personal_model_questions(self, session_id: str, **kwargs: Any) -> Mapping[str, Any]:
        payload = dict(kwargs)
        answer_text = _clean(payload.pop("answer", ""))
        result = self._questions.manage_questions(session_id, **payload)
        if _clean(payload.get("action")).lower() == "answer" and answer_text:
            question = result.get("question") if isinstance(result, Mapping) else None
            lens = _clean((question or {}).get("lens")) or _clean(payload.get("lens")) or "knowledge"
            topic = _question_topic(lens, _clean((question or {}).get("sub_lens")) or _clean(payload.get("sub_lens")) or "answer")
            update = self.update_personal_model(
                session_id,
                action="correct",
                lens=lens,
                topic=topic,
                text=answer_text,
                reason=_clean((question or {}).get("text")) or "answer to Personal Model question",
                source="user_said",
                personal_model_id=_clean(payload.get("personal_model_id")),
            )
            claim = update.get("claim") if isinstance(update, Mapping) else None
            claim_ref = _clean((claim or {}).get("ref"))
            if claim_ref:
                mark = getattr(self.repository, "mark_open_question", None)
                question_id = _clean((question or {}).get("question_id")) or _clean(payload.get("question_id"))
                if callable(mark) and question_id:
                    mark(
                        question_id=question_id,
                        status="answered",
                        user_response_episode_id=session_id,
                        generated_fact_ids=(claim_ref,),
                    )
            return {**dict(result), "claim_update": update}
        return result
