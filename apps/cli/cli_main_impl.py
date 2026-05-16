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

from packages.state import DEFAULT_ELEPHANT_IDENTITY_TEXT, render_default_elephant_identity, render_user_profile_text

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
        text = f"{mbti}；{traits}" if traits else mbti
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
        pass
    try:
        from packages.understanding import PersonalModelUnderstandingSurface
    except Exception:
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
        pass
    # Create nightly learning cron jobs
    try:
        _ensure_nightly_learning_crons(runtime)
    except Exception:
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
        pass



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
        display_name = _suggest_elephant_name(runtime)
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
        context_window_tokens = 128_000
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
            display_name=updated_identity.state.display_name,
            personality_preset=personality_preset,
            initiative=initiative,
            mode=updated_identity.state.mode,
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
        from dataclasses import replace as _dc_replace
        profile_state = runtime.repository.load_personal_model_runtime_state(first_elephant.personal_model_id)
        if profile_state is not None:
            runtime.repository.upsert_personal_model_runtime_state(
                _dc_replace(profile_state, learning_intensity=learning_intensity)
            )
    except Exception:
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
    report = runtime.provider_doctor()
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
        except RuntimeError as error:
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
    """Remove the former built-in diary cron; diary now runs inside Dream."""
    for job in runtime.cron_runtime.list_jobs():
        if job.action_kind != "learning":
            continue
        if job.payload.get("trigger") != "diary":
            continue
        name = str(getattr(job, "name", "") or "").strip().lower()
        summary = str(job.payload.get("summary") or "").strip().lower()
        if name == "daily diary" or summary == "daily diary entry for yesterday":
            runtime.cron_runtime.remove_job(job.job_id)


def _ensure_dream_cron(runtime: CliRuntime) -> None:
    """Create the nightly dream consolidation cron job if it doesn't already exist."""
    _remove_former_diary_crons(runtime)
    existing = runtime.cron_runtime.list_jobs()
    for job in existing:
        if job.payload.get("trigger") == "dream" and job.action_kind == "learning":
            return
    runtime.cron_runtime.create_job(
        name="Nightly dream",
        schedule_text="every day at 1am",
        payload={
            "action_kind": "learning",
            "trigger": "dream",
            "summary": "nightly Personal Model, question, skill, and diary maintenance",
            "metadata": {"features": "dream,questions,skills,diary"},
        },
    )


def _ensure_nightly_learning_crons(runtime: CliRuntime) -> None:
    """Create the single built-in nightly learning cron job."""
    _ensure_dream_cron(runtime)


