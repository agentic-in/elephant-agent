"""Compatibility module alias for shared CLI terminal UI helpers."""

from __future__ import annotations

import sys

from packages.operator import shell_ui as _shell_ui

sys.modules[__name__] = _shell_ui
