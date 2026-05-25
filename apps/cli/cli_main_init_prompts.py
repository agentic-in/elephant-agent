"""Interactive init prompt helpers for the CLI."""

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


def _prompt_first_elephant_name(
    default_name: str,
    *,
    allow_back: bool = False,
    language: str = "en",
) -> str | _WizardBackSignal:
    return _wizard_text_prompt(
        _init_text(language, "Name Your First Elephant Agent", "给你的第一个 Elephant Agent 起名"),
        _init_text(language, "This first Elephant Agent is yours. What name feels right?", "这是你的第一个 Elephant Agent。哪个名字最合适？"),
        default=default_name,
        allow_back=allow_back,
    )


def _prompt_learning_intensity(
    default: str = "medium",
    *,
    allow_back: bool = False,
    language: str = "en",
) -> str | _WizardBackSignal:
    """Let the user choose how often Elephant Agent may ask Personal Model questions."""
    return _wizard_choice_prompt(
        _init_text(language, "Elephant Agent's Questions", "Elephant Agent 的问题频率"),
        _init_text(language, "How often should Elephant Agent ask open questions to learn more about you?", "Elephant Agent 可以多频繁地问开放问题来更了解你？"),
        (
            WizardChoice(
                value="low",
                label=_init_text(language, "Quiet questions", "安静提问"),
                detail=_init_text(language, "Low touch. Up to two open questions per day, usually morning or before bed.", "低频打扰。每天最多两次，通常偏早晨或睡前。"),
                emoji="🌙",
            ),
            WizardChoice(
                value="medium",
                label=_init_text(language, "Gentle questions", "温和提问"),
                detail=_init_text(language, "Default. If an IM route is running, asks after roughly 3 idle hours.", "默认。如果 IM 通道在线，空闲约 3 小时后会问一个问题。"),
                emoji="🌿",
            ),
            WizardChoice(
                value="high",
                label=_init_text(language, "Active questions", "积极提问"),
                detail=_init_text(language, "Most active. Outside quiet hours, an IM route may ask once an elephant has been idle for 1 hour.", "最主动。静默时间外，如果 IM 通道在线，elephant 空闲 1 小时后就可以主动问。"),
                emoji="⚡",
            ),
        ),
        default=default or "medium",
        allow_back=allow_back,
    )


SUPPORTED_FIRST_LANGUAGES = {"en", "zh"}


def _normalize_first_language(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"zh", "zh-cn", "cn", "chinese", "中文", "汉语", "普通话"}:
        return "zh"
    return "en"


def _init_text(language: str, english: str, chinese: str) -> str:
    return chinese if _normalize_first_language(language) == "zh" else english


def _prompt_first_language(default: str = "en", *, allow_back: bool = False) -> str | _WizardBackSignal:
    return _wizard_choice_prompt(
        "First language / 第一语言",
        "Choose the language Elephant Agent should use for the rest of init.",
        (
            WizardChoice(value="en", label="English", detail="Use English for init and store English as your first language."),
            WizardChoice(value="zh", label="中文", detail="后续初始化过程使用中文，并把中文记录为你的第一语言。"),
        ),
        default=_normalize_first_language(default),
        allow_back=allow_back,
    )


def _prompt_optional_text(
    language: str,
    title_en: str,
    title_zh: str,
    prompt_en: str,
    prompt_zh: str,
    *,
    default: str = "",
    allow_back: bool = True,
) -> str | _WizardBackSignal:
    return _wizard_text_prompt(
        _init_text(language, title_en, title_zh),
        _init_text(language, prompt_en, prompt_zh),
        default=default or None,
        allow_back=allow_back,
    )


def _prompt_required_text(
    language: str,
    title_en: str,
    title_zh: str,
    prompt_en: str,
    prompt_zh: str,
    *,
    default: str = "",
    allow_back: bool = True,
) -> str | _WizardBackSignal:
    required = _init_text(language, "Please add a little something here before continuing.", "这里需要写一点内容，才能继续。")
    while True:
        answer = _wizard_text_prompt(
            _init_text(language, title_en, title_zh),
            _init_text(language, prompt_en, prompt_zh),
            default=default or None,
            allow_back=allow_back,
            required_message=required,
            preserve_default_on_empty=False,
        )
        if answer is WIZARD_BACK:
            return WIZARD_BACK
        cleaned = str(answer).strip()
        if cleaned:
            return cleaned


def _init_wizard_choice(item: tuple[str, ...]) -> WizardChoice:
    return WizardChoice(
        value=str(item[0]),
        label=str(item[1]) if len(item) >= 2 else str(item[0]),
        detail=str(item[2]) if len(item) >= 3 else "",
        emoji=str(item[3]) if len(item) >= 4 else "",
    )


def _choice_saved_value(choices: tuple[tuple[str, ...], ...], selected: str) -> str:
    """Return the hidden PM-facing answer for a selected init choice."""
    cleaned = str(selected or "").strip()
    if not cleaned:
        return ""
    for choice in choices:
        if str(choice[0]).strip() != cleaned:
            continue
        if len(choice) > 4:
            explicit = str(choice[4]).strip()
            if explicit:
                return explicit
        if len(choice) >= 3:
            detail = str(choice[2]).strip()
            if detail:
                return detail
        return cleaned
    return cleaned


