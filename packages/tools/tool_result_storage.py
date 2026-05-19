"""Large tool-result storage and observation budgeting helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha1
import math
from pathlib import Path
import re
import tempfile


DEFAULT_RESULT_SIZE_CHARS = 100_000
DEFAULT_TURN_BUDGET_CHARS = 200_000
DEFAULT_PREVIEW_SIZE_CHARS = 1_500
DEFAULT_PINNED_THRESHOLDS = {
    "read_file": math.inf,
    "tool.file.read": math.inf,
}

_PERSISTED_OUTPUT_MARKER = "<persisted-output"
_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class ToolResultBudgetConfig:
    result_size_chars: int | float = DEFAULT_RESULT_SIZE_CHARS
    turn_budget_chars: int = DEFAULT_TURN_BUDGET_CHARS
    preview_size_chars: int = DEFAULT_PREVIEW_SIZE_CHARS
    pinned_thresholds: Mapping[str, int | float] = field(default_factory=lambda: dict(DEFAULT_PINNED_THRESHOLDS))


def maybe_persist_tool_result(
    content: str,
    *,
    tool_name: str,
    tool_use_id: str,
    config: ToolResultBudgetConfig = ToolResultBudgetConfig(),
    storage_dir: Path | None = None,
) -> str:
    normalized = content.strip()
    if not normalized:
        return normalized
    threshold = config.pinned_thresholds.get(tool_name, config.result_size_chars)
    if threshold <= 0 or len(normalized) > threshold:
        try:
            path = _write_persisted_output(
                normalized,
                tool_use_id=tool_use_id,
                storage_dir=storage_dir,
            )
        except OSError:
            return _preview_text(normalized, preview_chars=config.preview_size_chars)
        preview = _preview_text(normalized, preview_chars=config.preview_size_chars)
        return "\n".join(
            (
                f'<persisted-output tool="{tool_name}" path="{path}">',
                "The full tool result was saved outside the model context.",
                f"Read the file if exact omitted content is needed: {path}",
                "",
                "Preview:",
                preview,
                "</persisted-output>",
            )
        )
    return normalized


def enforce_tool_observation_budget(
    observations: list[str],
    *,
    config: ToolResultBudgetConfig = ToolResultBudgetConfig(),
    storage_dir: Path | None = None,
) -> list[str]:
    if config.turn_budget_chars <= 0:
        return observations
    total = sum(len(item) for item in observations)
    if total <= config.turn_budget_chars:
        return observations

    budgeted = list(observations)
    for index, observation in sorted(
        enumerate(budgeted),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        if total <= config.turn_budget_chars:
            break
        if _PERSISTED_OUTPUT_MARKER in observation:
            continue
        shortened = maybe_persist_tool_result(
            observation,
            tool_name="tool.observation",
            tool_use_id=f"observation-{index}",
            config=ToolResultBudgetConfig(
                result_size_chars=0,
                turn_budget_chars=config.turn_budget_chars,
                preview_size_chars=config.preview_size_chars,
                pinned_thresholds={},
            ),
            storage_dir=storage_dir,
        )
        total -= len(budgeted[index])
        budgeted[index] = shortened
        total += len(shortened)

    if total <= config.turn_budget_chars:
        return budgeted

    for index, observation in sorted(
        enumerate(budgeted),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        if total <= config.turn_budget_chars:
            break
        per_item = max(160, config.turn_budget_chars // max(len(budgeted), 1))
        shortened = _preview_text(observation, preview_chars=per_item)
        total -= len(budgeted[index])
        budgeted[index] = shortened
        total += len(shortened)
    return budgeted


def _preview_text(content: str, *, preview_chars: int) -> str:
    normalized = content.strip()
    if preview_chars <= 0 or len(normalized) <= preview_chars:
        return normalized
    return f"{normalized[: max(0, preview_chars - 15)].rstrip()} ... [truncated]"


def _write_persisted_output(
    content: str,
    *,
    tool_use_id: str,
    storage_dir: Path | None,
) -> Path:
    root = storage_dir or (Path(tempfile.gettempdir()) / "elephant-tool-results")
    root.mkdir(parents=True, exist_ok=True)
    safe_id = _SAFE_NAME_PATTERN.sub("_", tool_use_id.strip())[-120:] or "tool-result"
    digest = sha1(content.encode("utf-8", errors="replace")).hexdigest()[:12]
    path = root / f"{safe_id}-{digest}.txt"
    path.write_text(content, encoding="utf-8", errors="replace")
    return path


__all__ = [
    "DEFAULT_PREVIEW_SIZE_CHARS",
    "DEFAULT_RESULT_SIZE_CHARS",
    "DEFAULT_TURN_BUDGET_CHARS",
    "ToolResultBudgetConfig",
    "enforce_tool_observation_budget",
    "maybe_persist_tool_result",
]
