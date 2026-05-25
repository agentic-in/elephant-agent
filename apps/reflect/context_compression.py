"""Compatibility module alias for Reflect context compression helpers."""

from __future__ import annotations

import sys

import packages.reflect.context_compression as _context_compression

sys.modules[__name__] = _context_compression
