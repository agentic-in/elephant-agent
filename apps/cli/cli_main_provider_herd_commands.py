"""Provider, init, and herd command runners for the CLI."""

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

DEFAULT_PROVIDER_ID = "openai-compatible"
CLI_THEME_TITLE_GLYPH = "🐘"
CLI_THEME_BULLET = "•"
CLI_THEME_WELCOME_GLYPH = "🐘"
CLI_THEME_SUBTITLE = "Personal Model first, curious at your pace."


from .cli_main_init_prompts import *  # noqa: F401,F403
from .cli_main_init_runtime import *  # noqa: F401,F403


LOGGER = logging.getLogger(__name__)


def _run_setup(runtime: CliRuntime, args: argparse.Namespace) -> int:
    provider_id = args.provider_id
    loaded = runtime.current_profile()
    provider_state = provider_setup_defaults(runtime, provider_id)
    initial_elephant_name = args.elephant_name
    if args.display_name is not None:
        display_name = args.display_name
    elif initial_elephant_name:
        display_name = _display_name_from_elephant_name(initial_elephant_name)
    else:
        display_name = "Mother Elephant"
        initial_elephant_name = "mother-elephant"
    mode = "companion"
    personality_preset = _default_personality_preset(
        runtime,
        mode=mode,
        current=(loaded.companion.personality_preset if loaded.companion is not None else None),
    ) or "companion"
    initiative = loaded.companion.initiative if loaded.companion is not None else "gentle"
    requested_elephant_identity_text = getattr(args, "elephant_identity_text", None)
    secret_env_var = getattr(args, "secret_env_var", None)
    embedding_provider = str(getattr(args, "embedding_provider", None) or "local").strip() or "local"
    embedding_source = str(getattr(args, "embedding_source", None) or "huggingface").strip() or "huggingface"
    embedding_base_url = str(getattr(args, "embedding_base_url", None) or "").strip()
    embedding_model = str(getattr(args, "embedding_model", None) or "").strip()
    embedding_dimensions = None
    if getattr(args, "embedding_dimensions", None) is not None:
        embedding_dimensions = int(str(args.embedding_dimensions).replace(",", ""))
    embedding_api_key = getattr(args, "embedding_api_key", None)
    embedding_secret_env_var = getattr(args, "embedding_secret_env_var", None)
    if embedding_api_key is None and embedding_secret_env_var:
        embedding_api_key = str(os.environ.get(embedding_secret_env_var) or "").strip() or None
    provider_state.base_url = args.base_url or provider_state.base_url
    provider_state.model_id = args.model_id or provider_state.model_id
    provider_state.api_key = args.api_key
    if provider_state.api_key is None and secret_env_var:
        provider_state.api_key = str(os.environ.get(secret_env_var) or "").strip() or None
    if args.context_window_mode is not None:
        provider_state.context_window_mode = args.context_window_mode
    if args.context_window is not None:
        provider_state.context_window_tokens = int(str(args.context_window).replace(",", ""))
    first_language = _normalize_first_language(getattr(args, "first_language", "en"))
    requested_learning_intensity = str(getattr(args, "learning_intensity", None) or "medium").strip().lower()
    if requested_learning_intensity not in {"low", "medium", "high"}:
        requested_learning_intensity = "medium"

    interactive_birth = _interactive_shell_supported() and not args.non_interactive
    wizard_state = None
    if interactive_birth:
        _print_birth_wizard_intro()
        wizard_state = _run_interactive_birth_wizard(
            runtime,
            display_name=display_name,
            provider_state=provider_state,
            first_language=first_language,
        )
        if wizard_state is None:
            _print_birth_paused()
            return 0
        _print_init_section(
            wizard_state.first_language,
            "Building the first model",
            "正在整理第一层地基",
            "Saving your anchors, writing the first Personal Model facts, doing a quick provider and embedding readiness check, then opening the TUI.",
            "正在保存你的锚点、写入第一层 Personal Model、快速检查模型配置与记忆状态，然后打开 TUI。",
        )
        display_name = wizard_state.display_name
        first_language = wizard_state.first_language
        embedding_provider = wizard_state.embedding_provider
        embedding_source = wizard_state.embedding_source
        embedding_base_url = wizard_state.embedding_base_url
        embedding_model = wizard_state.embedding_model
        embedding_dimensions = wizard_state.embedding_dimensions
        embedding_api_key = wizard_state.embedding_api_key
        provider_id = wizard_state.provider_id
        provider_state = ProviderSelectionState(
            provider_id=wizard_state.provider_id,
            base_url=wizard_state.base_url,
            api_key=wizard_state.api_key,
            model_id=wizard_state.model_id,
            reasoning_effort=wizard_state.reasoning_effort,
            context_window_mode=wizard_state.context_window_mode,
            context_window_tokens=wizard_state.context_window_tokens,
        )
    else:
        _print_setup_intro(runtime, provider_id=provider_id)

    bootstrap_state = wizard_state or SimpleNamespace(
        first_language=first_language,
        learning_intensity=requested_learning_intensity,
        preferred_name=str(getattr(args, "preferred_name", None) or "").strip(),
        age=str(getattr(args, "age", None) or "").strip(),
        birth_date=str(getattr(args, "birth_date", None) or "").strip(),
        gender=str(getattr(args, "gender", None) or "").strip(),
        occupation=str(getattr(args, "occupation", None) or "").strip(),
        city=str(getattr(args, "city", None) or "").strip(),
        mbti=str(getattr(args, "mbti", None) or "").strip(),
        hobbies=str(getattr(args, "hobbies", None) or "").strip(),
        relationship_mode=str(getattr(args, "relationship_mode", None) or "").strip(),
        astrology=str(getattr(args, "astrology", None) or "").strip(),
        safety_boundaries=str(getattr(args, "safety_boundaries", None) or "").strip(),
        communication_preference=str(getattr(args, "communication_preference", None) or "").strip(),
        starter_answers=(),
    )

    base_url = provider_state.base_url
    model_id = provider_state.model_id
    api_key = provider_state.api_key
    reasoning_effort = provider_state.reasoning_effort
    context_window_mode = provider_state.context_window_mode or "auto"
    context_window_tokens = provider_state.context_window_tokens

    if not base_url or not model_id:
        raise SystemExit("init requires a provider base URL plus one dialogue model id")
    if context_window_tokens is None and model_id:
        context_window_tokens = runtime.detect_provider_context_window(
            provider_id=provider_id,
            model_id=model_id,
            base_url=base_url,
            api_key=api_key,
        )
    if context_window_tokens is None:
        context_window_tokens = 256_000
    guide = runtime.provider_setup_guide(provider_id)
    if (
        guide.auth_type == "api_key"
        and guide.required_secret_keys
        and not api_key
        and not _provider_secret_ready(runtime, provider_id=provider_id)
    ):
        raise SystemExit("init requires a provider key for API-key providers; rerun interactively or pass --api-key")

    updated_identity = runtime.update_identity(
        display_name=display_name,
        mode=mode,
    )
    updated_identity = runtime.update_companion_settings(
        profile_id=updated_identity.state.profile_id,
        initiative=initiative,
        personality_preset=personality_preset,
    )
    elephant_identity_text = (
        requested_elephant_identity_text.strip()
        if requested_elephant_identity_text is not None and requested_elephant_identity_text.strip()
        else render_default_elephant_identity(
            display_name=updated_identity.state.display_name
        )
    )
    runtime.update_identity_state(
        profile_id=updated_identity.state.profile_id,
        elephant_identity_text=(elephant_identity_text or DEFAULT_ELEPHANT_IDENTITY_TEXT).strip(),
    )

    configured = runtime.set_default_provider(
        provider_id=provider_id,
        profile_id=updated_identity.state.profile_id,
        display_name=updated_identity.state.display_name,
        mode=updated_identity.state.mode,
        base_url=base_url,
        model_id=model_id,
        api_key=api_key,
        secret_env_var=secret_env_var,
        context_window_tokens=context_window_tokens,
        context_window_mode=context_window_mode,
        reasoning_effort=reasoning_effort,
    )
    # Persist the chosen Personal Model question cadence.
    learning_intensity = str(getattr(bootstrap_state, "learning_intensity", None) or "medium").strip().lower()
    if learning_intensity not in {"low", "medium", "high"}:
        learning_intensity = "medium"
    _persist_init_question_config(runtime, first_language=first_language, learning_intensity=learning_intensity)
    try:
        profile_state = runtime.repository.load_personal_model_runtime_state(configured.state.profile_id)
        if profile_state is not None:
            from dataclasses import replace as _dc_replace
            runtime.repository.upsert_personal_model_runtime_state(
                _dc_replace(profile_state, learning_intensity=learning_intensity)
            )
    except Exception:  # pragma: no cover — never block init on PM persistence
        LOGGER.warning("failed to persist init learning intensity for configured profile", exc_info=True)
        pass
    if embedding_provider == "local":
        embedding_summary = _mapping_or_empty(runtime.set_local_embedding_provider(source=embedding_source))
    else:
        if not embedding_base_url or not embedding_model or embedding_dimensions is None:
            raise SystemExit(
                "init embedding provider requires --embedding-base-url, --embedding-model, and --embedding-dimensions"
            )
        embedding_summary = _mapping_or_empty(
            runtime.set_openai_compatible_embedding_provider(
                base_url=embedding_base_url,
                model_id=embedding_model,
                dimensions=embedding_dimensions,
                api_key=embedding_api_key,
                secret_env_var=embedding_secret_env_var,
            )
        )

    # Interactive init is about to hand off to the chat TUI; avoid the deep
    # doctor here because it performs live model catalog discovery plus an LLM
    # probe. The TUI's first real turn will surface provider failures with the
    # normal turn error path, while this handoff only needs configured+secret
    # readiness.
    report = runtime.provider_doctor(deep=not interactive_birth)
    provider = report["provider"]
    elephant_name = _unique_elephant_name(runtime, initial_elephant_name or display_name)
    first_elephant, first_elephant_status = _ensure_elephant_ready(
        runtime,
        elephant_name=elephant_name,
        display_name=display_name,
        profile_id=configured.state.profile_id,
    )
    try:
        state = runtime.repository.load_state(first_elephant.state_id)
        if state is not None:
            from dataclasses import replace as _dc_replace

            runtime.repository.upsert_state(
                _dc_replace(
                    state,
                    metadata={
                        **dict(getattr(state, "metadata", {}) or {}),
                        "profile_id": state.personal_model_id,
                        "herd_kind": "mother",
                        "role_title": "Mother Elephant",
                        "role_prompt": "Coordinate work, maintain Personal Model continuity, discover baby elephants, and delegate bounded tasks through the Herd.",
                        "enabled": "true",
                    },
                )
            )
    except Exception:
        LOGGER.warning("failed to persist mother elephant metadata during setup", exc_info=True)
        pass
    try:
        from packages.operator.local_agents import scan_local_agents

        upsert = getattr(runtime.repository, "upsert_local_agent_runtimes", None)
        if callable(upsert):
            upsert(scan_local_agents())
    except Exception:
        LOGGER.warning("failed to scan local agent runtimes during setup", exc_info=True)
        pass
    try:
        from dataclasses import replace as _dc_replace
        profile_state = runtime.repository.load_personal_model_runtime_state(first_elephant.personal_model_id)
        if profile_state is not None:
            runtime.repository.upsert_personal_model_runtime_state(
                _dc_replace(profile_state, learning_intensity=learning_intensity)
            )
    except Exception:
        LOGGER.warning("failed to persist init learning intensity for first elephant profile", exc_info=True)
        pass
    _bootstrap_personal_model_from_init(runtime, first_elephant, bootstrap_state)
    if first_elephant_status == "created":
        _play_creating_transition("Elephant Agent init", f"{display_name} is becoming a continuing personal AI thread.")
    readiness_lines = [
        f"elephant · {runtime.elephant_id_for_session(first_elephant)}",
        f"status · {first_elephant_status}",
        f"provider · {provider['display_name'] if 'display_name' in provider else provider['provider_id']}",
        f"model · {provider.get('model_id') or provider.get('default_model') or '<unset>'}",
        f"embedding · {embedding_summary.get('source') or '<unset>'} / {embedding_summary.get('model_id') or '<unset>'}",
        *_embedding_bootstrap_status_lines(embedding_summary),
        f"context · {provider.get('context_window_tokens') or '<unset>'}",
        f"status · {report['status']}",
    ]
    birth_sections = [CliCardSection("Ready now", tuple(readiness_lines))]
    embedding_notice_lines = _embedding_bootstrap_notice_lines(embedding_summary)
    if embedding_notice_lines:
        birth_sections.append(CliCardSection("Background bootstrap", embedding_notice_lines))
    if report["status"] == "ready":
        birth_sections.append(
            CliCardSection(
                "Beyond local CLI",
                _gateway_birth_lines(elephant_name),
            )
        )
    if interactive_birth and report["status"] == "ready":
        _prompt_im_onboarding(runtime, elephant_name=elephant_name)
        return ProductizedShell(runtime, session_id=first_elephant.episode_id, opened="Born new").run()
    _print_cli_card(
        "Your Elephant Agent has shaped",
        f"{display_name} is awake and ready to stay with you.",
        sections=tuple(birth_sections),
        next_commands=("elephant wake", "elephant herd new <name>", "elephant herd")
        if report["status"] == "ready"
        else ("elephant status", "elephant init"),
    )
    return 0

