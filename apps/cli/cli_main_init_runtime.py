"""Interactive init runtime and bootstrap helpers for the CLI."""

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
LOGGER = logging.getLogger(__name__)


from .cli_main_init_prompts import *  # noqa: F401,F403

def _run_interactive_elephant_wizard(
    runtime: CliRuntime,
    *,
    elephant_name: str | None,
) -> str | None:
    current_elephant_name = elephant_name or _suggest_elephant_name(runtime)
    answer = _wizard_text_prompt(
        "Name Another Elephant Agent",
        "What should this new Elephant Agent be called?",
        default=current_elephant_name,
        allow_back=True,
    )
    if answer is WIZARD_BACK:
        return None
    return str(answer).strip() or current_elephant_name


def _run_embedding_birth_wizard(
    *,
    default_provider: str = "local",
    default_source: str = "huggingface",
    default_base_url: str = "",
    default_model: str = "",
    default_dimensions: int | None = None,
    language: str = "en",
) -> tuple[str, str, str, str, int | None, str | None] | _WizardBackSignal:
    provider = _wizard_choice_prompt(
        _init_text(language, "Choose Embedding Recall", "选择记忆嵌入方式"),
        _init_text(language, "How should Elephant Agent's evidence grow to know you?", "Elephant Agent 应该怎样建立可检索的记忆来了解你？"),
        (
            WizardChoice(
                value="local",
                label=_init_text(language, "Local embedding (recommended & free)", "本地嵌入（推荐 & 免费）"),
                detail=_init_text(
                    language,
                    "Powered by sentence-transformers. Runs entirely on your machine.",
                    "基于 sentence-transformers，完全在本地运行。",
                ),
            ),
            WizardChoice(
                value="openai-compatible",
                label=_init_text(language, "Embedding provider (paid & accuracy first)", "嵌入模型服务（付费 & 精度优先）"),
                detail=_init_text(language, "Use an OpenAI-compatible embedding endpoint.", "使用 OpenAI-compatible 的嵌入接口。"),
            ),
        ),
        default=default_provider or "local",
        allow_back=True,
    )
    if provider is WIZARD_BACK:
        return WIZARD_BACK
    selected = str(provider)
    if selected == "local":
        # Second-level: choose model source. Order depends on language.
        normalized_lang = _normalize_first_language(language)
        if normalized_lang == "zh":
            source_choices = (
                WizardChoice(
                    value="modelscope",
                    label="elephant-embeddings-v1-text-small (ModelScope)",
                    detail="agentic-intelligence-lab/elephant-embeddings-v1-text-small",
                ),
                WizardChoice(
                    value="huggingface",
                    label="elephant-embeddings-v1-text-small (HuggingFace)",
                    detail="llm-semantic-router/elephant-embeddings-v1-text-small",
                ),
            )
            source_default = "modelscope"
        else:
            source_choices = (
                WizardChoice(
                    value="huggingface",
                    label="elephant-embeddings-v1-text-small (HuggingFace)",
                    detail="llm-semantic-router/elephant-embeddings-v1-text-small",
                ),
                WizardChoice(
                    value="modelscope",
                    label="elephant-embeddings-v1-text-small (ModelScope)",
                    detail="agentic-intelligence-lab/elephant-embeddings-v1-text-small",
                ),
            )
            source_default = "huggingface"
        source = _wizard_choice_prompt(
            _init_text(language, "Choose Model Source", "选择模型来源"),
            _init_text(
                language,
                "Where should Elephant Agent download the local embedding model from? (powered by sentence-transformers)",
                "Elephant Agent 应该从哪里下载本地嵌入模型？（基于 sentence-transformers）",
            ),
            source_choices,
            default=source_default,
            allow_back=True,
        )
        if source is WIZARD_BACK:
            return WIZARD_BACK
        return ("local", str(source), "", "", None, None)
    base_url = _wizard_text_prompt(
        "Embedding Endpoint",
        "What embedding endpoint should Elephant Agent call?",
        default=default_base_url,
        allow_back=True,
    )
    if base_url is WIZARD_BACK:
        return WIZARD_BACK
    model = _wizard_text_prompt(
        "Embedding Model",
        "Which embedding model should Elephant Agent use?",
        default=default_model,
        allow_back=True,
    )
    if model is WIZARD_BACK:
        return WIZARD_BACK
    dimensions_text = _wizard_text_prompt(
        "Embedding Dimensions",
        "How many vector dimensions does this model return?",
        default=str(default_dimensions or 1024),
        allow_back=True,
    )
    if dimensions_text is WIZARD_BACK:
        return WIZARD_BACK
    try:
        dimensions = int(str(dimensions_text).strip().replace(",", ""))
    except ValueError:
        dimensions = default_dimensions or 1024
    api_key = _wizard_text_prompt(
        _init_text(language, "Embedding Key", "嵌入接口密钥"),
        _init_text(language, "Enter an embedding key if this endpoint needs one.", "如果这个接口需要密钥，请输入。"),
        default=None,
        allow_back=True,
        password=True,
    )
    if api_key is WIZARD_BACK:
        return WIZARD_BACK
    return (selected, "", str(base_url).strip(), str(model).strip(), dimensions, str(api_key).strip() or None)