def _prompt_choice_with_type(
    language: str,
    title_en: str,
    title_zh: str,
    prompt_en: str,
    prompt_zh: str,
    choices: tuple[tuple[str, ...], ...],
    *,
    default: str,
    allow_back: bool = True,
    persist_choice_detail: bool = False,
) -> str | _WizardBackSignal:
    answer = _wizard_choice_prompt(
        _init_text(language, title_en, title_zh),
        _init_text(language, prompt_en, prompt_zh),
        tuple(_init_wizard_choice(choice) for choice in choices),
        default=default,
        allow_back=allow_back,
    )
    if answer is WIZARD_CANCEL:
        return WIZARD_CANCEL
    if answer is WIZARD_BACK:
        return WIZARD_BACK
    selected = str(answer).strip()
    if selected == "skip":
        return ""
    if selected == "type":
        custom = _wizard_text_prompt(
            _init_text(language, "Write it your way", "用你的话写"),
            _init_text(language, "A short phrase is enough.", "一个短句就够。"),
            default=None,
            allow_back=allow_back,
            preserve_default_on_empty=False,
        )
        if custom is WIZARD_CANCEL:
            return WIZARD_CANCEL
        if custom is WIZARD_BACK:
            return WIZARD_BACK
        return str(custom).strip()
    if persist_choice_detail:
        return _choice_saved_value(choices, selected)
    return selected


def _prompt_birth_date(language: str, default: str = "", *, allow_back: bool = True) -> str | _WizardBackSignal:
    answer = _wizard_text_prompt(
        _init_text(language, "Birth date", "出生日期"),
        _init_text(
            language,
            "Optional. Use YYYY/MM/DD, for example 1999/12/03. Leave blank to skip.",
            "可选。用 YYYY/MM/DD，比如 1999/12/03；不想填就留空。",
        ),
        default=default or None,
        allow_back=allow_back,
        preserve_default_on_empty=True,
    )
    if answer is WIZARD_BACK:
        return WIZARD_BACK
    return str(answer).strip()


def _prompt_hobbies(language: str, default: str = "", *, allow_back: bool = True) -> str | _WizardBackSignal:
    choices = _HOBBY_CHOICES_ZH if _normalize_first_language(language) == "zh" else _HOBBY_CHOICES_EN
    existing = tuple(part.strip() for part in re.split(r"[,，、/]+", default or "") if part.strip())
    answer = _wizard_multi_choice_prompt(
        _init_text(language, "Personal hobbies", "个人爱好"),
        _init_text(language, "Optional. Use Space to select any hobbies Elephant Agent should know.", "可选。用空格多选你希望 Elephant Agent 知道的个人爱好。"),
        tuple(_init_wizard_choice(choice) for choice in choices),
        default_values=existing,
        allow_back=allow_back,
    )
    if answer is WIZARD_BACK:
        return WIZARD_BACK
    selected = tuple(value for value in answer if value and value != "skip")
    if not selected:
        return ""
    return ("、" if _normalize_first_language(language) == "zh" else ", ").join(selected)


_ATTENTION_CHOICES_EN = (
    ("a project wants to move", "A project wants to move", "Work, product, writing, craft, or something you want to bring into shape.", "🚀", "Primary attention is on moving a concrete project or piece of work forward; prioritize momentum, blockers, completion pressure, and output rhythm."),
    ("standing at a fork", "Standing at a fork", "Changing direction, deciding, leaving, or beginning a new road.", "🧭", "Currently in transition and choice, possibly changing direction, deciding, leaving an old path, or beginning a new one; prioritize trade-offs, risks, what is hard to leave, and reversible next steps."),
    ("chewing on a new question", "Chewing on a new question", "Reading, studying, testing ideas, or trying to understand something important.", "🔎", "Drawn to a new question and forming judgment through study, research, or testing; prioritize structure, key assumptions, evidence, and the next round of exploration."),
    ("relationships are tugging", "Relationships are tugging", "Family, friends, intimacy, distance, care, or where you belong among people.", "🤝", "Attention is being pulled by relationships, belonging, or social position; include distance, care, promises, boundaries, and emotional safety in the frame."),
    ("body needs attention first", "Body needs attention first", "Sleep, health, rhythm, pressure, stamina, or recovery may need to be seen first.", "🌿", "Body, energy, and recovery rhythm need attention first; consider sleep, pressure, stamina, safety, and restoration before pushing intensity."),
    ("steady the life floor", "Steady the life floor", "Home, money, routines, logistics, or making ordinary life hold you again.", "🏠", "Basic life stability needs to come first, including home, money, routines, logistics, or real-world order; prioritize structure, certainty, and low-friction arrangements that hold daily life."),
    ("type", "None fit; I’ll write one", "Write one short phrase instead", "✍️"),
)
_ATTENTION_CHOICES_ZH = (
    ("一件作品正在往前推", "一件作品正在往前推", "像是有件东西正在手里发热，想被认真推到前面去。可能是项目、产品、写作、作品，或任何你希望它慢慢成形的事。", "🚀", "最近的主要注意力在推进一个具体作品或项目；优先关注推进节奏、阻力、完成欲和产出压力。"),
    ("正站在一个岔路口", "正站在一个岔路口", "像站在一条路将要分开的地方，心里已经知道不能一直停在原处。可能关于换方向、做决定、离开，或开始一段新路。", "🧭", "最近处在过渡和选择中，可能正在考虑换方向、做决定、离开原来的路径或开始新路；优先澄清取舍、风险、舍不得的东西和可逆的下一步。"),
    ("在啃一个新问题", "在啃一个新问题", "有个问题一直在脑海里发亮，想被读懂、拆开、验证。可能是学习、研究、准备，或理解某件重要的事。", "🔎", "最近被一个新问题吸引，正在通过学习、研究或验证来形成判断；优先整理问题结构、关键假设、证据和下一轮探索。"),
    ("关系和归属感在拉扯", "关系和归属感在拉扯", "有些牵挂来自人和人之间的位置：靠近、距离、照顾、承诺，或不知道自己该站在哪里。", "🤝", "最近的注意力被关系、归属感或人际位置牵动；距离、照顾、承诺、边界和情感安全都需要一起纳入判断。"),
    ("身体和精力先要照顾", "身体和精力先要照顾", "身体像先举了一下手，提醒你慢一点。睡眠、健康、节奏、压力、体力或恢复，可能比别的事更需要被看见。", "🌿", "最近首先需要照顾身体、精力和恢复节奏；先考虑睡眠、压力、体力、安全感和节奏修复，再谈更高强度的推进。"),
    ("先把生活地基稳住", "先把生活地基稳住", "像先把房间的灯打开、地面扫平，让生活重新能托住你。可能关于住处、金钱、日程、杂事，或现实里的秩序。", "🏠", "最近需要先稳定生活基础，包括住处、金钱、日程、杂事或现实秩序；优先关注能承托日常的结构、确定性和低摩擦安排。"),
    ("type", "都不像，我写一句", "如果上面都不贴切，可以写一个短句", "✍️"),
)

