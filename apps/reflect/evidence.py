"""Compatibility module alias for Reflect evidence helpers."""

from __future__ import annotations

import sys

import packages.reflect.evidence as _evidence

sys.modules[__name__] = _evidence
