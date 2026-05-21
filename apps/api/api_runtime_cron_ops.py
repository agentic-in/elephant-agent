"""Cron-specific operator helpers for the API runtime."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .api_runtime_support import _now


def run_proactive_ask_now(self) -> dict[str, Any]:
    """Run the built-in proactive ask scheduler once on demand."""
    from apps.gateway.cron_service import CONFIGURED_IM_ADAPTERS
    from apps.gateway.proactive_ask_job import ProactiveAskTickResult, run_proactive_ask_tick
    from apps.gateway.runtime import build_gateway_app
    from packages.runtime_config import (
        global_config_path_for_state_dir,
        load_global_config,
        personal_model_question_config_from_global,
    )

    state_dir = Path(str(self.repository.database_path.parent))
    config = load_global_config(global_config_path_for_state_dir(state_dir), state_dir=state_dir)
    question_config = personal_model_question_config_from_global(config)
    proactive_config = question_config.get("proactive_ask")
    if not isinstance(proactive_config, Mapping):
        proactive_config = {}

    from .api_runtime_console import _proactive_ask_system_job

    job = _proactive_ask_system_job(self)
    if job is None:
        raise ValueError("system cron job unavailable: system:proactive-ask")
    if proactive_config.get("enabled") is False:
        return {
            "cron": {
                "job": job,
                "run": {
                    "outcome": "paused",
                    "summary": "Proactive Questions is paused.",
                    "delivered": False,
                    "delivery_error": None,
                    "recorded_at": _now().isoformat(),
                },
            }
        }

    app, outbound_queue, _ = build_gateway_app(state_dir=str(state_dir))
    aggregate = ProactiveAskTickResult()
    for adapter_id in CONFIGURED_IM_ADAPTERS:
        result = run_proactive_ask_tick(
            app=app,
            adapter_id=adapter_id,
            outbound_queue=outbound_queue,
            config=proactive_config,
        )
        aggregate = ProactiveAskTickResult(
            scanned=aggregate.scanned + result.scanned,
            eligible=aggregate.eligible + result.eligible,
            enqueued=aggregate.enqueued + result.enqueued,
            skipped_no_questions=aggregate.skipped_no_questions + result.skipped_no_questions,
            skipped_pending=aggregate.skipped_pending + result.skipped_pending,
            skipped_policy=aggregate.skipped_policy + result.skipped_policy,
            skipped_unbound=aggregate.skipped_unbound + result.skipped_unbound,
        )

    summary = (
        f"scanned={aggregate.scanned} · eligible={aggregate.eligible} · "
        f"enqueued={aggregate.enqueued} · pending={aggregate.skipped_pending} · "
        f"policy={aggregate.skipped_policy} · no-questions={aggregate.skipped_no_questions} · "
        f"unbound={aggregate.skipped_unbound}"
    )
    return {
        "cron": {
            "job": job,
            "run": {
                "outcome": "success" if aggregate.enqueued else "noop",
                "summary": summary,
                "delivered": bool(aggregate.enqueued),
                "delivery_error": None,
                "recorded_at": _now().isoformat(),
            },
        }
    }


def run_dream_now(self) -> dict[str, Any]:
    """Queue the built-in Dream learning pass once on demand."""
    from .api_runtime_console import _dream_system_job

    job = _dream_system_job(self)
    if job is None:
        raise ValueError("system cron job unavailable: system:dream")
    result = self.trigger_reflect_job(trigger="dream", features="dream")
    status = str(result.get("status") or "").strip().lower()
    outcome = "success" if status == "queued" else "error"
    detail = str(result.get("detail") or result.get("job_id") or status or "dream job queued")
    refreshed_job = _dream_system_job(self) or job
    return {
        "cron": {
            "job": refreshed_job,
            "run": {
                "outcome": outcome,
                "summary": detail,
                "delivered": False,
                "delivery_error": None if outcome == "success" else detail,
                "recorded_at": _now().isoformat(),
            },
        }
    }