def _run_brain(runtime: CliRuntime, args: argparse.Namespace) -> int:
    action = str(getattr(args, "provider_command", "configure") or "configure")
    if action == "status":
        _print_brain_status(runtime)
        return 0
    if action == "embeddings":
        return _run_embedding_provider(runtime, args)
    if action == "providers":
        _print_brain_provider_inventory(runtime)
        return 0
    if action == "models":
        provider = dict(runtime.provider_summary())
        provider_id = str(args.provider_id or provider.get("provider_id") or DEFAULT_PROVIDER_ID)
        _print_brain_models(runtime, provider_id=provider_id)
        return 0

    profile = runtime.current_profile()
    provider = dict(runtime.provider_summary())
    provider_id = str(args.provider_id or provider.get("provider_id") or DEFAULT_PROVIDER_ID)
    initial_state = provider_setup_defaults(runtime, provider_id)
    initial_state.base_url = str(args.base_url or provider.get("base_url") or initial_state.base_url)
    initial_state.model_id = str(
        args.model_id or provider.get("model_id") or provider.get("default_model") or initial_state.model_id
    )
    initial_state.api_key = args.api_key
    initial_state.reasoning_effort = (
        str(getattr(args, "reasoning_effort", None) or provider.get("reasoning_effort") or initial_state.reasoning_effort).strip() or None
    )
    if args.context_window_mode is not None:
        initial_state.context_window_mode = args.context_window_mode
    elif provider.get("context_window_mode") is not None:
        initial_state.context_window_mode = str(provider.get("context_window_mode"))
    if args.context_window is not None:
        initial_state.context_window_tokens = int(str(args.context_window).replace(",", ""))
    elif provider.get("context_window_tokens") is not None:
        try:
            initial_state.context_window_tokens = int(provider["context_window_tokens"])
        except (TypeError, ValueError):
            pass

    configured = initial_state
    if _interactive_shell_supported() and not args.non_interactive:
        answer = run_provider_selection_wizard(
            runtime,
            initial_state=initial_state,
            allow_back=True,
        )
        if answer is WIZARD_BACK or answer is WIZARD_CANCEL:
            _print_cli_card(
                "Provider unchanged",
                "No provider or model changes were written.",
                next_commands=("elephant provider", "elephant provider status"),
            )
            return 0
        configured = answer

    guide = runtime.provider_setup_guide(configured.provider_id)
    if (
        guide.auth_type == "api_key"
        and guide.required_secret_keys
        and not configured.api_key
        and not _provider_secret_ready(runtime, provider_id=configured.provider_id)
    ):
        raise SystemExit("provider requires a provider key for API-key providers; rerun interactively or pass --api-key")

    context_window_tokens = configured.context_window_tokens
    if context_window_tokens is None and configured.model_id:
        context_window_tokens = runtime.detect_provider_context_window(
            provider_id=configured.provider_id,
            model_id=configured.model_id,
            base_url=configured.base_url,
            api_key=configured.api_key,
        )

    runtime.set_default_provider(
        provider_id=configured.provider_id,
        profile_id=profile.state.profile_id,
        display_name=profile.state.display_name,
        mode=profile.state.mode,
        base_url=configured.base_url,
        model_id=configured.model_id,
        api_key=configured.api_key,
        context_window_tokens=context_window_tokens,
        context_window_mode=configured.context_window_mode,
        reasoning_effort=configured.reasoning_effort,
    )
    _print_cli_card(
        "Provider updated",
        "Elephant Agent will use the new provider and model posture on the next turn.",
        sections=(
            CliCardSection(
                "Saved",
                (
                    f"provider_id · {configured.provider_id}",
                    f"base_url · {configured.base_url}",
                    f"model · {configured.model_id}",
                    f"context_window_tokens · {context_window_tokens or '<unset>'}",
                    f"context_window_mode · {configured.context_window_mode}",
                    f"reasoning_effort · {configured.reasoning_effort or '<unset>'}",
                ),
            ),
        ),
        next_commands=("elephant provider status", "elephant wake"),
    )
    return 0


