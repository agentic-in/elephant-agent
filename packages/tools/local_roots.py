"""Default local filesystem roots for built-in tools."""

from __future__ import annotations

from pathlib import Path
import tempfile


def default_local_allowed_roots() -> tuple[Path, ...]:
    roots = (Path.home(), Path("/tmp"), Path(tempfile.gettempdir()))
    resolved: list[Path] = []
    for root in roots:
        candidate = root.expanduser().resolve()
        if candidate not in resolved:
            resolved.append(candidate)
    return tuple(resolved)


__all__ = ["default_local_allowed_roots"]