def _mapping_or_empty(value: object) -> dict[str, object]:
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return {}


def _mbti_traits(value: str, *, language: str = "en") -> str:
    traits = _MBTI_TRAITS_ZH if _normalize_first_language(language) == "zh" else _MBTI_TRAITS_EN
    return traits.get(str(value or "").strip().upper(), "")


def _starter_answer_map(bootstrap_state: object) -> dict[str, str]:
    answers: dict[str, str] = {}
    for question_id, _, answer in tuple(getattr(bootstrap_state, "starter_answers", ()) or ()):  # type: ignore[misc]
        cleaned = str(answer).strip()
        if cleaned:
            answers[str(question_id)] = cleaned
    return answers


def _infer_init_companion_posture(bootstrap_state: object, *, language: str) -> str:
    answers = _starter_answer_map(bootstrap_state)
    mbti = str(getattr(bootstrap_state, "mbti", "") or "").strip().upper()
    recovery = answers.get("recovery_style", "")
    pressure = answers.get("pressure_pattern", "")
    decision = answers.get("decision_compass", "")
    inner = answers.get("inner_landscape", "")
    quiet_signals = any(
        token in " ".join((recovery, decision, inner)).lower()
        for token in ("quiet", "安静", "room", "房间", "walk", "走")
    ) or mbti in {"INFJ", "INFP", "INTJ", "INTP", "ISFJ", "ISFP"}
    action_signals = any(
        token in " ".join((pressure, decision, recovery, str(getattr(bootstrap_state, "occupation", "")))).lower()
        for token in ("experiment", "实验", "project", "项目", "next step", "下一步", "plan", "计划", "move fast", "先动")
    ) or mbti in {"ENTJ", "ESTJ", "ESTP", "ISTP"}
    if language == "zh":
        if quiet_signals and not action_signals:
            return "安静、细腻、低压地陪在旁边；先映照和澄清，不急着推进。"
        if action_signals and not quiet_signals:
            return "直接、具体、能落地；先帮用户看清下一步，同时保留一点温度。"
        return "温和但清楚：先听见情绪和意义，再把事情慢慢整理成可行动的形状。"
    if quiet_signals and not action_signals:
        return "quiet, precise, low-pressure companionship; reflect and clarify before pushing forward."
    if action_signals and not quiet_signals:
        return "direct, concrete support; make the next step visible while keeping warmth in the room."
    return "steady and clear: notice feeling and meaning first, then gently shape it into action."


