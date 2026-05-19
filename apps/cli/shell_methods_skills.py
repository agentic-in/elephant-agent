"""Bound methods extracted from apps/cli/shell.py."""

from __future__ import annotations


from packages.skills import skill_provenance_fields
from .shell_stack import (
    Console,
    Document,
    RICH_AVAILABLE,
)
from .shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    COMMAND_PALETTE_VISIBLE_ROWS,
    ELEPHANT_STAGE_ROWS,
    GROWTH_HIGHLIGHT_FG,
    GROWTH_PROGRESS_EMPTY,
    GROWTH_PROGRESS_FILLED,
    GROWTH_PROGRESS_WIDTH,
    HATCHLING_HEAD_ROWS,
    HATCHLING_STAGE_ROWS,
    QUEUE_PREVIEW_INSET,
    SCOUT_STAGE_ROWS,
    SEED_STAGE_ROWS,
    SHELL_WELCOME_HEADLINE,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
    centered_elephant_rows as _centered_elephant_rows,
    display_width as _display_width,
    render_elephant_mark,
)

__all__ = [
    "BRAND_ACCENT",
    "BRAND_ACCENT_STRONG",
    "BRAND_DARK",
    "BRAND_LIGHT",
    "BRAND_MUTED",
    "COMMAND_PALETTE_VISIBLE_ROWS",
    "Console",
    "Document",
    "ELEPHANT_STAGE_ROWS",
    "GROWTH_HIGHLIGHT_FG",
    "GROWTH_PROGRESS_EMPTY",
    "GROWTH_PROGRESS_FILLED",
    "GROWTH_PROGRESS_WIDTH",
    "HATCHLING_HEAD_ROWS",
    "HATCHLING_STAGE_ROWS",
    "HATCHLING_STAGE_ROWS",
    "PendingShellCommand",
    "ProductizedShell",
    "QUEUE_PREVIEW_INSET",
    "RICH_AVAILABLE",
    "SCOUT_STAGE_ROWS",
    "SEED_STAGE_ROWS",
    "SHELL_WELCOME_HEADLINE",
    "ShellCompleter",
    "TranscriptEntry",
    "USER_HISTORY_BG",
    "USER_HISTORY_FG",
    "_centered_elephant_rows",
    "_display_width",
    "render_elephant_mark",
]


from .shell_support_runtime import *  # noqa: F401,F403


def recent_session_ids(self) -> tuple[str, ...]:
    return tuple(session.episode_id for session in self.runtime.recent_sessions(limit=8))


def recent_elephant_ids(self) -> tuple[str, ...]:
    return tuple(elephant.elephant_id for elephant in self.runtime.list_herd(limit=8))


def skill_slash_specs(self) -> tuple[SkillSlashSpec, ...]:
    return self._skill_slash_specs


def _refresh_skill_slash_specs(self) -> None:
    self._skill_slash_specs = self._load_skill_slash_specs()


def _load_skill_slash_specs(self) -> tuple[SkillSlashSpec, ...]:
    reserved = {spec.name.removeprefix("/").lower() for spec in self.command_specs}
    specs: list[SkillSlashSpec] = []
    seen: set[str] = set()
    for entry in self.runtime.list_skill_hub(limit=None):
        slug = str(entry.metadata.get("slash_command") or "").strip().lower()
        if not slug or slug in reserved or slug in seen:
            continue
        specs.append(
            SkillSlashSpec(
                command=f"/{slug}",
                skill_id=entry.skill_id,
                display_name=entry.display_name,
                summary=entry.summary,
                aliases=_skill_metadata_values(entry.metadata.get("aliases")),
                trigger_phrases=_skill_metadata_values(entry.metadata.get("trigger_phrases")),
                keywords=_skill_metadata_values(entry.metadata.get("keywords")),
            )
        )
        seen.add(slug)
    return tuple(specs)


def _resolve_skill_slash_spec(self, command: str) -> SkillSlashSpec | None:
    normalized = command.strip().lower().replace("_", "-")
    for spec in self._skill_slash_specs:
        if spec.command == normalized:
            return spec
    return None


