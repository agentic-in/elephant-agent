"""Shared logging setup for long-running Elephant processes.

Only intended for daemon and other long-lived processes.
CLI one-shot commands should NOT call :func:`setup_logging` — they rely
on ``print()`` / rich for user-facing output.
"""

from __future__ import annotations

import logging
import sys

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    *,
    level: str | int = "INFO",
    format: str = _DEFAULT_FORMAT,
    datefmt: str = _DEFAULT_DATEFMT,
    stream: object | None = None,
) -> None:
    """Configure the root logger for a long-running process.

    Safe to call multiple times (first call wins).
    """
    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    resolved_level = level if isinstance(level, int) else getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=resolved_level,
        format=format,
        datefmt=datefmt,
        stream=stream or sys.stderr,
    )