def _run_embedding_setup_wizard(runtime: CliRuntime) -> int:
    """Run the interactive embedding provider selection wizard standalone."""
    # Detect user's first language from global config.
    language = "en"
    try:
        from packages.runtime_config import global_config_path_for_state_dir, load_global_config

        config_path = global_config_path_for_state_dir(runtime.paths.state_dir)
        config = load_global_config(config_path, state_dir=runtime.paths.state_dir)
        language = str(dict(config.get("personal_model") or {}).get("first_language") or "en").strip() or "en"
    except Exception:
        LOGGER.warning("failed to load first language for embedding setup wizard", exc_info=True)
        pass
    answer = _run_embedding_birth_wizard(
        default_provider="local",
        default_source="huggingface",
        default_base_url="",
        default_model="",
        default_dimensions=None,
        language=language,
    )
    if answer is WIZARD_BACK:
        return 0
    provider, source, base_url, model, dimensions, api_key = answer
    if provider == "local":
        embedding = dict(runtime.set_local_embedding_provider(source=source))
        sections = [
            CliCardSection(
                "Saved",
                (
                    f"source · {embedding.get('source') or '<unset>'}",
                    f"provider_id · {embedding.get('provider_id') or '<unset>'}",
                    f"model_id · {embedding.get('model_id') or '<unset>'}",
                    f"dimensions · {embedding.get('dimensions') or '<unset>'}",
                    f"download_source · {source}",
                    *_embedding_bootstrap_status_lines(embedding),
                ),
            ),
        ]
        embedding_notice_lines = _embedding_bootstrap_notice_lines(embedding)
        if embedding_notice_lines:
            sections.append(CliCardSection("Background bootstrap", embedding_notice_lines))
        _print_cli_card(
            "Embedding provider updated",
            "Elephant Agent will use the local embedding model for semantic retrieval.",
            sections=tuple(sections),
            next_commands=("elephant provider embeddings status", "elephant provider status"),
        )
    else:
        if not base_url or not model or dimensions is None:
            raise SystemExit("embedding provider requires base_url, model, and dimensions")
        embedding = dict(
            runtime.set_openai_compatible_embedding_provider(
                base_url=base_url,
                model_id=model,
                dimensions=dimensions,
                api_key=api_key,
            )
        )
        _print_cli_card(
            "Embedding provider updated",
            "Elephant Agent will use the configured OpenAI-compatible embedding provider for semantic retrieval.",
            sections=(
                CliCardSection(
                    "Saved",
                    (
                        f"source · {embedding.get('source') or '<unset>'}",
                        f"provider_id · {embedding.get('provider_id') or '<unset>'}",
                        f"model_id · {embedding.get('model_id') or '<unset>'}",
                        f"dimensions · {embedding.get('dimensions') or '<unset>'}",
                        f"base_url · {embedding.get('base_url') or '<unset>'}",
                        f"secret_status · {embedding.get('secret_status') or '<unset>'}",
                    ),
                ),
            ),
            next_commands=("elephant provider embeddings status", "elephant provider status"),
        )
    return 0


