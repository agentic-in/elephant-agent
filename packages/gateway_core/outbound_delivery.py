"""Gateway outbound message delivery surface for tool.message.send.

Bridges the built-in ``tool.message.send`` tool onto the shared
``GatewayOutboundQueue`` so Elephant Agent can proactively send messages through any
configured IM adapter from both gateway sessions and CLI/TUI sessions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from packages.contracts.runtime import ExecutionResult

from .outbound_queue import GatewayOutboundQueue


class IdentityLookup(Protocol):
    """Minimal protocol for resolving IM routing from an elephant_id."""

    def list_records(self) -> tuple[Any, ...]:
        """Return all identity records (GatewayIdentityRecord-shaped)."""

    def lookup_by_elephant_id(self, elephant_id: str) -> tuple[Any, ...]:
        """Return identity records bound to the given elephant."""


@dataclass(frozen=True, slots=True)
class GatewayMessageDeliverySurface:
    """MessageDeliverySurface backed by the gateway outbound queue.

    Works in two modes:

    1. **Gateway session** — session_id is ``session:{adapter}:{account}:{conv}``
       and the routing triple is parsed directly. No identity lookup needed.

    2. **CLI/TUI session** — session_id doesn't encode routing. Falls back to the
       identity_store to find the IM route for the user's active elephant. The ``target``
       argument can hint which adapter to prefer (e.g. "feishu", "weixin").
    """

    outbound_queue: GatewayOutboundQueue
    identity_store: IdentityLookup | None = None
    default_elephant_id: str = ""

    def send_message(
        self,
        *,
        session_id: str,
        body: str,
        target: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any] | ExecutionResult:
        route = _try_parse_session_route(session_id)
        if route is None:
            route = self._resolve_route_from_identity(target=target)
        adapter_id, account_id, conversation_id = route
        row = self.outbound_queue.enqueue(
            adapter_id=adapter_id,
            account_id=account_id,
            conversation_id=conversation_id,
            body=body,
            metadata={
                **(metadata or {}),
                "enqueued_via": "tool.message.send",
                "session_id": session_id,
            },
        )
        return ExecutionResult(
            execution_id=row.row_id,
            episode_id=session_id,
            outcome="queued",
            summary=f"Message queued for delivery via {adapter_id}.",
            side_effects=("delivery",),
        )

    def _resolve_route_from_identity(self, *, target: str | None) -> tuple[str, str, str]:
        """Resolve IM routing via identity store (CLI/TUI fallback path)."""
        if self.identity_store is None:
            raise ValueError("Cannot send IM message: no gateway session context and no identity store configured.")
        if self.default_elephant_id:
            records = self.identity_store.lookup_by_elephant_id(self.default_elephant_id)
        else:
            records = self.identity_store.list_records()
        if not records:
            raise ValueError("Cannot send IM message: no IM identity records found. Pair an IM account first.")
        # Filter by target hint if provided (e.g. "feishu", "weixin", "dingding")
        if target:
            hint = target.strip().lower()
            matched = [r for r in records if hint in getattr(r, "key", r).adapter_id.lower()]
            if matched:
                records = matched
        record = records[0]
        key = getattr(record, "key", record)
        return key.adapter_id, key.account_id, key.conversation_id


def _try_parse_session_route(session_id: str) -> tuple[str, str, str] | None:
    """Try parsing 'session:{adapter_id}:{account_id}:{conversation_id}'.

    Returns None if the session_id doesn't match the gateway format.
    """
    parts = session_id.split(":", 3)
    if len(parts) == 4 and parts[0] == "session":
        return parts[1], parts[2], parts[3]
    return None
