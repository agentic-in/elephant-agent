"""Compatibility module alias for shared interactive wizard helpers."""

from __future__ import annotations

import sys

from packages.operator import wizard as _wizard

sys.modules[__name__] = _wizard
