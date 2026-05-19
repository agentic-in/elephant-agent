"""Delivery-agnostic gateway routing and message delivery primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from packages.security.runtime import (
    ApprovalClass,
    PolicyDecision,
    PolicyResult,
    SecurityPolicy,
    SecurityRequest,
    evaluate_with_telemetry,
)
from packages.telemetry.runtime import TelemetrySink


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


DEFAULT_GATEWAY_ACCOUNT_ID = "default"


def _dedupe_attachment_refs(
    values: tuple["GatewayAttachmentRef", ...],
) -> tuple["GatewayAttachmentRef", ...]:
    deduped: dict[str, GatewayAttachmentRef] = {}
    for value in values:
        deduped.setdefault(value.attachment_id, value)
    return tuple(deduped.values())


def _session_id(adapter_id: str, account_id: str, conversation_id: str) -> str:
    return f"session:{adapter_id}:{account_id}:{conversation_id}"


def _mapping_id(
    adapter_id: str,
    account_id: str,
    conversation_id: str,
) -> str:
    return f"mapping:{adapter_id}:{account_id}:{conversation_id}"


def _route_id(
    adapter_id: str,
    account_id: str,
    conversation_id: str,
) -> str:
    return f"route:{adapter_id}:{account_id}:{conversation_id}"


@dataclass(frozen=True, slots=True)
class GatewayAccountRef:
    adapter_id: str
    account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID
    tenant_id: str | None = None
    surface: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewayConversationRef:
    conversation_id: str
    parent_conversation_id: str | None = None
    thread_id: str | None = None
    chat_type: str | None = None
    title: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewaySenderRef:
    external_user_id: str
    display_name: str | None = None
    username: str | None = None
    is_bot: bool = False
    is_self: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewayAttachmentRef:
    attachment_id: str
    kind: str = "file"
    name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    platform_fetch_ref: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewayPolicyHint:
    target_trusted_default: bool = True
    consent_default: bool = True
    is_external_default: bool = False
    audience_scope: str | None = None
    sensitivity_tags: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewayIdentityKey:
    adapter_id: str
    account_id: str
    conversation_id: str


@dataclass(frozen=True, slots=True)
class GatewayIdentityRecord:
    mapping_id: str
    key: GatewayIdentityKey
    session_id: str
    state_id: str | None = None
    elephant_id: str | None = None
    episode_id: str | None = None
    display_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GatewayRouteState:
    session_id: str
    profile_id: str
    status: str
    started_at: datetime
    updated_at: datetime
    interruption_state: str | None = None


@dataclass(frozen=True, slots=True)
class GatewayInboundMessage:
    event_id: str
    account: GatewayAccountRef
    conversation: GatewayConversationRef
    sender: GatewaySenderRef
    body: str
    body_format: str = "text/plain"
    reply_to_message_id: str | None = None
    attachment_refs: tuple[GatewayAttachmentRef, ...] = ()
    policy_hint: GatewayPolicyHint = field(default_factory=GatewayPolicyHint)
    received_at: datetime | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def adapter_id(self) -> str:
        return self.account.adapter_id

    @property
    def account_id(self) -> str:
        return self.account.account_id

    @property
    def conversation_id(self) -> str:
        return self.conversation.conversation_id

    @property
    def parent_conversation_id(self) -> str | None:
        return self.conversation.parent_conversation_id

    @property
    def thread_id(self) -> str | None:
        return self.conversation.thread_id

    @property
    def chat_type(self) -> str | None:
        return self.conversation.chat_type

    @property
    def external_user_id(self) -> str:
        return self.sender.external_user_id

    @property
    def display_name(self) -> str | None:
        return self.sender.display_name

    @property
    def attachments(self) -> tuple[str, ...]:
        return tuple(ref.attachment_id for ref in self.attachment_refs)


@dataclass(frozen=True, slots=True)
class GatewayOutboundMessage:
    message_id: str
    account: GatewayAccountRef
    conversation: GatewayConversationRef
    session_id: str
    body: str
    body_format: str = "text/plain"
    reply_to_message_id: str | None = None
    attachment_refs: tuple[GatewayAttachmentRef, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def adapter_id(self) -> str:
        return self.account.adapter_id

    @property
    def account_id(self) -> str:
        return self.account.account_id

    @property
    def conversation_id(self) -> str:
        return self.conversation.conversation_id

    @property
    def attachments(self) -> tuple[str, ...]:
        return tuple(ref.attachment_id for ref in self.attachment_refs)


@dataclass(frozen=True, slots=True)
class GatewayRouteResult:
    route_id: str
    inbound: GatewayInboundMessage
    identity: GatewayIdentityRecord
    session: GatewayRouteState
    is_new_session: bool
    routed_at: datetime


@dataclass(frozen=True, slots=True)
class GatewayDeliveryReceipt:
    delivery_id: str
    route_id: str
    outbound: GatewayOutboundMessage | None
    policy_result: PolicyResult
    outcome: str
    summary: str
    external_message_id: str | None = None
    delivered_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GatewayExchange:
    route: GatewayRouteResult
    delivery: GatewayDeliveryReceipt


def resolve_cron_identity_records(
    *,
    identity_store: "GatewayIdentityStore",
    adapter_id: str,
    elephant_id: str | None,
) -> tuple["GatewayIdentityRecord", ...]:
    """Resolve which identity records a cron job should be delivered to.

    The normal case is ``elephant_id`` set on the job — we look up by elephant and filter to the
    calling adapter. When ``elephant_id`` is missing (e.g. jobs created from an older IM
    path or via the dashboard POST /operator/cron without an ``elephant_id`` field), we fall
    back to *the sole* identity for this adapter if exactly one exists. That matches
    the single-elephant UX of a fresh install. When there are multiple candidate herd we
    return an empty tuple rather than spam the wrong conversation — the caller's log
    line distinguishes the two cases.
    """
    if elephant_id:
        records = identity_store.lookup_by_elephant_id(elephant_id)
    else:
        records = identity_store.list_records()
    adapter_records = tuple(record for record in records if record.key.adapter_id == adapter_id)
    if elephant_id or not adapter_records:
        return adapter_records
    unique_elephants = {record.elephant_id for record in adapter_records if record.elephant_id}
    if len(unique_elephants) != 1:
        return ()
    only_elephant = next(iter(unique_elephants))
    return tuple(record for record in adapter_records if record.elephant_id == only_elephant)


@runtime_checkable
class GatewayIdentityStore(Protocol):
    def lookup(self, key: GatewayIdentityKey) -> GatewayIdentityRecord | None:
        """Return the stored identity mapping for a conversation if it exists."""

    def save(self, record: GatewayIdentityRecord) -> None:
        """Persist an identity mapping."""

    def lookup_by_elephant_id(self, elephant_id: str) -> tuple[GatewayIdentityRecord, ...]:
        """Return all identity records bound to a given elephant."""

    def list_records(self) -> tuple[GatewayIdentityRecord, ...]:
        """Return stored identity mappings for operator inspection."""


@runtime_checkable
class GatewaySessionStore(Protocol):
    def lookup(self, session_id: str) -> GatewayRouteState | None:
        """Return the stored route state for a gateway route if it exists."""

    def save(self, session: GatewayRouteState) -> None:
        """Persist a route-state record."""

    def list_records(self) -> tuple[GatewayRouteState, ...]:
        """Return stored route-state records for operator inspection."""


@dataclass(slots=True)
class InMemoryGatewayIdentityStore:
    _records: dict[GatewayIdentityKey, GatewayIdentityRecord] = field(default_factory=dict)

    def lookup(self, key: GatewayIdentityKey) -> GatewayIdentityRecord | None:
        return self._records.get(key)

    def save(self, record: GatewayIdentityRecord) -> None:
        self._records[record.key] = record

    def lookup_by_elephant_id(self, elephant_id: str) -> tuple[GatewayIdentityRecord, ...]:
        return tuple(
            sorted(
                (r for r in self._records.values() if r.elephant_id == elephant_id),
                key=lambda r: r.updated_at or r.created_at or _utc_now(),
                reverse=True,
            )
        )

    def list_records(self) -> tuple[GatewayIdentityRecord, ...]:
        return tuple(
            sorted(
                self._records.values(),
                key=lambda record: (
                    record.key.adapter_id,
                    record.key.account_id,
                    record.key.conversation_id,
                ),
            )
        )


@dataclass(slots=True)
class FileGatewayIdentityStore:
    path: Path

    def lookup(self, key: GatewayIdentityKey) -> GatewayIdentityRecord | None:
        return self._load_records().get(key)

    def save(self, record: GatewayIdentityRecord) -> None:
        records = self._load_records()
        records[record.key] = record
        self._write_records(records)

    def lookup_by_elephant_id(self, elephant_id: str) -> tuple[GatewayIdentityRecord, ...]:
        return tuple(
            sorted(
                (r for r in self._load_records().values() if r.elephant_id == elephant_id),
                key=lambda r: r.updated_at or r.created_at or _utc_now(),
                reverse=True,
            )
        )

    def list_records(self) -> tuple[GatewayIdentityRecord, ...]:
        return tuple(
            sorted(
                self._load_records().values(),
                key=lambda record: (
                    record.key.adapter_id,
                    record.key.account_id,
                    record.key.conversation_id,
                ),
            )
        )

    def _load_records(self) -> dict[GatewayIdentityKey, GatewayIdentityRecord]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError(f"{self.path} must contain a JSON array")
        records: dict[GatewayIdentityKey, GatewayIdentityRecord] = {}
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError(f"{self.path} entries must be JSON objects")
            record = GatewayIdentityRecord(
                mapping_id=str(item["mapping_id"]),
                key=GatewayIdentityKey(
                    adapter_id=str(item["adapter_id"]),
                    account_id=str(item.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
                    conversation_id=str(item["conversation_id"]),
                ),
                session_id=str(item["session_id"]),
                state_id=str(item["state_id"]) if item.get("state_id") is not None else None,
                elephant_id=str(item["elephant_id"]) if item.get("elephant_id") is not None else None,
                episode_id=str(item["episode_id"]) if item.get("episode_id") is not None else None,
                display_name=(str(item["display_name"]) if item.get("display_name") is not None else None),
                created_at=_parse_datetime(str(item["created_at"]) if item.get("created_at") is not None else None),
                updated_at=_parse_datetime(str(item["updated_at"]) if item.get("updated_at") is not None else None),
            )
            records[record.key] = record
        return records

    def _write_records(
        self,
        records: Mapping[GatewayIdentityKey, GatewayIdentityRecord],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "mapping_id": record.mapping_id,
                "adapter_id": record.key.adapter_id,
                "account_id": record.key.account_id,
                "conversation_id": record.key.conversation_id,
                "session_id": record.session_id,
                "state_id": record.state_id,
                "elephant_id": record.elephant_id,
                "episode_id": record.episode_id,
                "display_name": record.display_name,
                "created_at": _iso(record.created_at),
                "updated_at": _iso(record.updated_at),
            }
            for record in sorted(
                records.values(),
                key=lambda value: (
                    value.key.adapter_id,
                    value.key.account_id,
                    value.key.conversation_id,
                ),
            )
        ]
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")


@dataclass(slots=True)
class InMemoryGatewaySessionStore:
    _records: dict[str, GatewayRouteState] = field(default_factory=dict)

    def lookup(self, session_id: str) -> GatewayRouteState | None:
        return self._records.get(session_id)

    def save(self, session: GatewayRouteState) -> None:
        self._records[session.session_id] = session

    def list_records(self) -> tuple[GatewayRouteState, ...]:
        return tuple(
            sorted(
                self._records.values(),
                key=lambda session: (
                    session.updated_at,
                    session.started_at,
                    session.session_id,
                ),
            )
        )


@dataclass(slots=True)
class FileGatewaySessionStore:
    path: Path

    def lookup(self, session_id: str) -> GatewayRouteState | None:
        return self._load_records().get(session_id)

    def save(self, session: GatewayRouteState) -> None:
        records = self._load_records()
        records[session.session_id] = session
        self._write_records(records)

    def list_records(self) -> tuple[GatewayRouteState, ...]:
        return tuple(
            sorted(
                self._load_records().values(),
                key=lambda session: (
                    session.updated_at,
                    session.started_at,
                    session.session_id,
                ),
            )
        )

    def _load_records(self) -> dict[str, GatewayRouteState]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError(f"{self.path} must contain a JSON array")
        records: dict[str, GatewayRouteState] = {}
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError(f"{self.path} entries must be JSON objects")
            session = GatewayRouteState(
                session_id=str(item["session_id"]),
                profile_id=str(item["profile_id"]),
                status=str(item["status"]),
                started_at=datetime.fromisoformat(str(item["started_at"])),
                updated_at=datetime.fromisoformat(str(item["updated_at"])),
                interruption_state=(
                    str(item["interruption_state"]) if item.get("interruption_state") is not None else None
                ),
            )
            records[session.session_id] = session
        return records

    def _write_records(self, records: Mapping[str, GatewayRouteState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "session_id": session.session_id,
                "profile_id": session.profile_id,
                "status": session.status,
                "started_at": _iso(session.started_at),
                "updated_at": _iso(session.updated_at),
                "interruption_state": session.interruption_state,
            }
            for session in sorted(
                records.values(),
                key=lambda value: (
                    value.updated_at,
                    value.started_at,
                    value.session_id,
                ),
            )
        ]
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")


@dataclass(frozen=True, slots=True)
class GatewayCoreDependencies:
    identity_store: GatewayIdentityStore
    session_store: GatewaySessionStore
    security_policy: SecurityPolicy
    default_profile_id: str
    telemetry_sink: TelemetrySink | None = None


@dataclass(frozen=True, slots=True)
class GatewayCoreService:
    dependencies: GatewayCoreDependencies

    def bind_elephant(
        self,
        inbound: GatewayInboundMessage,
        *,
        elephant_id: str,
        state_id: str,
        bound_at: datetime | None = None,
    ) -> GatewayIdentityRecord:
        now = bound_at or inbound.received_at or _utc_now()
        key = GatewayIdentityKey(
            adapter_id=inbound.adapter_id,
            account_id=inbound.account_id,
            conversation_id=inbound.conversation_id,
        )
        existing = self.dependencies.identity_store.lookup(key)
        session_id = (
            existing.session_id
            if existing is not None
            else _session_id(
                inbound.adapter_id,
                inbound.account_id,
                inbound.conversation_id,
            )
        )
        session = self.dependencies.session_store.lookup(session_id)
        if session is None:
            session = GatewayRouteState(
                session_id=session_id,
                profile_id=self.dependencies.default_profile_id,
                status="active",
                started_at=now,
                updated_at=now,
            )
        else:
            session = replace(session, updated_at=now)
        identity = GatewayIdentityRecord(
            mapping_id=existing.mapping_id
            if existing is not None
            else _mapping_id(
                inbound.adapter_id,
                inbound.account_id,
                inbound.conversation_id,
            ),
            key=key,
            session_id=session.session_id,
            state_id=state_id,
            elephant_id=elephant_id,
            episode_id=existing.episode_id if existing is not None else None,
            display_name=inbound.display_name or (existing.display_name if existing is not None else None),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self.dependencies.identity_store.save(identity)
        self.dependencies.session_store.save(session)
        return identity

    def route_inbound(
        self,
        inbound: GatewayInboundMessage,
        *,
        state_id: str | None = None,
        elephant_id: str | None = None,
    ) -> GatewayRouteResult:
        now = inbound.received_at or _utc_now()
        key = GatewayIdentityKey(
            adapter_id=inbound.adapter_id,
            account_id=inbound.account_id,
            conversation_id=inbound.conversation_id,
        )
        identity = self.dependencies.identity_store.lookup(key)
        inherited: GatewayIdentityRecord | None = None
        if (
            identity is None
            and inbound.parent_conversation_id
            and inbound.parent_conversation_id != inbound.conversation_id
        ):
            inherited = self.dependencies.identity_store.lookup(
                GatewayIdentityKey(
                    adapter_id=inbound.adapter_id,
                    account_id=inbound.account_id,
                    conversation_id=inbound.parent_conversation_id,
                )
            )

        if identity is None:
            session = GatewayRouteState(
                session_id=_session_id(
                    inbound.adapter_id,
                    inbound.account_id,
                    inbound.conversation_id,
                ),
                profile_id=self.dependencies.default_profile_id,
                status="active",
                started_at=now,
                updated_at=now,
            )
            identity = GatewayIdentityRecord(
                mapping_id=_mapping_id(
                    inbound.adapter_id,
                    inbound.account_id,
                    inbound.conversation_id,
                ),
                key=key,
                session_id=session.session_id,
                state_id=state_id or (inherited.state_id if inherited is not None else None),
                elephant_id=elephant_id or (inherited.elephant_id if inherited is not None else None),
                episode_id=inherited.episode_id if inherited is not None else None,
                display_name=inbound.display_name,
                created_at=now,
                updated_at=now,
            )
            self.dependencies.identity_store.save(identity)
            self.dependencies.session_store.save(session)
            return GatewayRouteResult(
                route_id=_route_id(
                    inbound.adapter_id,
                    inbound.account_id,
                    inbound.conversation_id,
                ),
                inbound=inbound,
                identity=identity,
                session=session,
                is_new_session=True,
                routed_at=now,
            )

        session = self.dependencies.session_store.lookup(identity.session_id)
        if session is None:
            session = GatewayRouteState(
                session_id=identity.session_id,
                profile_id=self.dependencies.default_profile_id,
                status="active",
                started_at=now,
                updated_at=now,
            )
        else:
            session = replace(session, updated_at=now)
        identity = replace(
            identity,
            state_id=state_id or identity.state_id,
            elephant_id=elephant_id or identity.elephant_id,
            display_name=inbound.display_name or identity.display_name,
            updated_at=now,
        )
        self.dependencies.identity_store.save(identity)
        self.dependencies.session_store.save(session)
        return GatewayRouteResult(
            route_id=_route_id(
                inbound.adapter_id,
                inbound.account_id,
                inbound.conversation_id,
            ),
            inbound=inbound,
            identity=identity,
            session=session,
            is_new_session=False,
            routed_at=now,
        )

    def record_turn_outcome(
        self,
        route: GatewayRouteResult,
        *,
        state_id: str,
        elephant_id: str | None,
        episode_id: str,
        routed_at: datetime | None = None,
    ) -> GatewayRouteResult:
        current = routed_at or _utc_now()
        identity = replace(
            route.identity,
            state_id=state_id,
            elephant_id=elephant_id or route.identity.elephant_id,
            episode_id=episode_id,
            updated_at=current,
        )
        session = replace(route.session, updated_at=current)
        self.dependencies.identity_store.save(identity)
        self.dependencies.session_store.save(session)
        return replace(route, identity=identity, session=session, routed_at=current)

    def deliver(
        self,
        route: GatewayRouteResult,
        *,
        body: str,
        reply_to_message_id: str | None = None,
        attachment_refs: tuple[GatewayAttachmentRef, ...] = (),
        metadata: Mapping[str, object] | None = None,
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayDeliveryReceipt:
        resolved_target_trusted = (
            route.inbound.policy_hint.target_trusted_default if target_trusted is None else target_trusted
        )
        resolved_consent_given = route.inbound.policy_hint.consent_default if consent_given is None else consent_given
        resolved_is_external = route.inbound.policy_hint.is_external_default if is_external is None else is_external
        request = SecurityRequest(
            request_id=f"{route.route_id}:policy:{uuid4().hex[:8]}",
            approval_class=ApprovalClass.MESSAGING,
            operation="deliver-message",
            episode_id=route.session.session_id,
            description=body,
            is_external=resolved_is_external,
            consent_given=resolved_consent_given,
            target_trusted=resolved_target_trusted,
            metadata={
                "adapter_id": route.inbound.adapter_id,
                "account_id": route.inbound.account_id,
                "chat_type": route.inbound.chat_type or "",
            },
        )
        if self.dependencies.telemetry_sink is None:
            policy_result = self.dependencies.security_policy.evaluate(request)
        else:
            policy_result = evaluate_with_telemetry(
                self.dependencies.security_policy,
                request,
                self.dependencies.telemetry_sink,
                source="gateway.messaging",
            )
        outbound = GatewayOutboundMessage(
            message_id=f"{route.route_id}:delivery:{uuid4().hex[:8]}",
            account=route.inbound.account,
            conversation=route.inbound.conversation,
            session_id=route.session.session_id,
            body=body,
            body_format=route.inbound.body_format,
            reply_to_message_id=reply_to_message_id,
            attachment_refs=_dedupe_attachment_refs(attachment_refs),
            metadata=dict(metadata or {}),
        )
        if policy_result.decision != PolicyDecision.ALLOW:
            return GatewayDeliveryReceipt(
                delivery_id=outbound.message_id,
                route_id=route.route_id,
                outbound=None,
                policy_result=policy_result,
                outcome="blocked",
                summary=policy_result.rationale,
                external_message_id=None,
                delivered_at=_utc_now(),
            )
        return GatewayDeliveryReceipt(
            delivery_id=outbound.message_id,
            route_id=route.route_id,
            outbound=outbound,
            policy_result=policy_result,
            outcome="delivered",
            summary=outbound.body,
            external_message_id=outbound.message_id,
            delivered_at=_utc_now(),
        )

    def process_message(
        self,
        inbound: GatewayInboundMessage,
        *,
        body: str | None = None,
        state_id: str | None = None,
        elephant_id: str | None = None,
        reply_to_message_id: str | None = None,
        attachment_refs: tuple[GatewayAttachmentRef, ...] = (),
        metadata: Mapping[str, object] | None = None,
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayExchange:
        route = self.route_inbound(
            inbound,
            state_id=state_id,
            elephant_id=elephant_id,
        )
        delivery = self.deliver(
            route,
            body=body or inbound.body,
            reply_to_message_id=reply_to_message_id or inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=attachment_refs,
            metadata=metadata,
            target_trusted=target_trusted,
            consent_given=consent_given,
            is_external=is_external,
        )
        return GatewayExchange(route=route, delivery=delivery)