def _learned_init_entries(language: str, bootstrap_state: object) -> list[tuple[str, dict[str, str]]]:
    """Fast PM pass over init answers: synthesize useful facts, don't paste the form."""
    is_zh = language == "zh"
    entries: list[tuple[str, dict[str, str]]] = []
    if is_zh:
        entries.append(("中文", {"field": "first_language", **_INIT_FIELD_MODEL_HINTS["first_language"]}))
    else:
        entries.append(("English", {"field": "first_language", **_INIT_FIELD_MODEL_HINTS["first_language"]}))

    def add(field: str, value: object, extra: dict[str, str] | None = None) -> None:
        cleaned = str(value or "").strip()
        if not cleaned:
            return
        entries.append((cleaned, {"field": field, **_INIT_FIELD_MODEL_HINTS.get(field, {}), **(extra or {})}))

    add("preferred_name", getattr(bootstrap_state, "preferred_name", ""))
    add("occupation", getattr(bootstrap_state, "occupation", ""))
    add("gender", getattr(bootstrap_state, "gender", ""))
    add("birth_date", getattr(bootstrap_state, "birth_date", ""))
    add("city", getattr(bootstrap_state, "city", ""))
    mbti = str(getattr(bootstrap_state, "mbti", "") or "").strip().upper()
    if mbti:
        traits = _mbti_traits(mbti, language=language)
        if is_zh:
            text = f"MBTI：{mbti}；特征参考：{traits}" if traits else f"MBTI：{mbti}"
        else:
            text = f"MBTI: {mbti}; trait reference: {traits}" if traits else f"MBTI: {mbti}"
        entries.append((text, {"field": "mbti", "mbti_traits": traits, **_INIT_FIELD_MODEL_HINTS["mbti"]}))
    add("hobbies", getattr(bootstrap_state, "hobbies", ""))
    for field_id, value in _init_care_entries(bootstrap_state):
        entries.append((value, {"field": field_id, **_INIT_FIELD_MODEL_HINTS[field_id]}))

    for question_id, answer in _starter_answer_map(bootstrap_state).items():
        hints = _starter_question_model_hints(question_id)
        if not hints:
            continue
        entries.append((answer, {"field": question_id, **hints}))

    posture = _infer_init_companion_posture(bootstrap_state, language=language)
    entries.append((posture, {"field": "inferred_companion_posture", **_INIT_FIELD_MODEL_HINTS["inferred_companion_posture"]}))
    return entries


