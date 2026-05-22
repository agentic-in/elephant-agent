"""Prompt-section helpers for model runtime context updates."""

from __future__ import annotations

from dataclasses import replace

from packages.contracts.runtime import ContextBundle, PromptEnvelope


def context_with_fallback_tool_prompt(
    context: ContextBundle,
    prompt: str,
) -> ContextBundle:
    normalized = prompt.strip()
    if not normalized:
        return context
    envelope = context.prompt_envelope
    return replace(
        context,
        prompt_envelope=PromptEnvelope(
            frozen_prefix=append_prompt_section(envelope.frozen_prefix, normalized),
            session_snapshot=envelope.session_snapshot,
            loop_context=envelope.loop_context,
            messages=envelope.messages,
        ),
        rendered_prompt=append_prompt_section(
            context.rendered_prompt or "",
            normalized,
        ),
    )


def append_prompt_section(current: str, section: str) -> str:
    existing = str(current or "").strip()
    if not existing:
        return section
    if section in existing:
        return existing
    return f"{existing}\n\n{section}"


__all__ = ["append_prompt_section", "context_with_fallback_tool_prompt"]