_MBTI_EMOJI = {
    "INTJ": "♟️", "INTP": "🧩", "ENTJ": "🧭", "ENTP": "⚡",
    "INFJ": "🌙", "INFP": "🌿", "ENFJ": "🌻", "ENFP": "✨",
    "ISTJ": "📚", "ISFJ": "🕯️", "ESTJ": "🏗️", "ESFJ": "🤝",
    "ISTP": "🛠️", "ISFP": "🎨", "ESTP": "🏃", "ESFP": "🎉",
}
_MBTI_CODES = (
    "INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP",
)
_MBTI_TRAITS_EN = {
    "INTJ": "Architect: imaginative, strategic, private, and long-range; prefers clear plans, competence, and room to think independently",
    "INTP": "Logician: analytical, inventive, concept-driven, and independent; prefers precision, principles, and open-ended exploration",
    "ENTJ": "Commander: decisive, organized, strategic, and outcome-driven; prefers direct momentum, ownership, and ambitious execution",
    "ENTP": "Debater: quick, curious, reframing, and debate-friendly; prefers options, intellectual challenge, and flexible experimentation",
    "INFJ": "Advocate: meaning-oriented, intuitive, private, and idealistic; prefers depth, gentle precision, and values-aligned direction",
    "INFP": "Mediator: values-led, imaginative, inward, and empathetic; prefers authenticity, spaciousness, and personally meaningful work",
    "ENFJ": "Protagonist: people-attuned, encouraging, organizing, and charismatic; prefers shared meaning, relational momentum, and growth",
    "ENFP": "Campaigner: steady, associative, energetic, and novelty-seeking; prefers freedom, possibility, and human connection",
    "ISTJ": "Logistician: steady, practical, factual, and responsible; prefers reliability, standards, clear duties, and proven routines",
    "ISFJ": "Defender: careful, loyal, steady, and protective; prefers safety, continuity, considerate tone, and dependable care",
    "ESTJ": "Executive: practical, directive, structured, and managerial; prefers clear ownership, rules, execution, and visible progress",
    "ESFJ": "Consul: relational, supportive, concrete, and community-minded; prefers harmony, shared expectations, and helpful action",
    "ISTP": "Virtuoso: hands-on, concise, independent, and diagnostic; prefers practical tools, direct feedback, and room to act",
    "ISFP": "Adventurer: aesthetic, gentle, present-focused, and autonomous; prefers lived experience, feeling-respect, and flexible expression",
    "ESTP": "Entrepreneur: action-oriented, adaptive, direct, and perceptive; prefers fast feedback, concrete stakes, and real-world testing",
    "ESFP": "Entertainer: expressive, social, experiential, and vivid; prefers warmth, immediacy, shared energy, and concrete examples",
}
_MBTI_TRAITS_ZH = {
    "INTJ": "架构师：富有想象力和战略性，重视长期规划、独立思考、清晰方案和专业能力",
    "INTP": "逻辑学家：分析性强、喜欢概念和可能性，重视逻辑精度、底层原理和开放探索",
    "ENTJ": "指挥官：果断、有组织、目标驱动，重视战略推进、明确责任和高效执行",
    "ENTP": "辩论家：反应快、好奇、擅长重构问题，重视智力挑战、多种选项和灵活试验",
    "INFJ": "提倡者：关注意义、直觉敏锐、内在深，重视价值一致、温和精确和有方向的改变",
    "INFP": "调停者：价值驱动、想象力强、共情且内省，重视真实感、空间感和有个人意义的事",
    "ENFJ": "主人公：理解他人、鼓舞人心、善于组织，重视共同意义、关系动能和人的成长",
    "ENFP": "活动家：热情、联想丰富、追求新鲜和可能性，重视自由、能量流动和人与人的连接",
    "ISTJ": "物流师：稳定、务实、尊重事实和责任，重视可靠性、清晰标准、职责和成熟流程",
    "ISFJ": "守护者：细致、忠诚、温暖且保护性强，重视安全感、连续性、体贴语气和可靠照顾",
    "ESTJ": "管理者：务实、直接、有结构和管理感，重视明确归属、规则、执行和可见进展",
    "ESFJ": "执政官：关系敏感、支持性强、具体而合群，重视和谐、共同期待和能帮上忙的行动",
    "ISTP": "鉴赏家：动手能力强、简洁、独立、擅长诊断，重视实用工具、直接反馈和行动空间",
    "ISFP": "冒险家：有审美、温和、活在当下且重视自主，重视体验、感受被尊重和自由表达",
    "ESTP": "企业家：行动导向、适应快、直接且敏锐，重视快速反馈、现实筹码和现场试错",
    "ESFP": "表演者：表达力强、社交、体验感强且生动，重视温度、即时性、共同能量和具体例子",
}
_MBTI_TRAITS = _MBTI_TRAITS_EN


