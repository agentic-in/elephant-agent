"""Shared launcher for editable installs and checkout-backed wrappers."""

from __future__ import annotations

from pathlib import Path
import sys

import typer

from apps.runtime_layout import default_cli_state_dir

from .cli.shell import Align, BRAND_ACCENT, BRAND_LIGHT, BRAND_MUTED, Console, Group, Panel, RICH_AVAILABLE, Text, _resolve_elephant_version
from .cli.typer_support import run_typer_app
from .cli.cli_main_support import CLI_COMMAND_HELP, CLI_HELP_COMMANDS, CLI_HELP_NEXT_COMMANDS, CLI_HELP_TAGLINE, _print_cli_help, _render_cli_banner_mark

LAUNCHER_COMMAND_HELP = {
    **CLI_COMMAND_HELP,
    "upgrade": "Gracefully upgrade Elephant Agent, preserving state and restarting managed runtimes.",
}
LAUNCHER_HELP_COMMANDS = (*CLI_HELP_COMMANDS, ("upgrade", LAUNCHER_COMMAND_HELP["upgrade"]))


def _ensure_config_yaml(state_dir: Path) -> None:
    """Ensure config.yaml exists so the configuration is visible."""
    from packages.runtime_config import default_global_config, write_global_config, global_config_path_for_state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = global_config_path_for_state_dir(state_dir)
    if not config_path.exists():
        write_global_config(
            config_path,
            default_global_config(state_dir=state_dir),
        )


def _show_launcher_banner() -> None:
    if RICH_AVAILABLE and Panel is not None and Console is not None and Group is not None:
        console = Console(highlight=False, soft_wrap=True)
        header = Text()
        header.append("🥚  Elephant Agent\n", style=f"bold {BRAND_LIGHT}")
        header.append("Personal-model-first AI, with curiosity built in.\n", style=BRAND_MUTED)
        header.append(f"🐣  v{_resolve_elephant_version()} · understands first, gets curious at your pace.", style=BRAND_ACCENT)
        commands = Text()
        commands.append("Start here\n", style=f"bold {BRAND_ACCENT}")
        commands.append("🐣 elephant init\n", style=f"bold {BRAND_LIGHT}")
        commands.append("📋 elephant status\n", style=f"bold {BRAND_LIGHT}")
        commands.append("🌙 elephant wake\n", style=f"bold {BRAND_LIGHT}")
        commands.append("📚 elephant skills\n", style=f"bold {BRAND_LIGHT}")
        console.print(
            Panel(
                Group(
                    header,
                    Text(" "),
                    Align.center(_render_cli_banner_mark()),
                    Text(" "),
                    commands,
                ),
                border_style=BRAND_ACCENT,
                title=f"[bold {BRAND_ACCENT}]🐘 Welcome[/bold {BRAND_ACCENT}]",
                subtitle=f"[bold {BRAND_LIGHT}]warm memory, curiosity at your pace[/bold {BRAND_LIGHT}]",
                padding=(0, 1),
            )
        )
        return
    print("🐘 Elephant Agent · warm memory, personal-model-first AI.")


def _print_launcher_help() -> None:
    _print_cli_help(
        "Elephant Agent launcher",
        "Warm, steady ways back to the elephant that remembers your path.",
        commands=LAUNCHER_HELP_COMMANDS,
        next_commands=("elephant", *CLI_HELP_NEXT_COMMANDS, "elephant upgrade"),
        tagline=CLI_HELP_TAGLINE,
    )


def _forward_cli(
    argv: list[str],
    *,
    state_dir: Path,
) -> int:
    from apps.cli.__main__ import main as cli_main

    forwarded = [
        "--state-dir",
        str(state_dir),
        *argv,
    ]
    return cli_main(forwarded)


