"""Shared implementation for Elephant eval CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.evals.contracts import EvalRunConfig, EvalRunOutput
from packages.evals.datasets import load_locomo_dataset
from packages.evals.reports import write_eval_artifacts
from packages.evals.scorers import score_locomo_results
from packages.evals.targets import ElephantMemoryEvalTarget, ElephantModelAnswerRunner


DEFAULT_LOCOMO_PATH = Path("/Users/bitliu/locomo/data/locomo10.json")
DEFAULT_LOCOMO_REFINED_PATH = Path("/Users/bitliu/LoCoMo_refined/data/public")


def default_dataset_path(dataset: str) -> Path:
    normalized = _normalize_dataset_name(dataset)
    if normalized == "locomo_refined":
        return DEFAULT_LOCOMO_REFINED_PATH
    return DEFAULT_LOCOMO_PATH


def run_eval(
    config: EvalRunConfig,
    *,
    embedding_service: Any,
    answer_runner: Any | None = None,
    model_provider: Any | None = None,
    profile: Any | None = None,
    model_role: str = "strong",
) -> EvalRunOutput:
    dataset = load_locomo_dataset(
        dataset=config.dataset,
        path=config.dataset_path,
        limit_conversations=config.limit_conversations,
        limit_questions=config.limit_questions,
    )
    resolved_answer_runner = answer_runner
    if resolved_answer_runner is None:
        if model_provider is None or profile is None:
            raise ValueError("run_eval requires an answer runner or model_provider + profile")
        resolved_answer_runner = ElephantModelAnswerRunner(
            model_provider=model_provider,
            profile=profile,
            model_role=model_role,
        )
    target = ElephantMemoryEvalTarget(
        embedding_service=embedding_service,
        answer_runner=resolved_answer_runner,
        top_k=config.top_k,
        retrieval_mode=config.retrieval_mode,
        answer_mode=config.answer_mode,
    )
    results = target.evaluate_dataset(dataset)
    metrics = score_locomo_results(dataset, results, top_k=config.top_k)
    artifacts = write_eval_artifacts(
        dataset=dataset,
        results=results,
        metrics=metrics,
        config=config,
    )
    return EvalRunOutput(
        dataset=dataset,
        results=results,
        metrics=metrics,
        artifacts=artifacts,
    )


def summarize_eval_output(output: EvalRunOutput) -> dict[str, object]:
    return {
        "dataset_id": output.dataset.dataset_id,
        "question_count": len(output.results),
        "overall": dict(output.metrics.get("overall", {})),
        "artifacts": {key: str(value) for key, value in output.artifacts.items()},
    }


def print_eval_output(output: EvalRunOutput) -> None:
    print(json.dumps(summarize_eval_output(output), ensure_ascii=False, indent=2))


def _normalize_dataset_name(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"locomo_refined", "refined"}:
        return "locomo_refined"
    if text in {"locomo", "original", "locomo_original"}:
        return "locomo"
    raise ValueError(f"unsupported dataset: {value}")
