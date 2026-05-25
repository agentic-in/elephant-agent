"""Feature type definition."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Feature:
    feature_id: str
    tools: tuple[str, ...]
    sop_fragment: str
    constraints: str = ""
    requires: tuple[str, ...] = ()
    incompatible: tuple[str, ...] = ()
