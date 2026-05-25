"""Gateway CLI main implementation assembled from wizard, runtime, and parser helpers."""

from __future__ import annotations
import asyncio
from argparse import Namespace
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import getpass
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from wsgiref.simple_server import make_server

import typer

import packages.operator.wizard as cli_wizard
from packages.operator.shell_stack import Align, Console, Group, Panel, RICH_AVAILABLE, Table, Text
from packages.operator.shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_LIGHT,
    BRAND_MUTED,
    resolve_elephant_version as _resolve_elephant_version,
    render_elephant_mark,
)
from apps.provider_runtime import load_runtime_local_secret_env
from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir
from packages.gateway_core import DEFAULT_GATEWAY_ACCOUNT_ID

from . import (
    DEFAULT_DINGDING_CLIENT_ID_ENV,
    DEFAULT_DINGDING_CLIENT_SECRET_ENV,
    DEFAULT_DINGDING_ROBOT_CODE_ENV,
    DEFAULT_DISCORD_BOT_TOKEN_ENV,
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    DEFAULT_FEISHU_EVENT_PATH,
    DEFAULT_WECOM_BOT_ID_ENV,
    DEFAULT_WECOM_SECRET_ENV,
    FEISHU_ADAPTER_ID,
    GatewayHttpService,
    GatewayManagedRuntime,
    GatewayManagedService,
    SUPPORTED_DINGDING_TRANSPORTS,
    SUPPORTED_DISCORD_TRANSPORTS,
    SUPPORTED_FEISHU_TRANSPORTS,
    SUPPORTED_WECOM_TRANSPORTS,
    SUPPORTED_WEIXIN_TRANSPORTS,
    WECOM_ADAPTER_ID,
    build_gateway_app,
    build_gateway_plugin_registry,
    create_gateway_web_app,
)
from .dingding import DINGTALK_STREAM_PIP_SPEC, DingdingGatewayService
from .discord import DISCORD_PY_PIP_SPEC, DiscordGatewayService
from .feishu import FEISHU_SDK_PIP_SPEC, FeishuGatewayService
from .wecom import WecomGatewayService
from .weixin import WeixinGatewayService

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings as PromptKeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.shortcuts import input_dialog
    from prompt_toolkit.styles import Style as PromptStyle

    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional wizard polish
    Application = None
    PromptKeyBindings = None
    HSplit = None
    Window = None
    FormattedTextControl = None
    Layout = None
    input_dialog = None
    PromptStyle = None
    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = False


from .gateway_main_argparse import build_gateway_arg_parser
from .gateway_main_parser import *  # noqa: F401,F403
from .gateway_main_parser import _resolved_cli_account_id
from .gateway_main_runtime import *  # noqa: F401,F403
from .gateway_main_wizard import *  # noqa: F401,F403
from .gateway_main_wizard import (
    GATEWAY_WIZARD_BACK,
    _confirm_gateway_wizard_intro,
    _gateway_wizard_choice_prompt,
    _gateway_wizard_dialogs_supported,
    _gateway_wizard_secret_prompt,
    _gateway_wizard_text_prompt,
    _interactive_shell_supported,
    _print_gateway_dingding_wizard_intro,
    _print_gateway_discord_wizard_intro,
    _print_gateway_feishu_wizard_intro,
    _print_gateway_setup_paused,
    _print_gateway_wecom_wizard_intro,
    _print_gateway_weixin_wizard_intro,
    _run_interactive_dingding_wizard,
    _run_interactive_discord_wizard,
    _run_interactive_feishu_wizard,
    _run_interactive_wecom_wizard,
    _run_interactive_weixin_wizard,
    _shared_wizard_choice_prompt,
    _shared_wizard_text_prompt,
)


from .gateway_main_setup_impl import *  # noqa: F401,F403


LOGGER = logging.getLogger(__name__)