def _mbti_choices(language: str = "en") -> tuple[tuple[str, ...], ...]:
    is_zh = _normalize_first_language(language) == "zh"
    traits = _MBTI_TRAITS_ZH if is_zh else _MBTI_TRAITS_EN
    return tuple((value, value, traits[value], _MBTI_EMOJI[value]) for value in _MBTI_CODES) + (
        (
            "not_sure",
            "不确定 / Not sure",
            "先不记录；之后可以再补充。" if is_zh else "Leave it empty for now; you can add it later.",
            "➖",
        ),
    )


_MBTI_CHOICES = _mbti_choices("en")

_GENDER_CHOICES_EN = (
    ("woman", "Woman", "", "♀️"),
    ("man", "Man", "", "♂️"),
    ("skip", "Skip", "", "➖"),
)
_GENDER_CHOICES_ZH = (
    ("女性", "女性", "", "♀️"),
    ("男性", "男性", "", "♂️"),
    ("skip", "跳过", "", "➖"),
)

_HOBBY_CHOICES_EN = (
    ("reading", "Reading", "Books, essays, research, or long-form curiosity", "📚"),
    ("music", "Music", "Listening, playing, collecting, or live shows", "🎧"),
    ("films and shows", "Films / shows", "Movies, series, anime, documentaries", "🎬"),
    ("games", "Games", "Video games, board games, puzzles, or playful systems", "🎮"),
    ("sports and movement", "Sports / movement", "Gym, running, climbing, dancing, walking", "🏃"),
    ("food and cooking", "Food / cooking", "Eating, cooking, baking, coffee, restaurants", "🍳"),
    ("travel and city walks", "Travel / city walks", "Exploring places, routes, neighborhoods, trips", "🧳"),
    ("art and design", "Art / design", "Drawing, photography, visual taste, making things beautiful", "🎨"),
    ("writing", "Writing", "Journaling, essays, fiction, notes, scripts", "✍️"),
    ("technology and making", "Technology / making", "Coding, gadgets, tools, building small systems", "🛠️"),
    ("skip", "Skip", "Leave this blank for now", "➖"),
)
_HOBBY_CHOICES_ZH = (
    ("阅读", "阅读", "书、文章、研究，或长期好奇的问题", "📚"),
    ("音乐", "音乐", "听歌、演奏、收藏、演出", "🎧"),
    ("影视/动画", "影视/动画", "电影、剧集、动画、纪录片", "🎬"),
    ("游戏", "游戏", "电子游戏、桌游、解谜、好玩的系统", "🎮"),
    ("运动/身体活动", "运动/身体活动", "健身、跑步、攀岩、跳舞、散步", "🏃"),
    ("美食/做饭", "美食/做饭", "吃饭、做饭、烘焙、咖啡、探店", "🍳"),
    ("旅行/城市漫步", "旅行/城市漫步", "探索地方、路线、街区和旅程", "🧳"),
    ("艺术/设计", "艺术/设计", "绘画、摄影、审美、把东西做漂亮", "🎨"),
    ("写作", "写作", "日记、文章、小说、笔记、脚本", "✍️"),
    ("技术/创造", "技术/创造", "写代码、小工具、设备、搭系统", "🛠️"),
    ("skip", "暂时留空", "先不记录爱好", "➖"),
)

_INIT_FIELD_MODEL_HINTS = {
    "first_language": {"lens": "identity", "topic": "identity.style.language.first"},
    "preferred_name": {"lens": "identity", "topic": "identity.anchor.name.preferred"},
    "occupation": {"lens": "pulse", "topic": "pulse.chapter.work.role"},
    "gender": {"lens": "identity", "topic": "identity.anchor.gender.self_description"},
    "birth_date": {"lens": "identity", "topic": "identity.anchor.birth.date"},
    "age": {"lens": "identity", "topic": "identity.anchor.age.current"},
    "mbti": {"lens": "identity", "topic": "identity.character.mbti.type"},
    "hobbies": {"lens": "identity", "topic": "identity.style.hobbies.personal"},
    "city": {"lens": "world", "topic": "world.places.city.current"},
    "food_allergies": {"lens": "identity", "topic": "identity.body.allergy.food"},
    "medication_allergies": {"lens": "identity", "topic": "identity.body.allergy.medication"},
    "chronic_conditions": {"lens": "identity", "topic": "identity.body.condition.chronic"},
    "trauma_history": {"lens": "identity", "topic": "identity.body.history.trauma"},
    "safety_boundaries": {"lens": "identity", "topic": "identity.body.safety.boundary"},
    "inferred_companion_posture": {"lens": "identity", "topic": "identity.style.companion.posture"},
}


