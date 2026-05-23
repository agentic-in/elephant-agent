"""Helpers for provider runtime status summaries."""

from __future__ import annotations

from typing import Any


def embedding_bootstrap_summary_fields(state: Any) -> dict[str, Any]:
    return {
        "embedding_bootstrap_status": state.status,
        "embedding_bootstrap_summary": state.summary,
        "embedding_bootstrap_updated_at": state.updated_at,
        "embedding_bootstrap_failure_message": state.failure_message,
        "embedding_model_id": state.model_id,
        "embedding_model_root": state.model_root,
        "embedding_model_source_url": state.model_source_url,
        "embedding_bootstrap_source": state.source,
    }


def invalid_provider_resolution_summary(profile: Any, error: Exception) -> dict[str, Any]:
    return {
        "display_name": profile.provider_id,
        "transport_display_name": profile.transport_id,
        "supports_streaming": False,
        "supports_reasoning": False,
        "reasoning_efforts": (),
        "auth_type": profile.auth_method,
        "secret_status": "unknown",
        "secret_source": "unknown",
        "model_id": profile.default_model,
        "status": "configuration_required",
        "error": str(error),
    }