def _resolve_explicit_skill_request(self, message: str) -> SkillSlashSpec | None:
    if not message.strip():
        return None
    scored: list[tuple[int, SkillSlashSpec]] = []
    for spec in self._load_skill_slash_specs():
        score = 0
        slash_token = spec.command.lower()
        if slash_token in message.lower():
            score = max(score, 140)
        direct_phrases = (
            spec.skill_id,
            spec.skill_id.replace("_", "-"),
            spec.display_name,
            *spec.aliases,
        )
        for phrase in direct_phrases:
            if _skill_phrase_in_message(message, phrase):
                score = max(score, 120)
        if _skill_phrase_in_message(message, f"skill {spec.skill_id}"):
            score = max(score, 130)
        if _skill_phrase_in_message(message, f"skill {spec.display_name}"):
            score = max(score, 130)
        if score > 0:
            scored.append((score, spec))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1].skill_id))
    top_score, top_spec = scored[0]
    if len(scored) > 1 and scored[1][0] == top_score:
        return None
    return top_spec


def _resolve_contextual_skill_request(self, message: str) -> SkillSlashSpec | None:
    if not message.strip():
        return None
    scored: list[tuple[int, SkillSlashSpec]] = []
    for spec in self._load_skill_slash_specs():
        score = 0
        for phrase in spec.trigger_phrases:
            if _skill_phrase_in_message(message, phrase):
                score = max(score, 90)
        keyword_hits = sum(1 for keyword in spec.keywords if _skill_phrase_in_message(message, keyword))
        if keyword_hits >= 2:
            score = max(score, 60 + (keyword_hits * 10))
        if score > 0:
            scored.append((score, spec))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1].skill_id))
    top_score, top_spec = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0
    if top_score < 80 or top_score < second_score + 15:
        return None
    return top_spec


def _resolved_skill_route(self, message: str) -> tuple[SkillSlashSpec, str] | None:
    del self
    del message
    return None


def _dispatch_skill_slash_command(self, raw_command: str, command: str, args: list[str]) -> bool:
    spec = self._resolve_skill_slash_spec(command)
    if spec is None:
        return False
    try:
        skill = self.runtime.inspect_skill(spec.skill_id, session_id=self.session_id)
    except Exception as error:
        self._append_entry("recovery", "Skill command", str(error), meta=command)
        return True
    if not args:
        lines = [
            f"display_name: {skill.display_name}",
            f"skill_id: {skill.skill_id}",
            f"summary: {skill.summary}",
            f"run: {spec.command} <instruction>",
        ]
        installed = skill.metadata.get("installed")
        if isinstance(installed, bool):
            lines.append(f"installed: {installed}")
        self._append_entry("status", "Skill loaded", "\n".join(lines), meta=spec.command)
        return True

    user_instruction = " ".join(args).strip()
    if not user_instruction:
        self._append_entry("recovery", "Skill command", f"Usage: {spec.command} <instruction>")
        return True
    self._append_entry("user", "You", raw_command)
    self._render_pending_entries()
    prompt = self._compose_skill_turn_prompt(skill, user_instruction=user_instruction)
    try:
        outcome = self._run_turn_with_progress(prompt)
    except Exception as error:
        self._append_entry(
            "recovery",
            "Skill command failed",
            f"{error}\ncommand: {spec.command}",
        )
        return True
    self._append_outcome(outcome)
    growth_update = self._show_growth_celebration_if_needed()
    self._append_growth_update_message(growth_update)
    self._append_latest_learning_result()
    return True


def _compose_skill_turn_prompt(self, skill, *, user_instruction: str) -> str:
    return "\n".join(
        [
            f'[SYSTEM: This turn references the "{skill.display_name}" skill from the frozen skill index.]',
            "",
            f"Skill: {skill.display_name} ({skill.skill_id})",
            f"Summary: {skill.summary}",
            "The full skill body is not injected automatically. Use only the skill identity and summary unless the operator separately inspects the skill.",
            "",
            f"User request: {user_instruction}",
        ]
    ).strip()