def _run_grow(runtime: CliRuntime, args: argparse.Namespace) -> int:
    # Wake gate only needs "provider profile + credentials configured".
    # Skip deep checks (live model catalog + LLM probe) that added 10+ s
    # of network stall before the elephant-selection prompt could appear.
    report = runtime.provider_doctor(deep=False)
    if not _provider_session_ready(report):
        _print_grow_blocked(runtime)
        return 1

    try:
        session_id, opened = _resolve_growth_session(
            runtime,
            session_id=getattr(args, "session_id", None),
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
        runtime.prepare_session_surface(session_id)
        try:
            outcome = runtime.explain_next_step(session_id=session_id, prompt=args.message)
        except RuntimeError as error:
            _print_provider_turn_failed(runtime, error, session_id=session_id)
            return 1
        _print_assistant_turn(runtime, outcome)
        return 0

    if _interactive_shell_supported():
        return ProductizedShell(runtime, session_id=session_id, opened=opened, debug=args.debug).run()
    runtime.prepare_session_surface(session_id)
    return _run_stream_grow_loop(runtime, session_id, sys.stdin)

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


def _eval_output_dir(dataset: str) -> Path:
    normalized = str(dataset or "eval").strip().lower().replace("-", "_")
    return Path.cwd() / "_temp" / "evals" / normalized


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
        help="Elephant Agent CLI with explicit init, wake, dashboard, herd, provider, eval, Personal Model recall, learn, skills, gateway, cron, and status entrypoints.",
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

    @app.command("eval")
    def eval_command(
        ctx: typer.Context,
        dataset: str = typer.Option("locomo_refined", "--dataset", help="Dataset adapter: locomo or locomo_refined."),
        dataset_path: Path | None = typer.Option(None, "--dataset-path", help="Path to LoCoMo file or LoCoMo-Refined public directory."),
        output_dir: Path | None = typer.Option(None, "--output-dir", help="Directory for report.json, report.md, predictions, and traces."),
        top_k: int = typer.Option(5, "--top-k", help="Number of retrieved evidence hits per question."),
        limit_conversations: int | None = typer.Option(None, "--limit-conversations", help="Optional conversation cap for smoke runs."),
        limit_questions: int | None = typer.Option(None, "--limit-questions", help="Optional question cap for smoke runs."),
        model_role: str = typer.Option("strong", "--model-role", help="Configured model role to use for answer generation."),
        answer_concurrency: int = typer.Option(1, "--answer-concurrency", help="Concurrent model answer calls per conversation."),
        answer_batch_size: int = typer.Option(1, "--answer-batch-size", help="Questions per model answer request."),
    ) -> None:
        params = ctx.parent.params if ctx.parent is not None else ctx.params
        runtime = _cli_runtime(params["state_dir"])
        active_profile = runtime.model_provider.active_profile()
        if active_profile is None:
            raise typer.BadParameter("elephant eval requires an active provider profile; run `elephant provider` or `elephant init` first")
        evidence_retriever = getattr(runtime.recall_runtime, "evidence_retriever", None)
        embedding_service = getattr(evidence_retriever, "embedding_service", None)
        if embedding_service is None:
            raise typer.BadParameter("elephant eval requires a configured embedding service")
        from packages.evals.cli import default_dataset_path, print_eval_output, run_eval
        from packages.evals.contracts import EvalRunConfig

        resolved_dataset_path = Path(dataset_path).expanduser() if dataset_path is not None else default_dataset_path(dataset)
        resolved_output_dir = Path(output_dir).expanduser() if output_dir is not None else _eval_output_dir(dataset)
        config = EvalRunConfig(
            dataset=dataset,
            dataset_path=str(resolved_dataset_path),
            output_dir=str(resolved_output_dir),
            top_k=top_k,
            retrieval_mode="hybrid",
            answer_mode="model",
            answer_concurrency=answer_concurrency,
            answer_batch_size=answer_batch_size,
            limit_conversations=limit_conversations,
            limit_questions=limit_questions,
        )
        try:
            output = run_eval(
                config,
                embedding_service=embedding_service,
                model_provider=runtime.model_provider,
                profile=runtime.current_profile().state,
                model_role=model_role,
            )
        except Exception as error:
            raise typer.BadParameter(str(error)) from error
        print_eval_output(output)
        raise typer.Exit(0)

    @app.command("wake")
    def wake_command(
        ctx: typer.Context,
        elephant_id: str | None = typer.Option(None, "--elephant-id", help="Open the latest session for a known elephant."),
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
        features: str | None = typer.Option(None, "--features", help="Comma-separated feature set (pm,questions,dream,diary,skills,recall,compress)."),
        date: str | None = typer.Option(None, "--date", help="Target date for dream/diary feature (YYYY-MM-DD). Defaults to today for dream and yesterday for diary."),
        wait: bool = typer.Option(False, "--wait", help="Wait for the reflect agent to finish."),
        install_cron: bool = typer.Option(False, "--install-cron", help="Install the built-in nightly Dream learning cron job."),
    ) -> None:
        """Run a reflect agent with the specified features."""
        from datetime import date as date_type, timedelta

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

        extra_metadata: dict[str, str] = {}
        trigger = "manual"
        if features:
            extra_metadata["features"] = features.strip()
            feature_set = set(f.strip() for f in features.split(",") if f.strip())
            if "dream" in feature_set:
                trigger = "dream" if feature_set == {"dream"} else "manual"
                extra_metadata["target_date"] = date or date_type.today().isoformat()
                if feature_set == {"dream"}:
                    extra_metadata["diary_target_date"] = date or (date_type.today() - timedelta(days=1)).isoformat()
            if "diary" in feature_set:
                trigger = "diary" if feature_set == {"diary"} else "manual"
                target_date = date or (date_type.today() - timedelta(days=1)).isoformat()
                if "dream" in feature_set:
                    extra_metadata["diary_target_date"] = target_date
                else:
                    extra_metadata["target_date"] = target_date
        try:
            job = _queue_learning_job(
                runtime,
                elephant_id=elephant_id,
                trigger=trigger,
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
                        f"trigger · {trigger}",
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
