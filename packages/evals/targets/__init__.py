"""Target-system adapters for eval runs."""

from .elephant_memory import (
    AnswerRunner,
    ElephantMemoryEvalTarget,
    ElephantModelAnswerRunner,
    is_elephant_memory_mode,
)
from .locomo_baselines import LoCoMoBaselineEvalTarget, is_baseline_mode, normalize_baseline_mode

__all__ = [
    "AnswerRunner",
    "ElephantMemoryEvalTarget",
    "ElephantModelAnswerRunner",
    "is_elephant_memory_mode",
    "LoCoMoBaselineEvalTarget",
    "is_baseline_mode",
    "normalize_baseline_mode",
]