def _run_interactive_birth_wizard(
    runtime: CliRuntime,
    *,
    display_name: str,
    provider_state: ProviderSelectionState,
    first_language: str = "en",
) -> BirthWizardState | None:
    state = BirthWizardState(
        display_name=display_name,
        provider_id=provider_state.provider_id,
        base_url=provider_state.base_url,
        model_id=provider_state.model_id,
        api_key=provider_state.api_key,
        embedding_provider="local",
        embedding_source="huggingface",
        embedding_base_url="",
        embedding_model="",
        embedding_dimensions=None,
        embedding_api_key=None,
        reasoning_effort=provider_state.reasoning_effort,
        context_window_mode=provider_state.context_window_mode,
        context_window_tokens=provider_state.context_window_tokens,
        first_language=_normalize_first_language(first_language),
    )
    steps = (
        "welcome",
        "first_language",
        "personal_basics",
        "starter_questions",
        "display_name",
        "provider_setup",
        "embedding_setup",
        "learning_intensity",
    )
    step_index = 0

    def _go_back() -> bool:
        nonlocal step_index
        if step_index <= 0:
            return False
        step_index -= 1
        return True

    while step_index < len(steps):
        step = steps[step_index]
        if step == "welcome":
            if not _prompt_init_welcome_gate():
                return None
            step_index += 1
            continue
        if step == "first_language":
            answer = _prompt_first_language(state.first_language, allow_back=True)
            if answer is WIZARD_CANCEL:
                return None
            if answer is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.first_language = _normalize_first_language(answer)
            step_index += 1
            continue
        if step == "display_name":
            answer = _prompt_first_elephant_name(state.display_name, allow_back=True, language=state.first_language)
            if answer is WIZARD_CANCEL:
                return None
            if answer is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.display_name = str(answer).strip() or state.display_name
            step_index += 1
            continue
        if step == "personal_basics":
            _print_init_section(
                state.first_language,
                "First, a few anchors",
                "先留几个锚点",
                "A few plain facts help Elephant Agent begin with the right person and the right world in view.",
                "先从几件很朴素的事开始：我知道是谁在这里，也知道你大概处在什么生活语境里。",
            )
            name = _prompt_required_text(
                state.first_language,
                "What should I call you?",
                "我怎么称呼你比较自然？",
                "A name or nickname is enough. I'll use it in greetings and evidence.",
                "名字、昵称都可以。之后我会用这个称呼你。",
                default=state.preferred_name,
                allow_back=True,
            )
            if name is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.preferred_name = str(name).strip()

            attention_choices = _ATTENTION_CHOICES_ZH if state.first_language == "zh" else _ATTENTION_CHOICES_EN
            default_attention = state.occupation or attention_choices[0][0]
            occupation = _prompt_choice_with_type(
                state.first_language,
                "Which thread is taking most of your attention lately?",
                "最近脑海里经常出现的想法，大概是关于什么的？",
                "Pick the closest life thread, or add one short phrase. This gives Elephant Agent your current context without over-defining you.",
                "选一个最贴近的感觉就好，也可以自己写一句。它只是帮 Elephant Agent 轻轻看见你最近常常回到哪里，不会把你定死。",
                attention_choices,
                default=default_attention,
                allow_back=True,
                persist_choice_detail=True,
            )
            if occupation is WIZARD_CANCEL:
                return None
            if occupation is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.occupation = str(occupation).strip() or _choice_saved_value(attention_choices, str(attention_choices[0][0]))

            gender = _prompt_choice_with_type(
                state.first_language,
                "Gender",
                "性别",
                "Optional. This only helps avoid awkward wording later.",
                "可选。只是为了之后少一点别扭的称呼。",
                _GENDER_CHOICES_ZH if state.first_language == "zh" else _GENDER_CHOICES_EN,
                default=state.gender or "skip",
                allow_back=True,
            )
            if gender is WIZARD_CANCEL:
                return None
            if gender is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.gender = str(gender).strip()

            birth_date = _prompt_birth_date(state.first_language, default=state.birth_date, allow_back=True)
            if birth_date is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.birth_date = str(birth_date).strip()

            mbti = _prompt_choice_with_type(
                state.first_language,
                "MBTI shorthand",
                "MBTI 速记",
                "Optional. If this language helps you describe yourself, pick one; if not, choose 不确定.",
                "可选。如果你平时会用它描述自己，就选一个；如果没感觉，选“不确定”就好。",
                _mbti_choices(state.first_language),
                default=state.mbti or "not_sure",
                allow_back=True,
            )
            if mbti is WIZARD_CANCEL:
                return None
            if mbti is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.mbti = "" if str(mbti) == "not_sure" else str(mbti).strip()

            hobbies = _prompt_hobbies(state.first_language, default=state.hobbies, allow_back=True)
            if hobbies is WIZARD_CANCEL:
                return None
            if hobbies is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.hobbies = str(hobbies).strip()

            city = _prompt_optional_text(
                state.first_language,
                "City or timezone",
                "城市或时区",
                "Optional. Time and place change how days feel.",
                "可选。时间和地点会影响一天的节奏。",
                default=state.city,
                allow_back=True,
            )
            if city is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.city = str(city).strip()

            safety_values: list[str] = []
            _print_init_section(
                state.first_language,
                "Care context (optional)",
                "安全边界信息（可选）",
                "These details help Elephant Agent support you more safely. You can leave them empty or add them later in your profile.",
                "这些信息可帮助 Elephant Agent 更安全地陪伴你；也可以留空，稍后在个人资料中补充。",
            )
            safety_back = False
            for field_id, title_en, title_zh, prompt_en, prompt_zh in _SAFETY_PROMPTS:
                value = _prompt_optional_text(
                    state.first_language,
                    title_en,
                    title_zh,
                    prompt_en,
                    prompt_zh,
                    default="",
                    allow_back=True,
                )
                if value is WIZARD_BACK:
                    if not _go_back():
                        return None
                    safety_back = True
                    break
                cleaned = str(value).strip()
                if cleaned:
                    safety_values.append(f"{field_id}: {cleaned}")
            if safety_back:
                continue
            state.safety_boundaries = "; ".join(safety_values)
            step_index += 1
            continue
        if step == "provider_setup":
            answer = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id=state.provider_id,
                    base_url=state.base_url,
                    api_key=state.api_key,
                    model_id=state.model_id,
                    reasoning_effort=state.reasoning_effort,
                    context_window_mode=state.context_window_mode,
                    context_window_tokens=state.context_window_tokens,
                ),
                allow_back=True,
                language=state.first_language,
            )
            if answer is WIZARD_CANCEL:
                return None
            if answer is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.provider_id = answer.provider_id
            state.base_url = answer.base_url
            state.api_key = answer.api_key
            state.model_id = answer.model_id
            state.reasoning_effort = answer.reasoning_effort
            state.context_window_mode = answer.context_window_mode
            state.context_window_tokens = answer.context_window_tokens
            step_index += 1
            continue
        if step == "embedding_setup":
            answer = _run_embedding_birth_wizard(
                default_provider=state.embedding_provider,
                default_source=state.embedding_source,
                default_base_url=state.embedding_base_url,
                default_model=state.embedding_model,
                default_dimensions=state.embedding_dimensions,
                language=state.first_language,
            )
            if answer is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            (
                state.embedding_provider,
                state.embedding_source,
                state.embedding_base_url,
                state.embedding_model,
                state.embedding_dimensions,
                state.embedding_api_key,
            ) = answer
            step_index += 1
            continue
        if step == "learning_intensity":
            answer = _prompt_learning_intensity(state.learning_intensity, allow_back=True, language=state.first_language)
            if answer is WIZARD_CANCEL:
                return None
            if answer is WIZARD_BACK:
                if not _go_back():
                    return None
                continue
            state.learning_intensity = str(answer).strip().lower() or state.learning_intensity
            step_index += 1
            continue
        if step == "starter_questions":
            _print_init_section(
                state.first_language,
                "Then, a few small doors",
                "然后，打开几扇小门",
                "You can leave any blank. These five build the first foundation: present state, values, stress pattern, recovery, and decision compass.",
                "每一题都可以留空。它们不是测评，只是几盏小灯：让我更温柔地记住你现在的状态、在意的东西、压力来时的样子、恢复自己的方式，以及靠近答案的路。",
            )
            answers: list[tuple[str, str, str]] = []
            starter_back = False
            for spec in _STARTER_QUESTIONS:
                answer = _prompt_starter_question(state.first_language, spec)
                if answer is WIZARD_CANCEL:
                    return None
                if answer is WIZARD_BACK:
                    if not _go_back():
                        return None
                    starter_back = True
                    break
                if answer is not None:
                    answers.append(answer)
            if starter_back:
                continue
            state.starter_answers = tuple(answers)
            step_index += 1
            continue
    return state


