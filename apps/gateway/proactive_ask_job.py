"""Cron job for proactive personal model questions.

Runs inside the cron scheduler loop (same level as auto_retire).
Each tick checks all identities for a given adapter and delivers
at most one question per eligible user, respecting idle threshold,
daily max, and quiet hours from the flat proactive_ask config.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.curiosity import AskDecision, should_ask
from packages.gateway_core import GatewayOutboundQueue

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProactiveAskTickResult:
    """Result summary from a single proactive ask cron tick."""

    scanned: int = 0
    eligible: int = 0
    enqueued: int = 0
    skipped_no_questions: int = 0
    skipped_pending: int = 0
    skipped_policy: int = 0
    skipped_unbound: int = 0


def run_proactive_ask_tick(
    *,
    app: Any,
    adapter_id: str,
    outbound_queue: GatewayOutboundQueue,
    config: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> ProactiveAskTickResult:
    """Single tick of proactive ask evaluation for one adapter.

    Replaces the legacy GatewayIdleProactiveScheduler per-adapter daemon.

    Args:
        app: GatewayApp instance with repository, core, and execution methods.
        adapter_id: IM adapter (e.g. "messaging.weixin").
        outbound_queue: Queue for delivering messages.
        config: proactive_ask config dict (enabled, idle_threshold_minutes, daily_max, quiet_hours).
        now: Current datetime (defaults to UTC now).
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    # Load config with defaults.
    proactive_config = dict(config or {})
    enabled = proactive_config.get("enabled") is not False
    idle_threshold_minutes = int(proactive_config.get("idle_threshold_minutes") or 180)
    daily_max = int(proactive_config.get("daily_max") or 8)
    quiet_hours_raw = proactive_config.get("quiet_hours")
    if isinstance(quiet_hours_raw, (list, tuple)) and len(quiet_hours_raw) == 2:
        quiet_hours = (int(quiet_hours_raw[0]) % 24, int(quiet_hours_raw[1]) % 24)
    else:
        quiet_hours = (23, 7)

    if not enabled:
        return ProactiveAskTickResult()

    repository = app.repository
    identity_store = app.core.dependencies.identity_store
    session_store = app.core.dependencies.session_store

    scanned = eligible = enqueued = 0
    skipped_no_questions = skipped_pending = skipped_policy = skipped_unbound = 0

    for record in identity_store.list_records():
        if record.key.adapter_id != adapter_id:
            continue
        scanned += 1

        personal_model_id = _personal_model_id(app, record)
        if not personal_model_id:
            skipped_unbound += 1
            continue

        route_session = session_store.lookup(record.session_id)
        last_active = _last_activity(record, route_session)
        if last_active is None:
            skipped_unbound += 1
            continue

        # Check for pending (already asked, waiting response).
        list_open = getattr(repository, "list_open_questions", None)
        if not callable(list_open):
            skipped_no_questions += 1
            continue

        all_questions = list_open(
            personal_model_id=personal_model_id,
            status=("open", "asked"),
            limit=128,
        )

        if any(q.status == "asked" for q in all_questions):
            skipped_pending += 1
            continue

        candidates = tuple(q for q in all_questions if q.status == "open")
        if not candidates:
            skipped_no_questions += 1
            continue

        eligible += 1

        # Compute idle and user-local hour.
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)
        idle_minutes = (current - last_active).total_seconds() / 60.0
        tz_offset = _timezone_offset(repository, personal_model_id, now=current)
        user_local_hour = (current.hour + tz_offset) % 24
        asks_today = _count_asks_today(all_questions, now=current)

        decision: AskDecision = should_ask(
            enabled=enabled,
            idle_minutes=idle_minutes,
            idle_threshold_minutes=idle_threshold_minutes,
            daily_max=daily_max,
            asks_today=asks_today,
            quiet_hours=quiet_hours,
            current_hour=user_local_hour,
            candidate_questions=candidates,
        )

        if not decision.should_ask or decision.selected is None:
            skipped_policy += 1
            continue

        # Generate outbound message body via agent turn.
        body = _generate_body(app, record, route_session)
        if not body:
            skipped_policy += 1
            continue

        # Mark question as asked and deliver.
        outbound_queue.enqueue(
            adapter_id=adapter_id,
            account_id=record.key.account_id,
            conversation_id=record.key.conversation_id,
            body=body,
            metadata={
                "runtime_surface": "gateway_idle_proactive",
                "delivery_surface": "gateway_idle_proactive",
                "enqueued_via": "ProactiveAskCronJob",
                "question_id": decision.selected.question_id,
                "personal_model_id": personal_model_id,
                "state_id": record.state_id or "",
                "elephant_id": record.elephant_id or "",
                "session_id": record.session_id,
            },
        )

        record_delivery = getattr(app, "record_idle_proactive_delivery", None)
        if callable(record_delivery):
            record_delivery(record=record, route_session=route_session, body=body)

        enqueued += 1

    return ProactiveAskTickResult(
        scanned=scanned,
        eligible=eligible,
        enqueued=enqueued,
        skipped_no_questions=skipped_no_questions,
        skipped_pending=skipped_pending,
        skipped_policy=skipped_policy,
        skipped_unbound=skipped_unbound,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _personal_model_id(app: Any, record: Any) -> str | None:
    if record.state_id:
        try:
            state = app.repository.load_state(record.state_id)
        except Exception:
            state = None
        if state is not None and getattr(state, "personal_model_id", None):
            return str(state.personal_model_id)
    route_session = app.core.dependencies.session_store.lookup(record.session_id)
    if route_session is not None and route_session.profile_id:
        return str(route_session.profile_id)
    return None


def _last_activity(record: Any, route_session: Any) -> datetime | None:
    stamps = [
        getattr(route_session, "updated_at", None) if route_session is not None else None,
        getattr(record, "updated_at", None),
        getattr(record, "created_at", None),
    ]
    return next((s for s in stamps if isinstance(s, datetime)), None)


def _count_asks_today(questions: Any, *, now: datetime) -> int:
    today = now.astimezone(timezone.utc).date()
    count = 0
    for q in questions:
        last_asked = getattr(q, "last_asked_at", None)
        if isinstance(last_asked, datetime):
            if last_asked.tzinfo is None:
                last_asked = last_asked.replace(tzinfo=timezone.utc)
            if last_asked.date() == today:
                count += 1
    return count


def _timezone_offset(repository: Any, personal_model_id: str, *, now: datetime) -> int:
    """Resolve user timezone offset in hours."""
    tz_name = _profile_timezone_name(repository, personal_model_id)
    if tz_name:
        try:
            zone = ZoneInfo(tz_name)
            offset = now.astimezone(zone).utcoffset()
            if offset is not None:
                return int(round(offset.total_seconds() / 3600))
        except (ZoneInfoNotFoundError, Exception):
            pass
    offset = now.astimezone().utcoffset()
    return int(round(offset.total_seconds() / 3600)) if offset else 0


def _profile_timezone_name(repository: Any, personal_model_id: str) -> str | None:
    load_profile = getattr(repository, "load_personal_model_runtime_state", None)
    if not callable(load_profile):
        return _env_tz()
    try:
        profile = load_profile(personal_model_id)
    except Exception:
        return _env_tz()
    for entry in tuple(getattr(profile, "preferences", ()) or ()):
        text = str(entry).strip()
        lowered = text.lower()
        if lowered.startswith(("timezone=", "timezone:", "tz=", "tz:")):
            return text.split("=", 1)[-1].split(":", 1)[-1].strip()
    return _env_tz()


def _env_tz() -> str | None:
    return (os.environ.get("ELEPHANT_TIMEZONE") or os.environ.get("TZ") or "").strip() or None


def _generate_body(app: Any, record: Any, route_session: Any) -> str:
    """Generate outbound message via agent idle proactive turn."""
    run_turn = getattr(app, "run_idle_proactive_turn", None)
    if not callable(run_turn) or route_session is None:
        return ""
    outcome = run_turn(record=record, route_session=route_session)
    body = str(getattr(getattr(outcome, "execution", None), "summary", "") or "").strip()
    return "" if body == "[SILENT]" else body


__all__ = ["ProactiveAskTickResult", "run_proactive_ask_tick"]
