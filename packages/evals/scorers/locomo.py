"""Scoring helpers for LoCoMo-family eval results."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from packages.evals.contracts import EvalDataset, EvalQuestionResult


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u3400-\u9fff\uf900-\ufaff]")


def score_locomo_results(
    dataset: EvalDataset,
    results: Iterable[EvalQuestionResult],
    *,
    top_k: int,
) -> dict[str, Any]:
    rows = [_score_row(result, top_k=top_k) for result in results]
    return {
        "dataset_id": dataset.dataset_id,
        "source_path": dataset.source_path,
        "conversation_count": len(dataset.conversations),
        "question_count": len(rows),
        "top_k": top_k,
        "overall": _aggregate(rows),
        "by_category": _grouped(rows, key="category"),
        "by_conversation": _grouped(rows, key="conversation_id"),
        "by_modality": _grouped(rows, key="modality"),
    }


def _score_row(result: EvalQuestionResult, *, top_k: int) -> dict[str, Any]:
    gold = tuple(str(item) for item in result.evidence_ids if str(item).strip())
    rank = _first_hit_rank(gold, result.hits[:top_k])
    answer_scores = [_answer_scores(result.predicted_answer, answer) for answer in result.answers]
    best_answer = max(answer_scores, key=lambda item: item["answer_f1"], default={"answer_exact": 0.0, "answer_f1": 0.0, "answer_bleu1": 0.0})
    no_match_safe = 1.0 if not gold and (not result.hits[:top_k] or _is_abstention(result.predicted_answer)) else 0.0
    return {
        "question_id": result.question_id,
        "conversation_id": result.conversation_id,
        "category": result.category or "<none>",
        "modality": "multimodal_available" if result.is_multimodal else "text_only",
        "has_gold_evidence": bool(gold),
        "retrieval_hit": 1.0 if rank is not None else 0.0,
        "retrieval_mrr": 0.0 if rank is None else 1.0 / float(rank),
        "no_match_safe": no_match_safe,
        "answer_exact": best_answer["answer_exact"],
        "answer_f1": best_answer["answer_f1"],
        "answer_bleu1": best_answer["answer_bleu1"],
    }


def _first_hit_rank(gold: tuple[str, ...], hits: tuple[object, ...]) -> int | None:
    if not gold:
        return None
    gold_set = set(gold)
    for index, hit in enumerate(hits, start=1):
        if gold_set.intersection(_represented_source_ids(hit)):
            return index
    return None


def _represented_source_ids(hit: object) -> set[str]:
    source_ids = {str(getattr(hit, "source_id", "") or "").strip()}
    metadata = dict(getattr(hit, "metadata", {}) or {})
    for key in ("source_ids", "evidence_ids", "message_ids"):
        source_ids.update(
            item.strip()
            for item in str(metadata.get(key) or "").split(",")
            if item.strip()
        )
    return {source_id for source_id in source_ids if source_id}


def _answer_scores(prediction: str, answer: str) -> dict[str, float]:
    pred_tokens = _tokens(prediction)
    gold_tokens = _tokens(answer)
    if not pred_tokens and not gold_tokens:
        f1 = 1.0
    elif not pred_tokens or not gold_tokens:
        f1 = 0.0
    else:
        common = _multiset_overlap(pred_tokens, gold_tokens)
        precision = common / max(len(pred_tokens), 1)
        recall = common / max(len(gold_tokens), 1)
        f1 = 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)
    exact = 1.0 if _normalize(prediction) == _normalize(answer) and _normalize(answer) else 0.0
    bleu1 = _bleu1(pred_tokens, gold_tokens)
    return {"answer_exact": exact, "answer_f1": f1, "answer_bleu1": bleu1}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = ("retrieval_hit", "retrieval_mrr", "answer_exact", "answer_f1", "answer_bleu1", "no_match_safe")
    out: dict[str, Any] = {"count": len(rows)}
    rows_with_gold = [row for row in rows if row["has_gold_evidence"]]
    rows_without_gold = [row for row in rows if not row["has_gold_evidence"]]
    for metric in metrics:
        source = rows_without_gold if metric == "no_match_safe" else rows
        if metric in {"retrieval_hit", "retrieval_mrr"}:
            source = rows_with_gold
        out[metric] = _mean(row[metric] for row in source)
    out["gold_evidence_count"] = len(rows_with_gold)
    out["no_gold_evidence_count"] = len(rows_without_gold)
    return out


def _grouped(rows: list[dict[str, Any]], *, key: str) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key) or "<none>")].append(row)
    return {name: _aggregate(items) for name, items in sorted(buckets.items())}


def _mean(values: Iterable[float]) -> float:
    items = tuple(float(value) for value in values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def _tokens(value: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(_normalize(value))]


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _multiset_overlap(left: list[str], right: list[str]) -> int:
    remaining: dict[str, int] = defaultdict(int)
    for token in right:
        remaining[token] += 1
    count = 0
    for token in left:
        if remaining[token] <= 0:
            continue
        count += 1
        remaining[token] -= 1
    return count


def _bleu1(pred_tokens: list[str], gold_tokens: list[str]) -> float:
    if not pred_tokens or not gold_tokens:
        return 0.0
    precision = _multiset_overlap(pred_tokens, gold_tokens) / len(pred_tokens)
    brevity = min(1.0, len(pred_tokens) / max(len(gold_tokens), 1))
    return precision * brevity


def _is_abstention(value: str) -> bool:
    normalized = _normalize(value)
    return normalized in {"", "i don't know", "unknown", "not enough information"}
