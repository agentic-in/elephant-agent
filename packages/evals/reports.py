"""Report writers for unified eval runs."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from packages.evals.contracts import EvalDataset, EvalQuestionResult, EvalRunConfig


def write_eval_artifacts(
    *,
    dataset: EvalDataset,
    results: tuple[EvalQuestionResult, ...],
    metrics: dict[str, Any],
    config: EvalRunConfig,
) -> dict[str, Path]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "predictions.jsonl"
    traces_path = output_dir / "retrieval_traces.jsonl"
    report_json_path = output_dir / "report.json"
    report_md_path = output_dir / "report.md"

    _write_jsonl(
        predictions_path,
        (
            {
                "qa_id": result.question_id,
                "predicted_answer": result.predicted_answer,
            }
            for result in results
        ),
    )
    _write_jsonl(
        traces_path,
        (
            {
                "qa_id": result.question_id,
                "question": result.question,
                "gold_answers": result.answers,
                "gold_evidence": result.evidence_ids,
                "predicted_answer": result.predicted_answer,
                "hits": [asdict(hit) for hit in result.hits],
            }
            for result in results
        ),
    )
    report_payload = {
        "config": asdict(config),
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "source_path": dataset.source_path,
            "conversation_count": len(dataset.conversations),
            "question_count": dataset.question_count,
            "metadata": dict(dataset.metadata),
        },
        "metrics": metrics,
        "artifacts": {
            "predictions": str(predictions_path),
            "retrieval_traces": str(traces_path),
            "report_json": str(report_json_path),
            "report_md": str(report_md_path),
        },
    }
    report_json_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md_path.write_text(_markdown_report(report_payload), encoding="utf-8")
    return {
        "predictions": predictions_path,
        "retrieval_traces": traces_path,
        "report_json": report_json_path,
        "report_md": report_md_path,
    }


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    payload = "\n".join(lines)
    if lines:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def _markdown_report(payload: dict[str, Any]) -> str:
    metrics = dict(payload["metrics"])
    overall = dict(metrics.get("overall") or {})
    lines = [
        f"# {metrics.get('dataset_id', 'eval')} Report",
        "",
        "## Run",
        "",
        f"- Dataset: `{metrics.get('dataset_id', '')}`",
        f"- Source: `{metrics.get('source_path', '')}`",
        f"- Conversations: {metrics.get('conversation_count', 0)}",
        f"- Questions: {metrics.get('question_count', 0)}",
        f"- Top K: {metrics.get('top_k', 0)}",
        f"- Retrieval mode: `{payload['config'].get('retrieval_mode', '')}`",
        f"- Answer mode: `{payload['config'].get('answer_mode', '')}`",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Retrieval hit@k | {_pct(overall.get('retrieval_hit', 0.0))} |",
        f"| Retrieval MRR | {_pct(overall.get('retrieval_mrr', 0.0))} |",
        f"| Answer exact | {_pct(overall.get('answer_exact', 0.0))} |",
        f"| Answer F1 | {_pct(overall.get('answer_f1', 0.0))} |",
        f"| Answer BLEU-1 | {_pct(overall.get('answer_bleu1', 0.0))} |",
        "",
        "## By Category",
        "",
        "| Category | Count | Retrieval hit@k | Answer F1 |",
        "|---|---:|---:|---:|",
    ]
    for category, item in dict(metrics.get("by_category") or {}).items():
        lines.append(
            f"| {category} | {item.get('count', 0)} | "
            f"{_pct(item.get('retrieval_hit', 0.0))} | {_pct(item.get('answer_f1', 0.0))} |"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Predictions JSONL: `{payload['artifacts'].get('predictions', '')}`",
            f"- Retrieval traces JSONL: `{payload['artifacts'].get('retrieval_traces', '')}`",
            f"- Machine report JSON: `{payload['artifacts'].get('report_json', '')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _pct(value: object) -> str:
    return f"{float(value or 0.0) * 100:.2f}%"
