"""Filesystem helpers for elephant-local identity files.

``ELEPHANT.md`` is the authored, human-editable source of an elephant's own
voice. Runtime State owns structured continuity and may cache the latest text,
but prompt assembly should read this file at Episode open and freeze that
sanitized snapshot for the Episode.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
import re
from urllib.parse import unquote

ELEPHANT_IDENTITY_FILENAME = "ELEPHANT.md"
LOGGER = logging.getLogger(__name__)


def elephant_identity_file_path(elephant_root: Path) -> Path:
    return elephant_root / ELEPHANT_IDENTITY_FILENAME


def read_elephant_identity_file(elephant_root: Path) -> str | None:
    path = elephant_identity_file_path(elephant_root)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def write_elephant_identity_file(elephant_root: Path, content: str) -> Path:
    text = str(content or "").strip()
    if not text:
        raise ValueError("elephant identity content must not be empty")
    path = elephant_identity_file_path(elephant_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def ensure_elephant_identity_file(elephant_root: Path, content: str) -> Path:
    path = elephant_identity_file_path(elephant_root)
    if not path.exists():
        return write_elephant_identity_file(elephant_root, content)
    return path


def profile_with_authored_elephant_identity(profile, elephant_root: Path):
    """Overlay a LoadedProfile with the authored ``ELEPHANT.md`` text when present.

    This keeps file ownership at the State boundary instead of teaching prompt
    contract code how to find files. Missing files intentionally fall back to
    the profile's persisted/cached identity text.
    """
    authored_text = read_elephant_identity_file(elephant_root)
    if authored_text is None:
        return profile
    display_name = _display_name_from_authored_identity(profile, authored_text, elephant_root=elephant_root)
    if _is_legacy_default_identity_text(authored_text):
        authored_text = _refreshed_default_identity_text(
            profile,
            display_name=display_name or _fallback_display_name(elephant_root),
        )
        write_elephant_identity_file(elephant_root, authored_text)
    state = profile.state
    if display_name is not None:
        state = replace(state, display_name=display_name)
    return replace(profile, state=state, elephant_identity_text=authored_text)


def elephant_id_from_session(session) -> str:
    """Resolve the elephant id carried by an Episode-like object."""
    elephant_id = str(getattr(session, "elephant_id", "") or "").strip()
    if elephant_id:
        return elephant_id
    state_id = str(getattr(session, "state_id", "") or "").strip()
    if state_id.startswith("state:") and ":" not in state_id[len("state:"):]:
        return state_id[len("state:"):].strip()
    return ""


_RESERVED_DISPLAY_NAMES = {"", "you", "we", "i", "me", "myself", "yourself", "elephant", "elephant agent"}


def _display_name_from_authored_identity(profile, authored_text: str, *, elephant_root: Path) -> str | None:
    current = str(getattr(profile.state, "display_name", "") or "").strip()
    if current and current.casefold() not in _RESERVED_DISPLAY_NAMES:
        return None
    try:
        from .governance import parse_elephant_identity_display_name

        parsed = parse_elephant_identity_display_name(authored_text)
    except Exception:
        LOGGER.debug(
            "Failed to parse authored elephant identity display name; using elephant folder fallback.",
            exc_info=True,
        )
        parsed = None
    if parsed:
        return parsed
    folder_name = unquote(elephant_root.name).replace("-", " ").replace("_", " ").strip()
    return folder_name.title() if folder_name else None


def _fallback_display_name(elephant_root: Path) -> str:
    folder_name = unquote(elephant_root.name).replace("-", " ").replace("_", " ").strip()
    return folder_name.title() if folder_name else "this elephant"


_LEGACY_DEFAULT_LINES = (
    "How you show up: Steady, present, and continuity-first without losing boundaries.",
    "How you sound: steady, present, grounded.",
    "How you take initiative: gentle.",
    "Stay continuous without performing intimacy: use remembered context naturally, keep uncertainty visible, and let the person correct you.",
)

_LEGACY_GENERATED_HEADER_PATTERNS = (
    re.compile(r"^#\s*elephant\s+identity\s*:.*$", re.IGNORECASE),
    re.compile(r"^display\s+name\s*:.*$", re.IGNORECASE),
    re.compile(r"^mode\s*:.*$", re.IGNORECASE),
    re.compile(r"^you\s+are\s+[^,\n.]+,\s*this\s+person['’]s\s+companion\.?$", re.IGNORECASE),
)


def _is_legacy_default_identity_text(text: str) -> bool:
    lines = tuple(
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip() and not line.strip().startswith("<!--")
    )
    body = tuple(
        line
        for line in lines
        if not any(pattern.match(line) for pattern in _LEGACY_GENERATED_HEADER_PATTERNS)
    )
    return body == _LEGACY_DEFAULT_LINES


def _refreshed_default_identity_text(profile, *, display_name: str) -> str:
    try:
        from .governance import render_default_elephant_identity

        return render_default_elephant_identity(display_name=display_name)
    except Exception:
        LOGGER.debug(
            "Failed to render refreshed default elephant identity; using deterministic fallback text.",
            exc_info=True,
        )
        return "\n".join(
            (
                f"You are {display_name}, this person's companion.",
                "Stay recognizable across sessions, use remembered context naturally, and keep uncertainty visible.",
                "Be useful without performing intimacy or certainty you do not have.",
            )
        )
