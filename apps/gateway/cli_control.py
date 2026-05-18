"""Remote-control bridge from messaging surfaces into the CLI runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
import json
from pathlib import Path
import threading
from typing import Any, Protocol

from apps.cli.runtime import CliRuntime
from packages.contracts import Episode
from packages.gateway_core import GatewayIdentityKey, GatewayInboundMessage
from packages.runtime_layout import infer_install_root_from_state_dir


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _episode_status_from_route(status: str) -> str:
    normalized = str(status or "").strip()
    if normalized in ("paused", "interrupted"):
        return "paused"
    if normalized == "closed":
        return "closed"
    return "open"


def _abbreviate_identifier(value: str, *, head: int = 12, tail: int = 6) -> str:
    text = value.strip()
    if not text:
        return ""
    if tail <= 0:
        return text if len(text) <= head else f"{text[:head]}…"
    if len(text) <= head + tail + 1:
        return text
    return f"{text[:head]}…{text[-tail:]}"


class CliRuntimeLike(Protocol):
    def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
        ...

    def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
        ...

    def session_ids_for_elephant(self, elephant_id: str) -> tuple[str, ...]:
        ...

    def create_elephant(
        self,
        *,
        elephant_id: str,
        profile_id: str | None = None,
        display_name: str | None = None,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> Episode:
        ...

    def inspect_session(self, session_id: str) -> Episode:
        ...

    def prepare_session_surface(self, session_id: str) -> Episode:
        ...

    def explain_next_step(
        self,
        *,
        session_id: str,
        prompt: str,
        state_query: str | None = None,
        tool_name: str | None = None,
        tool_arguments: Mapping[str, Any] | None = None,
        delivery_payload: Mapping[str, Any] | None = None,
    ) -> Any:
        ...

    def compact_session_context(
        self,
        session_id: str,
        *,
        reason: str = "gateway-hygiene",
        force: bool = False,
    ) -> Any:
        ...

    def schedule_learning_for_session(
        self,
        *,
        session_id: str,
        trigger: str,
        summary: str = "",
        metadata: Mapping[str, str] | None = None,
    ) -> Any:
        ...

    def open_next_episode(
        self,
        episode_id: str,
        *,
        next_episode_id: str | None = None,
        reason: str = "wake_boundary",
        summary: str = "",
    ) -> Any:
        ...

    def elephant_id_for_session(self, session: Episode) -> str:
        ...


CliRuntimeFactory = Callable[[Path, Path], CliRuntimeLike]


@dataclass(frozen=True, slots=True)
class GatewayCliControlConfig:
    state_dir: str | None = None
    allow_group_chats: bool = False


@dataclass(frozen=True, slots=True)
class GatewayCliBinding:
    account_id: str
    conversation_id: str
    elephant_id: str
    updated_at: str
    session_id: str | None = None


@dataclass(slots=True)
class GatewayCliBindingStore:
    path: Path | None = None
    _bindings: dict[str, GatewayCliBinding] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        with self._lock:
            self._bindings = self._load()

    def get(self, *, account_id: str, conversation_id: str) -> GatewayCliBinding | None:
        with self._lock:
            return self._bindings.get(self._key(account_id, conversation_id))

    def set(
        self,
        *,
        account_id: str,
        conversation_id: str,
        elephant_id: str,
        session_id: str | None = None,
    ) -> GatewayCliBinding:
        with self._lock:
            binding = GatewayCliBinding(
                account_id=account_id,
                conversation_id=conversation_id,
                elephant_id=elephant_id,
                session_id=session_id,
                updated_at=_utc_now().isoformat(),
            )
            self._bindings[self._key(account_id, conversation_id)] = binding
            self._persist()
            return binding

    def _key(self, account_id: str, conversation_id: str) -> str:
        return f"{account_id}:{conversation_id}"

    def _load(self) -> dict[str, GatewayCliBinding]:
        if self.path is None or not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        items = payload.get("bindings")
        if not isinstance(items, list):
            return {}
        loaded: dict[str, GatewayCliBinding] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                binding = GatewayCliBinding(
                    account_id=str(item["account_id"]),
                    conversation_id=str(item["conversation_id"]),
                    elephant_id=str(item["elephant_id"]),
                    session_id=_optional_text(item.get("session_id")),
                    updated_at=str(item["updated_at"]),
                )
            except KeyError:
                continue
            loaded[self._key(binding.account_id, binding.conversation_id)] = binding
        return loaded

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "bindings": [
                asdict(binding)
                for binding in sorted(
                    self._bindings.values(),
                    key=lambda item: (item.account_id, item.conversation_id),
                )
            ]
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@dataclass(frozen=True, slots=True)
class GatewayCliControlResult:
    body: str | None
    elephant_id: str | None = None
    session_id: str | None = None
    handled: bool = True
    summary: str | None = None


def load_gateway_cli_control_config(
    manifest: Mapping[str, object],
    *,
    adapter_key: str,
    default_when_missing: bool = False,
) -> GatewayCliControlConfig | None:
    gateway_payload = _mapping(manifest.get("gateway")) or {}
    adapters_payload = _mapping(gateway_payload.get("adapters")) or {}
    adapter_payload = _mapping(adapters_payload.get(adapter_key)) or {}
    control_payload = _mapping(adapter_payload.get("control"))
    if control_payload is None:
        return GatewayCliControlConfig() if default_when_missing else None
    return GatewayCliControlConfig(
        state_dir=_optional_text(control_payload.get("state_dir")),
        allow_group_chats=bool(control_payload.get("allow_group_chats", False)),
    )


def load_feishu_cli_control_config(manifest: Mapping[str, object]) -> GatewayCliControlConfig:
    config = load_gateway_cli_control_config(
        manifest,
        adapter_key="feishu",
        default_when_missing=True,
    )
    return config if config is not None else GatewayCliControlConfig()


@dataclass(slots=True)
class GatewayCliControlService:
    config: GatewayCliControlConfig
    app: "GatewayApp | None" = None
    runtime_factory: CliRuntimeFactory | None = None
    binding_store: GatewayCliBindingStore | None = None
    surface_label: str = "Gateway"
    binding_subject: str = "conversation"
    direct_chat_types: tuple[str | None, ...] = (None, "direct")
    direct_message_label: str = "direct message"
    control_config_path: str = "gateway.adapters.gateway.control"
    _runtime: CliRuntimeLike | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding_store is None:
            self.binding_store = GatewayCliBindingStore()

    def describe(self) -> Mapping[str, object]:
        herd = tuple(state.elephant_id for state in self._list_states(limit=8) if state.elephant_id)
        runtime_status = "ready" if self.app is not None else "misconfigured"
        error = None if self.app is not None else "gateway app is unavailable"
        return {
            "enabled": True,
            "runtime": "shared-runtime",
            "state_dir": self.config.state_dir,
            "allow_group_chats": self.config.allow_group_chats,
            "runtime_status": runtime_status,
            "runtime_error": error,
            "known_elephants": herd,
        }

    def handle_message(self, inbound: GatewayInboundMessage) -> GatewayCliControlResult:
        if inbound.sender.is_bot:
            return GatewayCliControlResult(
                body=None,
                handled=False,
                summary="ignored bot sender",
            )
        if not self.config.allow_group_chats and inbound.chat_type not in self.direct_chat_types:
            return GatewayCliControlResult(
                body=(
                    f"{self.surface_label} remote control currently supports private chats only. "
                    f"Move this conversation to a {self.direct_message_label} or enable "
                    f"`{self.control_config_path}.allow_group_chats`."
                ),
                summary="group chat blocked",
            )

        body = inbound.body.strip()
        command, argument = self._parse_command(body)
        try:
            if command:
                return self._handle_command(inbound, command=command, argument=argument)

            elephant_id, session, _ = self._current_binding(inbound)
            if elephant_id is None or session is None:
                auto_bound = self._auto_bind_single_elephant(inbound)
                if auto_bound is not None:
                    return auto_bound
                return GatewayCliControlResult(
                    body=self._elephant_selection_hint(),
                    summary="no elephant binding",
                )
            if self.app is not None:
                state = self._state_for_elephant(elephant_id)
                self.app.core.bind_elephant(
                    inbound,
                    elephant_id=state.elephant_id,
                    state_id=state.state_id,
                )
            return GatewayCliControlResult(
                body=None,
                elephant_id=elephant_id,
                session_id=session.episode_id,
                handled=False,
                summary="forward to gateway runtime",
            )
        except Exception as exc:
            return GatewayCliControlResult(
                body=f"⚠️ control error: {exc}",
                summary="control error",
            )

    def runtime(self) -> CliRuntimeLike:
        if self._runtime is not None:
            return self._runtime
        if self.config.state_dir is None:
            raise RuntimeError(
                f"{self.control_config_path} requires state_dir so the bridge can target the existing CLI runtime."
            )
        state_dir = Path(self.config.state_dir)
        if self.runtime_factory is None:
            self._runtime = CliRuntime.create(state_dir=state_dir)
            return self._runtime
        profile_dir = infer_install_root_from_state_dir(state_dir) / "profile"
        self._runtime = self.runtime_factory(profile_dir, state_dir)
        return self._runtime

    def _handle_command(
        self,
        inbound: GatewayInboundMessage,
        *,
        command: str,
        argument: str | None,
    ) -> GatewayCliControlResult:
        if command in {"help", "start"}:
            return GatewayCliControlResult(body=self._help_text(), summary="help")
        if command == "elephant":
            return self._handle_elephant_command(
                inbound=inbound,
                argument=argument,
            )
        if command == "clear":
            return self._handle_clear_command(inbound=inbound)
        if command == "status":
            elephant_id, session, selection_mode = self._current_binding(inbound)
            if elephant_id is None or session is None:
                auto_bound = self._auto_bind_single_elephant(inbound)
                if auto_bound is not None:
                    return auto_bound
                return GatewayCliControlResult(
                    body=self._elephant_selection_hint(),
                    summary="status without elephant",
                )
            selection_label = {
                "bound": "bound",
                "bound-session": "bound-session",
                "bound-recovered": "bound-session-recovered",
                "parent-bound": "parent-bound",
                "parent-bound-session": "parent-bound-session",
                "parent-bound-recovered": "parent-bound-session-recovered",
                "auto-bound-single": "auto-bound-single",
            }.get(selection_mode or "", "unknown")
            return GatewayCliControlResult(
                body=(
                    f"Current elephant: {self._elephant_display(elephant_id)}\n"
                    f"personal_model_id: `{session.personal_model_id}`\n"
                    f"selection: `{selection_label}`\n"
                    f"route_status: `{session.status}`\n"
                    "Send plain text next and I will continue on that bound elephant."
                ),
                elephant_id=elephant_id,
                session_id=session.episode_id,
                summary="status",
            )
        return GatewayCliControlResult(
            body=(
                f"Unknown command `/{command}`.\n"
                "Try /help, /elephant list, /elephant use <name>, /elephant current, /clear, or /status."
            ),
            summary="unknown command",
        )

    def _handle_clear_command(
        self,
        *,
        inbound: GatewayInboundMessage,
    ) -> GatewayCliControlResult:
        """Close this Episode and open the next Episode for the binding."""
        elephant_id, session, _selection_mode = self._current_binding(inbound)
        if elephant_id is None or session is None:
            return GatewayCliControlResult(
                body=self._elephant_selection_hint(),
                summary="clear without elephant",
            )
        if self.app is None:
            raise RuntimeError("gateway app is unavailable")

        previous_episode_id = session.episode_id
        runtime = self.runtime()

        previous = runtime.inspect_session(previous_episode_id)
        fresh_session = runtime.open_next_episode(
            previous_episode_id,
            reason="shell_clear",
            summary=(previous.exit_summary or "").strip() or "/clear requested a fresh Episode",
        ).episode
        learning_detail = "episode closed · learning queued"
        new_episode_id = fresh_session.episode_id

        # Rewrite the gateway identity so the fresh Episode becomes the active route.
        identity_store = self.app.core.dependencies.identity_store
        session_store = self.app.core.dependencies.session_store
        now = _utc_now()
        lookup_order = self._binding_lookup_order(inbound)
        for conversation_id in lookup_order:
            key = GatewayIdentityKey(
                adapter_id=inbound.adapter_id,
                account_id=inbound.account_id,
                conversation_id=conversation_id,
            )
            identity = identity_store.lookup(key)
            if identity is None:
                continue
            rotated = replace(
                identity,
                session_id=new_episode_id,
                episode_id=new_episode_id,
                updated_at=now,
            )
            identity_store.save(rotated)

            route_session = session_store.lookup(identity.session_id)
            if route_session is not None:
                session_store.save(
                    replace(
                        route_session,
                        session_id=new_episode_id,
                        profile_id=fresh_session.personal_model_id or route_session.profile_id,
                        status="active",
                        updated_at=now,
                    )
                )
            break

        # Keep the local CLI-control binding store in sync so /status and routing
        # agree on which Episode backs the conversation.
        if self.binding_store is not None:
            self.binding_store.set(
                account_id=inbound.account_id,
                conversation_id=inbound.conversation_id,
                elephant_id=elephant_id,
                session_id=new_episode_id,
            )

        body = (
            f"🔄 Reopened this {self.binding_subject} on a fresh Episode.\n"
            f"🥚 Elephant: {self._elephant_display(elephant_id)}\n"
            f"🧠 {learning_detail}.\n"
            "Send plain text next and I will continue on the new Episode."
        )
        return GatewayCliControlResult(
            body=body,
            elephant_id=elephant_id,
            session_id=new_episode_id,
            summary="clear episode",
        )

    def _handle_elephant_command(
        self,
        *,
        inbound: GatewayInboundMessage,
        argument: str | None,
    ) -> GatewayCliControlResult:
        if not argument:
            return GatewayCliControlResult(
                body=(
                    "Usage:\n"
                    "- /elephant list\n"
                    "- /elephant use <name>\n"
                    "- /elephant current"
                ),
                summary="missing elephant subcommand",
            )
        action, _, remainder = argument.strip().partition(" ")
        action = action.strip().lower()
        remainder = remainder.strip()
        if action == "list":
            if remainder:
                return GatewayCliControlResult(
                    body="Usage: /elephant list",
                    summary="unexpected elephant list arguments",
                )
            return GatewayCliControlResult(body=self._elephant_listing(), summary="list herd")
        if action == "current":
            if remainder:
                return GatewayCliControlResult(
                    body="Usage: /elephant current",
                    summary="unexpected elephant current arguments",
                )
            elephant_id, session, selection_mode = self._current_binding(inbound)
            if elephant_id is None or session is None:
                auto_bound = self._auto_bind_single_elephant(inbound)
                if auto_bound is not None:
                    return auto_bound
                return GatewayCliControlResult(
                    body=self._elephant_selection_hint(),
                    summary="current without elephant",
                )
            selection_label = {
                "bound": "bound",
                "bound-session": "bound-session",
                "bound-recovered": "bound-session-recovered",
                "parent-bound": "parent-bound",
                "parent-bound-session": "parent-bound-session",
                "parent-bound-recovered": "parent-bound-session-recovered",
                "auto-bound-single": "auto-bound-single",
            }.get(selection_mode or "", "unknown")
            return GatewayCliControlResult(
                body=(
                    f"Current elephant: {self._elephant_display(elephant_id)}\n"
                    f"personal_model_id: `{session.personal_model_id}`\n"
                    f"selection: `{selection_label}`\n"
                    f"route_status: `{session.status}`"
                ),
                elephant_id=elephant_id,
                session_id=session.episode_id,
                summary="current elephant",
            )
        if action in ("use", "switch", "create"):
            if not remainder:
                return GatewayCliControlResult(
                    body="Usage: /elephant use <name>\nTry /elephant list first.",
                    summary="missing elephant id",
                )
            current_elephant_id, current_session, _selection_mode = self._current_binding(inbound)
            state = self._state_for_elephant(remainder)
            if current_session is not None and current_elephant_id and current_elephant_id != state.elephant_id:
                try:
                    self.runtime().schedule_learning_for_session(
                        session_id=current_session.episode_id,
                        trigger="state_switch",
                        summary=f"gateway binding switched to {state.elephant_id}",
                        metadata={"source": "gateway.cli_control"},
                    )
                except Exception:
                    pass
            if self.app is None:
                raise RuntimeError("gateway app is unavailable")
            bound = self.app.core.bind_elephant(
                inbound,
                elephant_id=state.elephant_id,
                state_id=state.state_id,
            )
            route_session = self.app.core.dependencies.session_store.lookup(bound.session_id)
            if route_session is not None:
                self.app.core.dependencies.session_store.save(
                    replace(route_session, profile_id=state.personal_model_id, updated_at=_utc_now())
                )
            return GatewayCliControlResult(
                body=(
                    f"Shaped this {self.binding_subject} on elephant {self._elephant_display(state.elephant_id)}.\n"
                    f"personal_model_id: `{state.personal_model_id}`\n"
                    "Send plain text next and I will continue through the shared gateway runtime."
                ),
                elephant_id=state.elephant_id,
                session_id=bound.session_id,
                summary="elephant shaped",
            )
        return GatewayCliControlResult(
            body=(
                "Usage:\n"
                "- /elephant list\n"
                "- /elephant use <name>\n"
                "- /elephant current"
            ),
            summary="unknown elephant subcommand",
        )

    def _session_for_elephant(self, runtime: CliRuntimeLike, elephant_id: str) -> Episode:
        session = runtime.latest_session_for_elephant(elephant_id)
        if session is not None:
            return session
        raise RuntimeError(f"unknown elephant: {elephant_id}. Try /elephant list first.")

    def _session_selection(
        self,
        runtime: CliRuntimeLike,
        inbound: GatewayInboundMessage,
    ) -> tuple[str | None, Episode | None, str | None]:
        elephant_id, session_id, selection_mode, binding_conversation_id = self._elephant_selection(
            runtime,
            inbound,
        )
        if elephant_id is None:
            return None, None, selection_mode
        if session_id is not None:
            try:
                return elephant_id, runtime.inspect_session(session_id), selection_mode
            except KeyError:
                recovered = self._session_for_elephant(runtime, elephant_id)
                assert self.binding_store is not None
                self.binding_store.set(
                    account_id=inbound.account_id,
                    conversation_id=binding_conversation_id or inbound.conversation_id,
                    elephant_id=elephant_id,
                    session_id=recovered.episode_id,
                )
                if selection_mode in {"parent-bound", "parent-bound-session"}:
                    return elephant_id, recovered, "parent-bound-recovered"
                return elephant_id, recovered, "bound-recovered"
        return elephant_id, self._session_for_elephant(runtime, elephant_id), selection_mode

    def _elephant_selection(
        self,
        runtime: CliRuntimeLike,
        inbound: GatewayInboundMessage,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        assert self.binding_store is not None
        lookup_order = self._binding_lookup_order(inbound)
        for conversation_id in lookup_order:
            binding = self.binding_store.get(
                account_id=inbound.account_id,
                conversation_id=conversation_id,
            )
            if binding is None:
                continue
            if conversation_id == inbound.conversation_id:
                return (
                    binding.elephant_id,
                    binding.session_id,
                    "bound-session" if binding.session_id else "bound",
                    conversation_id,
                )
            return (
                binding.elephant_id,
                binding.session_id,
                "parent-bound-session" if binding.session_id else "parent-bound",
                conversation_id,
            )
        return None, None, None, None

    def _resolve_bound_elephant(
        self,
        runtime: CliRuntimeLike,
        inbound: GatewayInboundMessage,
    ) -> str | None:
        elephant_id, _, _, _ = self._elephant_selection(runtime, inbound)
        return elephant_id

    def _binding_lookup_order(
        self,
        inbound: GatewayInboundMessage,
    ) -> tuple[str, ...]:
        candidates = [inbound.conversation_id]
        if (
            inbound.parent_conversation_id is not None
            and inbound.parent_conversation_id != inbound.conversation_id
        ):
            candidates.append(inbound.parent_conversation_id)
        return tuple(dict.fromkeys(candidates))

    def _elephant_id_for_session(self, session: Episode) -> str:
        personal_model_id = session.personal_model_id.strip()
        if personal_model_id.startswith("elephant:"):
            resolved = personal_model_id.split(":", 1)[1].strip()
            if resolved:
                return resolved
        raise RuntimeError(
            f"session {session.episode_id} is not attached to a named elephant, so {self.surface_label} cannot bind it by elephant."
        )

    def _elephant_display(self, elephant_id: str) -> str:
        normalized = elephant_id.strip()
        if self.app is not None:
            for state in self.app.repository.list_states():
                if str(getattr(state, "elephant_id", "")).strip() != normalized:
                    continue
                elephant_name = str(getattr(state, "elephant_name", "")).strip()
                if elephant_name and elephant_name != normalized:
                    return f"{elephant_name} (`{normalized}`)"
                return f"`{normalized}`"
        return f"`{normalized}`" if normalized else "`<unknown>`"

    def _elephant_listing(self) -> str:
        herd = self._list_states(limit=12)
        if not herd:
            return (
                "No local Elephant Agent herd are available yet.\n"
                "Create one from the CLI first."
            )
        lines = ["Available local Elephant Agent herd:"]
        for state in herd:
            elephant_id = str(getattr(state, "elephant_id", "") or getattr(state, "elephant_name", "") or getattr(state, "state_id", ""))
            elephant_name = str(getattr(state, "elephant_name", "") or "").strip()
            elephant_label = f"{elephant_name} (`{elephant_id}`)" if elephant_name and elephant_name != elephant_id else f"`{elephant_id}`"
            status = str(getattr(state, "status", "") or getattr(state, "latest_status", "") or "active")
            summary = str(getattr(state, "summary", "") or "").strip()
            current_marker = ""
            current_state = self._current_state()
            if current_state is not None and getattr(state, "state_id", None) == current_state.state_id:
                current_marker = " · current"
            lines.append(f"- {elephant_label} · {status}{current_marker}")
            if summary:
                lines.append(f"  {summary}")
        lines.append(
            f"Plain text does not route until this {self.binding_subject} is pinned. "
            f"Send `/elephant use <name>` when you want to bind this {self.binding_subject} to a specific elephant."
        )
        return "\n".join(lines)

    def _elephant_selection_hint(self) -> str:
        herd = self._list_states(limit=8)
        if not herd:
            return (
                f"This {self.binding_subject} is not connected to a local Elephant Agent elephant yet, and no herd are "
                "available. Create one in the CLI first."
            )
        return (
            f"This {self.binding_subject} is not pinned yet. Plain text will not continue until you bind it.\n"
            "Send `/elephant list` to inspect the local herd this bridge can see.\n"
            "Send `/elephant use <name>` when you want to pin this conversation to an elephant.\n\n"
            + self._elephant_listing()
        )

    def _help_text(self) -> str:
        return "\n".join(
            (
                f"{self.surface_label} remote control commands:",
                "- /elephant list · list the local Elephant Agent herd this bridge can see",
                f"- /elephant use <name> · pin this {self.binding_subject} to an elephant",
                f"- /elephant current · inspect the elephant currently handling this {self.binding_subject}",
                f"- /status · inspect the elephant currently handling this {self.binding_subject}",
                f"- /clear · close this Episode and open a fresh one on the same elephant",
                f"- plain text · forward the message into the bound elephant after this {self.binding_subject} is pinned",
            )
        )

    def _list_states(self, *, limit: int) -> tuple[object, ...]:
        states: tuple[object, ...] = ()
        if self.app is not None:
            states = tuple(self.app.repository.list_states())
            states = tuple(state for state in states if str(getattr(state, "elephant_id", "")).strip())
        if states:
            return tuple(
                sorted(
                    states,
                    key=lambda state: (
                        str(getattr(state, "elephant_id", "")).strip() == "",
                        str(getattr(state, "elephant_id", "")).strip(),
                        str(getattr(state, "elephant_name", "")).strip(),
                    ),
                )[:limit]
            )
        try:
            runtime = self.runtime()
        except RuntimeError:
            return ()
        return tuple(runtime.list_herd(limit=limit))

    def _current_state(self):
        if self.app is None:
            return None
        return self.app.repository.current_state()

    def _state_for_elephant(self, elephant_ref: str):
        normalized = elephant_ref.strip()
        if not normalized:
            raise RuntimeError("missing elephant name. Try /elephant list first.")
        matches = []
        for state in tuple(self.app.repository.list_states()) if self.app is not None else ():
            elephant_id = str(getattr(state, "elephant_id", "")).strip()
            elephant_name = str(getattr(state, "elephant_name", "")).strip()
            if normalized == elephant_id or normalized.lower() == elephant_name.lower():
                matches.append(state)
        if len(matches) == 1:
            return matches[0]
        if not matches and self.app is not None:
            runtime = self.runtime()
            session = runtime.latest_session_for_elephant(normalized)
            if session is not None:
                return self.app.repository.create_state(
                    state_id=f"state:{normalized}",
                    elephant_id=normalized,
                    elephant_name=normalized,
                    surface_bindings=("gateway",),
                    metadata={"profile_id": session.personal_model_id},
                )
        if not matches:
            raise RuntimeError(f"unknown elephant: {normalized}. Try /elephant list first.")
        raise RuntimeError(f"elephant reference `{normalized}` is ambiguous. Try /elephant list first.")

    def _current_binding(
        self,
        inbound: GatewayInboundMessage,
    ) -> tuple[str | None, Episode | None, str | None]:
        if self.app is None:
            return None, None, None
        lookup_order = self._binding_lookup_order(inbound)
        for conversation_id in lookup_order:
            identity = self.app.core.dependencies.identity_store.lookup(
                GatewayIdentityKey(
                    adapter_id=inbound.adapter_id,
                    account_id=inbound.account_id,
                    conversation_id=conversation_id,
                )
            )
            if identity is None or identity.state_id is None or identity.elephant_id is None:
                continue
            session = self.app.core.dependencies.session_store.lookup(identity.session_id)
            if session is None:
                continue
            runtime_session = self.app.repository.load_episode_state(session.session_id)
            resolved_session = runtime_session or Episode(
                episode_id=session.session_id,
                state_id=identity.state_id or "unresolved",
                personal_model_id=session.profile_id,
                entry_surface="gateway",
                elephant_id=identity.elephant_id or "",
                status=_episode_status_from_route(session.status),
                started_at=session.started_at,
                updated_at=session.updated_at,
                interruption_state=session.interruption_state,
            )
            if conversation_id == inbound.conversation_id:
                return identity.elephant_id, resolved_session, "bound"
            return identity.elephant_id, resolved_session, "parent-bound"
        return None, None, None

    def _auto_bind_single_elephant(
        self,
        inbound: GatewayInboundMessage,
    ) -> GatewayCliControlResult | None:
        """When only a single elephant exists, forward the message on that elephant without asking.

        Returns a forward-to-runtime result when auto-binding is possible, otherwise ``None``
        so the caller can fall back to the selection hint. Multiple herd always require an
        explicit ``/elephant use <name>``.
        """
        if self.app is None:
            return None
        herd = self._list_states(limit=2)
        if len(herd) != 1:
            return None
        only_state = herd[0]
        elephant_ref = str(
            getattr(only_state, "elephant_id", "")
            or getattr(only_state, "elephant_name", "")
            or ""
        ).strip()
        if not elephant_ref:
            return None
        try:
            state = self._state_for_elephant(elephant_ref)
        except RuntimeError:
            return None
        bound = self.app.core.bind_elephant(
            inbound,
            elephant_id=state.elephant_id,
            state_id=state.state_id,
        )
        route_session = self.app.core.dependencies.session_store.lookup(bound.session_id)
        if route_session is not None:
            self.app.core.dependencies.session_store.save(
                replace(
                    route_session,
                    profile_id=state.personal_model_id,
                    updated_at=_utc_now(),
                )
            )
        return GatewayCliControlResult(
            body=None,
            elephant_id=state.elephant_id,
            session_id=bound.session_id,
            handled=False,
            summary="auto-bound single elephant",
        )

    def _parse_command(self, body: str) -> tuple[str | None, str | None]:
        normalized = body.strip()
        while normalized:
            if normalized.startswith("/"):
                break
            stripped = False
            for prefix in ("-", "•", "*", "—", "·", ">"):
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix) :].lstrip()
                    stripped = True
                    break
            if not stripped:
                return None, None
        if not normalized.startswith("/"):
            return None, None
        parts = normalized[1:].split(None, 1)
        command = parts[0].strip().lower()
        argument = parts[1].strip() if len(parts) > 1 else None
        return (command or None, argument)


FeishuCliControlConfig = GatewayCliControlConfig
FeishuCliBinding = GatewayCliBinding
FeishuCliBindingStore = GatewayCliBindingStore
FeishuCliControlResult = GatewayCliControlResult
FeishuCliControlService = GatewayCliControlService


__all__ = [
    "CliRuntimeFactory",
    "CliRuntimeLike",
    "GatewayCliBinding",
    "GatewayCliBindingStore",
    "GatewayCliControlConfig",
    "GatewayCliControlResult",
    "GatewayCliControlService",
    "FeishuCliBinding",
    "FeishuCliBindingStore",
    "FeishuCliControlConfig",
    "FeishuCliControlResult",
    "FeishuCliControlService",
    "load_feishu_cli_control_config",
    "load_gateway_cli_control_config",
]
