"""Internal dashboard projection for Paths."""

from __future__ import annotations

from typing import Any

from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID

from .api_runtime_paths import paths_dashboard


def fill_paths_section(dashboard: dict[str, Any], self) -> None:
    dashboard["paths"] = paths_dashboard(self.repository, personal_model_id=DEFAULT_PERSONAL_MODEL_ID)
