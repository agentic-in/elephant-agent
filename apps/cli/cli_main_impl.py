"""CLI main implementation assembled from setup and elephant helper modules."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import random
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace

import typer

from packages.cron import (
    ensure_dream_cron as _ensure_dream_cron_row,
    ensure_nightly_learning_crons as _ensure_nightly_learning_cron_rows,
    remove_former_diary_crons as _remove_former_diary_cron_rows,
)
from packages.state import DEFAULT_ELEPHANT_IDENTITY_TEXT, render_default_elephant_identity, render_user_profile_text, write_elephant_identity_file
from packages.sandbox import CloudProfileOptions, CloudSandboxOptions, DockerSandboxOptions, SandboxConfig, SeatbeltSandboxOptions, SshSandboxOptions

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
    BRAND_DARK,
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

DEFAULT_PROVIDER_ID = "openai-compatible"
DEFAULT_ELEPHANT_NAME_SUGGESTIONS = (
    "Ada",
    "Asher",
    "Avery",
    "Caleb",
    "Chloe",
    "Eden",
    "Eli",
    "Eliza",
    "Felix",
    "Hazel",
    "Iris",
    "Jasper",
    "Julian",
    "Leah",
    "Lena",
    "Leo",
    "Maya",
    "Miles",
    "Milo",
    "Nina",
    "Nora",
    "Owen",
    "Ruby",
    "Rowan",
    "Simon",
    "Silas",
    "Theo",
    "Vera",
    "Zoe",
)
CLI_THEME_TITLE_GLYPH = "🐘"
CLI_THEME_BULLET = "•"
CLI_THEME_WELCOME_GLYPH = "🐘"
CLI_THEME_SUBTITLE = "Personal Model first, curious at your pace."



from .cli_main_elephant_support import *  # noqa: F401,F403
from .cli_main_elephant_support import _current_elephant_session
from .cli_main_setup import *  # noqa: F401,F403
from .cli_main_support import *  # noqa: F401,F403


from .cli_main_init_prompts import *  # noqa: F401,F403
from .cli_main_init_runtime import *  # noqa: F401,F403
from .cli_main_provider_herd_commands import *  # noqa: F401,F403
from .cli_main_learning_commands import *  # noqa: F401,F403

from . import cli_main_init_prompts as _init_prompt_module
from . import cli_main_init_runtime as _init_runtime_module
from . import cli_main_provider_herd_commands as _provider_herd_module
from . import cli_main_learning_commands as _learning_command_module


def _sync_cli_main_overrides(target_module) -> None:
    """Preserve cli_main_impl monkeypatch compatibility after module splits."""
    for name, value in tuple(globals().items()):
        if name.startswith("__"):
            continue
        if getattr(value, "_cli_delegate_wrapper", False) is True:
            continue
        current = getattr(target_module, name, None)
        if (
            callable(current)
            and getattr(current, "__module__", None) == target_module.__name__
            and callable(value)
            and getattr(value, "__module__", None) == __name__
        ):
            continue
        setattr(target_module, name, value)


def _delegate_cli_helper(target_module, name: str):
    def _wrapper(*args, **kwargs):
        _sync_cli_main_overrides(target_module)
        return getattr(target_module, name)(*args, **kwargs)

    _wrapper._cli_delegate_wrapper = True  # type: ignore[attr-defined]
    return _wrapper


for _helper_module, _helper_names in (
    (
        _init_prompt_module,
        (
            "_choice_saved_value",
            "_init_text",
            "_init_wizard_choice",
            "_mbti_choices",
            "_normalize_first_language",
            "_print_init_section",
            "_prompt_birth_date",
            "_prompt_choice_with_type",
            "_prompt_first_elephant_name",
            "_prompt_first_language",
            "_prompt_hobbies",
            "_prompt_optional_text",
            "_prompt_required_text",
            "_prompt_starter_question",
            "_starter_question_model_hints",
        ),
    ),
    (
        _init_runtime_module,
        (
            "_bootstrap_personal_model_from_init",
            "_bootstrap_user_profile_from_init",
            "_infer_init_companion_posture",
            "_init_profile_learning_metadata",
            "_learned_init_entries",
            "_mapping_or_empty",
            "_mbti_traits",
            "_persist_init_question_config",
            "_proactive_ask_config_for_learning_intensity",
            "_run_embedding_birth_wizard",
            "_run_interactive_birth_wizard",
            "_run_interactive_elephant_wizard",
            "_starter_answer_map",
        ),
    ),
    (
        _provider_herd_module,
        (
            "_run_brain",
            "_run_elephant",
            "_run_embedding_provider",
            "_run_embedding_setup_wizard",
            "_run_herd",
            "_run_herd_adopt",
            "_run_herd_discover",
            "_run_setup",
        ),
    ),
    (
        _learning_command_module,
        (
            "_cli_runtime",
            "_delete_personal_model_fact",
            "_ensure_dream_cron",
            "_ensure_nightly_learning_crons",
            "_fact_owner_id",
            "_fact_status_breakdown",
            "_learning_job_lines",
            "_learning_result_payload_for_job",
            "_learning_time",
            "_learning_worker_lines",
            "_list_personal_fact_entries",
            "_namespace",
            "_personal_fact_preview",
            "_print_fact_list",
            "_print_learning_history",
            "_print_learning_status",
            "_print_root_cli_help",
            "_queue_learning_job",
            "_resolve_fact_target",
            "_resolve_reflect_run_request",
            "_run_default_entry",
            "_run_facts",
            "_run_grow",
            "_run_learn",
            "_run_stream_grow_loop",
            "_show_cli_banner",
        ),
    ),
):
    for _helper_name in _helper_names:
        globals()[_helper_name] = _delegate_cli_helper(_helper_module, _helper_name)

del _helper_module, _helper_name, _helper_names

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


# ── Sandbox helpers ───────────────────────────────────────────────────

def _load_sandbox_config(runtime: CliRuntime) -> SandboxConfig:
    """Load sandbox config from config.yaml, falling back to defaults."""
    from packages.runtime_config import load_global_config, load_sandbox_from_config, global_config_path_for_state_dir
    config_path = global_config_path_for_state_dir(runtime.paths.state_dir)
    try:
        global_config = load_global_config(config_path, state_dir=runtime.paths.state_dir)
    except OSError:
        return SandboxConfig()
    section = load_sandbox_from_config(global_config)
    if not section:
        return SandboxConfig()
    return SandboxConfig.from_config_section(section)


def _save_sandbox_config(runtime: CliRuntime, config: SandboxConfig) -> None:
    """Persist sandbox config to config.yaml."""
    from packages.runtime_config import save_sandbox_to_config, global_config_path_for_state_dir
    config_path = global_config_path_for_state_dir(runtime.paths.state_dir)
    save_sandbox_to_config(
        config_path,
        state_dir=runtime.paths.state_dir,
        sandbox_payload=config.to_config_section(),
    )


def _run_sandbox_status(runtime: CliRuntime) -> int:
    config = _load_sandbox_config(runtime)
    if RICH_AVAILABLE and Table is not None and Console is not None and Panel is not None:
        console = Console(highlight=False, soft_wrap=True)
        table = Table.grid(expand=True, padding=(0, 2))
        table.add_column(style=BRAND_MUTED, no_wrap=True)
        table.add_column()
        table.add_row("mode", config.mode)
        table.add_row("backend", config.backend)
        table.add_row("scope", config.scope)
        table.add_row("workspace_access", config.workspace_access)
        table.add_row("max_wall_seconds", str(config.resource_limits.max_wall_seconds))
        table.add_row("max_memory_mb", str(config.resource_limits.max_memory_mb))
        table.add_row("max_processes", str(config.resource_limits.max_processes))
        if config.backend == "docker":
            table.add_row("docker.image", config.docker.image)
        elif config.backend == "ssh":
            table.add_row("ssh.host", config.ssh.host or "(not set)")
            table.add_row("ssh.port", str(config.ssh.port))
        elif config.backend == "seatbelt":
            table.add_row("seatbelt.allow_network", str(config.seatbelt.allow_network))
            table.add_row("seatbelt.allow_network_loopback", str(config.seatbelt.allow_network_loopback))
        elif config.backend == "cloud":
            active = config.effective_cloud()
            table.add_row("cloud.profile", config.cloud_profile or "(default)")
            table.add_row("cloud.provider", active.provider)
            table.add_row("cloud.template", active.template or "(not set)")
            table.add_row("cloud.domain", active.domain)
            table.add_row("cloud.timeout", str(active.timeout))
            table.add_row("cloud.allow_internet", str(active.allow_internet))
            if config.clouds:
                table.add_row("cloud.profiles", ", ".join(config.clouds.keys()))
        status_label = "active" if config.is_active else "off"
        status_style = f"bold {BRAND_ACCENT}" if config.is_active else BRAND_MUTED
        console.print(Panel(
            table,
            title=f"[bold {BRAND_ACCENT}]Sandbox[/bold {BRAND_ACCENT}]  [{status_style}]{status_label}[/{status_style}]",
            border_style=BRAND_ACCENT,
            padding=(1, 2),
        ))
    else:
        _print_heading("Sandbox", f"mode: {config.mode}, backend: {config.backend}")
        _print_field("active", "yes" if config.is_active else "no")
        _print_field("scope", config.scope)
        _print_field("workspace_access", config.workspace_access)
        _print_field("max_wall_seconds", str(config.resource_limits.max_wall_seconds))
        _print_field("max_memory_mb", str(config.resource_limits.max_memory_mb))
        _print_field("max_processes", str(config.resource_limits.max_processes))
        if config.backend == "docker":
            _print_field("docker.image", config.docker.image)
        elif config.backend == "ssh":
            _print_field("ssh.host", config.ssh.host or "(not set)")
            _print_field("ssh.port", str(config.ssh.port))
        elif config.backend == "seatbelt":
            _print_field("seatbelt.allow_network", str(config.seatbelt.allow_network))
            _print_field("seatbelt.allow_network_loopback", str(config.seatbelt.allow_network_loopback))
        elif config.backend == "cloud":
            active = config.effective_cloud()
            _print_field("cloud.profile", config.cloud_profile or "(default)")
            _print_field("cloud.provider", active.provider)
            _print_field("cloud.template", active.template or "(not set)")
            _print_field("cloud.domain", active.domain)
            _print_field("cloud.timeout", str(active.timeout))
            _print_field("cloud.allow_internet", str(active.allow_internet))
            if config.clouds:
                _print_field("cloud.profiles", ", ".join(config.clouds.keys()))
    return 0


def _run_sandbox_configure(
    runtime: CliRuntime,
    *,
    mode: str | None,
    backend: str | None,
    docker_image: str | None,
    ssh_host: str | None,
    ssh_port: int | None,
    ssh_user: str | None,
    ssh_identity_file: str | None,
    cloud_provider: str | None = None,
    cloud_profile: str | None = None,
    cloud_template: str | None = None,
    cloud_browser_template: str | None = None,
    cloud_domain: str | None = None,
    cloud_api_key: str | None = None,
    cloud_timeout: int | None = None,
) -> int:
    config = _load_sandbox_config(runtime)

    # If no options provided, show interactive guide
    _has_cloud_opts = any(x is not None for x in [cloud_provider, cloud_profile, cloud_template, cloud_browser_template, cloud_domain, cloud_api_key, cloud_timeout])
    if mode is None and backend is None and docker_image is None and ssh_host is None and ssh_port is None and ssh_user is None and ssh_identity_file is None and not _has_cloud_opts:
        _print_sandbox_configure_guide(config)
        return 0

    # Apply mode (default to current if not specified)
    resolved_mode = mode if mode is not None else config.mode
    valid_modes = ("off", "all", "non-main")
    if resolved_mode not in valid_modes:
        print(f"Error: invalid mode '{resolved_mode}'. Choose from: {', '.join(valid_modes)}", file=sys.stderr)
        return 1

    # Apply backend (default to current if not specified)
    resolved_backend = backend if backend is not None else config.backend
    valid_backends = ("local", "docker", "ssh", "seatbelt", "cloud")
    if resolved_backend not in valid_backends:
        print(f"Error: invalid backend '{resolved_backend}'. Choose from: {', '.join(valid_backends)}", file=sys.stderr)
        return 1

    new_config = SandboxConfig(
        mode=resolved_mode,
        backend=resolved_backend,
        scope=config.scope,
        workspace_access=config.workspace_access,
        resource_limits=config.resource_limits,
        docker=DockerSandboxOptions(
            image=docker_image or config.docker.image,
        ),
        ssh=SshSandboxOptions(
            host=ssh_host or config.ssh.host,
            port=ssh_port or config.ssh.port,
            user=ssh_user or config.ssh.user,
            identity_file=ssh_identity_file or config.ssh.identity_file,
        ),
        cloud=CloudProfileOptions(
            provider=cloud_provider or config.cloud.provider,
            template=cloud_template or config.cloud.template,
            browser_template=cloud_browser_template or config.cloud.browser_template,
            domain=cloud_domain or config.cloud.domain,
            api_key=cloud_api_key or config.cloud.api_key,
            timeout=cloud_timeout or config.cloud.timeout,
            allow_internet=config.cloud.allow_internet,
        ),
        clouds=config.clouds,
        cloud_profile=cloud_profile or config.cloud_profile,
    )

    _save_sandbox_config(runtime, new_config)

    # Auto-build Docker image if backend is docker and image is missing
    build_result = None
    if new_config.is_active and new_config.backend == "docker":
        build_result = _try_build_docker_image(new_config.docker.image)

    _print_sandbox_configured(new_config, build_result=build_result)
    return 0


def _try_build_docker_image(image: str) -> str | None:
    """Try to build the Docker sandbox image if it doesn't exist.

    Returns:
        "exists" if image already present,
        "built" if successfully built,
        "failed" if build failed,
        "no-dockerfile" if Dockerfile.sandbox not found,
        None if Docker CLI unavailable.
    """
    import subprocess

    # Check if Docker CLI is available
    try:
        result = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
        if result.returncode != 0:
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    # Check if image already exists
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            return "exists"
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Find Dockerfile.sandbox — search common locations
    search_paths = [
        Path.cwd() / "Dockerfile.sandbox",
        Path(__file__).resolve().parents[2] / "Dockerfile.sandbox",
    ]
    # Also check PACKAGE_ROOT / project root
    for p in list(search_paths):
        parent = p.parent
        while parent != parent.parent:
            candidate = parent / "Dockerfile.sandbox"
            if candidate.exists():
                search_paths.append(candidate)
                break
            parent = parent.parent

    dockerfile_path = None
    for p in search_paths:
        if p.exists():
            dockerfile_path = p
            break

    if dockerfile_path is None:
        return "no-dockerfile"

    # Build the image
    build_context = str(dockerfile_path.parent)
    if RICH_AVAILABLE and Console is not None:
        console = Console(highlight=False, soft_wrap=True)
        console.print(
            Text.from_markup(
                f"  [bold {BRAND_ACCENT}]Building sandbox image[/bold {BRAND_ACCENT}] {image} …",
                style=BRAND_LIGHT,
            )
        )

    try:
        result = subprocess.run(
            ["docker", "build", "-t", image, "-f", str(dockerfile_path), build_context],
            capture_output=True, timeout=300,
        )
        if result.returncode == 0:
            return "built"
        else:
            if RICH_AVAILABLE and Console is not None:
                console = Console(highlight=False, soft_wrap=True)
                console.print(
                    Text.from_markup(
                        f"  [bold red]Build failed:[/bold red] {result.stderr.decode()[:200]}",
                    )
                )
            return "failed"
    except (subprocess.TimeoutExpired, OSError) as exc:
        if RICH_AVAILABLE and Console is not None:
            console = Console(highlight=False, soft_wrap=True)
            console.print(
                Text.from_markup(
                    f"  [bold red]Build error:[/bold red] {exc}",
                )
            )
        return "failed"


def _print_sandbox_configure_guide(config: SandboxConfig) -> None:
    """Show an interactive-style guide for sandbox configuration."""
    if not (RICH_AVAILABLE and Panel is not None and Console is not None and Table is not None):
        _print_heading("Sandbox configure", f"Current: mode={config.mode}, backend={config.backend}")
        _print_bullet("elephant sandbox configure --mode all")
        _print_bullet("elephant sandbox configure --mode all --backend docker --docker-image elephant-sandbox:latest")
        _print_bullet("elephant sandbox configure --mode non-main --backend ssh --ssh-host 10.0.0.1 --ssh-user ubuntu")
        _print_bullet("elephant sandbox configure --mode all --backend cloud --cloud-provider tencent --cloud-template tpl-xxx")
        return

    console = Console(highlight=False, soft_wrap=True)

    # Current config summary
    status_label = "active" if config.is_active else "off"
    status_style = f"bold {BRAND_ACCENT}" if config.is_active else BRAND_MUTED

    current_rows = Table.grid(expand=True, padding=(0, 2))
    current_rows.add_column(style=BRAND_MUTED, no_wrap=True)
    current_rows.add_column()
    current_rows.add_row("mode", f"[{status_style}]{config.mode}[/{status_style}]")
    current_rows.add_row("backend", config.backend)
    if config.backend == "docker":
        current_rows.add_row("docker.image", config.docker.image)
    elif config.backend == "ssh":
        current_rows.add_row("ssh.host", config.ssh.host or "(not set)")

    # Mode options
    mode_table = Table.grid(expand=True, padding=(0, 2))
    mode_table.add_column(style=f"bold {BRAND_ACCENT}", no_wrap=True, width=12)
    mode_table.add_column(style=BRAND_LIGHT, no_wrap=True, width=12)
    mode_table.add_column(style=BRAND_MUTED)
    mode_table.add_row("off", "(default)", "No sandboxing — all commands run on the host")
    mode_table.add_row("all", "", "Sandbox every tool execution")
    mode_table.add_row("non-main", "", "Sandbox background/automated runs only; interactive runs stay on host")

    # Backend options
    backend_table = Table.grid(expand=True, padding=(0, 2))
    backend_table.add_column(style=f"bold {BRAND_ACCENT}", no_wrap=True, width=12)
    backend_table.add_column(style=BRAND_LIGHT, no_wrap=True, width=12)
    backend_table.add_column(style=BRAND_MUTED)
    backend_table.add_row("local", "(default)", "Isolate via process restrictions on the host (no container)")
    backend_table.add_row("docker", "", "Run commands inside a Docker container")
    backend_table.add_row("ssh", "", "Execute commands on a remote machine via SSH")
    backend_table.add_row("seatbelt", "(macOS)", "Isolate via macOS Seatbelt sandbox (sandbox-exec)")
    backend_table.add_row("cloud", "", "Tencent Cloud Agent Runtime (E2B-compatible cloud sandbox)")

    # Quick-start examples
    examples_table = Table.grid(expand=True, padding=(0, 1))
    examples_table.add_column(style=f"bold {BRAND_ACCENT}", no_wrap=True)
    examples_table.add_column(style=BRAND_MUTED)
    examples_table.add_row("elephant sandbox configure --mode all", "Enable sandbox for all runs")
    examples_table.add_row(
        "elephant sandbox configure --mode all --backend docker --docker-image elephant-sandbox:latest",
        "Docker backend with custom image",
    )
    examples_table.add_row(
        "elephant sandbox configure --mode non-main --backend ssh --ssh-host 10.0.0.1 --ssh-user ubuntu",
        "SSH backend for automated runs",
    )
    examples_table.add_row(
        "elephant sandbox configure --mode off",
        "Turn off sandboxing",
    )
    examples_table.add_row(
        "elephant sandbox configure --mode all --backend cloud --cloud-provider tencent --cloud-template tpl-xxx",
        "Cloud sandbox with Tencent provider",
    )

    console.print(Panel(
        Group(
            # Header
            Text.from_markup(f"  {CLI_THEME_WELCOME_GLYPH} Sandbox Configure\n", style=f"bold {BRAND_LIGHT}"),
            Text("  Review and configure the sandbox isolation layer.\n", style=BRAND_MUTED),
            Text(" "),
            # Current config
            Text.from_markup(f"  [bold {BRAND_ACCENT}]Current Configuration[/bold {BRAND_ACCENT}]\n"),
            current_rows,
            Text(" "),
            # Modes
            Text.from_markup(f"  [bold {BRAND_ACCENT}]Modes[/bold {BRAND_ACCENT}]  (--mode)\n"),
            mode_table,
            Text(" "),
            # Backends
            Text.from_markup(f"  [bold {BRAND_ACCENT}]Backends[/bold {BRAND_ACCENT}]  (--backend)\n"),
            backend_table,
            Text(" "),
            # Examples
            Text.from_markup(f"  [bold {BRAND_ACCENT}]Quick Start[/bold {BRAND_ACCENT}]\n"),
            examples_table,
            Text(" "),
            # Backend-specific flags
            Text.from_markup(f"  [bold {BRAND_ACCENT}]Backend Flags[/bold {BRAND_ACCENT}]\n"),
            Text.from_markup(f"  [bold]Docker:[/bold]  --docker-image  Container image name\n", style=BRAND_MUTED),
            Text.from_markup(f"  [bold]SSH:[/bold]    --ssh-host, --ssh-port, --ssh-user, --ssh-identity-file\n", style=BRAND_MUTED),
            Text.from_markup(f"  [bold]Seatbelt:[/bold]  (no extra flags — auto-detects macOS sandbox-exec)\n", style=BRAND_MUTED),
            Text(" "),
            # Doctor hint
            Text.from_markup(f"  Run [bold {BRAND_ACCENT}]elephant sandbox doctor[/bold {BRAND_ACCENT}] after configuring to verify connectivity.", style=BRAND_LIGHT),
        ),
        title=f"[bold {BRAND_ACCENT}] {CLI_THEME_TITLE_GLYPH} Sandbox [/bold {BRAND_ACCENT}]  [{status_style}]{status_label}[/{status_style}]",
        subtitle=f"[bold {BRAND_LIGHT}]{CLI_THEME_SUBTITLE}[/bold {BRAND_LIGHT}]",
        border_style=BRAND_ACCENT,
        padding=(1, 2),
    ))


def _print_sandbox_configured(new_config: SandboxConfig, *, build_result: str | None = None) -> None:
    """Show the result of a successful configure."""
    if not (RICH_AVAILABLE and Panel is not None and Console is not None and Table is not None):
        _print_cli_card(
            "Sandbox configured",
            f"mode: {new_config.mode}, backend: {new_config.backend}",
            next_commands=(
                "elephant sandbox status",
                "elephant sandbox doctor",
            ),
        )
        return

    console = Console(highlight=False, soft_wrap=True)

    status_label = "active" if new_config.is_active else "off"
    status_style = f"bold {BRAND_ACCENT}" if new_config.is_active else BRAND_MUTED

    result_table = Table.grid(expand=True, padding=(0, 2))
    result_table.add_column(style=BRAND_MUTED, no_wrap=True)
    result_table.add_column()
    result_table.add_row("mode", f"[{status_style}]{new_config.mode}[/{status_style}]")
    result_table.add_row("backend", new_config.backend)
    if new_config.backend == "docker":
        result_table.add_row("docker.image", new_config.docker.image)
    elif new_config.backend == "ssh":
        result_table.add_row("ssh.host", new_config.ssh.host or "(not set)")
        result_table.add_row("ssh.port", str(new_config.ssh.port))
        if new_config.ssh.user:
            result_table.add_row("ssh.user", new_config.ssh.user)

    # Build status block
    build_block: list[object] = []
    if build_result is not None:
        build_block.append(Text(" "))
        if build_result == "exists":
            build_block.append(Text.from_markup(f"  ✅  Image [bold]{new_config.docker.image}[/bold] already available", style=BRAND_LIGHT))
        elif build_result == "built":
            build_block.append(Text.from_markup(f"  ✅  Image [bold]{new_config.docker.image}[/bold] built successfully", style=BRAND_LIGHT))
        elif build_result == "failed":
            build_block.append(Text.from_markup(
                f"  ⚠️  Image build failed — run [bold]docker build -t {new_config.docker.image} -f Dockerfile.sandbox .[/bold] manually",
                style="bold yellow",
            ))
        elif build_result == "no-dockerfile":
            build_block.append(Text.from_markup(
                f"  ⚠️  Dockerfile.sandbox not found — image [bold]{new_config.docker.image}[/bold] must be built manually",
                style="bold yellow",
            ))

    # Footer hint
    footer_hint = "  Run elephant sandbox doctor to verify your setup."
    if new_config.backend == "docker" and build_result in ("failed", "no-dockerfile"):
        footer_hint = "  Fix the image issue above, then run elephant sandbox doctor."

    console.print(Panel(
        Group(
            Text.from_markup(f"  {CLI_THEME_WELCOME_GLYPH} Configuration saved\n", style=f"bold {BRAND_LIGHT}"),
            Text(" "),
            result_table,
            *build_block,
            Text(" "),
            Text.from_markup(f"  Run [bold {BRAND_ACCENT}]elephant sandbox doctor[/bold {BRAND_ACCENT}] to verify your setup.", style=BRAND_LIGHT),
        ),
        title=f"[bold {BRAND_ACCENT}] {CLI_THEME_TITLE_GLYPH} Sandbox [/bold {BRAND_ACCENT}]  [{status_style}]{status_label}[/{status_style}]",
        subtitle=f"[bold {BRAND_LIGHT}]{CLI_THEME_SUBTITLE}[/bold {BRAND_LIGHT}]",
        border_style=BRAND_ACCENT,
        padding=(1, 2),
    ))


def _run_sandbox_doctor(runtime: CliRuntime) -> int:
    config = _load_sandbox_config(runtime)
    checks: list[dict[str, str]] = []

    # Check 1: mode
    if config.is_active:
        checks.append({"check": "mode", "status": "ok", "summary": f"sandbox mode is '{config.mode}'"})
    else:
        checks.append({"check": "mode", "status": "off", "summary": "sandbox is off — commands run without isolation"})

    # Check 2: backend-specific health
    if config.is_active:
        if config.backend == "docker":
            import subprocess
            try:
                result = subprocess.run(
                    ["docker", "info"], capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    checks.append({"check": "docker_daemon", "status": "ok", "summary": "Docker daemon is running"})
                else:
                    checks.append({"check": "docker_daemon", "status": "not-ready", "summary": "Docker daemon returned non-zero exit code"})
            except FileNotFoundError:
                checks.append({"check": "docker_daemon", "status": "not-ready", "summary": "docker CLI not found on PATH"})
            except (subprocess.TimeoutExpired, OSError) as exc:
                checks.append({"check": "docker_daemon", "status": "not-ready", "summary": str(exc)[:80]})

            # Check Docker image
            try:
                result = subprocess.run(
                    ["docker", "image", "inspect", config.docker.image],
                    capture_output=True, timeout=10,
                )
                if result.returncode == 0:
                    checks.append({"check": "docker_image", "status": "ok", "summary": f"image '{config.docker.image}' is available"})
                else:
                    checks.append({"check": "docker_image", "status": "not-ready", "summary": f"image '{config.docker.image}' not found — run: docker build -t {config.docker.image} -f Dockerfile.sandbox ."})
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                checks.append({"check": "docker_image", "status": "not-ready", "summary": str(exc)[:80]})

        elif config.backend == "ssh":
            if config.ssh.host:
                import subprocess
                ssh_args = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-p", str(config.ssh.port)]
                if config.ssh.identity_file:
                    ssh_args.extend(["-i", config.ssh.identity_file])
                if config.ssh.user:
                    ssh_args.append(f"{config.ssh.user}@{config.ssh.host}")
                else:
                    ssh_args.append(config.ssh.host)
                ssh_args.extend(["echo", "ok"])
                try:
                    result = subprocess.run(ssh_args, capture_output=True, timeout=10)
                    if result.returncode == 0:
                        checks.append({"check": "ssh_connectivity", "status": "ok", "summary": f"SSH to {config.ssh.host}:{config.ssh.port} is reachable"})
                    else:
                        checks.append({"check": "ssh_connectivity", "status": "not-ready", "summary": f"SSH to {config.ssh.host}:{config.ssh.port} returned non-zero exit code"})
                except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                    checks.append({"check": "ssh_connectivity", "status": "not-ready", "summary": str(exc)[:80]})
            else:
                checks.append({"check": "ssh_connectivity", "status": "not-ready", "summary": "sandbox.ssh.host is not configured"})

        elif config.backend == "local":
            checks.append({"check": "local_backend", "status": "ok", "summary": "local backend requires no external dependencies"})

        elif config.backend == "seatbelt":
            import subprocess as _sp
            _sandbox_exec = "/usr/bin/sandbox-exec"
            if _sp.run([_sandbox_exec, "-n", "no-network", "/usr/bin/true"], capture_output=True, timeout=5).returncode == 0:
                checks.append({"check": "seatbelt_available", "status": "ok", "summary": f"{_sandbox_exec} is available and functional"})
            else:
                checks.append({"check": "seatbelt_available", "status": "not-ready", "summary": f"{_sandbox_exec} not found or not functional (macOS only)"})

        elif config.backend == "cloud":
            try:
                import e2b as _e2b  # noqa: F401
                has_e2b = True
            except ImportError:
                has_e2b = False
            if not has_e2b:
                checks.append({"check": "e2b_sdk", "status": "not-ready", "summary": "e2b package not installed — run: pip install e2b"})
            else:
                api_key = config.cloud.api_key or os.environ.get("E2B_API_KEY", "")
                if api_key:
                    checks.append({"check": "e2b_sdk", "status": "ok", "summary": f"e2b package installed, API key configured ({api_key[:8]}...)"})
                else:
                    checks.append({"check": "e2b_sdk", "status": "not-ready", "summary": "e2b package installed, but no API key configured (sandbox.cloud.api_key or E2B_API_KEY)"})
            if config.cloud.template:
                checks.append({"check": "cloud_template", "status": "ok", "summary": f"template: {config.cloud.template}"})
            else:
                checks.append({"check": "cloud_template", "status": "not-ready", "summary": "sandbox.cloud.template not set — create one in Tencent Cloud console"})

    # Render results
    overall = "ready" if all(c["status"] in {"ok", "off"} for c in checks) else "not-ready"
    if RICH_AVAILABLE and Table is not None and Console is not None and Panel is not None:
        console = Console(highlight=False, soft_wrap=True)
        table = Table(show_header=True, border_style=BRAND_DARK)
        table.add_column("Check", style=BRAND_LIGHT)
        table.add_column("Status")
        table.add_column("Summary", style=BRAND_MUTED)
        for check in checks:
            status = check["status"]
            style = f"bold {BRAND_ACCENT}" if status == "ok" else (BRAND_MUTED if status == "off" else f"bold red")
            table.add_row(check["check"], f"[{style}]{status}[/{style}]", check["summary"])
        overall_style = f"bold {BRAND_ACCENT}" if overall == "ready" else "bold red"
        console.print(Panel(
            table,
            title=f"[bold {BRAND_ACCENT}]Sandbox Doctor[/bold {BRAND_ACCENT}]  [{overall_style}]{overall}[/{overall_style}]",
            border_style=BRAND_ACCENT,
            padding=(1, 2),
        ))
    else:
        _print_heading("Sandbox Doctor", f"overall: {overall}")
        for check in checks:
            _print_field(check["check"], f"{check['status']} — {check['summary']}")

    return 0 if overall == "ready" else 1


def _run_sandbox_verify(runtime: CliRuntime) -> int:
    """Run live policy probes inside the configured sandbox backend.

    Creates a real sandbox session, executes a series of commands that test
    whether Seatbelt/Docker/SSH policies are actually enforced, and reports
    PASS/FAIL for each check.
    """
    import tempfile
    from pathlib import Path
    from packages.sandbox import SandboxEnvironment, SecurityGuard

    config = _load_sandbox_config(runtime)
    if not config.is_active:
        _print_field("sandbox", "off — nothing to verify")
        return 1

    # Select backend (same logic as factory.py)
    if config.backend == "docker":
        from packages.sandbox import DockerBackend
        backend = DockerBackend(config)
    elif config.backend == "ssh":
        from packages.sandbox import SSHBackend
        backend = SSHBackend(
            config,
            host=config.ssh.host,
            port=config.ssh.port,
            user=config.ssh.user or None,
            identity_file=Path(config.ssh.identity_file) if config.ssh.identity_file else None,
        )
    elif config.backend == "seatbelt":
        from packages.sandbox import SeatbeltBackend
        backend = SeatbeltBackend(config)
        if not backend.health_check():
            from packages.sandbox import LocalBackend
            backend = LocalBackend(config)
    elif config.backend == "cloud":
        from packages.sandbox.backends.cloud_registry import get_cloud_backend
        backend = get_cloud_backend(config)
        if not backend.health_check():
            from packages.sandbox import LocalBackend
            backend = LocalBackend(config)
    else:
        from packages.sandbox import LocalBackend
        backend = LocalBackend(config)

    env = SandboxEnvironment(config, backend)
    guard = SecurityGuard()
    results: list[dict[str, str]] = []

    # Create a temporary workspace for the test
    test_cwd = Path(tempfile.mkdtemp(prefix="elephant-verify-"))
    sanitized_env = guard.sanitize_env(dict(os.environ))
    try:
        handle = env.create_session(session_id="verify", cwd=test_cwd, env=sanitized_env)

        # ── Probe 1: Environment variable ──────────────────────────────
        output = env.execute(handle, "echo $ELEPHANT_SANDBOX", cwd=test_cwd, timeout_seconds=10)
        sandbox_var = output.stdout.strip()
        if sandbox_var == config.backend:
            results.append({"probe": "env_var", "status": "PASS", "detail": f"ELEPHANT_SANDBOX={sandbox_var}"})
        elif sandbox_var:
            results.append({"probe": "env_var", "status": "WARN", "detail": f"ELEPHANT_SANDBOX={sandbox_var} (expected {config.backend})"})
        else:
            results.append({"probe": "env_var", "status": "FAIL", "detail": "ELEPHANT_SANDBOX not set — commands may not be sandboxed"})

        # ── Probe 2: Write to cwd (should be allowed) ─────────────────
        probe_file = test_cwd / "_verify_write.txt"
        output = env.execute(
            handle,
            f"python3 -c \"open('{probe_file}', 'w').write('ok')\"",
            cwd=test_cwd, timeout_seconds=10,
        )
        wrote_ok = probe_file.exists() and probe_file.read_text() == "ok"
        if wrote_ok:
            results.append({"probe": "write_cwd", "status": "PASS", "detail": "can write to cwd (workspace_access policy)"})
        else:
            results.append({"probe": "write_cwd", "status": "FAIL", "detail": f"cannot write to cwd: rc={output.returncode}, stderr={output.stderr[:80]}"})

        # ── Probe 3: Write to /tmp (should be allowed) ────────────────
        tmp_probe = Path("/tmp") / f"_elephant_verify_{os.getpid()}.txt"
        output = env.execute(
            handle,
            f"python3 -c \"open('{tmp_probe}', 'w').write('ok')\"",
            cwd=test_cwd, timeout_seconds=10,
        )
        wrote_tmp = tmp_probe.exists() and tmp_probe.read_text() == "ok"
        if wrote_tmp:
            results.append({"probe": "write_tmp", "status": "PASS", "detail": "can write to /tmp"})
        else:
            results.append({"probe": "write_tmp", "status": "FAIL", "detail": f"cannot write to /tmp: rc={output.returncode}"})
        # Cleanup
        tmp_probe.unlink(missing_ok=True)

        # ── Probe 4: Write outside writable roots (should be DENIED) ───
        # Use ~/Desktop or ~/Documents — user has permission but sandbox should deny
        home = Path.home()
        outside_probe = home / "_elephant_verify_sandbox_test.txt"
        # Pick a path that's NOT cwd and NOT /tmp
        # If cwd IS home, use a subdirectory instead
        if test_cwd.resolve().is_relative_to(home.resolve()):
            outside_probe = home / "Desktop" / "_elephant_verify_sandbox_test.txt"
        output = env.execute(
            handle,
            f"python3 -c \"open('{outside_probe}', 'w').write('leak')\"",
            cwd=test_cwd, timeout_seconds=10,
        )
        leaked = outside_probe.exists()
        if leaked:
            outside_probe.unlink(missing_ok=True)
            results.append({"probe": "write_escape", "status": "FAIL", "detail": f"wrote to {outside_probe} — sandbox DID NOT restrict writes!"})
        else:
            results.append({"probe": "write_escape", "status": "PASS", "detail": f"cannot write to {outside_probe} (write containment OK)"})

        # ── Probe 5: Network access (should be DENIED by default) ─────
        if config.backend == "seatbelt" and not config.seatbelt.allow_network:
            output = env.execute(
                handle,
                "curl -s --connect-timeout 3 -o /dev/null -w '%{http_code}' https://httpbin.org/get 2>/dev/null; echo EXIT:$?",
                cwd=test_cwd, timeout_seconds=15,
            )
            stdout = output.stdout.strip()
            # curl returns 000 when it cannot connect; exit code != 0 also indicates failure
            http_code = stdout.strip().strip("'").split("EXIT:")[0].strip() if "EXIT:" in stdout else stdout.strip("'")
            curl_exit = stdout.split("EXIT:")[-1].strip() if "EXIT:" in stdout else ""
            network_blocked = http_code == "000" or curl_exit != "0" or output.returncode != 0
            if network_blocked:
                results.append({"probe": "network_block", "status": "PASS", "detail": f"outbound network blocked (curl http_code={http_code}, exit={curl_exit})"})
            else:
                results.append({"probe": "network_block", "status": "FAIL", "detail": f"outbound network NOT blocked — curl returned http_code={http_code}"})
        else:
            results.append({"probe": "network_block", "status": "SKIP", "detail": f"network allowed by policy (allow_network={config.seatbelt.allow_network if config.backend == 'seatbelt' else 'N/A'})"})

        # ── Probe 6: Fork bomb protection ─────────────────────────────
        output = env.execute(
            handle,
            "python3 -c \"import os; [os.fork() for _ in range(10)]\" 2>&1 || echo 'FORK_BLOCKED'",
            cwd=test_cwd, timeout_seconds=10,
        )
        # With Seatbelt (allow process-fork), this may succeed or hit resource limits
        # With Docker, process limits should kick in
        if "FORK_BLOCKED" in output.stdout or output.returncode != 0:
            results.append({"probe": "fork_limit", "status": "PASS", "detail": f"fork flood controlled (rc={output.returncode})"})
        else:
            results.append({"probe": "fork_limit", "status": "WARN", "detail": "fork flood not blocked — resource limits may be permissive"})

        # Cleanup session
        env.cleanup(handle)

    finally:
        # Cleanup temp dir
        import shutil
        shutil.rmtree(test_cwd, ignore_errors=True)

    # ── Render results ─────────────────────────────────────────────────
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    warn_count = sum(1 for r in results if r["status"] in ("WARN", "SKIP"))
    overall = "VERIFIED" if fail_count == 0 else "ISSUES FOUND"

    if RICH_AVAILABLE and Table is not None and Console is not None and Panel is not None:
        console = Console(highlight=False, soft_wrap=True)
        table = Table(show_header=True, border_style=BRAND_DARK)
        table.add_column("Probe", style=BRAND_LIGHT)
        table.add_column("Result", width=8)
        table.add_column("Detail", style=BRAND_MUTED)
        for r in results:
            status = r["status"]
            if status == "PASS":
                style = f"bold green"
            elif status == "FAIL":
                style = "bold red"
            elif status == "SKIP":
                style = BRAND_MUTED
            else:
                style = "bold yellow"
            table.add_row(r["probe"], f"[{style}]{status}[/{style}]", r["detail"])
        overall_style = f"bold green" if fail_count == 0 else "bold red"
        console.print(Panel(
            table,
            title=f"[bold {BRAND_ACCENT}]Sandbox Verify[/bold {BRAND_ACCENT}]  [{overall_style}]{overall}[/{overall_style}]  "
                  f"({pass_count} pass, {fail_count} fail, {warn_count} skip/warn)",
            border_style=BRAND_ACCENT,
            padding=(1, 2),
        ))
    else:
        _print_heading("Sandbox Verify", f"overall: {overall}")
        for r in results:
            _print_field(r["probe"], f"{r['status']} — {r['detail']}")

    return 0 if fail_count == 0 else 1


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


def build_typer_app() -> typer.Typer:
    app = typer.Typer(
        name="elephant",
        help="Elephant Agent CLI with explicit init, wake, dashboard, herd, provider, Personal Model recall, learn, skills, gateway, cron, and status entrypoints.",
        no_args_is_help=False,
        rich_markup_mode="rich",
        add_completion=False,
    )
    provider_app = typer.Typer(
        name="provider",
        help="Configure or inspect the active provider, model, reasoning effort, and context window.",
        rich_markup_mode="rich",
        add_completion=False,
    )
    herd_app = typer.Typer(
        name="herd",
        help="Create, inspect, select, or delete existing Elephant Agent herd.",
        rich_markup_mode="rich",
        add_completion=False,
    )
    facts_app = typer.Typer(
        name="facts",
        help="Inspect or retire Personal Model facts without entering wake.",
        rich_markup_mode="rich",
        add_completion=False,
    )
    reflect_app = typer.Typer(
        name="reflect",
        help="Run, inspect, and manage background reflect agents (PM learning, dream, diary, audit).",
        rich_markup_mode="rich",
        add_completion=False,
    )
    provider_embeddings_app = typer.Typer(
        name="embeddings",
        help="Inspect or configure the embedding provider used for semantic retrieval.",
        rich_markup_mode="rich",
        add_completion=False,
    )
    sandbox_app = typer.Typer(
        name="sandbox",
        help="Inspect, configure, or diagnose the sandbox isolation layer.",
        rich_markup_mode="rich",
        add_completion=False,
    )

    app.add_typer(provider_app, name="provider")
    app.add_typer(herd_app, name="herd")
    app.add_typer(facts_app, name="facts")
    app.add_typer(reflect_app, name="reflect")
    app.add_typer(sandbox_app, name="sandbox")
    provider_app.add_typer(provider_embeddings_app, name="embeddings")

    @app.callback(invoke_without_command=True)
    def main_callback(
        ctx: typer.Context,
        state_dir: Path = typer.Option(..., "--state-dir", hidden=True),
        no_animation: bool = typer.Option(
            False,
            "--no-animation",
            help="Prefer steady output over animated transitions when the terminal supports motion.",
        ),
        color: str = typer.Option(
            "auto",
            "--color",
            help="Control colorized output: auto, always, or never.",
            case_sensitive=False,
        ),
    ) -> None:
        if no_animation:
            os.environ["ELEPHANT_NO_ANIMATION"] = "1"
        if color.strip().lower() == "never":
            os.environ["NO_COLOR"] = "1"
        if ctx.resilient_parsing:
            _print_root_cli_help()
            raise typer.Exit(0)
        if ctx.invoked_subcommand is None:
            runtime = _cli_runtime(state_dir)
            raise typer.Exit(_run_default_entry(runtime))

    @app.command("init")
    def init_command(
        ctx: typer.Context,
        provider_id: str = typer.Option(DEFAULT_PROVIDER_ID, "--provider-id", help="Provider id to configure for dialogue turns."),
        display_name: str | None = typer.Option(None, "--display-name", help="Display name to persist for the active profile."),
        elephant_text: str | None = typer.Option(None, "--elephant-text", help="Optional identity text for the first elephant."),
        elephant_name: str | None = typer.Option(None, "--elephant-name", help="Name for the first elephant created during init."),
        base_url: str | None = typer.Option(None, "--base-url", help="Provider base URL."),
        model_id: str | None = typer.Option(None, "--model-id", help="Dialogue model id to save as default."),
        api_key: str | None = typer.Option(None, "--api-key", help="Provider API key to persist or use immediately."),
        secret_env_var: str | None = typer.Option(None, "--secret-env-var", help="Environment variable name to read the provider key from."),
        embedding_provider: str = typer.Option("local", "--embedding-provider", help="Embedding provider kind: local or openai-compatible."),
        embedding_base_url: str | None = typer.Option(None, "--embedding-base-url", help="Embedding provider base URL."),
        embedding_model: str | None = typer.Option(None, "--embedding-model", help="Embedding model id."),
        embedding_dimensions: str | None = typer.Option(None, "--embedding-dimensions", help="Embedding vector dimensions."),
        embedding_api_key: str | None = typer.Option(None, "--embedding-api-key", help="Embedding API key."),
        embedding_secret_env_var: str | None = typer.Option(None, "--embedding-secret-env-var", help="Environment variable name for the embedding provider key."),
        context_window_mode: str | None = typer.Option(None, "--context-window-mode", help="Context window selection mode."),
        context_window: str | None = typer.Option(None, "--context-window", help="Explicit context window token count."),
        first_language: str = typer.Option("en", "--first-language", help="User first language for Personal Model bootstrap: en or zh."),
        learning_intensity: str = typer.Option("medium", "--learning-intensity", help="Personal Model question cadence tier: low, medium, or high."),
        preferred_name: str | None = typer.Option(None, "--preferred-name", help="Preferred name for Personal Model bootstrap."),
        age: str | None = typer.Option(None, "--age", help="Optional age or age range for Personal Model bootstrap."),
        birth_date: str | None = typer.Option(None, "--birth-date", help="Optional birth date for Personal Model bootstrap."),
        gender: str | None = typer.Option(None, "--gender", help="Optional gender/self-description for Personal Model bootstrap."),
        occupation: str | None = typer.Option(None, "--occupation", help="Optional role or occupation for Personal Model bootstrap."),
        city: str | None = typer.Option(None, "--city", help="Optional city or timezone for Personal Model bootstrap."),
        mbti: str | None = typer.Option(None, "--mbti", help="Optional MBTI/self-label for Personal Model bootstrap."),
        hobbies: str | None = typer.Option(None, "--hobbies", help="Optional comma-separated personal hobbies for Personal Model bootstrap."),
        astrology: str | None = typer.Option(None, "--astrology", help="Optional astrology/zodiac self-label for Personal Model bootstrap."),
        safety_boundaries: str | None = typer.Option(None, "--safety-boundaries", help="Optional boundaries Elephant Agent should respect."),
        communication_preference: str | None = typer.Option(None, "--communication-preference", help="Optional communication preference for Personal Model bootstrap."),
        relationship_mode: str | None = typer.Option(None, "--relationship-mode", help="Optional starting relationship mode for Personal Model bootstrap."),
        non_interactive: bool = typer.Option(False, "--non-interactive", help="Skip wizards and rely on flags only."),
    ) -> None:
        params = ctx.parent.params if ctx.parent is not None else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        args = _namespace(
            provider_id=provider_id,
            display_name=display_name,
            elephant_identity_text=elephant_text,
            elephant_name=elephant_name,
            base_url=base_url,
            model_id=model_id,
            api_key=api_key,
            secret_env_var=secret_env_var,
            embedding_provider=embedding_provider,
            embedding_base_url=embedding_base_url,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            embedding_api_key=embedding_api_key,
            embedding_secret_env_var=embedding_secret_env_var,
            context_window_mode=context_window_mode,
            context_window=context_window,
            first_language=first_language,
            learning_intensity=learning_intensity,
            preferred_name=preferred_name,
            age=age,
            birth_date=birth_date,
            gender=gender,
            occupation=occupation,
            city=city,
            mbti=mbti,
            hobbies=hobbies,
            relationship_mode=relationship_mode,
            astrology=astrology,
            safety_boundaries=safety_boundaries,
            communication_preference=communication_preference,
            non_interactive=non_interactive,
        )
        raise typer.Exit(_run_setup(runtime, args))

    @app.command("status")
    def status_command(
        ctx: typer.Context,
        deep: bool = typer.Option(False, "--deep", help="Run live provider catalog and runtime probe checks."),
    ) -> None:
        params = ctx.parent.params if ctx.parent is not None else ctx.params
        runtime = _cli_runtime(params["state_dir"], warm_embedding=False)
        _print_doctor(runtime, deep=deep)
        raise typer.Exit(0)

    @app.command("wake")
    def wake_command(
        ctx: typer.Context,
        elephant_id: str | None = typer.Option(None, "--elephant-id", help="Open the next Episode for a known elephant."),
        debug: bool = typer.Option(False, "--debug", help="Show runtime diagnostics inside the wake surface."),
        message: str | None = typer.Option(None, "--message", help="Run one wake turn and exit."),
    ) -> None:
        params = ctx.parent.params if ctx.parent is not None else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        args = _namespace(elephant_id=elephant_id, debug=debug, message=message)
        try:
            raise typer.Exit(_run_grow(runtime, args))
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error

    @provider_app.callback(invoke_without_command=True)
    def provider_callback(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            params = ctx.parent.params if ctx.parent is not None else ctx.params
            runtime = _cli_runtime(params["state_dir"])
            args = _namespace(
                provider_command="configure",
                provider_id=None,
                base_url=None,
                model_id=None,
                embedding_model=None,
                embedding_dimensions=None,
                api_key=None,
                secret_env_var=None,
                reasoning_effort=None,
                context_window_mode=None,
                context_window=None,
                non_interactive=False,
            )
            raise typer.Exit(_run_brain(runtime, args))

    @provider_app.command("status")
    def provider_status_command(ctx: typer.Context) -> None:
        params = ctx.parent.parent.params if ctx.parent is not None and ctx.parent.parent is not None else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_brain(runtime, _namespace(provider_command="status")))

    @provider_app.command("providers")
    def provider_catalog_command(ctx: typer.Context) -> None:
        params = ctx.parent.parent.params if ctx.parent is not None and ctx.parent.parent is not None else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_brain(runtime, _namespace(provider_command="providers")))

    @provider_app.command("models")
    def provider_models_command(
        ctx: typer.Context,
        provider_id: str | None = typer.Option(None, "--provider-id", help="Inspect models for a specific provider id."),
    ) -> None:
        params = ctx.parent.parent.params if ctx.parent is not None and ctx.parent.parent is not None else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_brain(runtime, _namespace(provider_command="models", provider_id=provider_id)))

    @provider_app.command("configure")
    def provider_configure_command(
        ctx: typer.Context,
        provider_id: str | None = typer.Option(None, "--provider-id", help="Provider id to configure."),
        base_url: str | None = typer.Option(None, "--base-url", help="Provider base URL."),
        model_id: str | None = typer.Option(None, "--model-id", help="Dialogue model id."),
        api_key: str | None = typer.Option(None, "--api-key", help="Provider API key."),
        secret_env_var: str | None = typer.Option(None, "--secret-env-var", help="Environment variable name to read the provider key from."),
        reasoning_effort: str | None = typer.Option(None, "--reasoning-effort", help="Reasoning effort to save for the active model."),
        context_window_mode: str | None = typer.Option(None, "--context-window-mode", help="Context window selection mode."),
        context_window: str | None = typer.Option(None, "--context-window", help="Explicit context window token count."),
        non_interactive: bool = typer.Option(False, "--non-interactive", help="Skip interactive provider selection."),
    ) -> None:
        params = ctx.parent.parent.params if ctx.parent is not None and ctx.parent.parent is not None else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        args = _namespace(
            provider_command="configure",
            provider_id=provider_id,
            base_url=base_url,
            model_id=model_id,
            api_key=api_key,
            secret_env_var=secret_env_var,
            reasoning_effort=reasoning_effort,
            context_window_mode=context_window_mode,
            context_window=context_window,
            non_interactive=non_interactive,
        )
        raise typer.Exit(_run_brain(runtime, args))

    @provider_embeddings_app.command("status")
    def provider_embeddings_status_command(ctx: typer.Context) -> None:
        params = ctx.parent.parent.parent.params if ctx.parent and ctx.parent.parent and ctx.parent.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_brain(runtime, _namespace(provider_command="embeddings", embedding_command="status")))

    @provider_embeddings_app.command("local")
    def provider_embeddings_local_command(
        ctx: typer.Context,
        source: str = typer.Option("huggingface", "--source", help="Model source: huggingface or modelscope."),
    ) -> None:
        params = ctx.parent.parent.parent.params if ctx.parent and ctx.parent.parent and ctx.parent.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_brain(runtime, _namespace(provider_command="embeddings", embedding_command="local", embedding_source=source)))

    @provider_embeddings_app.command("setup")
    def provider_embeddings_setup_command(ctx: typer.Context) -> None:
        """Interactive embedding provider setup wizard."""
        params = ctx.parent.parent.parent.params if ctx.parent and ctx.parent.parent and ctx.parent.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_brain(runtime, _namespace(provider_command="embeddings", embedding_command="setup")))

    @provider_embeddings_app.command("openai-compatible")
    def provider_embeddings_openai_command(
        ctx: typer.Context,
        base_url: str = typer.Option(..., "--base-url", help="Embedding provider base URL."),
        model: str = typer.Option(..., "--model", help="Embedding model id."),
        dimensions: str = typer.Option(..., "--dimensions", help="Embedding vector dimensions."),
        api_key: str | None = typer.Option(None, "--api-key", help="Embedding API key."),
        secret_env_var: str | None = typer.Option(None, "--secret-env-var", help="Environment variable name for the embedding provider key."),
    ) -> None:
        params = ctx.parent.parent.parent.params if ctx.parent and ctx.parent.parent and ctx.parent.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        args = _namespace(
            provider_command="embeddings",
            embedding_command="openai-compatible",
            base_url=base_url,
            embedding_model=model,
            embedding_dimensions=dimensions,
            api_key=api_key,
            secret_env_var=secret_env_var,
        )
        raise typer.Exit(_run_brain(runtime, args))

    @herd_app.callback(invoke_without_command=True)
    def herd_callback(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            params = ctx.parent.params if ctx.parent is not None else ctx.params
            runtime = _cli_runtime(params["state_dir"])
            raise typer.Exit(_run_herd(runtime, _namespace(herd_command=None)))

    @herd_app.command("new")
    def herd_new_command(
        ctx: typer.Context,
        elephant_name: str | None = typer.Argument(None, help="Name the new Elephant Agent elephant."),
        profile_id: str | None = typer.Option(None, "--profile-id", help="Profile id to attach the new elephant to."),
        display_name: str | None = typer.Option(None, "--display-name", help="Display name to show for the elephant."),
        debug: bool = typer.Option(False, "--debug", help="Show runtime diagnostics inside the wake surface."),
        message: str | None = typer.Option(None, "--message", help="Create the elephant, run one turn, and exit."),
    ) -> None:
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(
            _run_herd(
                runtime,
                _namespace(
                    herd_command="new",
                    elephant_name=elephant_name,
                    profile_id=profile_id,
                    display_name=display_name,
                    debug=debug,
                    message=message,
                ),
            )
        )

    @herd_app.command("current")
    def herd_current_command(ctx: typer.Context) -> None:
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_herd(runtime, _namespace(herd_command="current")))

    @herd_app.command("discover")
    def herd_discover_command(ctx: typer.Context) -> None:
        """Scan local agent CLIs and show baby elephant candidates."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_herd(runtime, _namespace(herd_command="discover")))

    @herd_app.command("adopt")
    def herd_adopt_command(
        ctx: typer.Context,
        runtime_id: str = typer.Argument(..., help="Runtime id from elephant herd discover."),
        display_name: str | None = typer.Option(None, "--display-name", help="Display name for the baby elephant."),
        role_title: str | None = typer.Option(None, "--role-title", help="Role title for Mother Elephant delegation."),
        role_prompt: str | None = typer.Option(None, "--role-prompt", help="Role instructions for this baby elephant."),
        enable: bool = typer.Option(False, "--enable", help="Enable this baby for local CLI delegation immediately."),
    ) -> None:
        """Create a baby elephant from a discovered local agent runtime."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        try:
            raise typer.Exit(
                _run_herd(
                    runtime,
                    _namespace(
                        herd_command="adopt",
                        runtime_id=runtime_id,
                        display_name=display_name,
                        role_title=role_title,
                        role_prompt=role_prompt,
                        enable=enable,
                    ),
                )
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error

    @herd_app.command("use")
    def herd_use_command(
        ctx: typer.Context,
        elephant_id: str | None = typer.Argument(None, help="Name the Elephant Agent elephant to select."),
    ) -> None:
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        try:
            raise typer.Exit(_run_herd(runtime, _namespace(herd_command="use", elephant_id=elephant_id)))
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error

    @herd_app.command("delete")
    def herd_delete_command(
        ctx: typer.Context,
        elephant_id: str | None = typer.Argument(None, help="Name the Elephant Agent elephant to delete."),
        delete_all: bool = typer.Option(False, "--all", help="Delete every elephant."),
    ) -> None:
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        try:
            raise typer.Exit(
                _run_herd(runtime, _namespace(herd_command="delete", elephant_id=elephant_id, delete_all=delete_all))
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error

    @facts_app.callback(invoke_without_command=True)
    def facts_callback(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            params = ctx.parent.params if ctx.parent is not None else ctx.params
            runtime = _cli_runtime(params["state_dir"])
            raise typer.Exit(_run_facts(runtime, _namespace(facts_command=None, elephant_id=None)))

    @facts_app.command("list")
    def facts_list_command(
        ctx: typer.Context,
        elephant_id: str | None = typer.Option(None, "--elephant-id", help="Resolve Personal Model facts through a named elephant."),
    ) -> None:
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_facts(runtime, _namespace(facts_command="list", elephant_id=elephant_id)))

    @facts_app.command("delete")
    def facts_delete_command(
        ctx: typer.Context,
        fact_id: str = typer.Argument(..., help="Name the Personal Model entry to retire."),
        elephant_id: str | None = typer.Option(None, "--elephant-id", help="Resolve Personal Model facts through a named elephant."),
        reason: str | None = typer.Option(None, "--reason", help="Record why this Personal Model entry is being retired."),
    ) -> None:
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        try:
            raise typer.Exit(
                _run_facts(
                    runtime,
                    _namespace(facts_command="delete", elephant_id=elephant_id, fact_id=fact_id, reason=reason),
                )
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error

    @reflect_app.callback(invoke_without_command=True)
    def reflect_callback(
        ctx: typer.Context,
        limit: int = typer.Option(12, "--limit", help="Number of recent reflect jobs to display."),
        elephant_id: str | None = typer.Option(None, "--elephant-id", help="Resolve status through a named elephant."),
    ) -> None:
        if ctx.invoked_subcommand is None:
            params = ctx.parent.params if ctx.parent is not None else ctx.params
            runtime = _cli_runtime(params["state_dir"])
            try:
                raise typer.Exit(_run_learn(runtime, _namespace(learn_command="list", elephant_id=elephant_id, limit=limit)))
            except ValueError as error:
                raise typer.BadParameter(str(error)) from error

    @reflect_app.command("list")
    def reflect_list_command(
        ctx: typer.Context,
        limit: int = typer.Option(12, "--limit", help="Number of recent reflect jobs to display."),
    ) -> None:
        """Show recent reflect job history."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_learn(runtime, _namespace(learn_command="list", elephant_id=None, limit=limit)))

    @reflect_app.command("run")
    def reflect_run_command(
        ctx: typer.Context,
        elephant_id: str | None = typer.Option(None, "--elephant-id", help="Run reflect for a named elephant."),
        trigger: str | None = typer.Option(None, "--trigger", help="Reflect trigger to use: manual, dream, diary, or skill_review."),
        features: str | None = typer.Option(None, "--features", help="Comma-separated feature set (pm,questions,dream,diary,skills,skill_optimization,recall,compress)."),
        date: str | None = typer.Option(None, "--date", help="Target date for dream/diary trigger or feature (YYYY-MM-DD). Defaults to today for dream and yesterday for diary."),
        wait: bool = typer.Option(False, "--wait", help="Wait for the reflect agent to finish."),
        install_cron: bool = typer.Option(False, "--install-cron", help="Install the built-in nightly Dream learning cron job."),
    ) -> None:
        """Run a reflect agent with the specified trigger and features."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])

        if install_cron:
            requested_features = set(f.strip() for f in (features or "").split(",") if f.strip())
            if not requested_features:
                _ensure_nightly_learning_crons(runtime)
                cron_label = "Nightly dream cron job installed."
            else:
                if "dream" not in requested_features:
                    raise typer.BadParameter("--install-cron only installs the dream feature; diary remains manual-only outside Dream")
                _ensure_dream_cron(runtime)
                cron_label = "Nightly dream cron job installed."
            _print_cli_card(
                "Elephant Agent learning cron",
                cron_label,
                next_commands=("elephant reflect run --features dream --date <YYYY-MM-DD>", "elephant reflect run --features diary --date <YYYY-MM-DD>", "elephant cron list"),
            )
            if not features:
                raise typer.Exit(0)

        try:
            resolved_trigger, extra_metadata = _resolve_reflect_run_request(
                trigger=trigger,
                features=features,
                date=date,
            )
            job = _queue_learning_job(
                runtime,
                elephant_id=elephant_id,
                trigger=resolved_trigger,
                summary=f"reflect run features={features or 'default'}",
                source="cli.reflect.run",
                force_new=True,
                start_worker=not wait,
                extra_metadata=extra_metadata or None,
            )
            worker_line = "queued and background worker requested"
            worker_exit_code = 0
            if wait:
                completed = subprocess.run(
                    (sys.executable, "-m", "apps.learning_worker_command", "--state-dir", str(runtime.paths.state_dir), "--once"),
                    check=False,
                )
                worker_exit_code = int(completed.returncode or 0)
                worker_line = f"worker once exit · {worker_exit_code}"
            _print_cli_card(
                "Elephant Agent reflect",
                f"Reflect agent {'completed' if wait else 'queued'}.",
                sections=(
                    CliCardSection("Job", (
                        f"job_id · {job.job_id}",
                        f"trigger · {resolved_trigger}",
                        f"features · {features or '(trigger default)'}",
                        f"status · {worker_line}",
                    )),
                ),
                next_commands=("elephant reflect list",),
            )
            raise typer.Exit(worker_exit_code)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error

    @reflect_app.command("kill")
    def reflect_kill_command(ctx: typer.Context) -> None:
        """Stop the background reflect worker."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_learn(runtime, _namespace(learn_command="kill", elephant_id=None, limit=12)))

    # ── Sandbox sub-commands ──────────────────────────────────────────
    _register_sandbox_commands(sandbox_app)

    return app