def _persist_init_question_config(runtime: CliRuntime, *, first_language: str, learning_intensity: str) -> None:
    try:
        from packages.runtime_config import (
            personal_model_question_config_from_global,
            global_config_path_for_state_dir,
            load_global_config,
            write_global_config,
        )
        config_path = global_config_path_for_state_dir(runtime.paths.state_dir)
        config = load_global_config(config_path, state_dir=runtime.paths.state_dir)
        question_config = personal_model_question_config_from_global(config)
        question_config["learning_intensity"] = learning_intensity
        proactive = dict(question_config.get("proactive_ask") or {})
        proactive.update(_proactive_ask_config_for_learning_intensity(learning_intensity))
        question_config["proactive_ask"] = proactive
        config["personal_model_questions"] = question_config
        personal = dict(config.get("personal_model") or {})
        personal["first_language"] = _normalize_first_language(first_language)
        config["personal_model"] = personal
        write_global_config(config_path, config)
    except Exception:  # pragma: no cover
        LOGGER.debug("Failed to persist init Personal Model question config.", exc_info=True)
        return


def _proactive_ask_config_for_learning_intensity(learning_intensity: str) -> dict[str, object]:
    intensity = str(learning_intensity or "").strip().lower()
    if intensity == "low":
        return {"idle_threshold_minutes": 720, "daily_max": 2, "quiet_hours": [23, 7]}
    if intensity == "high":
        return {"idle_threshold_minutes": 60, "daily_max": 24, "quiet_hours": [1, 7]}
    return {"idle_threshold_minutes": 180, "daily_max": 8, "quiet_hours": [23, 7]}


