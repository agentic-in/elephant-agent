"""Glob pattern to Seatbelt regex converter.

Converts shell-style glob patterns (e.g. ``**/.env``, ``*.key``) into
macOS Seatbelt regex syntax for use in ``(deny file-read* (regex #"..."))``
rules.

Reference: Codex ``codex-rs/sandboxing/src/seatbelt.rs`` —
``seatbelt_regex_for_unreadable_glob()``

Supported patterns:
- ``*``   — matches any characters except path separator
- ``**``  — matches zero or more path components
- ``?``   — matches exactly one character (not separator)
- ``[...]`` — character class (passed through)
- Literal text is regex-escaped
"""

from __future__ import annotations

import re
from collections import deque


def glob_to_seatbelt_regex(pattern: str) -> str | None:
    """Convert a glob pattern to a Seatbelt regex string.

    Returns the regex body (without the ``#"..."`` wrapper) or ``None``
    if the pattern is empty.

    Examples::

        >>> glob_to_seatbelt_regex("**/.env")
        '(.*/)?\\\\.env$'
        >>> glob_to_seatbelt_regex("*.key")
        '^[^/]*\\\\.key$'
        >>> glob_to_seatbelt_regex("**/secret/**")
        '(.*/)?secret(/.*)?$'
    """
    if not pattern:
        return None

    chars = deque(pattern)
    regex_parts: list[str] = ["^"] if not pattern.startswith("*") else []
    saw_glob = False

    while chars:
        ch = chars.popleft()

        if ch == "*":
            saw_glob = True
            if chars and chars[0] == "*":
                # ** — globstar
                chars.popleft()
                if chars and chars[0] == "/":
                    chars.popleft()
                    # **/ — matches zero or more path components followed by /
                    regex_parts.append("(.*/)?")
                else:
                    # ** at end or before non-slash
                    regex_parts.append(".*")
            else:
                # * — matches within one component
                regex_parts.append("[^/]*")

        elif ch == "?":
            saw_glob = True
            regex_parts.append("[^/]")

        elif ch == "[":
            saw_glob = True
            # Collect character class
            class_chars: list[str] = []
            closed = False
            while chars:
                class_ch = chars.popleft()
                if class_ch == "]":
                    closed = True
                    break
                class_chars.append(class_ch)

            if not closed:
                # Unclosed bracket — treat as literal
                regex_parts.append(re.escape("["))
                # Push chars back
                for c in reversed(class_chars):
                    chars.appendleft(c)
                continue

            # Build character class
            regex_parts.append("[")
            first = True
            for i, class_ch in enumerate(class_chars):
                if first and class_ch == "!":
                    regex_parts.append("^")
                elif first and class_ch == "^":
                    regex_parts.append("\\^")
                elif class_ch == "\\":
                    regex_parts.append("\\\\")
                else:
                    regex_parts.append(class_ch)
                first = False
            regex_parts.append("]")

        elif ch == "]":
            saw_glob = True
            regex_parts.append("\\]")

        else:
            # Escape regex metacharacters
            regex_parts.append(re.escape(ch))

    # If no glob metacharacter was seen, treat as exact path + subtree
    if not saw_glob:
        regex_parts.append("(/.*)?")

    regex_parts.append("$")
    return "".join(regex_parts)


def format_seatbelt_deny_read(pattern: str) -> str | None:
    """Convert a glob to a complete Seatbelt deny-read rule.

    Returns a string like:
    ``(deny file-read* (regex #"^.*/\\.env$"))``

    or ``None`` if the pattern cannot be converted.
    """
    regex = glob_to_seatbelt_regex(pattern)
    if regex is None:
        return None
    # Escape quotes for SBPL embedding
    regex_escaped = regex.replace('"', '\\"')
    return f'(deny file-read* (regex #"{regex_escaped}"))'