def build_sandbox_app() -> typer.Typer:
    """Build a standalone sandbox sub-app for use by the launcher."""
    app = typer.Typer(
        name="sandbox",
        help="Inspect, configure, or diagnose the sandbox isolation layer.",
        rich_markup_mode="rich",
        add_completion=False,
    )
    _register_sandbox_commands(app)
    return app


def _register_sandbox_commands(sandbox_app: typer.Typer) -> None:
    """Register sandbox sub-commands onto a Typer app."""

    @sandbox_app.callback(invoke_without_command=True)
    def sandbox_callback(ctx: typer.Context) -> None:
        """Show current sandbox configuration."""
        if ctx.invoked_subcommand is None:
            params = ctx.parent.params if ctx.parent is not None else ctx.params
            runtime = _cli_runtime(params["state_dir"])
            raise typer.Exit(_run_sandbox_status(runtime))

    @sandbox_app.command("status")
    def sandbox_status_command(ctx: typer.Context) -> None:
        """Show current sandbox configuration and backend health."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_sandbox_status(runtime))

    @sandbox_app.command("configure")
    def sandbox_configure_command(
        ctx: typer.Context,
        mode: str | None = typer.Option(None, "--mode", help="Sandbox mode: off, all, non-main."),
        backend: str | None = typer.Option(None, "--backend", help="Sandbox backend: local, docker, ssh, seatbelt, cloud."),
        docker_image: str | None = typer.Option(None, "--docker-image", help="Docker image name for docker backend."),
        ssh_host: str | None = typer.Option(None, "--ssh-host", help="SSH host for ssh backend."),
        ssh_port: int | None = typer.Option(None, "--ssh-port", help="SSH port for ssh backend."),
        ssh_user: str | None = typer.Option(None, "--ssh-user", help="SSH user for ssh backend."),
        ssh_identity_file: str | None = typer.Option(None, "--ssh-identity-file", help="SSH identity file for ssh backend."),
        cloud_provider: str | None = typer.Option(None, "--cloud-provider", help="Cloud provider name (e.g. tencent, e2b)."),
        cloud_profile: str | None = typer.Option(None, "--cloud-profile", help="Named cloud profile to activate (from clouds config)."),
        cloud_template: str | None = typer.Option(None, "--cloud-template", help="Cloud sandbox template ID."),
        cloud_domain: str | None = typer.Option(None, "--cloud-domain", help="Cloud sandbox API domain."),
        cloud_api_key: str | None = typer.Option(None, "--cloud-api-key", help="Cloud sandbox API key."),
        cloud_timeout: int | None = typer.Option(None, "--cloud-timeout", help="Cloud sandbox timeout in seconds."),
    ) -> None:
        """Configure sandbox mode, backend, and backend-specific options."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_sandbox_configure(
            runtime,
            mode=mode,
            backend=backend,
            docker_image=docker_image,
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_identity_file=ssh_identity_file,
            cloud_provider=cloud_provider,
            cloud_profile=cloud_profile,
            cloud_template=cloud_template,
            cloud_domain=cloud_domain,
            cloud_api_key=cloud_api_key,
            cloud_timeout=cloud_timeout,
        ))

    @sandbox_app.command("doctor")
    def sandbox_doctor_command(ctx: typer.Context) -> None:
        """Run sandbox health diagnostics."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_sandbox_doctor(runtime))

    @sandbox_app.command("verify")
    def sandbox_verify_command(ctx: typer.Context) -> None:
        """Run live policy probes to verify sandbox enforcement."""
        params = ctx.parent.parent.params if ctx.parent and ctx.parent.parent else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        raise typer.Exit(_run_sandbox_verify(runtime))


def main(argv: list[str] | None = None) -> int:
    from .typer_support import run_typer_app

    resolved_argv = list(sys.argv[1:] if argv is None else argv)
    if resolved_argv and resolved_argv[0] in {"--help", "-h"}:
        _print_root_cli_help()
        return 0
    return run_typer_app(build_typer_app(), resolved_argv, prog_name="elephant")