_STARTER_QUESTIONS = (
    {
        "id": "inner_landscape",
        "lens": "pulse",
        "sub_lens": "existential_state",
        "en": "If your recent inner weather were an image, which one is closest?",
        "zh": "如果把你现在的内心状态想象成一种风景，会是什么样的？",
        "choices_en": (
            ("standing in fog", "Standing in fog", "Not lost, but the horizon has not opened yet; reflect context first, then clarify the next visible step", "🌫️", "Not completely lost, but visibility and direction are not open yet; first confirm the ground underfoot, then gently clarify the next visible step."),
            ("tabs open everywhere", "Tabs open everywhere", "Many thoughts are running in the background; help gather, order, and reduce cognitive load", "🗂️", "Many thoughts or unfinished tasks are open at once; help gather, order, and reduce cognitive load."),
            ("boat resting in harbor", "Boat resting in harbor", "Pausing at shore before setting out again; allow recovery before asking for motion", "⚓", "In a pause, repair, or harboring phase before setting out again; do not push too quickly, allow replenishment and rhythm to return."),
            ("small light ahead", "Small light ahead", "Direction is faint but present; protect the signal and test forward gradually", "🕯️", "A faint but meaningful direction is already visible; protect that signal and use small experiments to make the path clearer."),
            ("type", "None fit; I’ll describe it", "A short image or phrase", "✍️"),
            ("skip", "Leave this blank for now", "", "➖"),
        ),
        "choices_zh": (
            ("像站在起雾的路口", "像站在起雾的路口", "雾还没有散，不是不知道往哪走，只是远处暂时看不清。也许可以先陪你确认脚下，再慢慢等下一步显出来。", "🌫️", "并非完全迷失，而是处在视野未打开、方向暂不清晰的阶段；适合先确认脚下处境，再温和澄清下一步。"),
            ("像房间里开满标签页", "像房间里开满标签页", "脑海里像同时亮着很多窗口，每个都还在发出一点声音。也许先把它们轻轻放到桌面上，会舒服一些。", "🗂️", "近期可能同时承载很多念头和未关闭的任务；适合帮助收束、排序、减轻认知负荷。"),
            ("像一艘船暂时靠岸", "像一艘船暂时靠岸", "不是不再出发，只是船需要靠岸、补给、修整一下。等风向更清楚时，再离岸也不迟。", "⚓", "可能处在修整、恢复或重新出发前的停靠期；不要急着推动，应允许补给和节奏恢复。"),
            ("像远处有一盏小灯", "像远处有一盏小灯", "答案还没有完全出现，但远处已经有一点光。那点光也许很小，却值得先被守住。", "🕯️", "已有微弱但重要的方向感；适合保护这点信号，并用小步试探让方向更清晰。"),
            ("type", "都不像，我自己描述", "写一个短句或画面就好", "✍️"),
            ("skip", "暂时留空", "", "➖"),
        ),
    },
    {
        "id": "value_anchor",
        "lens": "identity",
        "sub_lens": "values_and_meaning",
        "en": "When you make trade-offs lately, what feels most important not to lose?",
        "zh": "最近做取舍时，你最不想弄丢的是什么？",
        "choices_en": (
            ("keep my authorship", "Keep my authorship", "Autonomy and authorship matter in trade-offs; preserve choice space and avoid over-directing", "🧭", "Authorship and autonomy matter in trade-offs; do not over-decide on their behalf, preserve choice space and help them hold the wheel."),
            ("keep the ground steady", "Keep the ground steady", "Safety and certainty matter in trade-offs; reduce collapse risk before optimizing", "🪨", "Safety and certainty are bottom-layer needs in the trade-off; reduce collapse risk and real-world instability before optimizing or taking bigger risks."),
            ("stay true inside", "Stay true inside", "Authenticity and inner consistency matter in trade-offs; slower is better than self-betrayal", "💎", "Authenticity and inner consistency matter; respect the value signal rather than evaluating only by efficiency, gain, or speed."),
            ("protect important people", "Protect important people", "Relationships, promises, and care matter in trade-offs; include responsibility and attachment in the frame", "🤲", "Relationships, promises, and care strongly shape the decision; include emotional responsibility and relational boundaries in the analysis."),
            ("open the future", "Open the future", "Possibility matters in trade-offs; evaluate long-term space, growth, and optionality", "🌱", "Possibility, growth space, and long-term optionality matter; help evaluate which path makes the future wider."),
            ("type", "None fit; I’ll name it", "A short value or phrase", "✍️"),
            ("skip", "Leave this blank for now", "", "➖"),
        ),
        "choices_zh": (
            ("我想保住选择权", "我想保住选择权", "最怕的不是慢一点，而是把方向感交出去。这个选择最好仍然像是你自己做出的。", "🧭", "取舍中很在意自主感和作者性；不要替其下结论，应保留选择空间，帮助重新握住方向盘。"),
            ("我想先踩稳地面", "我想先踩稳地面", "在往前之前，你可能需要先确认地面不会塌。安全感和确定性，是这次取舍里很重要的底色。", "🪨", "安全感和确定性是当前取舍中的底层需求；应先降低坍塌感和现实风险，再谈优化或冒险。"),
            ("我不想背离真心", "我不想背离真心", "有些决定不只是对错，也关乎是否还像自己。宁可慢一点，也不想把真实感弄丢。", "💎", "真实感和内在一致性很重要；需要尊重其价值感，不要只用效率或收益衡量。"),
            ("我想顾住重要的人", "我想顾住重要的人", "这件事不只属于你一个人。关系、承诺、照顾和亏欠感，都可能一起坐在桌边。", "🤲", "关系、承诺和照顾会显著影响判断；应把情感责任和关系边界纳入分析。"),
            ("我想把未来打开", "我想把未来打开", "你在意这个选择会把生活带到哪里。它最好不是关上一扇门，而是让未来多一点空气。", "🌱", "重视可能性、成长空间和长期可选项；应帮助评估哪条路让未来更宽。"),
            ("type", "都不像，我自己命名", "写一个词或短句就好", "✍️"),
            ("skip", "暂时留空", "", "➖"),
        ),
    },
    {
        "id": "pressure_pattern",
        "lens": "identity",
        "sub_lens": "stress_response",
        "en": "When pressure rises, what do you usually do first?",
        "zh": "压力升起来时，你通常会先怎么保护自己？",
        "choices_en": (
            ("retreat into quiet", "Retreat into quiet", "Under pressure, tends to pull inward and process quietly before speaking", "🫧", "Under pressure, low-input and low-interruption inner processing space is needed; offer quiet and buffer before inviting expression."),
            ("comb the knots into lines", "Comb the knots into lines", "Under pressure, tends to use lists, structure, and plans to separate the knots", "🧵", "Under pressure, stability returns through structure, lists, and decomposition; organize the mess into layers and steps."),
            ("get the wheels moving", "Get the wheels moving", "Under pressure, tends to move first and regain stability by adjusting in motion", "🏃", "Under pressure, action restores feel and stability; offer a concrete small step rather than staying in abstract analysis."),
            ("ask where it hurts", "Ask where it hurts", "Under pressure, tends to ask what pain point, value, or meaning is being touched", "🔦", "Under pressure, the deeper pain point, value, or emotion needs to be understood; ask first about meaning and where it hurts."),
            ("borrow another mind", "Borrow another mind", "Under pressure, tends to think with another person rather than metabolize it alone", "👂", "Under pressure, co-thinking and being held matter more than processing alone; provide companionate sorting and shared simulation."),
            ("type", "None fit; I’ll describe it", "A short pattern is enough", "✍️"),
            ("skip", "Leave this blank for now", "", "➖"),
        ),
        "choices_zh": (
            ("先缩回安静里", "先缩回安静里", "压力一来，你可能会先往安静处退一小步。不是逃开，是给自己一点重新听见自己的空间。", "🫧", "压力下需要低输入、低打扰的内在处理空间；应先给安静和缓冲，再邀请表达。"),
            ("先把乱麻理成线", "先把乱麻理成线", "混乱靠近时，你会想把它拆成线、列成项、排出顺序。把看不清的东西变清楚，会让人稳一点。", "🧵", "压力下靠结构、清单和拆解恢复稳定；适合把混乱整理成层次和步骤。"),
            ("先动手让车跑起来", "先动手让车跑起来", "你可能不是等想明白才动，而是在动起来之后找回手感。车先跑起来，方向可以边走边调。", "🏃", "压力下通过行动找回手感和稳定；适合给出可执行的小步，而不是停留在抽象分析。"),
            ("先问这事伤到哪儿", "先问这事伤到哪儿", "你会想知道它到底碰到了哪里：是害怕、委屈、价值感，还是某个一直没被说清的东西。", "🔦", "压力下需要理解被触动的深层痛点、价值或情绪；应先追问意义和伤处。"),
            ("先找个人一起想", "先找个人一起想", "压力太满时，一个人在房间里可能不够。你需要另一个脑子，也需要一个能接住话的人。", "👂", "压力下需要共思和被接住，而不是独自消化；应提供陪伴式梳理和共同推演。"),
            ("type", "都不像，我自己描述", "写一个短句就好", "✍️"),
            ("skip", "暂时留空", "", "➖"),
        ),
    },
    {
        "id": "recovery_style",
        "lens": "identity",
        "sub_lens": "energy_recovery",
        "en": "When your energy is low, what usually helps you return to yourself?",
        "zh": "当你需要恢复精力、让自己舒服一点时，通常会怎么做？",
        "choices_en": (
            ("give me a quiet corner", "Give me a quiet corner", "Low energy recovery starts with quiet space, less input, and no rushing", "🌙", "Recovery needs less input, less rushing, and space that does not require explanation; lower interruption density."),
            ("talk softly for a while", "Talk softly for a while", "Low energy recovery is helped by calm presence and gentle conversation", "🕯️", "Steady presence and low-pressure conversation help the mind land; accompany first, solve second."),
            ("change the body rhythm", "Change the body rhythm", "Low energy recovery is helped by walking, sleep, music, food, or a body-rhythm reset", "🌿", "Body rhythm can lead psychological recovery; consider walking, rest, music, food, or rhythm reset first."),
            ("finish one tiny action", "Finish one tiny action", "Low energy recovery is helped by completing one tiny action and restoring agency", "✅", "Tiny completion restores agency; break suggestions into one very small step that can be completed immediately."),
            ("use beauty and ritual", "Use beauty and ritual", "Low energy recovery is helped by beauty, light, music, order, objects, or small rituals", "✨", "Beauty, order, light, music, objects, or small rituals help return to self; support through sensory and ritualized cues."),
            ("type", "None fit; I’ll name it", "A short recovery cue", "✍️"),
            ("skip", "Leave this blank for now", "", "➖"),
        ),
        "choices_zh": (
            ("给我一块安静角落", "给我一块安静角落", "恢复有时不是被鼓励，而是先少一点声音、少一点催促。你需要一块不必解释自己的安静角落。", "🌙", "恢复时需要少输入、少催促、不必解释自己的空间；应降低打扰密度。"),
            ("陪我轻轻说一会儿", "陪我轻轻说一会儿", "有时候不是要立刻解决什么，只是有人在旁边轻轻说话，心就会慢慢落回身体里。", "🕯️", "通过温和陪伴和低压对话恢复落地感；应先陪伴，再解决。"),
            ("先让身体换个节奏", "先让身体换个节奏", "身体换了节奏，心也会跟着松一点。走路、睡觉、音乐、吃点东西，都可能是一条回来的路。", "🌿", "身体节奏会带动心理恢复；可优先建议散步、休息、音乐、饮食或节奏重置。"),
            ("完成一个很小动作", "完成一个很小动作", "把一件很小的事做完，会像在地上放下一颗钉子：不大，却能让人重新有一点掌控感。", "✅", "微小完成感能帮助恢复掌控；应把建议切成很小、能立刻完成的一步。"),
            ("靠一点美感和仪式", "靠一点美感和仪式", "一点光线、音乐、整理、香气或小物件，能把散掉的自己慢慢召回来。", "✨", "审美、秩序、光线、音乐或小仪式能帮助回到自己；可用更有感官和仪式感的方式支持。"),
            ("type", "都不像，我自己命名", "写一个短句就好", "✍️"),
            ("skip", "暂时留空", "", "➖"),
        ),
    },
    {
        "id": "decision_compass",
        "lens": "identity",
        "sub_lens": "agency_and_decision",
        "en": "When a choice stays unresolved, what usually brings the answer closer?",
        "zh": "当一个选择还悬在那里，什么会让你离答案近一点？",
        "choices_en": (
            ("put trade-offs on paper", "Put trade-offs on paper", "Unresolved choices become clearer when trade-offs are written down and invisible factors become visible", "📝", "Externalizing and writing make hidden weights visible; help list trade-offs, costs, and what must be preserved."),
            ("hear it spoken aloud", "Hear it spoken aloud", "Unresolved choices become clearer when spoken aloud, giving the problem a shape", "🗣️", "Speaking gives the problem shape; use conversational reflection, follow-up questions, and shared naming."),
            ("lay out possible futures", "Lay out possible futures", "Unresolved choices become clearer by laying out possible futures and where each road leads", "🛤️", "Different paths need to be compared as lived future scenes; unfold possible futures rather than only listing pros and cons."),
            ("try one small experiment", "Try one small experiment", "Unresolved choices become clearer through a small reversible experiment before deciding", "🧪", "Reversible experiments are a good way to gather feedback; design low-risk trials rather than forcing a one-shot decision."),
            ("wait for the body signal", "Wait for the body signal", "Unresolved choices become clearer by noticing body signals like relief, resistance, energy, or fatigue", "🌡️", "Body signals help calibrate decisions; pay attention to relief, resistance, excitement, and fatigue."),
            ("type", "None fit; I’ll name it", "A short decision cue", "✍️"),
            ("skip", "Leave this blank for now", "", "➖"),
        ),
        "choices_zh": (
            ("把取舍写到纸上", "把取舍写到纸上", "有些答案要先落到纸上才会显形。把取舍写出来，心里那些看不见的重量就有了位置。", "📝", "靠外化和书写看清选择里的隐形权重；应帮助列出取舍、代价和保留项。"),
            ("说出来听听形状", "说出来听听形状", "话说出口之前，问题像一团雾；说出来以后，它会有边缘、有形状，也更容易被一起看见。", "🗣️", "通过表达来让问题成形；适合用对话复述、追问和共同命名。"),
            ("把几种未来摆开", "把几种未来摆开", "你需要的不只是选项列表，而是看见每条路会把生活带向哪里，哪一种未来更像你。", "🛤️", "需要比较不同路径导向的生活图景；应帮助展开未来场景，而不是只列优缺点。"),
            ("先做一个小实验", "先做一个小实验", "不用一下子把门关死。先试一个可逆的小动作，身体和现实都会给出一点回音。", "🧪", "适合通过可逆试探获得反馈；应设计低风险实验，而不是要求一次性定案。"),
            ("等身体先给信号", "等身体先给信号", "有时候答案不是先从脑子里来，而是从身体里冒出来：放松、抗拒、兴奋，或者忽然很累。", "🌡️", "会用身体感受校准决定；应关注放松、抗拒、兴奋和疲惫等体感线索。"),
            ("type", "都不像，我自己命名", "写一个短句就好", "✍️"),
            ("skip", "暂时留空", "", "➖"),
        ),
    },
)