def _guard_daemon_running(args: Namespace) -> int | None:
    """If the unified daemon is already running, redirect the user to it.

    Legacy ``gateway <adapter> start`` (without --detach) would launch a
    standalone foreground process that conflicts with the daemon.  When the
    daemon is alive we intercept and delegate instead.
    """
    if _daemon_is_running_for_state(args):
        return _start_via_daemon(args)
    return None


def _run_start(service: FeishuGatewayService, args: Namespace) -> int:
    transport = _resolve_runtime_target_argument(args, service=service)

    if transport == "long-connection":
        service.prepare_managed_runtime(action="startup", target=transport)
    if args.detach:
        return _start_via_daemon(args)
    guarded = _guard_daemon_running(args)
    if guarded is not None:
        return guarded

    if transport == "long-connection":
        account_label = args.account_id or "<default>"
        print("Starting Elephant Agent Gateway Feishu long-connection transport")
        print(f"Feishu account: {account_label}")
        # Start the outbound queue drainer so cron / CLI 'message' rows are delivered
        # through this process's own _send_outbound path (token refresh, retry, etc.).
        service.start_outbound_drain()
        try:
            service.start_long_connection(account_id=args.account_id)
        finally:
            service.stop_outbound_drain()
        return 0

    app = create_gateway_web_app({"feishu": service}, app=service.app)
    service.start_outbound_drain()
    try:
        with make_server(args.host, args.port, app) as server:
            event_paths = ", ".join(service.event_paths) or "<none>"
            print(f"Serving Elephant Agent Gateway on http://{args.host}:{args.port}")
            print(f"Feishu event paths: {event_paths}")
            server.serve_forever()
    finally:
        service.stop_outbound_drain()
    return 0

def _run_discord_start(service: DiscordGatewayService, args: Namespace) -> int:
    transport = _resolve_runtime_target_argument(args, service=service)
    service.prepare_managed_runtime(action="startup", target=transport)
    if args.detach:
        return _start_via_daemon(args)
    guarded = _guard_daemon_running(args)
    if guarded is not None:
        return guarded

    account_label = args.account_id or "<all enabled>"
    print("Starting Elephant Agent Gateway Discord gateway transport")
    print(f"Discord account: {account_label}")
    asyncio.run(service.start_gateway(account_id=args.account_id))
    return 0

def _run_dingding_start(service: DingdingGatewayService, args: Namespace) -> int:
    transport = _resolve_runtime_target_argument(args, service=service)
    service.prepare_managed_runtime(action="startup", target=transport)
    if args.detach:
        return _start_via_daemon(args)
    guarded = _guard_daemon_running(args)
    if guarded is not None:
        return guarded

    account_label = args.account_id or "<all enabled>"
    print("Starting Elephant Agent Gateway DingDing stream transport")
    print(f"DingDing account: {account_label}")
    asyncio.run(service.start_gateway(account_id=args.account_id))
    return 0

def _run_weixin_start(service: WeixinGatewayService, args: Namespace) -> int:
    transport = _resolve_runtime_target_argument(args, service=service)
    service.prepare_managed_runtime(action="startup", target=transport)
    if args.detach:
        return _start_via_daemon(args)
    guarded = _guard_daemon_running(args)
    if guarded is not None:
        return guarded

    account_label = args.account_id or "<default>"
    print("Starting Elephant Agent Gateway WeChat iLink transport")
    print(f"WeChat account: {account_label}")
    asyncio.run(service.start_gateway(account_id=args.account_id))
    return 0


def _run_weixin_message(service: WeixinGatewayService, args: Namespace) -> int:
    """Enqueue one arbitrary text into the weixin outbound queue for operator testing.

    See ``_run_adapter_message`` for semantics; this wrapper sets the adapter id
    and wires a service-specific account fallback (the last resort is the service's
    resolved default account).
    """
    from apps.gateway.runtime import WEIXIN_ADAPTER_ID

    def _fallback_account_id() -> str | None:
        try:
            resolved = service._resolve_credentials(account_id=None)
            return resolved.config.account_id
        except Exception:
            LOGGER.warning("failed to resolve fallback Weixin account id", exc_info=True)
            return None

    return _run_adapter_message(
        args,
        adapter_id=WEIXIN_ADAPTER_ID,
        adapter_label="weixin",
        surface_hint="weixin-ilink",
        fallback_account_id=_fallback_account_id,
    )