def _init_profile_learning_metadata(
    bootstrap_state: object,
    *,
    learning_intensity: str,
    language: str,
) -> dict[str, str]:
    normalized_intensity = str(learning_intensity or "").strip().lower()
    if normalized_intensity not in {"low", "medium", "high"}:
        normalized_intensity = "medium"
    metadata: dict[str, str] = {
        "source": "elephant_init",
        "purpose": "profile_and_skill_affinity",
        "init_first_language": language,
        "init_learning_intensity": normalized_intensity,
    }
    for field in (
        "preferred_name",
        "occupation",
        "gender",
        "birth_date",
        "city",
        "mbti",
        "hobbies",
        "relationship_mode",
        "safety_boundaries",
    ):
        value = str(getattr(bootstrap_state, field, "") or "").strip()
        if value:
            metadata[f"init_{field}"] = value
    starter_answers = []
    for question_id, _question_text, answer in tuple(getattr(bootstrap_state, "starter_answers", ()) or ()):
        cleaned = str(answer or "").strip()
        if cleaned:
            starter_answers.append(f"{question_id}: {cleaned}")
    if starter_answers:
        metadata["init_starter_answers"] = " | ".join(starter_answers)
    care_entries = _init_care_entries(bootstrap_state)
    if care_entries:
        metadata["init_safety_boundaries"] = " | ".join(f"{field}: {value}" for field, value in care_entries)
    return metadata


def _bootstrap_user_profile_from_init(runtime: CliRuntime, *, personal_model_id: str, bootstrap_state: object) -> None:
    """Mirror init anchors into the canonical user card used by dashboard + prompt."""
    language = _normalize_first_language(getattr(bootstrap_state, "first_language", "en"))
    fields = {
        "preferred_name": str(getattr(bootstrap_state, "preferred_name", "") or "").strip(),
        "current_work": str(getattr(bootstrap_state, "occupation", "") or "").strip(),
        "current_city": str(getattr(bootstrap_state, "city", "") or "").strip(),
        "birth_date": str(getattr(bootstrap_state, "birth_date", "") or "").strip(),
        "mbti": str(getattr(bootstrap_state, "mbti", "") or "").strip(),
        "hobbies": str(getattr(bootstrap_state, "hobbies", "") or "").strip(),
        "gender": str(getattr(bootstrap_state, "gender", "") or "").strip(),
        "relationship_mode": _infer_init_companion_posture(bootstrap_state, language=language),
    }
    fields.update({field_id: value for field_id, value in _init_care_entries(bootstrap_state)})
    if not any(fields.values()):
        return
    try:
        runtime.update_user_state(
            profile_id=personal_model_id,
            text=render_user_profile_text(**{key: value for key, value in fields.items() if value}),
            fields={key: value for key, value in fields.items() if value},
            append=True,
        )
    except Exception:
        LOGGER.debug("Failed to persist init user profile fields.", exc_info=True)
        return


