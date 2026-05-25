"""Compatibility module alias for reflect feature definitions."""

from __future__ import annotations

import sys

from packages.reflect import features as _features

sys.modules[__name__] = _features
