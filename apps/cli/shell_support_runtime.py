"""Support classes and helper functions for the productized shell."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import re

from .shell_stack import (
    Completion,
    Completer,
    Document,
)


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    kind: str
    title: str
    body: str
    meta: str = ""


@dataclass(frozen=True, slots=True)
class _PendingFileReview:
    path: Path
    before_text: str | None


@dataclass(frozen=True, slots=True)
class PendingShellCommand:
    command: str
    display_command: str = ""
    event_payload: Mapping[str, str] = field(default_factory=dict)


def coerce_pending_shell_command(value: object) -> PendingShellCommand:
    if isinstance(value, PendingShellCommand):
        return value
    command = str(getattr(value, "command", value) or "")
    display_command = str(getattr(value, "display_command", "") or "")
    payload = getattr(value, "event_payload", None)
    if isinstance(payload, Mapping):
        event_payload = {str(key): str(item) for key, item in payload.items()}
    else:
        event_payload = {}
    return PendingShellCommand(
        command=command,
        display_command=display_command,
        event_payload=event_payload,
    )


@dataclass(frozen=True, slots=True)
class ShellCommandSpec:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class SkillSlashSpec:
    command: str
    skill_id: str
    display_name: str
    summary: str
    aliases: tuple[str, ...] = ()
    trigger_phrases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


def _skill_metadata_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        raw_items = tuple(value)
    else:
        text = str(value).strip()
        if not text:
            return ()
        raw_items = tuple(segment.strip() for segment in text.split(","))
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        token = str(item).strip().strip("\"'")
        if not token:
            continue
        dedupe_key = token.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(token)
    return tuple(normalized)


def _normalize_skill_match_text(value: str) -> str:
    normalized = value.strip().lower().replace("/", " ").replace("_", " ").replace("-", " ")
    normalized = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())


def _skill_phrase_in_message(message: str, phrase: str) -> bool:
    normalized_message = _normalize_skill_match_text(message)
    normalized_phrase = _normalize_skill_match_text(phrase)
    if not normalized_phrase:
        return False
    if re.search(r"[\u4e00-\u9fff]", normalized_phrase):
        return normalized_phrase in normalized_message
    return f" {normalized_phrase} " in f" {normalized_message} "


def _completion(text: str, *, start_position: int, display: str, meta: str = "") -> Completion:
    try:
        return Completion(text, start_position=start_position, display=display, display_meta=meta)
    except TypeError:  # pragma: no cover - fallback signature
        return Completion(text, start_position=start_position, display=display)


class ShellCompleter(Completer):
    def __init__(self, shell: "ProductizedShell") -> None:
        self.shell = shell

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor
        stripped = text.lstrip()
        if not stripped.startswith("/"):
            return
        words = stripped.split()
        current_word = document.get_word_before_cursor(WORD=True)
        if not words:
            return
        command = words[0]
        if len(words) <= 1 and not text.endswith(" "):
            for spec in self.shell.command_specs:
                if spec.name.startswith(command):
                    yield _completion(
                        spec.name,
                        start_position=-len(current_word),
                        display=spec.name,
                        meta=spec.description,
                    )
            return

        if command == "/tools":
            candidates = (
                ("inspect", "Show metadata for one tool"),
                ("enable", "Enable a tool for this elephant"),
                ("disable", "Disable a tool for this elephant"),
                ("install", "Load a tool manifest into this elephant"),
                ("run", "Run a tool with explicit key=value arguments"),
            )
        elif command == "/skills":
            candidates = (
                ("list", "List discoverable skill packages from local shelves"),
                ("active", "Show currently active installed skills"),
                ("search", "Search installable skill packages from local shelves"),
                ("view", "Load one skill package and show its instructions"),
                ("inspect", "Alias for view"),
                ("enable", "Enable a skill for this elephant"),
                ("disable", "Disable a skill for this elephant"),
                ("install", "Install a skill package or manifest into this elephant"),
            )
        elif command == "/learn":
            candidates = (
                ("queue", "Queue learning for this episode"),
                ("run", "Queue learning and run the worker once now"),
                ("start", "Start the detached learning worker"),
                ("status", "Show recent learning jobs for this episode"),
                ("history", "Show recent learning jobs across herd"),
            )
        elif command == "/gateway":
            candidates = (
                ("status", "Show gateway setup guidance"),
                ("setup", "Open the CLI gateway setup command guidance"),
                ("doctor", "Show gateway doctor command guidance"),
            )
        elif command == "/providers":
            candidates = (
                (
                    "configure",
                    "Choose a provider, endpoint, key, model, and context window",
                ),
                ("status", "Show the active provider configuration"),
                ("list", "List supported provider catalogs"),
            )
        elif command == "/models":
            candidates = (
                ("configure", "Choose the active model and context window"),
                ("status", "Show the active model configuration"),
                ("list", "List models exposed by the active provider endpoint"),
            )
        elif command == "/cron":
            candidates = (
                ("create", "Create a scheduled prompt task"),
                ("inspect", "Show one cron job"),
                ("pause", "Pause a cron job"),
                ("resume", "Resume a paused cron job"),
                ("remove", "Remove a cron job"),
            )
        else:
            return

        for value, description in candidates:
            if value.startswith(current_word):
                yield _completion(
                    value,
                    start_position=-len(current_word),
                    display=value,
                    meta=description,
                )


__all__ = [
    "TranscriptEntry",
    "_PendingFileReview",
    "PendingShellCommand",
    "coerce_pending_shell_command",
    "ShellCommandSpec",
    "SkillSlashSpec",
    "_skill_metadata_values",
    "_normalize_skill_match_text",
    "_skill_phrase_in_message",
    "_completion",
    "ShellCompleter",
]
