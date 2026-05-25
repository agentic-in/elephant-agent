"""Cron-specific operator helpers for the API runtime."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .api_runtime_support import _now


def run_proactive_ask_now(self) -> dict[str, Any]:
    """Run the built-in proactive ask scheduler once on demand."""
    from packages.gateway_core.proactive_ask import ProactiveAskTickResult
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

    aggregate, delivery_error = _run_proactive_ask_via_bridge(
        self,
        state_dir=state_dir,
        proactive_config=proactive_config,
    )

    summary = (
        f"scanned={aggregate.scanned} · eligible={aggregate.eligible} · "
        f"enqueued={aggregate.enqueued} · pending={aggregate.skipped_pending} · "
        f"policy={aggregate.skipped_policy} · no-questions={aggregate.skipped_no_questions} · "
        f"unbound={aggregate.skipped_unbound}"
    )
    outcome = "success" if aggregate.enqueued else "noop"
    if delivery_error is not None:
        outcome = "unavailable"
    return {
        "cron": {
            "job": job,
            "run": {
                "outcome": outcome,
                "summary": summary,
                "delivered": bool(aggregate.enqueued),
                "delivery_error": delivery_error,
                "recorded_at": _now().isoformat(),
            },
        }
    }


def _run_proactive_ask_via_bridge(
    app: Any,
    *,
    state_dir: Path,
    proactive_config: Mapping[str, Any],
) -> tuple[Any, str | None]:
    from packages.gateway_core.proactive_ask import ProactiveAskTickResult

    bridge = getattr(app, "gateway_runtime_bridge", None)
    run_once = getattr(bridge, "run_proactive_ask_once", None)
    if not callable(run_once):
        return ProactiveAskTickResult(), "gateway runtime bridge unavailable"
    try:
        result = run_once(state_dir=state_dir, config=proactive_config)
    except Exception as exc:
        return ProactiveAskTickResult(), f"{type(exc).__name__}: {exc}"
    if isinstance(result, ProactiveAskTickResult):
        return result, None
    if isinstance(result, Mapping):
        return ProactiveAskTickResult(
            scanned=int(result.get("scanned") or 0),
            eligible=int(result.get("eligible") or 0),
            enqueued=int(result.get("enqueued") or 0),
            skipped_no_questions=int(result.get("skipped_no_questions") or 0),
            skipped_pending=int(result.get("skipped_pending") or 0),
            skipped_policy=int(result.get("skipped_policy") or 0),
            skipped_unbound=int(result.get("skipped_unbound") or 0),
        ), None
    return ProactiveAskTickResult(), "gateway runtime bridge returned invalid proactive ask result"


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