def _append_skills(self, args: list[str]) -> None:
    command = args[0] if args else "list"
    if command in {"list", "ls"}:
        entries = self.runtime.list_skill_hub(limit=24)
        lines = [
            f"{_display_skill_reference(entry)} | {entry.display_name} | source={entry.source_id} | {entry.summary}"
            for entry in entries
        ] or ["<empty>"]
        lines.extend(
            [
                "",
                "active installed skills: /skills active",
                "operator search public sources: /skills search <query>",
                "view local or operator-reviewed source: /skills view <skill-id|reference>",
                "enable: /skills enable <skill-id>",
                "disable: /skills disable <skill-id>",
                "operator install from source: /skills install <skill-id|reference>",
                "install from path: /skills install </path/to/skill-or-skills.json>",
            ]
        )
        self._append_entry("notice", "Skills", "\n".join(lines))
        return
    if command == "active":
        skills = self.runtime.skill_catalog(session_id=self.session_id)
        lines = [
            f"{skill.skill_id} | enabled={skill.enabled} | {skill.display_name} | {skill.summary}"
            for skill in skills
            if skill.enabled
        ] or ["<empty>"]
        self._append_entry("notice", "Active skills", "\n".join(lines))
        return
    if command == "search":
        if len(args) < 2:
            self._append_entry("recovery", "Skills", "Usage: /skills search <query>")
            return
        query = " ".join(args[1:]).strip()
        local_entries = self.runtime.search_skill_hub(query, limit=12)
        external_entries = self.runtime.search_skill_sources(query, limit=12)
        lines: list[str] = []
        if local_entries:
            lines.append("local shelves:")
            lines.extend(
                f"- {_display_skill_reference(entry)} | {entry.display_name} | source={entry.source_id} | {entry.summary}"
                for entry in local_entries
            )
        if external_entries:
            if lines:
                lines.append("")
            lines.append("external sources:")
            lines.extend(
                f"- {entry.reference} | {entry.display_name} | source={entry.source_id} | trust={entry.trust_level or '<unknown>'} | {entry.summary}"
                for entry in external_entries
            )
        if not lines:
            lines.append("<empty>")
        lines.extend(
            [
                "",
                "install one: /skills install <skill-id|reference>",
                "view one: /skills view <skill-id|reference>",
            ]
        )
        self._append_entry("notice", "Skill search", "\n".join(lines))
        return
    if command in {"inspect", "view"}:
        if len(args) < 2:
            self._append_entry("recovery", "Skills", "Usage: /skills view <skill-id|reference>")
            return
        try:
            skill = self.runtime.inspect_skill_source(args[1], session_id=self.session_id)
        except Exception as error:
            self._append_entry("recovery", "Skills", str(error))
            return
        lines = [
            f"skill_id: {skill.skill_id}",
            f"display_name: {skill.display_name}",
            f"enabled: {skill.enabled}",
            f"version: {skill.version}",
            f"summary: {skill.summary}",
            f"provenance: {skill.provenance or 'built-in'}",
        ]
        installed = skill.metadata.get("installed")
        if isinstance(installed, bool):
            lines.append(f"installed: {installed}")
        lines.extend(_skill_provenance_lines(skill.metadata))
        slash_command = str(skill.metadata.get("slash_command") or "").strip()
        if slash_command:
            lines.append(f"slash_command: /{slash_command}")
        if skill.instruction_text.strip():
            lines.extend(["", skill.instruction_text.strip()])
        self._append_entry(
            "status",
            "Skill",
            "\n".join(lines),
        )
        return
    if command in {"enable", "disable"}:
        if len(args) < 2:
            self._append_entry("recovery", "Skills", f"Usage: /skills {command} <skill-id>")
            return
        try:
            updated = self.runtime.set_skill_enabled(
                args[1],
                command == "enable",
                session_id=self.session_id,
            )
        except Exception as error:
            self._append_entry("recovery", "Skills", str(error))
            return
        self._append_entry("status", "Skill updated", f"{updated.skill_id}\nenabled: {updated.enabled}")
        return
    if command == "install":
        if len(args) < 2:
            self._append_entry(
                "recovery",
                "Skills",
                "Usage: /skills install <skill-id|/path/to/skill|/path/to/skills.json>",
            )
            return
        try:
            result = self.runtime.install_skill_source(args[1], session_id=self.session_id)
        except Exception as error:
            self._append_entry("recovery", "Skills", str(error))
            return
        self._append_entry(
            "status",
            "Skill installed",
            "\n".join(_skill_install_lines(result)),
        )
        self._refresh_skill_slash_specs()
        return
    self._append_entry(
        "recovery",
        "Skills",
        "Usage: /skills [list|active|search|view|enable|disable|install]",
    )


def _skill_provenance_lines(metadata) -> list[str]:
    return [f"{label}: {value}" for label, value in skill_provenance_fields(metadata)]


def _display_skill_reference(entry) -> str:
    if getattr(entry, "source_id", "") == "builtin":
        return str(getattr(entry, "skill_id", "")).strip() or str(getattr(entry, "reference", ""))
    return str(getattr(entry, "reference", "")).strip()


def _skill_install_lines(result) -> list[str]:
    lines = [
        f"source_path: {result.source_path}",
        f"skill_ids: {', '.join(result.skill_ids) or '<empty>'}",
        f"status: {result.status}",
    ]
    detail = str(getattr(result, "detail", "") or "").strip()
    if detail:
        lines.append(f"detail: {detail}")
    metadata = getattr(result, "metadata", {})
    lines.extend(_skill_provenance_lines(metadata))
    return lines