def _run_embedding_provider(runtime: CliRuntime, args: argparse.Namespace) -> int:
    action = str(getattr(args, "embedding_command", None) or "status").strip().lower()
    if action == "status":
        _print_embedding_provider_status(runtime)
        return 0
    if action == "setup":
        return _run_embedding_setup_wizard(runtime)
    if action == "local":
        source = str(getattr(args, "embedding_source", None) or "huggingface").strip().lower()
        if source not in {"huggingface", "modelscope"}:
            source = "huggingface"
        embedding = dict(runtime.set_local_embedding_provider(source=source))
        sections = [
            CliCardSection(
                "Saved",
                (
                    f"source · {embedding.get('source') or '<unset>'}",
                    f"provider_id · {embedding.get('provider_id') or '<unset>'}",
                    f"model_id · {embedding.get('model_id') or '<unset>'}",
                    f"dimensions · {embedding.get('dimensions') or '<unset>'}",
                    *_embedding_bootstrap_status_lines(embedding),
                ),
            ),
        ]
        embedding_notice_lines = _embedding_bootstrap_notice_lines(embedding)
        if embedding_notice_lines:
            sections.append(CliCardSection("Background bootstrap", embedding_notice_lines))
        _print_cli_card(
            "Embedding provider updated",
            "Elephant Agent will fall back to the local embedding default for semantic retrieval.",
            sections=tuple(sections),
            next_commands=("elephant provider embeddings status", "elephant provider status"),
        )
        return 0
    if action != "openai-compatible":
        raise SystemExit("unsupported embedding provider action; use status, local, or openai-compatible")

    base_url = str(args.base_url or "").strip()
    model_id = str(getattr(args, "embedding_model", None) or "").strip()
    dimensions_raw = getattr(args, "embedding_dimensions", None)
    if not base_url:
        raise SystemExit("embedding provider requires --base-url")
    if not model_id:
        raise SystemExit("embedding provider requires --model")
    if dimensions_raw is None:
        raise SystemExit("embedding provider requires --dimensions")
    try:
        dimensions = int(str(dimensions_raw).replace(",", ""))
    except ValueError as error:
        raise SystemExit("embedding --dimensions must be a positive integer") from error
    embedding = dict(
        runtime.set_openai_compatible_embedding_provider(
            base_url=base_url,
            model_id=model_id,
            dimensions=dimensions,
            api_key=args.api_key,
            secret_env_var=args.secret_env_var,
        )
    )
    _print_cli_card(
        "Embedding provider updated",
        "Elephant Agent will use the configured OpenAI-compatible embedding provider for semantic retrieval.",
        sections=(
            CliCardSection(
                "Saved",
                (
                    f"source · {embedding.get('source') or '<unset>'}",
                    f"provider_id · {embedding.get('provider_id') or '<unset>'}",
                    f"model_id · {embedding.get('model_id') or '<unset>'}",
                    f"dimensions · {embedding.get('dimensions') or '<unset>'}",
                    f"base_url · {embedding.get('base_url') or '<unset>'}",
                    f"secret_status · {embedding.get('secret_status') or '<unset>'}",
                ),
            ),
        ),
        next_commands=("elephant provider embeddings status", "elephant provider status"),
    )
    return 0