def _run_feishu_message(service: FeishuGatewayService, args: Namespace) -> int:
    """Enqueue one arbitrary text into the feishu outbound queue for operator testing."""
    from apps.gateway.runtime import FEISHU_ADAPTER_ID

    def _fallback_account_id() -> str | None:
        if len(service.account_configs) == 1:
            return service.account_configs[0].account_id
        return None

    return _run_adapter_message(
        args,
        adapter_id=FEISHU_ADAPTER_ID,
        adapter_label="feishu",
        surface_hint="feishu",
        fallback_account_id=_fallback_account_id,
    )


def _run_discord_message(service: DiscordGatewayService, args: Namespace) -> int:
    """Enqueue one arbitrary text into the discord outbound queue for operator testing."""
    from apps.gateway.runtime import DISCORD_ADAPTER_ID

    def _fallback_account_id() -> str | None:
        if len(service.account_configs) == 1:
            return service.account_configs[0].account_id
        return None

    return _run_adapter_message(
        args,
        adapter_id=DISCORD_ADAPTER_ID,
        adapter_label="discord",
        surface_hint="discord",
        fallback_account_id=_fallback_account_id,
    )


def _run_adapter_message(
    args: Namespace,
    *,
    adapter_id: str,
    adapter_label: str,
    surface_hint: str,
    fallback_account_id,
) -> int:
    """Shared implementation for ``elephant gateway <provider> message`` subcommands.

    All adapters use the same cross-process outbound queue, so the CLI is one
    piece of code parameterised by ``adapter_id`` and an adapter-specific
    ``fallback_account_id`` resolver. The command:

    - Resolves (account_id, conversation_id) from explicit flags, then an
      ``--elephant-id`` lookup against the gateway identity store, then the
      single-identity fallback rule shared with cron delivery.
    - Enqueues one row. The live gateway process's drain worker sends it via
      the adapter's normal send path, so cron replies, interactive replies, and
      operator-issued test messages now travel exactly one delivery implementation.
    - With ``--wait``, blocks until the row drains from the queue (= sent) or
      ``--wait-timeout`` elapses.

    Purpose: let the operator prove IM connectivity end-to-end *without* depending
    on the LLM or on the cron agent producing output. If this command doesn't
    reach your chat, the problem is in the gateway; if it does, the problem is
    upstream (prompt, scheduler, model provider).
    """
    import time
    from pathlib import Path

    from packages.gateway_core import (
        FileGatewayIdentityStore,
        GatewayOutboundQueue,
        default_outbound_queue_path,
        resolve_cron_identity_records,
    )

    state_dir = Path(str(args.state_dir))
    identity_store = FileGatewayIdentityStore(state_dir / "gateway-identities.json")

    conversation_id = getattr(args, "conversation_id", None)
    account_id = getattr(args, "account_id", None)
    elephant_id = getattr(args, "elephant_id", None)

    if not conversation_id:
        # Reuse the cron identity resolver so single-elephant fallback behaves identically
        # to the cron delivery path.
        records = resolve_cron_identity_records(
            identity_store=identity_store,
            adapter_id=adapter_id,
            elephant_id=elephant_id,
        )
        if not records:
            print(
                f"No {adapter_label} identity resolved. Pass --conversation-id or --elephant-id, or "
                f"ensure at least one {adapter_label} conversation is registered.",
                flush=True,
            )
            return 2
        record = records[0]
        conversation_id = record.key.conversation_id
        if not account_id:
            account_id = record.key.account_id
    if not account_id and callable(fallback_account_id):
        account_id = fallback_account_id()
    if not account_id:
        print(
            f"Could not resolve a {adapter_label} account_id. Pass the account id as a positional argument.",
            flush=True,
        )
        return 2

    queue = GatewayOutboundQueue(path=default_outbound_queue_path(state_dir))
    row = queue.enqueue(
        adapter_id=adapter_id,
        account_id=account_id,
        conversation_id=conversation_id,
        body=args.body,
        metadata={
            "enqueued_via": f"elephant gateway {adapter_label} message",
            "runtime_surface": surface_hint,
        },
    )
    print(f"Enqueued row {row.row_id}")
    print(f"  adapter_id:      {row.adapter_id}")
    print(f"  account_id:      {row.account_id}")
    print(f"  conversation_id: {row.conversation_id}")
    print(f"  body:            {row.body}")

    if not bool(getattr(args, "wait", False)):
        print(
            f"The live {adapter_label} gateway process will pick this up within ~2s and send it. "
            f"Pass --wait to block until the row drains.",
            flush=True,
        )
        return 0

    deadline = time.monotonic() + float(getattr(args, "wait_timeout", 10.0) or 10.0)
    while time.monotonic() < deadline:
        remaining = [item for item in queue.list_rows() if item.row_id == row.row_id]
        if not remaining:
            print("Delivered (row drained from queue).")
            return 0
        current = remaining[0]
        if current.last_error:
            print(
                f"Attempt {current.attempts} failed: {current.last_error}",
                flush=True,
            )
        time.sleep(0.5)
    print("Timed out waiting for delivery. The row may still be retried in the background.")
    return 3


