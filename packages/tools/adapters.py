"""Surface adapters that bridge built-in tools onto app-specific capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from packages.capabilities.runtime import DeliveryAdapterCapability, ToolCapability
from packages.contracts.runtime import ExecutionResult

from .runtime import ToolRuntime, ToolRequester
from .surfaces import ClarifySurface, MessageDeliverySurface


@dataclass(frozen=True, slots=True)
class RequesterScopedToolCapability(ToolCapability):
    runtime: ToolRuntime
    requester: ToolRequester

    @property
    def descriptor(self):
        return self.runtime.descriptor

    def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        session_id: str,
    ) -> ExecutionResult:
        return self.runtime.invoke(
            tool_name,
            arguments,
            session_id=session_id,
            requester=self.requester,
        )


@dataclass(frozen=True, slots=True)
class DeliveryMessageSurfaceAdapter(MessageDeliverySurface):
    delivery: DeliveryAdapterCapability
    surface_label: str = "delivery-adapter"
    default_target: str | None = None

    def send_message(
        self,
        *,
        session_id: str,
        body: str,
        target: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any] | ExecutionResult:
        payload = {
            "summary": body,
            "body": body,
            "target": target or self.default_target or "",
            "surface": self.surface_label,
        }
        if metadata:
            payload["metadata"] = dict(metadata)
        return self.delivery.deliver(session_id, payload)


@dataclass(frozen=True, slots=True)
class StructuredClarifySurface(ClarifySurface):
    surface_label: str = "interactive-surface"
    default_outcome: str = "needs_input"
    extra_metadata: Mapping[str, str] = field(default_factory=dict)

    def request_clarification(
        self,
        *,
        session_id: str,
        question: str,
        mode: str,
        choices: tuple[str, ...] = (),
    ) -> Mapping[str, Any] | ExecutionResult:
        lines = [
            f"question: {question}",
            f"mode: {mode}",
            f"surface: {self.surface_label}",
        ]
        if choices:
            lines.append("choices:")
            lines.extend(f"- {choice}" for choice in choices)
        if self.extra_metadata:
            lines.append("metadata:")
            lines.extend(f"- {key}={value}" for key, value in sorted(self.extra_metadata.items()))
        return ExecutionResult(
            execution_id=f"clarify:{session_id}:{uuid4().hex[:8]}",
            episode_id=session_id,
            outcome=self.default_outcome,
            summary="\n".join(lines),
            side_effects=("clarify",),
        )


@dataclass(slots=True)
class DelegatingClarifySurface(ClarifySurface):
    delegate: ClarifySurface | None = None
    fallback_surface: ClarifySurface = field(default_factory=StructuredClarifySurface)

    def set_delegate(self, surface: ClarifySurface | None) -> None:
        self.delegate = surface

    def request_clarification(
        self,
        *,
        session_id: str,
        question: str,
        mode: str,
        choices: tuple[str, ...] = (),
    ) -> Mapping[str, Any] | ExecutionResult:
        surface = self.delegate or self.fallback_surface
        return surface.request_clarification(
            session_id=session_id,
            question=question,
            mode=mode,
            choices=choices,
        )