def _run_elephant(runtime: CliRuntime, args: argparse.Namespace) -> int:
    # Creating a new elephant only needs "configured provider profile + usable
    # credentials". Avoid the deep doctor here because it performs live model
    # catalog discovery plus an LLM probe, which can flap or stall in CI before
    # the first real turn ever starts.
    report = runtime.provider_doctor(deep=False)
    if not _provider_session_ready(report):
        _print_elephant_blocked(runtime)
        return 1
    raw_elephant_name = args.elephant_name
    interactive_shell = _interactive_shell_supported()
    if raw_elephant_name is None and not interactive_shell:
        _print_heading("Name needed", "Run elephant herd new <name>, or rerun in a TTY and Elephant Agent will ask you.")
        _print_command_hints("elephant herd new <name>", "elephant wake", "elephant herd")
        return 1
    if interactive_shell and raw_elephant_name is None:
        _print_heading("Elephant Agent elephant", "Let's bring another elephant online.")
        wizard_state = _run_interactive_elephant_wizard(
            runtime,
            elephant_name=raw_elephant_name,
        )
        if wizard_state is None:
            _print_elephant_paused()
            return 0
        raw_elephant_name = wizard_state
    elephant_id = _unique_elephant_name(runtime, raw_elephant_name)
    display_name = args.display_name or _display_name_from_elephant_name(raw_elephant_name)
    _play_creating_transition("Elephant Agent elephant", f"{display_name} is opening a new continuing thread.")
    session = runtime.create_elephant(
        elephant_id=elephant_id,
        profile_id=args.profile_id,
        display_name=display_name,
        mode="companion",
    )
    if args.message is not None:
        runtime.prepare_session_surface(session.episode_id)
        _print_elephant_created(runtime, session.episode_id)
        try:
            outcome = runtime.explain_next_step(session_id=session.episode_id, prompt=args.message)
        except Exception as error:
            _print_provider_turn_failed(runtime, error, session_id=session.episode_id)
            return 1
        _print_assistant_turn(runtime, outcome)
        return 0
    if _interactive_shell_supported():
        return ProductizedShell(runtime, session_id=session.episode_id, opened="Shaped new", debug=args.debug).run()
    _print_elephant_created(runtime, session.episode_id)
    return 0

