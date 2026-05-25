"""Facts, reflect, wake, and root command runners for the CLI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import os
import random
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace

from packages.cron import (
    ensure_dream_cron as _ensure_dream_cron_row,
    ensure_nightly_learning_crons as _ensure_nightly_learning_cron_rows,
    remove_former_diary_crons as _remove_former_diary_cron_rows,
)
from packages.state import (
    DEFAULT_ELEPHANT_IDENTITY_TEXT,
    render_default_elephant_identity,
    render_user_profile_text,
    write_elephant_identity_file,
)

from .runtime import CliRuntime
from .provider_flow import (
    ProviderSelectionState,
    provider_choices as _shared_provider_choices,
    provider_setup_defaults,
    run_provider_selection_wizard,
)
from .shell import (
    Align,
    BRAND_ACCENT,
    BRAND_LIGHT,
    BRAND_MUTED,
    Console,
    Group,
    Panel,
    ProductizedShell,
    RICH_AVAILABLE,
    Table,
    Text,
    _resolve_elephant_version,
    render_stage_zero_elephant_mark,
)
from .wizard import (
    WIZARD_BACK,
    WIZARD_CANCEL,
    WizardChoice,
    _WizardBackSignal,
    _interactive_shell_supported,
    _wizard_choice_prompt,
    _wizard_dialogs_supported,
    _wizard_multi_choice_prompt,
    _wizard_text_prompt,
)

from .cli_main_elephant_support import *  # noqa: F401,F403
from .cli_main_elephant_support import _current_elephant_session
from .cli_main_setup import *  # noqa: F401,F403
from .cli_main_support import *  # noqa: F401,F403

LOGGER = logging.getLogger(__name__)

DEFAULT_PROVIDER_ID = "openai-compatible"
CLI_THEME_TITLE_GLYPH = "🐘"
CLI_THEME_BULLET = "•"
CLI_THEME_WELCOME_GLYPH = "🐘"
CLI_THEME_SUBTITLE = "Personal Model first, curious at your pace."


from .cli_main_init_prompts import *  # noqa: F401,F403
from .cli_main_init_runtime import *  # noqa: F401,F403

def _personal_fact_preview(text: str, *, limit: int = 88) -> str:
    compact = " ".join(str(text).split())
    if not compact:
        return "<empty>"
    if len(compact) <= limit:
        return compact
    return f"{compact[: max(0, limit - 1)].rstrip()}…"


def _resolve_fact_target(runtime: CliRuntime, *, elephant_id: str | None = None):
    resolved_elephant_id = str(elephant_id or "").strip()
    if resolved_elephant_id:
        session = runtime.latest_session_for_elephant(resolved_elephant_id)
        if session is None:
            raise ValueError(f"unknown elephant: {resolved_elephant_id}")
    else:
        session = _current_elephant_session(runtime)
        if session is None:
            herd = runtime.list_herd(limit=2)
            if not herd:
                raise ValueError("no elephant is available yet")
            if len(herd) > 1:
                raise ValueError("elephant evidence requires --elephant-id when no current elephant is set")
            resolved_elephant_id = herd[0].elephant_id
            session = runtime.latest_session_for_elephant(resolved_elephant_id)
            if session is None:
                raise ValueError(f"unknown elephant: {resolved_elephant_id}")
        else:
            resolved_elephant_id = runtime.elephant_id_for_session(session)
    state = runtime.state_for_elephant(resolved_elephant_id) or runtime.current_elephant_state()
    if state is None or getattr(state, "elephant_id", "") != resolved_elephant_id:
        state = runtime.ensure_elephant_state(session)
    return session, state, resolved_elephant_id


def _fact_owner_id(session, state) -> str:
    owner_id = str(getattr(session, "personal_model_id", "") or getattr(state, "personal_model_id", "") or "").strip()
    if not owner_id:
        raise ValueError("Personal Model target is missing a personal_model_id")
    return owner_id


def _fact_status_breakdown(entries) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for entry in entries:
        key = str(getattr(entry, "status", "") or "unknown").strip().lower() or "unknown"
        counts[key] = counts.get(key, 0) + 1
    preferred = ["committed", "active", "approved", "candidate", "unknown"]
    ordered = [status for status in preferred if status in counts]
    ordered.extend(sorted(status for status in counts if status not in ordered))
    return tuple(f"{status}={counts[status]}" for status in ordered)


def _list_personal_fact_entries(runtime: CliRuntime, owner_id: str):
    list_facts = getattr(runtime.repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    try:
        return tuple(reversed(tuple(list_facts(personal_model_id=owner_id, status="active"))))
    except Exception:
        LOGGER.warning(
            "failed to load learning command owner facts",
            extra={"personal_model_id": owner_id},
            exc_info=True,
        )
        return ()


def _print_fact_list(runtime: CliRuntime, *, elephant_id: str | None = None) -> None:
    session, state, resolved_elephant_id = _resolve_fact_target(runtime, elephant_id=elephant_id)
    owner_id = _fact_owner_id(session, state)
    entries = _list_personal_fact_entries(runtime, owner_id)
    status_breakdown = ", ".join(_fact_status_breakdown(entries)) or "<empty>"
    fact_line_list: list[str] = []
    for entry in entries[:10]:
        timestamp = entry.committed_at.isoformat(timespec="seconds") if getattr(entry, "committed_at", None) is not None else "<time?>"
        metadata = dict(getattr(entry, "metadata", {}) or {})
        facet = str(metadata.get("facet") or metadata.get("topic") or "claim").strip()
        fact_line_list.append(f"{entry.fact_id} · {entry.lens}.{facet} · status={entry.status} · {timestamp}")
        fact_line_list.append(entry.text.strip() or "<empty>")
    fact_lines = tuple(fact_line_list) or ("<no Personal Model facts>",)
    _print_cli_card(
        "Elephant Agent understanding",
        "Personal Model entries attached to the current elephant.",
        sections=(
            CliCardSection(
                "Target",
                (
                    f"elephant_id · {resolved_elephant_id}",
                    f"state_id · {state.state_id}",
                    f"personal_model_id · {owner_id}",
                    f"episode_id · {session.episode_id}",
                    f"facts · {len(entries)}",
                    f"status_breakdown · {status_breakdown}",
                ),
            ),
            CliCardSection("Personal Model facts", fact_lines),
        ),
        next_commands=(
            "elephant evidence",
            "elephant evidence delete <fact-id>",
            "elephant wake",
        ),
    )


def _delete_personal_model_fact(runtime: CliRuntime, *, elephant_id: str | None, fact_id: str, reason: str | None) -> None:
    session, state, resolved_elephant_id = _resolve_fact_target(runtime, elephant_id=elephant_id)
    owner_id = _fact_owner_id(session, state)
    deletion_reason = reason or "fact retired from elephant evidence command"
    facts = tuple(runtime.repository.list_personal_model_facts(personal_model_id=owner_id, status=("active", "retired", "disputed")))
    current = next((fact for fact in facts if getattr(fact, "fact_id", "") == fact_id), None)
    if current is None:
        raise ValueError(f"unknown Personal Model entry: {fact_id}")
    from dataclasses import replace as _dc_replace
    from datetime import datetime, timezone
    updated = _dc_replace(
        current,
        status="deleted",
        metadata={
            **dict(getattr(current, "metadata", {}) or {}),
            "retired_by": "elephant evidence delete",
            "retired_reason": deletion_reason,
            "retired_at": datetime.now(timezone.utc).isoformat(),
            "understanding_status": "deleted",
        },
    )
    runtime.repository.upsert_personal_model_fact(updated)
    _print_cli_card(
        "Understanding retired",
        "A Personal Model entry was marked retired.",
        sections=(
            CliCardSection(
                "Deleted entry",
                (
                    f"elephant_id · {resolved_elephant_id}",
                    f"personal_model_id · {owner_id}",
                    f"fact_id · {updated.fact_id}",
                    f"lens · {updated.lens}",
                    f"status · {updated.status}",
                    f"reason · {deletion_reason}",
                    f"content · {_personal_fact_preview(updated.text, limit=120)}",
                ),
            ),
        ),
        next_commands=(
            "elephant evidence",
            "elephant wake",
        ),
    )


def _run_facts(runtime: CliRuntime, args: argparse.Namespace) -> int:
    if not runtime.list_herd(limit=1):
        _print_cli_card(
            "Elephant Agent evidence",
            "No elephant is available yet.",
            next_commands=("elephant init", "elephant herd new <name>", "elephant wake"),
        )
        return 1
    command = args.facts_command or "list"
    if command == "list":
        _print_fact_list(runtime, elephant_id=getattr(args, "elephant_id", None))
        return 0
    if command == "delete":
        _delete_personal_model_fact(
            runtime,
            elephant_id=getattr(args, "elephant_id", None),
            fact_id=args.fact_id,
            reason=getattr(args, "reason", None),
        )
        return 0
    raise ValueError(f"unknown evidence command: {command}")


def _learning_time(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    if not callable(isoformat):
        return ""
    try:
        return isoformat(timespec="seconds")
    except TypeError:
        return isoformat()


def _learning_result_payload_for_job(job: object) -> Mapping[str, object]:
    payload = getattr(job, "result_json", {})
    return dict(payload) if isinstance(payload, Mapping) else {}


def _learning_job_lines(jobs: Iterable[object], *, runtime: CliRuntime | None = None) -> tuple[str, ...]:
    lines: list[str] = []
    for job in jobs:
        started = _learning_time(getattr(job, "started_at", None))
        finished = _learning_time(getattr(job, "finished_at", None))
        time_part = finished or started or _learning_time(getattr(job, "created_at", None)) or "<time?>"
        progress = str(getattr(job, "progress_stage", "") or "").strip()
        detail = str(getattr(job, "progress_detail", "") or "").strip()
        result_payload = _learning_result_payload_for_job(job)
        result_status = str(result_payload.get("status") or "").strip()
        result_summary = str(result_payload.get("summary") or "").strip()
        suffix = f" · {progress}" if progress else ""
        if result_status or result_summary:
            suffix += f" · result={result_status or 'written'}"
            if result_summary:
                suffix += f" · {_personal_fact_preview(result_summary, limit=96)}"
        elif detail and detail != progress:
            suffix += f" · {_personal_fact_preview(detail, limit=96)}"
        lines.append(
            " · ".join(
                (
                    str(getattr(job, "status", "") or "unknown"),
                    str(getattr(job, "job_type", "") or "learning"),
                    f"trigger={getattr(job, 'trigger', '') or '<none>'}",
                    f"attempts={getattr(job, 'attempt_count', 0)}/{getattr(job, 'max_attempts', 0)}",
                    time_part,
                    str(getattr(job, "job_id", "") or "<job?>"),
                )
            )
            + suffix
        )
    return tuple(lines) or ("<no learning jobs>",)


def _learning_worker_lines(runtime: CliRuntime) -> tuple[str, ...]:
    from apps.learning_worker_runtime import load_learning_worker_record, learning_worker_is_running

    record = load_learning_worker_record(runtime.paths.state_dir) or {}
    return (
        f"worker_status · {record.get('status') or 'stopped'}",
        f"worker_running · {learning_worker_is_running(runtime.paths.state_dir)}",
        f"worker_pid · {record.get('pid') or '<none>'}",
        f"active_job_id · {record.get('active_job_id') or '<none>'}",
        f"current_stage · {record.get('current_stage') or '<none>'}",
    )


def _print_learning_history(runtime: CliRuntime, *, limit: int) -> None:
    jobs = runtime.repository.list_learning_jobs(limit=max(1, limit))
    _print_cli_card(
        "Elephant Agent learn history",
        "Recent background learning jobs across herd.",
        sections=(
            CliCardSection("Worker", _learning_worker_lines(runtime)),
            CliCardSection("Jobs", _learning_job_lines(jobs, runtime=runtime)),
        ),
        next_commands=("elephant reflect status", "elephant reflect start", "elephant wake"),
    )


def _print_learning_status(runtime: CliRuntime, *, elephant_id: str | None, limit: int) -> None:
    if not runtime.list_herd(limit=1):
        _print_learning_history(runtime, limit=limit)
        return
    session, state, resolved_elephant_id = _resolve_fact_target(runtime, elephant_id=elephant_id)
    status = runtime.learning_runtime_status(session_id=session.episode_id, limit=max(1, limit))
    job_rows = tuple(status.get("jobs") or ()) if isinstance(status, dict) else ()
    lines = [
        f"running · {status.get('running_count', 0) if isinstance(status, dict) else 0}",
        f"queued · {status.get('queued_count', 0) if isinstance(status, dict) else 0}",
        f"failed · {status.get('failed_count', 0) if isinstance(status, dict) else 0}",
        f"completed · {status.get('completed_count', 0) if isinstance(status, dict) else 0}",
    ]
    job_lines = []
    for job in job_rows:
        if not isinstance(job, dict):
            continue
        result_summary = str(job.get("result_summary") or "").strip()
        detail = result_summary or str(job.get("progress_detail") or "").strip()
        result_status = str(job.get("result_status") or "").strip()
        result_suffix = f" · result={result_status}" if result_status else ""
        suffix = f" · {_personal_fact_preview(detail, limit=96)}" if detail else ""
        job_lines.append(
            f"{job.get('status', 'unknown')} · {job.get('job_type', 'learning')} · trigger={job.get('trigger', '<none>')} · {job.get('job_id', '<job?>')}{result_suffix}{suffix}"
        )
    _print_cli_card(
        "Elephant Agent learn status",
        "Background learning posture for the selected elephant.",
        sections=(
            CliCardSection(
                "Target",
                (
                    f"elephant_id · {resolved_elephant_id}",
                    f"state_id · {state.state_id}",
                    f"personal_model_id · {session.personal_model_id}",
                    f"episode_id · {session.episode_id}",
                ),
            ),
            CliCardSection("Worker", _learning_worker_lines(runtime)),
            CliCardSection("Counts", tuple(lines)),
            CliCardSection("Recent jobs", tuple(job_lines) or ("<no learning jobs>",)),
        ),
        next_commands=("elephant reflect queue", "elephant reflect run", "elephant reflect history"),
    )


def _queue_learning_job(
    runtime: CliRuntime,
    *,
    elephant_id: str | None,
    trigger: str,
    summary: str,
    source: str,
    force_new: bool = False,
    start_worker: bool = True,
    extra_metadata: dict[str, str] | None = None,
):
    session, _state, _resolved_elephant_id = _resolve_fact_target(runtime, elephant_id=elephant_id)
    metadata = {"source": source}
    if extra_metadata:
        metadata.update(extra_metadata)
    return runtime.schedule_learning_for_session(
        session_id=session.episode_id,
        trigger=trigger,
        summary=summary,
        metadata=metadata,
        force_new=force_new,
        start_worker=start_worker,
    )


def _run_learn(runtime: CliRuntime, args: argparse.Namespace) -> int:
    command = str(getattr(args, "learn_command", None) or "list").strip().lower()
    limit = max(1, int(getattr(args, "limit", 12) or 12))
    elephant_id = getattr(args, "elephant_id", None)
    wait_for_worker = bool(getattr(args, "wait", False))
    if command in {"status", "ls", "list", "history"}:
        _print_learning_history(runtime, limit=limit)
        return 0
    if command == "kill":
        from apps.learning_worker_runtime import stop_learning_worker

        stopped = stop_learning_worker(state_dir=runtime.paths.state_dir, reason="operator requested learn kill")
        _print_cli_card(
            "Elephant Agent learn worker stopped",
            "Background learning worker was asked to stop.",
            sections=(
                CliCardSection(
                    "Worker",
                    (
                        f"status · {stopped.get('status') or 'stopped'}",
                        f"stopped_pid · {stopped.get('stopped_pid') or '<none>'}",
                        f"signal_sent · {stopped.get('signal_sent')}",
                    ),
                ),
            ),
            next_commands=("elephant reflect list", "elephant reflect run"),
        )
        return 0
    if command in {"run", "queue", "start"}:
        job = _queue_learning_job(
            runtime,
            elephant_id=elephant_id,
            trigger="manual",
            summary="manual background learning requested from CLI",
            source=f"cli.reflect.{command}",
            force_new=True,
            start_worker=not wait_for_worker,
        )
        worker_line = "queued and background worker requested"
        worker_exit_code = 0
        if wait_for_worker:
            completed = subprocess.run(
                (
                    sys.executable,
                    "-m",
                    "apps.learning_worker_command",
                    "--state-dir",
                    str(runtime.paths.state_dir),
                    "--once",
                ),
                check=False,
            )
            worker_exit_code = int(completed.returncode or 0)
            if worker_exit_code:
                from apps.learning_worker_runtime import mark_learning_job_terminal_failure

                mark_learning_job_terminal_failure(
                    runtime,
                    job_id=job.job_id,
                    worker_id="cli.reflect.run",
                    error=f"learning worker subprocess exited with code {worker_exit_code}",
                )
            worker_line = f"worker once exit · {worker_exit_code}"
        _print_cli_card(
            "Elephant Agent learn run",
            "A background learning job was requested for the selected elephant.",
            sections=(
                CliCardSection(
                    "Job",
                    (
                        f"job_id · {job.job_id}",
                        f"job_type · {job.job_type}",
                        f"status · {job.status}",
                        f"trigger · {job.trigger}",
                        worker_line,
                    ),
                ),
            ),
            next_commands=("elephant reflect list", "elephant reflect kill", "elephant wake"),
        )
        return worker_exit_code
    raise ValueError(f"unknown learn command: {command}")


def _remove_former_diary_crons(runtime: CliRuntime) -> None:
    _remove_former_diary_cron_rows(runtime.cron_runtime)


def _ensure_dream_cron(runtime: CliRuntime) -> None:
    """Create the nightly Dream consolidation cron job if it does not exist."""
    _ensure_dream_cron_row(runtime.cron_runtime)


def _ensure_nightly_learning_crons(runtime: CliRuntime) -> None:
    """Create the single built-in nightly learning cron job."""
    _ensure_nightly_learning_cron_rows(runtime.cron_runtime)


def _run_grow(runtime: CliRuntime, args: argparse.Namespace) -> int:
    # Wake gate only needs "provider profile + credentials configured".
    # Skip deep checks (live model catalog + LLM probe) that added 10+ s
    # of network stall before the elephant-selection prompt could appear.
    report = runtime.provider_doctor(deep=False)
    if not _provider_session_ready(report):
        _print_grow_blocked(runtime)
        return 1

    try:
        episode_id, opened = _open_growth_episode(
            runtime,
            episode_id=getattr(args, "episode_id", None),
            elephant_id=args.elephant_id,
            prompt_for_multiple=args.message is None and _interactive_shell_supported(),
        )
    except _WizardCancelledError:
        _print_cli_card(
            "Grow paused",
            "No elephant was selected.",
            next_commands=("elephant wake", "elephant herd", "elephant herd new <name>"),
        )
        return 0
    except LookupError:
        _print_no_elephants()
        return 1

    if args.message is not None:
        runtime.prepare_session_surface(episode_id)
        try:
            outcome = runtime.explain_next_step(session_id=episode_id, prompt=args.message)
        except RuntimeError as error:
            _print_provider_turn_failed(runtime, error, session_id=episode_id)
            return 1
        _print_assistant_turn(runtime, outcome)
        return 0

    if _interactive_shell_supported():
        return ProductizedShell(runtime, session_id=episode_id, opened=opened, debug=args.debug).run()
    runtime.prepare_session_surface(episode_id)
    return _run_stream_grow_loop(runtime, episode_id, sys.stdin)

def _run_stream_grow_loop(runtime: CliRuntime, session_id: str, stream: Iterable[str]) -> int:
    for line in stream:
        prompt = line.rstrip("\n").strip()
        if not prompt:
            continue
        try:
            outcome = runtime.explain_next_step(session_id=session_id, prompt=prompt)
        except RuntimeError as error:
            _print_provider_turn_failed(runtime, error, session_id=session_id)
            return 1
        _print_assistant_turn(runtime, outcome)
    return 0

def _run_default_entry(runtime: CliRuntime) -> int:
    _print_root_cli_help()
    return 0


def _namespace(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _cli_runtime(state_dir: Path, *, warm_embedding: bool = True) -> CliRuntime:
    resolved_state_dir = Path(state_dir).expanduser()
    return CliRuntime.create(state_dir=resolved_state_dir, warm_embedding=warm_embedding)


def _resolve_reflect_run_request(
    *,
    trigger: str | None,
    features: str | None,
    date: str | None,
) -> tuple[str, dict[str, str]]:
    from datetime import date as date_type, timedelta

    allowed_triggers = {"manual", "dream", "diary", "skill_review"}
    requested_trigger = str(trigger or "").strip().lower() or None
    if requested_trigger is not None and requested_trigger not in allowed_triggers:
        choices = ", ".join(sorted(allowed_triggers))
        raise ValueError(f"--trigger must be one of: {choices}")

    explicit_features = str(features or "").strip() or None
    feature_set = {item.strip() for item in (explicit_features or "").split(",") if item.strip()}
    effective_trigger = requested_trigger or "manual"
    extra_metadata: dict[str, str] = {}

    if explicit_features:
        extra_metadata["features"] = explicit_features
        if "dream" in feature_set:
            if requested_trigger is None:
                effective_trigger = "dream" if feature_set == {"dream"} else "manual"
            extra_metadata["target_date"] = date or date_type.today().isoformat()
            if feature_set == {"dream"}:
                extra_metadata["diary_target_date"] = date or (date_type.today() - timedelta(days=1)).isoformat()
        if "diary" in feature_set:
            if requested_trigger is None:
                effective_trigger = "diary" if feature_set == {"diary"} else "manual"
            target_date = date or (date_type.today() - timedelta(days=1)).isoformat()
            if "dream" in feature_set:
                extra_metadata["diary_target_date"] = target_date
            else:
                extra_metadata["target_date"] = target_date
    else:
        if effective_trigger == "dream":
            extra_metadata["target_date"] = date or date_type.today().isoformat()
            extra_metadata["diary_target_date"] = date or (date_type.today() - timedelta(days=1)).isoformat()
        elif effective_trigger == "diary":
            extra_metadata["target_date"] = date or (date_type.today() - timedelta(days=1)).isoformat()
        elif date:
            raise ValueError("--date requires --trigger dream/diary or dream/diary features")

    return effective_trigger, extra_metadata


def _show_cli_banner() -> None:
    if RICH_AVAILABLE and Panel is not None and Console is not None and Group is not None:
        console = Console(highlight=False, soft_wrap=True)
        header = Text()
        header.append("🐘  Elephant Agent CLI\n", style=f"bold {BRAND_LIGHT}")
        header.append("A warm, steady way back to the elephant that remembers your path.\n", style=BRAND_MUTED)
        header.append(f"🐾  v{_resolve_elephant_version()} · here with you, built to stay.", style=BRAND_ACCENT)
        console.print(
            Panel(
                Group(
                    header,
                    Text(" "),
                    Align.center(_render_cli_banner_mark()),
                    Text(" "),
                    Text("Model what matters · ask gently · follow the path", style=BRAND_LIGHT),
                ),
                border_style=BRAND_ACCENT,
                title=f"[bold {BRAND_ACCENT}]Welcome[/bold {BRAND_ACCENT}]",
                subtitle=f"[bold {BRAND_LIGHT}]One elephant, a durable path; many elephants, one herd[/bold {BRAND_LIGHT}]",
                padding=(0, 1),
            )
        )
        return
    print("Elephant Agent CLI · here with you, built to stay.")


def _print_root_cli_help() -> None:
    _print_cli_help(
        "Elephant Agent CLI",
        "Warm, steady ways back to the elephant that remembers your path.",
        commands=CLI_HELP_COMMANDS,
        options=(
            ("--help", "Show this message and exit."),
            ("--no-animation", "Prefer steady output over animated transitions when the terminal supports motion."),
            ("--color <auto|always|never>", "Control colorized output."),
        ),
        next_commands=CLI_HELP_NEXT_COMMANDS,
        tagline=CLI_HELP_TAGLINE,
    )


__all__ = tuple(name for name in globals() if not name.startswith("__"))
