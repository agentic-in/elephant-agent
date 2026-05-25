"""Compatibility module alias for the Reflect runner."""

from __future__ import annotations

import sys

import packages.reflect.runner as _runner

sys.modules[__name__] = _runner