_SAFETY_PROMPTS = (
    (
        "food_allergies",
        "Food allergies",
        "食物过敏",
        "Anything Elephant Agent should remember before suggesting food, travel, or routines? Leave empty if none.",
        "如果以后聊到饮食、旅行或日常安排，有没有需要避开的食物？没有就留空。",
    ),
    (
        "medication_allergies",
        "Medication allergies",
        "药物过敏",
        "Only write what you want Elephant Agent to avoid mentioning casually. Leave empty if none.",
        "只写你希望 Elephant Agent 之后别随口建议或忽略的部分；没有就留空。",
    ),
    (
        "chronic_conditions",
        "Chronic conditions",
        "慢性疾病等",
        "Optional. This is only for safer, more considerate suggestions — never diagnosis.",
        "可选。只用于让建议更安全、更有分寸；不会用于诊断。",
    ),
    (
        "trauma_history",
        "Secrets you keep inside",
        "不愿给别人说、藏在心里的秘密",
        "Optional. A word or short phrase is enough; leave it empty if you do not want to put it here.",
        "可选。一个词或短句就够；不想放在这里就留空。",
    ),
)
_SAFETY_FIELD_LABELS = {
    field_id: (title_en, title_zh)
    for field_id, title_en, title_zh, _prompt_en, _prompt_zh in _SAFETY_PROMPTS
}
_SAFETY_LABEL_TO_FIELD = {
    label.casefold(): field_id
    for field_id, labels in _SAFETY_FIELD_LABELS.items()
    for label in (field_id, *labels)
}
_SAFETY_FACT_TEMPLATES = {
    "food_allergies": ("食物过敏：{value}。", "Food allergies: {value}."),
    "medication_allergies": ("药物过敏：{value}。", "Medication allergies: {value}."),
    "chronic_conditions": ("健康注意事项：{value}。", "Health notes: {value}."),
    "trauma_history": ("不愿给别人说、藏在心里的秘密：{value}。", "Secrets you keep inside: {value}."),
}


