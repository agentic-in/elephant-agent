"""Compatibility module alias for terminal stack primitives."""

from __future__ import annotations

import sys

from packages.operator import shell_stack as _shell_stack

sys.modules[__name__] = _shell_stack