def _run_wecom_start(service: WecomGatewayService, args: Namespace) -> int:
    transport = _resolve_runtime_target_argument(args, service=service)
    service.prepare_managed_runtime(action="startup", target=transport)
    if args.detach:
        return _start_via_daemon(args)
    guarded = _guard_daemon_running(args)
    if guarded is not None:
        return guarded

    account_label = args.account_id or "<all enabled>"
    print("Starting Elephant Agent Gateway WeCom WebSocket transport")
    print(f"WeCom account: {account_label}")
    asyncio.run(service.start_gateway(account_id=args.account_id))
    return 0

def _start_wecom_runtime_after_setup(args: Namespace, *, transport: str) -> int:
    start_args = Namespace(**vars(args))
    start_args.runtime_target = transport or "configured"
    start_args.account_id = None
    start_args.detach = True
    start_args.timeout = float(getattr(start_args, "timeout", 10.0) or 10.0)
    start_args.force = bool(getattr(start_args, "force", False))
    return _start_via_daemon(start_args)


def _start_via_daemon(args: Namespace) -> int:
    """Start the unified Elephant daemon instead of a per-adapter detached process.

    All IM adapters, cron, supervisor, and learning worker now run inside a
    single daemon process.  When ``gateway <adapter> start --detach`` is
    invoked we redirect to ``elephant daemon start --detach``.

    If the daemon is already running, we dynamically start the requested
    adapter via the daemon's HTTP API instead of just printing a notice.
    """
    from apps.daemon_command import (
        daemon_is_running,
        daemon_pid_path,
        daemon_record_path,
        start_daemon_detached,
        _read_pid,
        _load_record,
        _pid_from_healthz,
    )

    state_dir = Path(args.state_dir)

    # If daemon is already running, start the specific adapter via API
    if daemon_is_running(state_dir):
        service_key = getattr(args, "service_key", None)
        if service_key:
            return _start_adapter_via_daemon_api(args, service_key)
        # No specific adapter — just report daemon status
        pid = _read_pid(daemon_pid_path(state_dir))
        if pid is None:
            pid = _pid_from_healthz(state_dir)
        record = _load_record(daemon_record_path(state_dir)) or {}
        host = record.get("host", "0.0.0.0")
        port = record.get("port", 8900)
        print(f"Elephant daemon is already running (pid {pid}).")
        print(f"All configured IM adapters are managed by the daemon.")
        print(f"  HTTP: http://{host}:{port}/healthz")
        print(f"  Stop: elephant daemon stop")
        print(f"  Status: elephant daemon status")
        return 0

    # Start the daemon — use args.host/port if available, otherwise defaults
    host = getattr(args, "host", "0.0.0.0") or "0.0.0.0"
    port = int(getattr(args, "port", 8900) or 8900)
    return start_daemon_detached(
        state_dir,
        Path(args.cli_state_dir),
        host=host,
        port=port,
    )