def _run_herd(runtime: CliRuntime, args: argparse.Namespace) -> int:
    if args.herd_command is None:
        _print_herd(runtime)
        return 0
    if args.herd_command == "new":
        return _run_elephant(runtime, args)
    if args.herd_command == "current":
        _print_current_elephant(runtime)
        return 0
    if args.herd_command == "discover":
        return _run_herd_discover(runtime, args)
    if args.herd_command == "adopt":
        return _run_herd_adopt(runtime, args)
    if args.herd_command == "use":
        if args.elephant_id is None:
            herd = runtime.list_herd(limit=16)
            if not herd:
                _print_no_elephants()
                return 1
            if _interactive_shell_supported():
                selected = _prompt_elephant_choice(runtime, herd, state_focus="enter")
                if selected is WIZARD_BACK:
                    _print_cli_card(
                        "Elephant selection paused",
                        "No current elephant was changed.",
                        next_commands=("elephant herd", "elephant wake", "elephant herd new <name>"),
                    )
                    return 0
                elephant_id = selected.elephant_id
            else:
                raise ValueError("elephant herd use requires <name>")
        else:
            elephant_id = args.elephant_id
        _select_elephant(runtime, elephant_id)
        _print_elephant_selected(runtime, elephant_id)
        return 0
    if args.herd_command != "delete":
        raise ValueError(f"unknown herd command: {args.herd_command}")
    if args.delete_all:
        if args.elephant_id is not None:
            raise ValueError("elephant herd delete accepts either an elephant name or --all")
        deleted_elephants, deleted_sessions = runtime.delete_all_elephants()
        _print_all_herd_retired(deleted_elephants, deleted_sessions)
        return 0
    if args.elephant_id is None:
        herd = runtime.list_herd(limit=16)
        if not herd:
            _print_no_elephants()
            return 1
        if _interactive_shell_supported():
            selected = _prompt_elephant_choice(runtime, herd, state_focus="retire")
            if selected is WIZARD_BACK:
                _print_elephant_retire_paused()
                return 0
            elephant_id = selected.elephant_id
        else:
            raise ValueError("elephant herd delete requires <name> or --all")
    else:
        elephant_id = args.elephant_id
    deleted_sessions = runtime.delete_elephant(elephant_id)
    if deleted_sessions == 0:
        raise ValueError(f"unknown elephant: {elephant_id}")
    _print_elephant_retired(elephant_id, deleted_sessions)
    return 0


