from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .context import TraceContextFilter

_REDACT_PATTERNS = (
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),
    re.compile(r"(key-[a-zA-Z0-9]{20,})"),
    re.compile(r"(api[_-]?key\s*[:=]\s*)[\"']?([^\s\"',]+)", re.IGNORECASE),
    re.compile(r"(bearer\s+)([^\s]+)", re.IGNORECASE),
    re.compile(r"(token\s*[:=]\s*)[\"']?([^\s\"',]+)", re.IGNORECASE),
)

_REDACTED = "[REDACTED]"
_configured = False


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg and isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _redact(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _redact(str(a)) if isinstance(a, str) else a for a in record.args
                )
        return True


def _redact(text: str) -> str:
    for pattern in _REDACT_PATTERNS:
        if pattern.groups == 1:
            text = pattern.sub(_REDACTED, text)
        else:
            text = pattern.sub(lambda m: m.group(1) + _REDACTED, text)
    return text


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, "trace_id", ""),
            "episode_id": getattr(record, "episode_id", ""),
            "loop_id": getattr(record, "loop_id", ""),
            "step_id": getattr(record, "step_id", ""),
            "request_id": getattr(record, "request_id", ""),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


_CONSOLE_FORMAT = (
    "%(asctime)s %(levelname)-5s [%(trace_id).8s] %(name)s: %(message)s"
)


def configure_logging(
    *,
    log_level: str = "INFO",
    log_file: str | Path = "",
    state_dir: str | Path = "",
) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, log_level.upper(), logging.INFO)

    root = logging.getLogger("elephant")
    root.setLevel(level)

    ctx_filter = TraceContextFilter()
    redact_filter = _RedactingFilter()

    if log_file:
        log_path = Path(log_file)
    elif state_dir:
        log_path = Path(state_dir) / "logs" / "elephant.log"
    else:
        log_path = None

    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(_JSONFormatter())
        file_handler.addFilter(ctx_filter)
        file_handler.addFilter(redact_filter)
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"elephant.{name}")