def _resolve_daemon_http_addr(state_dir: Path) -> tuple[str, int]:
    """Resolve the daemon HTTP address from runtime record."""
    from apps.daemon_command import _load_record, _daemon_record_path
    record_path = _daemon_record_path(state_dir)
    record = _load_record(record_path) if record_path.exists() else {}
    record = record or {}
    host = record.get("host", "0.0.0.0")
    port = record.get("port", 8900)
    # Use loopback when bound to all interfaces
    addr = host if host != "0.0.0.0" else "127.0.0.1"
    return addr, port


def _start_adapter_via_daemon_api(args: Namespace, service_key: str) -> int:
    """Dynamically start a single adapter in a running daemon via HTTP API."""
    import urllib.request
    import urllib.error

    state_dir = Path(args.state_dir)
    addr, port = _resolve_daemon_http_addr(state_dir)

    url = f"http://{addr}:{port}/api/adapters/{service_key}/start"
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = {}
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            LOGGER.warning("failed to parse gateway adapter start error response", exc_info=True)
            pass
        # HTTP 403 from daemon means "skipped" (e.g. no credentials)
        if body.get("status") == "skipped":
            reason = body.get("reason", "unknown")
            print(f"{service_key} adapter skipped: {reason}")
            print(f"Configure credentials first: elephant gateway {service_key} add")
            return 1
        reason = body.get("reason", f"HTTP {exc.code}")
        print(f"Failed to start {service_key} adapter: {reason}")
        return 1
    except Exception as exc:
        print(f"Failed to reach daemon: {exc}")
        return 1

    status = result.get("status", "unknown")
    if status == "running":
        print(f"{service_key} adapter started successfully.")
    elif status == "already_running":
        print(f"{service_key} adapter is already running.")
    elif status == "skipped":
        reason = result.get("reason", "unknown")
        print(f"{service_key} adapter skipped: {reason}")
        print(f"Configure credentials first: elephant gateway {service_key} add")
        return 1
    else:
        reason = result.get("reason", "unknown")
        print(f"{service_key} adapter failed to start: {reason}")
        return 1
    return 0


def _stop_adapter_via_daemon_api(args: Namespace, service_key: str) -> int:
    """Dynamically stop a single adapter in a running daemon via HTTP API."""
    import urllib.request
    import urllib.error

    state_dir = Path(args.state_dir)
    addr, port = _resolve_daemon_http_addr(state_dir)

    url = f"http://{addr}:{port}/api/adapters/{service_key}/stop"
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = {}
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            LOGGER.warning("failed to parse gateway adapter stop error response", exc_info=True)
            pass
        reason = body.get("reason", f"HTTP {exc.code}")
        print(f"Failed to stop {service_key} adapter: {reason}")
        return 1
    except Exception as exc:
        print(f"Failed to reach daemon: {exc}")
        return 1

    status = result.get("status", "unknown")
    if status == "stopped":
        print(f"{service_key} adapter stopped.")
    elif status == "not_running":
        print(f"{service_key} adapter is not running.")
    else:
        print(f"{service_key} adapter: {status}")
    return 0


def _daemon_is_running_for_state(args: Namespace) -> bool:
    """Check if the unified daemon is running for the given state directory."""
    from apps.daemon_command import daemon_is_running

    return daemon_is_running(Path(args.state_dir))


def _stop_via_daemon(args: Namespace) -> int:
    """Redirect stop to the unified daemon.

    When the daemon is running, stop the specific adapter via HTTP API
    rather than stopping the entire daemon process.
    """
    service_key = getattr(args, "service_key", None)
    if service_key and _daemon_is_running_for_state(args):
        return _stop_adapter_via_daemon_api(args, service_key)

    # Fallback: stop the entire daemon
    from apps.daemon_command import stop_daemon

    print("Stopping unified Elephant daemon...")
    return stop_daemon(
        Path(args.state_dir),
        timeout=float(getattr(args, "timeout", 10.0) or 10.0),
        force=bool(getattr(args, "force", False)),
    )