def _init_care_entries(bootstrap_state: object) -> tuple[tuple[str, str], ...]:
    raw = str(getattr(bootstrap_state, "safety_boundaries", "") or "").strip()
    if not raw:
        return ()
    entries: list[tuple[str, str]] = []
    for chunk in raw.replace("；", ";").split(";"):
        part = chunk.strip()
        if not part:
            continue
        label, sep, value = part.partition(":")
        if not sep:
            label, sep, value = part.partition("：")
        if not sep:
            continue
        field_id = _SAFETY_LABEL_TO_FIELD.get(label.strip().casefold())
        cleaned = value.strip()
        if field_id and cleaned:
            entries.append((field_id, cleaned))
    return tuple(entries)


def _print_init_section(language: str, title_en: str, title_zh: str, body_en: str, body_zh: str) -> None:
    title = _init_text(language, title_en, title_zh)
    body = _init_text(language, body_en, body_zh)
    if not _interactive_shell_supported():
        return
    if not RICH_AVAILABLE or Panel is None or Console is None:
        _print_heading(title, body)
        return
    console = Console(highlight=False, soft_wrap=True)
    console.print(Panel(body, title=f"[bold {BRAND_ACCENT}]{title}[/bold {BRAND_ACCENT}]", border_style=BRAND_ACCENT, padding=(1, 2)))


