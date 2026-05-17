"""Lazy facade for apps.cli.shell_impl (PEP 562)."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    import apps.cli.shell_impl as _impl

    return getattr(_impl, name)


def __dir__() -> list[str]:
    import apps.cli.shell_impl as _impl

    return list(_impl.__all__) + ["__all__"]