def _restart_via_daemon(args: Namespace) -> int:
    """Redirect restart to the unified daemon.

    When the daemon is running, restart the specific adapter via HTTP API
    (stop then start) rather than restarting the entire daemon process.
    """
    service_key = getattr(args, "service_key", None)
    if service_key and _daemon_is_running_for_state(args):
        rc = _stop_adapter_via_daemon_api(args, service_key)
        if rc != 0:
            return rc
        return _start_adapter_via_daemon_api(args, service_key)

    # Fallback: restart the entire daemon
    from apps.daemon_command import restart_daemon

    host = getattr(args, "host", "0.0.0.0") or "0.0.0.0"
    port = int(getattr(args, "port", 8900) or 8900)
    print("Restarting unified Elephant daemon...")
    return restart_daemon(
        Path(args.state_dir),
        Path(args.cli_state_dir),
        host=host,
        port=port,
        timeout=float(getattr(args, "timeout", 10.0) or 10.0),
        force=bool(getattr(args, "force", False)),
    )

def _http_services(
    services: Mapping[str, object],
) -> dict[str, GatewayHttpService]:
    return {
        key: service
        for key, service in services.items()
        if isinstance(service, GatewayHttpService)
    }

def _run_serve(args: Namespace) -> int:
    app, services = _build_services(args)
    if not services:
        raise SystemExit("No gateway services are enabled in the active profile manifest.")
    http_services = _http_services(services)
    if not http_services:
        raise SystemExit("No enabled gateway HTTP services are available in the active profile manifest.")
    web_app = create_gateway_web_app(http_services, app=app)
    with make_server(args.host, args.port, web_app) as server:
        print(f"Serving Elephant Agent Gateway on http://{args.host}:{args.port}")
        for key, service in http_services.items():
            event_paths = ", ".join(getattr(service, "http_paths", ())) or "<none>"
            print(f"{key} event paths: {event_paths}")
        server.serve_forever()
    return 0

