"""Compatibility module alias for Reflect prompt fragments."""

from __future__ import annotations

import sys

import packages.reflect.prompts as _prompts

sys.modules[__name__] = _prompts
