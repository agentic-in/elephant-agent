"""Canonical event-to-outcome lifecycle orchestration.

The kernel is intentionally thin: it coordinates the turn lifecycle across the
shared contracts and capability ports without embedding provider, SQL, or
delivery specifics.
"""

from __future__ import annotations

from .runtime_support import *  # noqa: F401,F403
from .lifecycle_support import *  # noqa: F401,F403
