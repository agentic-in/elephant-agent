"""Contextual renderers for OpenQuestion text on user-facing surfaces."""

from __future__ import annotations

from typing import Any, Sequence

from packages.contracts import OpenQuestion


_LEADS = {
    "en": {
        "opener": {
            "high": "I've been holding one delicate thread — only if it feels okay: ",
            "medium": "A small thing I'm curious about, if it fits the moment: ",
            "low": "Before we pick up, one light question: ",
        },
        "idle": "I have a small question — no rush to answer; this just felt like a useful thread to keep steady: ",
    },
    "zh": {
        "opener": {
            "high": "我这里轻轻捧着一个有点细的问题；如果此刻合适的话：",
            "medium": "有个小小的线头，我想更懂一点：",
            "low": "继续之前，我想轻轻问一句：",
        },
        "idle": "不用立刻回答，只是这条线索我想替你轻轻留着：",
    },
}

_LENS_NOUN = {
    "en": {
        "trait": "the way you move through things",
        "chapter": "the season you're in",
        "rapport": "how we should sit beside each other",
        "knowledge": "the world around you",
    },
    "zh": {
        "trait": "你做事和感受世界的方式",
        "chapter": "你此刻所处的人生段落",
        "rapport": "我们怎样并肩会更舒服",
        "knowledge": "你身边重要的人、事和世界",
    },
}

_SUB_LENS_QUESTIONS = {
    "en": {
        "big_five.conscientiousness": "when things get messy, do you usually want a clear checklist first, or room to explore before structure?",
        "big_five.extraversion": "when your energy is low, do you think better by talking it through or by having quiet space first?",
        "big_five.agreeableness": "when I disagree or push back, should I be very direct, or soften the landing a little?",
        "feedback_preference": "when you ask for help, do you want options first, a recommendation first, or questions first?",
        "autonomy_boundary": "what should I avoid pushing on unless you clearly invite me in?",
        "communication_culture": "do you prefer me to say things explicitly, or leave more room for implication and context?",
    },
    "zh": {
        "big_five.conscientiousness": "事情变乱的时候，你更希望我先给清单和步骤，还是先陪你把可能性摊开？",
        "big_five.extraversion": "你能量低的时候，是说出来一点更容易恢复，还是先安静一会儿更有用？",
        "big_five.agreeableness": "如果我不同意你，应该直接说，还是先把语气放软一点？",
        "feedback_preference": "你找我一起想事时，更想先看选项、先听推荐，还是先被问几个问题？",
        "autonomy_boundary": "哪些地方我不要主动往前推，除非你先邀请我进去？",
        "communication_culture": "你更喜欢我把话说得明一点，还是多留一点上下文和余地？",
    },
}


def render_opener(
    question: OpenQuestion,
    *,
    language: str = "en",
    facts: Sequence[Any] = (),
) -> str:
    lang = _language(language)
    lead = _LEADS[lang]["opener"].get(question.sensitivity, _LEADS[lang]["opener"]["low"])
    return lead + contextualize_question(
        question,
        language=lang,
        surface="opener",
        facts=facts,
    )


def render_idle_push(
    question: OpenQuestion,
    *,
    language: str = "en",
    facts: Sequence[Any] = (),
) -> str:
    lang = _language(language)
    seed = _display_question_seed(question, lang)
    if not seed:
        seed = contextualize_question(
            question,
            language=lang,
            surface="idle",
            facts=facts,
        )
    seed = _ensure_question_mark(seed, lang)
    return seed