def command_main(
    argv: Sequence[str] | None = None,
    *,
    default_state_dir: Path | None = None,
    default_control_state_dir: Path | None = None,
) -> int:
    defaults = _resolved_defaults(
        default_state_dir_override=default_state_dir,
        default_control_state_dir_override=default_control_state_dir,
    )
    resolved_argv = list(argv) if argv is not None else list(sys.argv[1:])
    if not resolved_argv:
        resolved_argv = ["status"]
    parser = build_gateway_arg_parser(defaults=defaults)
    args = parser.parse_args(resolved_argv)
    if hasattr(args, "account_id_flag"):
        args.account_id = _resolved_cli_account_id(args)
    action = getattr(args, "command_action", None)
    if action is None:
        parser.print_help()
        return 2
    if action == "setup":
        return run_im_setup(
            default_state_dir=args.state_dir,
            default_control_state_dir=args.cli_state_dir,
            prompt_title=str(getattr(args, "prompt_title", "💬 IM Setup") or "💬 IM Setup"),
            prompt_text=str(
                getattr(args, "prompt_text", "💬 Which IM should Elephant Agent configure right now?")
                or "💬 Which IM should Elephant Agent configure right now?"
            ),
            allow_skip=bool(getattr(args, "allow_skip", False)),
        )
    if action == "status_all":
        return _run_status_all(args)
    if action == "describe_all":
        app, services = _build_services(args)
        _print_json(_describe_services_payload(app, services))
        return 0
    if action == "doctor_all":
        app, services = _build_services(args)
        print("\n".join(_doctor_services_lines(app, services, args)))
        return 0
    if action == "serve_all":
        return _run_serve(args)
    if action == "add_discord":
        return _run_add_discord(args)
    if action == "add_feishu":
        return _run_add_feishu(args)
    if action == "add_dingding":
        return _run_add_dingding(args)
    if action == "add_weixin":
        return _run_add_weixin(args)
    if action == "add_wecom":
        return _run_add_wecom(args)
    if action == "remove_discord":
        return _run_remove_discord(args)
    if action == "remove_feishu":
        return _run_remove_feishu(args)
    if action == "remove_dingding":
        return _run_remove_dingding(args)
    if action == "remove_weixin":
        return _run_remove_weixin(args)
    if action == "remove_wecom":
        return _run_remove_wecom(args)

    service_key = str(getattr(args, "service_key", "feishu") or "feishu")
    service: object | None = None
    managed_service: GatewayManagedService | None = None

    def ensure_service() -> object:
        nonlocal service
        if service is None:
            if service_key == "discord":
                service = _build_discord_service(args)
            elif service_key == "feishu":
                service = _build_feishu_service(args)
            elif service_key == "dingding":
                service = _build_dingding_service(args)
            elif service_key == "weixin":
                service = _build_weixin_service(args)
            elif service_key == "wecom":
                service = _build_wecom_service(args)
            else:
                raise SystemExit(f"Unsupported IM service: {service_key}")
        return service

    def ensure_managed_service() -> GatewayManagedService:
        nonlocal managed_service
        if managed_service is None:
            managed_service = _build_managed_service(args, service_key=service_key)
        return managed_service

    if action == "describe":
        _print_json(_describe_payload(service_key, ensure_service()))
        return 0
    if action == "doctor":
        if service_key == "discord":
            print("\n".join(_discord_doctor_lines(ensure_service(), args)))
        elif service_key == "dingding":
            print("\n".join(_dingding_doctor_lines(ensure_service(), args)))
        elif service_key == "weixin":
            print("\n".join(_weixin_doctor_lines(ensure_service(), args)))
        elif service_key == "wecom":
            print("\n".join(_wecom_doctor_lines(ensure_service(), args)))
        else:
            print("\n".join(_doctor_lines(ensure_service(), args)))
        return 0
    if action == "status":
        return _run_status(args, service=ensure_managed_service())
    if action == "stop":
        if _daemon_is_running_for_state(args):
            return _stop_via_daemon(args)
        print("Elephant daemon is not running. Nothing to stop.")
        return 0
    if action == "restart":
        if _daemon_is_running_for_state(args):
            return _restart_via_daemon(args)
        # No daemon running — start a fresh daemon
        return _start_via_daemon(args)
    if action == "logs":
        return _run_logs(args, service=ensure_managed_service())
    if action == "message":
        if service_key == "weixin":
            weixin_service = ensure_service()
            if not isinstance(weixin_service, WeixinGatewayService):
                raise TypeError("gateway service plugin 'weixin' must build WeixinGatewayService")
            return _run_weixin_message(weixin_service, args)
        if service_key == "feishu":
            feishu_service = ensure_service()
            if not isinstance(feishu_service, FeishuGatewayService):
                raise TypeError("gateway service plugin 'feishu' must build FeishuGatewayService")
            return _run_feishu_message(feishu_service, args)
        if service_key == "discord":
            discord_service = ensure_service()
            if not isinstance(discord_service, DiscordGatewayService):
                raise TypeError("gateway service plugin 'discord' must build DiscordGatewayService")
            return _run_discord_message(discord_service, args)
        raise SystemExit(f"'message' command is not yet supported for {service_key}.")
    if service_key == "discord":
        discord_service = ensure_service()
        if not isinstance(discord_service, DiscordGatewayService):
            raise TypeError("gateway service plugin 'discord' must build DiscordGatewayService")
        return _run_discord_start(discord_service, args)
    if service_key == "dingding":
        dingding_service = ensure_service()
        if not isinstance(dingding_service, DingdingGatewayService):
            raise TypeError("gateway service plugin 'dingding' must build DingdingGatewayService")
        return _run_dingding_start(dingding_service, args)
    if service_key == "weixin":
        weixin_service = ensure_service()
        if not isinstance(weixin_service, WeixinGatewayService):
            raise TypeError("gateway service plugin 'weixin' must build WeixinGatewayService")
        return _run_weixin_start(weixin_service, args)
    if service_key == "wecom":
        wecom_service = ensure_service()
        if not isinstance(wecom_service, WecomGatewayService):
            raise TypeError("gateway service plugin 'wecom' must build WecomGatewayService")
        return _run_wecom_start(wecom_service, args)
    feishu_service = ensure_service()
    if not isinstance(feishu_service, FeishuGatewayService):
        raise TypeError("gateway service plugin 'feishu' must build FeishuGatewayService")
    return _run_start(feishu_service, args)

