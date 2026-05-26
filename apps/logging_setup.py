"""Shared logging setup for long-running Elephant processes.

Only intended for daemon and other long-lived processes.
CLI one-shot commands should NOT call :func:`setup_logging` — they rely
on ``print()`` / rich for user-facing output.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _configure_handler(
    handler: logging.Handler,
    *,
    format: str,
    datefmt: str,
) -> logging.Handler:
    handler.setFormatter(logging.Formatter(fmt=format, datefmt=datefmt))
    return handler


def _has_file_handler(root: logging.Logger, log_path: Path) -> bool:
    resolved = log_path.expanduser().resolve()
    for handler in root.handlers:
        base_filename = getattr(handler, "baseFilename", None)
        if not base_filename:
            continue
        try:
            if Path(base_filename).expanduser().resolve() == resolved:
                return True
        except OSError:
            continue
    return False


def setup_logging(
    *,
    level: str | int = "INFO",
    format: str = _DEFAULT_FORMAT,
    datefmt: str = _DEFAULT_DATEFMT,
    stream: object | None = None,
    log_path: str | Path | None = None,
) -> None:
    """Configure the root logger for a long-running process.

    Safe to call multiple times. The first call establishes the default stream
    handler; subsequent calls may still attach a file handler when ``log_path``
    is provided.
    """
    root = logging.getLogger()
    resolved_level = level if isinstance(level, int) else getattr(logging, level.upper(), logging.INFO)
    root.setLevel(resolved_level)

    if not root.handlers:
        stream_handler = logging.StreamHandler(stream or sys.stderr)
        root.addHandler(
            _configure_handler(
                stream_handler,
                format=format,
                datefmt=datefmt,
            )
        )

    if log_path is None:
        return

    resolved_log_path = Path(log_path).expanduser()
    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)
    if _has_file_handler(root, resolved_log_path):
        return

    file_handler = logging.FileHandler(resolved_log_path, encoding="utf-8")
    root.addHandler(
        _configure_handler(
            file_handler,
            format=format,
            datefmt=datefmt,
        )
    )
