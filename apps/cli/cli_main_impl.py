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

    app.add_typer(provider_app, name="provider")
    app.add_typer(herd_app, name="herd")
    app.add_typer(facts_app, name="facts")
    app.add_typer(reflect_app, name="reflect")
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
        preset: str | None = typer.Option(None, "--preset", help="User-facing job preset: memory, skill-affinity, skill-evolution, dream, diary, letter."),
        trigger: str | None = typer.Option(None, "--trigger", help="Reflect trigger to use. Common values: manual, dream, diary, skill_review."),
        features: str | None = typer.Option(None, "--features", help="Comma-separated feature set: pm, questions, dream, diary, skill_affinity, skill_evolution, compress. Legacy skills/skill_optimization aliases still work."),
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
                preset=preset,
                trigger=trigger,
                features=features,
                date=date,
            )
            summary_label = f"preset={preset.strip()}" if preset and preset.strip() else f"features={features or 'default'}"
            job = _queue_learning_job(
                runtime,
                elephant_id=elephant_id,
                trigger=resolved_trigger,
                summary=f"reflect run {summary_label}",
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
                        *( (f"preset · {preset.strip()}",) if preset and preset.strip() else () ),
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

    return app


def main(argv: list[str] | None = None) -> int:
    from .typer_support import run_typer_app

    resolved_argv = list(sys.argv[1:] if argv is None else argv)
    if resolved_argv and resolved_argv[0] in {"--help", "-h"}:
        _print_root_cli_help()
        return 0
    return run_typer_app(build_typer_app(), resolved_argv, prog_name="elephant")