def run_im_setup(
    *,
    default_state_dir: Path | None = None,
    default_control_state_dir: Path | None = None,
    prompt_title: str = "💬 IM Setup",
    prompt_text: str = "💬 Which IM should Elephant Agent configure right now?",
    allow_skip: bool = False,
) -> int:
    answer = _gateway_wizard_choice_prompt(
        prompt_title,
        prompt_text,
        _im_setup_choices(allow_skip=allow_skip),
        default="skip" if allow_skip else "weixin",
        allow_back=not allow_skip,
    )
    if answer is GATEWAY_WIZARD_BACK or answer == "skip":
        return 0
    if answer not in {"feishu", "discord", "dingding", "weixin", "wecom"}:
        raise SystemExit(f"Unsupported IM setup target: {answer}")
    argv = [str(answer), "setup", "--wizard"]
    return command_main(
        argv,
        default_state_dir=default_state_dir,
        default_control_state_dir=default_control_state_dir,
    )

def build_typer_app(
    *,
    default_state_dir: Path | None = None,
    default_control_state_dir: Path | None = None,
) -> typer.Typer:
    app = typer.Typer(
        name="elephant gateway",
        help="Manage IM providers and accounts.",
        no_args_is_help=False,
        rich_markup_mode="rich",
        add_completion=False,
    )
    passthrough_settings = {"allow_extra_args": True, "ignore_unknown_options": True}

    def _forward(ctx: typer.Context, command_name: str | None = None) -> int:
        argv = []
        if command_name:
            argv.append(command_name)
        argv.extend(ctx.args)
        return command_main(
            argv,
            default_state_dir=default_state_dir,
            default_control_state_dir=default_control_state_dir,
        )

    @app.callback(invoke_without_command=True)
    def gateway_callback(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            raise typer.Exit(_forward(ctx))

    @app.command("setup", help="Open interactive IM setup.", context_settings=passthrough_settings)
    def setup_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "setup"))

    @app.command("status", help="Show status for all providers and accounts.", context_settings=passthrough_settings)
    def status_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "status"))

    @app.command("doctor", help="Run health checks for all providers and accounts.", context_settings=passthrough_settings)
    def doctor_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "doctor"))

    @app.command("describe", help="Print resolved IM provider and account wiring as JSON.", context_settings=passthrough_settings)
    def describe_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "describe"))

    @app.command("feishu", help="Manage Feishu accounts.", context_settings=passthrough_settings)
    def feishu_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "feishu"))

    @app.command("discord", help="Manage Discord accounts.", context_settings=passthrough_settings)
    def discord_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "discord"))

    @app.command("dingding", help="Manage DingDing accounts.", context_settings=passthrough_settings)
    def dingding_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "dingding"))

    @app.command("weixin", help="Manage WeChat accounts.", context_settings=passthrough_settings)
    def weixin_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "weixin"))

    @app.command("wecom", help="Manage WeCom accounts.", context_settings=passthrough_settings)
    def wecom_command(ctx: typer.Context) -> None:
        raise typer.Exit(_forward(ctx, "wecom"))

    return app


def main(
    argv: Sequence[str] | None = None,
    *,
    default_state_dir: Path | None = None,
    default_control_state_dir: Path | None = None,
) -> int:
    from packages.operator.typer_support import run_typer_app

    return run_typer_app(
        build_typer_app(
            default_state_dir=default_state_dir,
            default_control_state_dir=default_control_state_dir,
        ),
        list(argv) if argv is not None else None,
        prog_name="elephant gateway",
    )