def _run_herd_discover(runtime: CliRuntime, args: argparse.Namespace) -> int:
    del args
    from packages.operator.local_agents import scan_local_agents

    records = scan_local_agents()
    upsert = getattr(runtime.repository, "upsert_local_agent_runtimes", None)
    if callable(upsert):
        upsert(records)
    lines = tuple(
        f"{record.runtime_id} · {record.display_name} · executable={'yes' if record.can_execute else 'no'} · {record.resolved_path}"
        for record in records
    ) or ("<no local agent CLIs found>",)
    _print_cli_card(
        "Local agent discovery",
        "Discovered local agent CLIs that Mother Elephant can adopt as baby elephants.",
        sections=(CliCardSection("Candidates", lines),),
        next_commands=("elephant herd adopt <runtime-id> --enable", "elephant herd"),
    )
    return 0


def _run_herd_adopt(runtime: CliRuntime, args: argparse.Namespace) -> int:
    runtime_id = str(getattr(args, "runtime_id", "") or "").strip()
    if not runtime_id:
        raise ValueError("elephant herd adopt requires <runtime-id>")
    load_runtime = getattr(runtime.repository, "load_local_agent_runtime", None)
    record = load_runtime(runtime_id) if callable(load_runtime) else None
    if record is None:
        raise ValueError(f"unknown local agent runtime: {runtime_id}")
    if not getattr(record, "can_execute", False):
        raise ValueError(f"local agent runtime is not executable yet: {runtime_id}")
    role_title = str(getattr(args, "role_title", None) or record.role_title or "local agent").strip()
    role_prompt = str(getattr(args, "role_prompt", None) or record.role_prompt or "").strip()
    display_name = str(getattr(args, "display_name", None) or f"{record.display_name} {role_title}").strip()
    elephant_id = _unique_elephant_name(runtime, display_name)
    mother = runtime.repository.load_state("state:mother-elephant")
    personal_model_id = mother.personal_model_id if mother is not None else runtime.repository.ensure_default_personal_model().personal_model_id
    identity_text = "\n".join(
        (
            f"# {display_name}",
            "",
            "## Role",
            "",
            role_title,
            "",
            "## Operating Notes",
            "",
            role_prompt or f"Use {record.display_name} for delegated local-agent work.",
        )
    )
    state = runtime.repository.create_state(
        personal_model_id=personal_model_id,
        state_id=f"state:{elephant_id}",
        state_anchor=f"elephant:{elephant_id}",
        elephant_id=elephant_id,
        elephant_name=display_name,
        identity_mode="baby",
        initiative="delegated",
        working_style="local_agent",
        surface_bindings=("cli", "local-agent"),
        elephant_identity_text=identity_text,
        summary=f"{display_name} is available as a baby elephant for {role_title}.",
        metadata={
            "profile_id": personal_model_id,
            "herd_kind": "baby",
            "parent_elephant_id": "mother-elephant",
            "role_title": role_title,
            "role_prompt": role_prompt,
            "runtime_id": record.runtime_id,
            "provider_id": record.provider_id,
            "enabled": "true" if bool(getattr(args, "enable", False)) else "false",
            "max_concurrency": "1",
        },
    )
    write_elephant_identity_file(runtime.paths.elephant_file_path(elephant_id), identity_text)
    _print_cli_card(
        "Baby elephant adopted",
        f"{display_name} was added to the Herd.",
        sections=(
            CliCardSection(
                "Baby",
                (
                    f"elephant_id · {state.elephant_id}",
                    f"role · {role_title}",
                    f"provider · {record.provider_id}",
                    f"enabled · {'true' if bool(getattr(args, 'enable', False)) else 'false'}",
                ),
            ),
        ),
        next_commands=("elephant herd", "elephant wake"),
    )
    return 0


__all__ = tuple(name for name in globals() if not name.startswith("__"))
