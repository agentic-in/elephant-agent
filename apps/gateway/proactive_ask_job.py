"""Compatibility module alias for proactive gateway ask evaluation."""

from __future__ import annotations

import sys

from packages.gateway_core import proactive_ask as _proactive_ask

sys.modules[__name__] = _proactive_ask