def build_typer_app() -> typer.Typer:
    app = typer.Typer(
        name="elephant",
        help=(
            "Elephant Agent launcher with explicit init, wake, dashboard, herd, provider, eval, facts, learn, skills, gateway, cron, and status entrypoints."
        ),
        no_args_is_help=False,
        rich_markup_mode="rich",
        add_completion=False,
    )

    @app.callback(invoke_without_command=True)
    def launcher_callback(ctx: typer.Context) -> None:
        state_dir = default_cli_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        _ensure_config_yaml(state_dir)
        if ctx.resilient_parsing:
            _print_launcher_help()
            raise typer.Exit(0)
        if ctx.invoked_subcommand is None:
            raise typer.Exit(_forward_cli([], state_dir=state_dir))
        ctx.obj = {
            "state_dir": state_dir,
        }

    passthrough_settings = {"allow_extra_args": True, "ignore_unknown_options": True}

    @app.command("init", help=CLI_COMMAND_HELP["init"], context_settings=passthrough_settings)
    def init_command(ctx: typer.Context) -> None:
        obj = ctx.obj or {}
        raise typer.Exit(_forward_cli(["init", *ctx.args], state_dir=obj["state_dir"]))

    @app.command("status", help=CLI_COMMAND_HELP["status"], context_settings=passthrough_settings)
    def status_command(
        ctx: typer.Context,
        deep: bool = typer.Option(False, "--deep", help="Run live provider catalog and runtime probe checks."),
    ) -> None:
        obj = ctx.obj or {}
        deep_args = ["--deep"] if deep else []
        raise typer.Exit(_forward_cli(["status", *deep_args, *ctx.args], state_dir=obj["state_dir"]))

    @app.command("wake", help=CLI_COMMAND_HELP["wake"], context_settings=passthrough_settings)
    def wake_command(ctx: typer.Context) -> None:
        obj = ctx.obj or {}
        raise typer.Exit(_forward_cli(["wake", *ctx.args], state_dir=obj["state_dir"]))

    @app.command("skills", help=CLI_COMMAND_HELP["skills"], context_settings=passthrough_settings)
    def skills_command(ctx: typer.Context) -> None:
        from apps.cli.skills_command import command_main as skills_command_main

        obj = ctx.obj or {}
        raise typer.Exit(
            skills_command_main(
                list(ctx.args),
                default_state_dir=obj["state_dir"],
            )
        )

    @app.command("gateway", help=CLI_COMMAND_HELP["gateway"], context_settings=passthrough_settings)
    def gateway_command(ctx: typer.Context) -> None:
        from apps.gateway.__main__ import command_main as gateway_command_main

        obj = ctx.obj or {}
        raise typer.Exit(
            gateway_command_main(
                list(ctx.args),
                default_state_dir=obj["state_dir"],
                default_control_state_dir=obj["state_dir"],
            )
        )

    @app.command("cron", help=CLI_COMMAND_HELP["cron"], context_settings=passthrough_settings)
    def cron_command(ctx: typer.Context) -> None:
        from apps.cron_scheduler_command import command_main as cron_scheduler_command_main

        obj = ctx.obj or {}
        raise typer.Exit(
            cron_scheduler_command_main(
                list(ctx.args),
                default_state_dir=obj["state_dir"],
                default_control_state_dir=obj["state_dir"],
            )
        )

    @app.command("upgrade", help=LAUNCHER_COMMAND_HELP["upgrade"], context_settings=passthrough_settings)
    def upgrade_command(ctx: typer.Context) -> None:
        from apps.upgrade_command import command_main as upgrade_command_main

        obj = ctx.obj or {}
        raise typer.Exit(
            upgrade_command_main(
                [
                    "--state-dir",
                    str(obj["state_dir"]),
                    "--gateway-state-dir",
                    str(obj["gateway_state_dir"]),
                    *ctx.args,
                ]
            )
        )

    @app.command(
        "supervisor",
        help="Long-horizon harness supervisor (crash scan + timer wake).",
        context_settings=passthrough_settings,
    )
    def supervisor_command(ctx: typer.Context) -> None:
        from apps.supervisor_command import command_main as supervisor_command_main

        obj = ctx.obj or {}
        raise typer.Exit(
            supervisor_command_main(
                list(ctx.args),
                default_state_dir=obj["state_dir"],
            )
        )

    @app.command("dashboard", help=CLI_COMMAND_HELP["dashboard"], context_settings=passthrough_settings)
    def dashboard_command(ctx: typer.Context) -> None:
        from apps.dashboard_command import command_main as dashboard_command_main

        obj = ctx.obj or {}
        raise typer.Exit(
            dashboard_command_main(
                list(ctx.args),
                default_state_dir=obj["state_dir"],
            )
        )

    @app.command("provider", help=CLI_COMMAND_HELP["provider"], context_settings=passthrough_settings)
    def provider_passthrough(ctx: typer.Context) -> None:
        obj = ctx.obj or {}
        raise typer.Exit(_forward_cli(["provider", *ctx.args], state_dir=obj["state_dir"]))

    @app.command("eval", help=CLI_COMMAND_HELP["eval"], context_settings=passthrough_settings)
    def eval_passthrough(
        ctx: typer.Context,
        dataset: str = typer.Option("locomo_refined", "--dataset", help="Dataset adapter: locomo or locomo_refined."),
        dataset_path: Path | None = typer.Option(None, "--dataset-path", help="Path to LoCoMo file or LoCoMo-Refined public directory."),
        output_dir: Path | None = typer.Option(None, "--output-dir", help="Directory for report.json, report.md, predictions, and traces."),
        top_k: int = typer.Option(5, "--top-k", help="Number of retrieved evidence hits per question."),
        retrieval_mode: str = typer.Option(
            "hybrid",
            "--retrieval-mode",
            help=(
                "Memory retrieval mode: hybrid, semantic_raw_dialog, semantic_session_summary, "
                "semantic_observation, semantic_combined, full_context, oracle_evidence, "
                "hybrid_query_fusion, hybrid_observation, hybrid_multilayer, "
                "or hybrid_multilayer_query_fusion."
            ),
        ),
        limit_conversations: int | None = typer.Option(None, "--limit-conversations", help="Optional conversation cap for smoke runs."),
        limit_questions: int | None = typer.Option(None, "--limit-questions", help="Optional question cap for smoke runs."),
        model_role: str = typer.Option("strong", "--model-role", help="Configured model role to use for answer generation."),
        answer_concurrency: int = typer.Option(1, "--answer-concurrency", help="Concurrent model answer calls per conversation."),
        answer_batch_size: int = typer.Option(1, "--answer-batch-size", help="Questions per model answer request."),
        start_conversation: int = typer.Option(1, "--start-conversation", help="1-based first conversation index to evaluate."),
        end_conversation: int | None = typer.Option(None, "--end-conversation", help="1-based inclusive last conversation index to evaluate."),
    ) -> None:
        obj = ctx.obj or {}
        forwarded = [
            "eval",
            "--dataset",
            dataset,
            "--top-k",
            str(top_k),
            "--retrieval-mode",
            retrieval_mode,
            "--model-role",
            model_role,
            "--answer-concurrency",
            str(answer_concurrency),
            "--answer-batch-size",
            str(answer_batch_size),
            "--start-conversation",
            str(start_conversation),
        ]
        if end_conversation is not None:
            forwarded.extend(("--end-conversation", str(end_conversation)))
        if dataset_path is not None:
            forwarded.extend(("--dataset-path", str(dataset_path)))
        if output_dir is not None:
            forwarded.extend(("--output-dir", str(output_dir)))
        if limit_conversations is not None:
            forwarded.extend(("--limit-conversations", str(limit_conversations)))
        if limit_questions is not None:
            forwarded.extend(("--limit-questions", str(limit_questions)))
        forwarded.extend(ctx.args)
        raise typer.Exit(_forward_cli(forwarded, state_dir=obj["state_dir"]))

    @app.command("herd", help=CLI_COMMAND_HELP["herd"], context_settings=passthrough_settings)
    def herd_passthrough(ctx: typer.Context) -> None:
        obj = ctx.obj or {}
        raise typer.Exit(_forward_cli(["herd", *ctx.args], state_dir=obj["state_dir"]))

    @app.command("facts", help=CLI_COMMAND_HELP["facts"], context_settings=passthrough_settings)
    def facts_passthrough(ctx: typer.Context) -> None:
        obj = ctx.obj or {}
        raise typer.Exit(_forward_cli(["facts", *ctx.args], state_dir=obj["state_dir"]))

    @app.command("reflect", help=CLI_COMMAND_HELP["reflect"], context_settings=passthrough_settings)
    def reflect_passthrough(ctx: typer.Context) -> None:
        obj = ctx.obj or {}
        raise typer.Exit(_forward_cli(["reflect", *ctx.args], state_dir=obj["state_dir"]))

    return app


def main(argv: list[str] | None = None) -> int:
    resolved_argv = list(sys.argv[1:] if argv is None else argv)
    if resolved_argv and resolved_argv[0] in {"--help", "-h"}:
        _print_launcher_help()
        return 0
    return run_typer_app(build_typer_app(), resolved_argv, prog_name="elephant")


if __name__ == "__main__":
    raise SystemExit(main())