def _starter_question_model_hints(question_id: str) -> dict[str, str]:
    topic_map = {
        "inner_landscape": {"lens": "pulse", "topic": "pulse.mood.inner_landscape"},
        "value_anchor": {"lens": "identity", "topic": "identity.values.trade_off_anchor"},
        "recent_resonance": {"lens": "pulse", "topic": "pulse.mood.recent_resonance"},
        "pressure_pattern": {"lens": "identity", "topic": "identity.character.rhythm.pressure"},
        "recovery_style": {"lens": "identity", "topic": "identity.character.rhythm.recovery"},
        "decision_compass": {"lens": "identity", "topic": "identity.character.decision.compass"},
    }
    return topic_map.get(question_id, {})


def _prompt_starter_question(language: str, spec: dict[str, object]) -> tuple[str, str, str] | None | _WizardBackSignal:
    is_zh = _normalize_first_language(language) == "zh"
    question = str(spec["zh" if is_zh else "en"])
    raw_choices = spec["choices_zh" if is_zh else "choices_en"]
    choices: tuple[WizardChoice, ...] = tuple(
        _init_wizard_choice(item)
        for item in raw_choices  # type: ignore[arg-type]
    )
    answer = _wizard_choice_prompt(
        _init_text(language, "A small door", "一扇小门"),
        question,
        choices,
        default=choices[0].value,
        allow_back=True,
    )
    if answer is WIZARD_CANCEL:
        return WIZARD_CANCEL
    if answer is WIZARD_BACK:
        return WIZARD_BACK
    selected = str(answer).strip()
    if selected == "skip":
        return None
    if selected == "type":
        custom = _wizard_text_prompt(
            _init_text(language, "Say it in your own words", "用自己的话补充"),
            question,
            default=None,
            allow_back=True,
            preserve_default_on_empty=False,
        )
        if custom is WIZARD_CANCEL:
            return WIZARD_CANCEL
        if custom is WIZARD_BACK:
            return WIZARD_BACK
        selected = str(custom).strip()
    if not selected:
        return None
    persisted = _choice_saved_value(tuple(raw_choices), selected)  # type: ignore[arg-type]
    return (str(spec["id"]), question, persisted)


__all__ = tuple(name for name in globals() if not name.startswith("__"))