def render_session_hint(
    questions: Sequence[OpenQuestion],
    *,
    language: str = "en",
    facts: Sequence[Any] = (),
) -> str:
    """Prompt hint for the chat model; never forces a questionnaire turn."""
    visible = list(questions[:1])
    if not visible:
        return ""
    lang = _language(language)
    bullets = "\n".join(
        f"- ({q.sensitivity}) {contextualize_question(q, language=lang, surface='session', facts=facts)}"
        for q in visible
    )
    if lang == "zh":
        return (
            "这里有一个可以顺带理解用户的开放问题。只在对话自然走到这里时，用自己的话轻轻问；"
            "不要照抄模板，也不要像问卷。若用户回答，用 tool.personal_model.update 写成一个四 lens claim：\n" + bullets
        )
    return (
        "One open question may help you understand the user. Ask it only when the conversation naturally opens a door; "
        "rewrite it in your own voice, never as a survey. If the user answers, write it through tool.personal_model.update as one four-lens claim:\n"
        + bullets
    )


def contextualize_question(
    question: OpenQuestion,
    *,
    language: str = "en",
    surface: str = "session",
    facts: Sequence[Any] = (),
) -> str:
    lang = _language(language)
    preferred_name = _preferred_name(facts)
    lens_noun = _LENS_NOUN[lang].get(question.lens, _LENS_NOUN[lang]["knowledge"])
    seed = _display_question_seed(question, lang)
    intent = str(question.metadata.get("question_intent") or question.rationale or "").strip()
    rationale = _soft_reason(seed or intent, limit=86 if lang == "zh" else 110)
    if lang == "zh":
        name_prefix = f"{preferred_name}，" if preferred_name else ""
        if question.source == "ambiguity":
            return f"{name_prefix}我好像同时听见了两种线索。关于{lens_noun}，你更希望我怎么理解才不跑偏？"
        if question.source == "contextual":
            return f"{name_prefix}刚才那条关于{lens_noun}的线索有点发光。你愿意多给我一小块背景吗？"
        if rationale:
            return f"{name_prefix}为了以后更贴近你，我想慢慢理解{lens_noun}：{_ensure_question_mark(rationale, lang)}"
        return f"{name_prefix}关于{lens_noun}，有什么是你希望我以后自然记得的？"
    name_prefix = f"{preferred_name}, " if preferred_name else ""
    if question.source == "ambiguity":
        return f"{name_prefix}I may be holding two different signals. Around {lens_noun}, how should I understand you so I don't drift?"
    if question.source == "contextual":
        return f"{name_prefix}that thread around {lens_noun} feels worth keeping steady. Would you like to give me one more piece of context?"
    if rationale:
        return f"{name_prefix}so I can meet you with a little more precision around {lens_noun}: {_ensure_question_mark(rationale, lang)}"
    return f"{name_prefix}what should I quietly learn about {lens_noun} for next time?"


def _language(language: str) -> str:
    normalized = str(language or "").strip().lower()
    return "zh" if normalized.startswith("zh") else "en"


def _display_question_seed(question: OpenQuestion, language: str) -> str:
    mapped = _SUB_LENS_QUESTIONS[language].get(str(question.sub_lens or ""))
    if mapped:
        return mapped
    samples = str(question.metadata.get("sample_phrasings") or "").strip()
    if samples:
        return samples.split("|")[0].strip()
    return str(question.metadata.get("seed_text") or question.text or "").strip()


def _preferred_name(facts: Sequence[Any]) -> str:
    for fact in facts:
        field = str(getattr(fact, "metadata", {}).get("field", "") or "")
        text = str(getattr(fact, "text", "") or "").strip()
        if field == "preferred_name":
            for marker in ("：", ":", "called "):
                if marker in text:
                    return text.rsplit(marker, 1)[-1].strip(" .。")[:40]
            return text[:40]
    return ""


def _soft_reason(text: str, *, limit: int) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    lowered = cleaned.lower()
    for prefix in ("no observation under ", "contextual follow-up", "coverage gap"):
        if lowered.startswith(prefix):
            return ""
    if lowered.startswith(("determines ", "calibrates ")):
        return ""
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _ensure_question_mark(text: str, language: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped.endswith(("?", "？")):
        return stripped
    return stripped + ("？" if language == "zh" else "?")


__all__ = [
    "contextualize_question",
    "render_opener",
    "render_idle_push",
    "render_session_hint",
]