def _bootstrap_personal_model_from_init(runtime: CliRuntime, session, bootstrap_state: object) -> None:
    personal_model_id = str(getattr(session, "personal_model_id", "") or "").strip()
    if not personal_model_id:
        return
    _bootstrap_user_profile_from_init(runtime, personal_model_id=personal_model_id, bootstrap_state=bootstrap_state)
    language = _normalize_first_language(getattr(bootstrap_state, "first_language", "en"))
    try:
        from dataclasses import replace as _dc_replace
        profile = runtime.repository.load_personal_model_runtime_state(personal_model_id)
        if profile is not None:
            preferences = list(tuple(getattr(profile, "preferences", ()) or ()))
            for entry in (
                f"first_language={language}",
                f"preferred_name={getattr(bootstrap_state, 'preferred_name', '')}",
                f"occupation={getattr(bootstrap_state, 'occupation', '')}",
                f"birth_date={getattr(bootstrap_state, 'birth_date', '')}",
                f"hobbies={getattr(bootstrap_state, 'hobbies', '')}",
                f"city={getattr(bootstrap_state, 'city', '')}",
                f"relationship_mode={_infer_init_companion_posture(bootstrap_state, language=language)}",
            ):
                if entry.endswith("="):
                    continue
                if entry not in preferences:
                    preferences.append(entry)
            runtime.repository.upsert_personal_model_runtime_state(_dc_replace(profile, preferences=tuple(preferences)))
    except Exception:
        LOGGER.debug("Failed to persist init profile runtime preferences.", exc_info=True)
        pass
    try:
        from packages.understanding import PersonalModelUnderstandingSurface
    except Exception:
        LOGGER.debug("Failed to import Personal Model understanding surface during init bootstrap.", exc_info=True)
        return
    semantic_summary_indexer = None
    embedding_service = runtime.recall_runtime.retriever.evidence_retriever.embedding_service
    if runtime.semantic_index_bundle is not None and embedding_service is not None:
        try:
            from packages.evidence import SemanticSummaryIndexer

            semantic_summary_indexer = SemanticSummaryIndexer(
                semantic_index=runtime.semantic_index_bundle.service,
                embedding_service=embedding_service,
                repository=runtime.repository,
            )
        except Exception:
            LOGGER.debug("Failed to build semantic summary indexer for init bootstrap.", exc_info=True)
            semantic_summary_indexer = None
    understanding = PersonalModelUnderstandingSurface(
        repository=runtime.repository,
        semantic_summary_indexer=semantic_summary_indexer,
        semantic_searcher=(
            runtime.semantic_index_bundle.searcher
            if runtime.semantic_index_bundle is not None
            else None
        ),
        embedding_service=embedding_service,
    )
    entries = _learned_init_entries(language, bootstrap_state)
    for content, metadata in entries:
        try:
            understanding.update_personal_model(
                str(getattr(session, "episode_id", "") or "init"),
                action="remember",
                lens=str(metadata.get("lens") or "world"),
                topic=str(metadata.get("topic") or "world.assets.init.answer"),
                text=content,
                reason="elephant init answer",
                source="user_said",
                personal_model_id=personal_model_id,
                metadata={**metadata, "source": "init"},
            )
        except Exception:
            LOGGER.debug("Failed to persist init answer as Personal Model fact.", exc_info=True)
            continue
    try:
        episode_id = str(getattr(session, "episode_id", "") or getattr(session, "session_id", "") or "").strip()
        if episode_id:
            runtime.schedule_learning_for_session(
                session_id=episode_id,
                trigger="init_profile",
                summary="initial profile and skill-affinity learning",
                metadata=_init_profile_learning_metadata(
                    bootstrap_state,
                    learning_intensity=str(
                        getattr(bootstrap_state, "learning_intensity", "medium") or "medium"
                    ),
                    language=language,
                ),
            )
    except Exception:
        LOGGER.debug("Failed to schedule init profile learning job.", exc_info=True)
        pass
    # Create nightly learning cron jobs
    try:
        _ensure_nightly_learning_cron_rows(runtime.cron_runtime)
    except Exception:
        LOGGER.debug("Failed to ensure nightly learning cron rows after init.", exc_info=True)
        pass
    try:
        refreshed_profile = runtime._load_profile(personal_model_id)
        runtime._write_snapshot(
            profile=refreshed_profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=None,
            delivery=None,
            stages=(),
            event=None,
            elephant_identity_text=refreshed_profile.elephant_identity_text,
            state_focus=None,
        )
    except Exception:
        LOGGER.debug("Failed to write init runtime snapshot.", exc_info=True)
        pass


__all__ = tuple(name for name in globals() if not name.startswith("__"))
