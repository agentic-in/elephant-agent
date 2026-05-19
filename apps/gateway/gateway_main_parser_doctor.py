"""Gateway parser doctor and status rendering helpers."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Mapping

from . import GatewayManagedService
from .gateway_main_parser_state import *  # noqa: F401,F403
from .gateway_main_runtime import *  # noqa: F401,F403


def _mapping_payload(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _render_feishu_account_line(account: Mapping[str, object], *, prefix: str = "feishu_account") -> str:
    parts = [
        str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
        f"credentials={account.get('credentials_status') or '<unknown>'}",
        f"surface={account.get('surface') or '<unset>'}",
        f"event_path={account.get('event_path') or '<unset>'}",
    ]
    resolved_app_id = str(account.get("resolved_app_id") or "").strip()
    if resolved_app_id:
        parts.append(f"app_id={resolved_app_id}")
    return f"{prefix}: " + " · ".join(parts)


def _selected_account_payloads(
    description: Mapping[str, object],
    *,
    account_id: str | None,
    provider: str,
) -> tuple[Mapping[str, object], ...]:
    accounts = tuple(account for account in tuple(description.get("accounts") or ()) if isinstance(account, Mapping))
    if account_id is None:
        return accounts
    matched = tuple(
        account for account in accounts if str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID) == account_id
    )
    if matched:
        return matched
    raise SystemExit(f"unknown {provider} account: {account_id}")


def _next_steps(service) -> tuple[str, ...]:
    description = service.describe()
    accounts = tuple(description.get("accounts") or ())
    control = dict(description.get("control") or {})
    steps: list[str] = []
    if description.get("sdk_dependency_status") == "missing_optional_dependency":
        steps.append(
            "Elephant Agent will auto-install the Feishu SDK when you run `elephant gateway` or `elephant gateway feishu start`."
        )
    if any(account.get("credentials_status") != "configured" for account in accounts if isinstance(account, dict)):
        env_vars: list[str] = []
        secret_reference_ids: list[str] = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            credential_env_vars = account.get("credential_env_vars")
            if isinstance(credential_env_vars, (list, tuple)):
                env_vars.extend(value for value in credential_env_vars if isinstance(value, str) and value)
            else:
                env_vars.extend(
                    value
                    for value in (
                        account.get("app_id_env_var"),
                        account.get("app_secret_env_var"),
                    )
                    if isinstance(value, str) and value
                )
            secret_refs = account.get("secret_reference_ids")
            if isinstance(secret_refs, (list, tuple)):
                secret_reference_ids.extend(value for value in secret_refs if isinstance(value, str) and value)
        if env_vars:
            steps.append(
                "Complete Feishu IM setup again with `elephant gateway` to store the App ID and App Secret locally, or export these advanced credential aliases manually: "
                + ", ".join(dict.fromkeys(env_vars))
            )
        elif secret_reference_ids:
            steps.append(
                "Complete Feishu IM setup again with `elephant gateway` or configure the active Feishu runtime secrets referenced by: "
                + ", ".join(dict.fromkeys(secret_reference_ids))
            )
    if control.get("runtime_status") != "ready":
        steps.append(
            "Make sure the IM bridge can open the local CLI runtime, or pass `--cli-state-dir` explicitly when the launcher defaults are not correct."
        )
    known_elephants = tuple(control.get("known_elephants") or ()) if isinstance(control, dict) else ()
    if not known_elephants:
        steps.append(
            "Create a local elephant first with `elephant herd new demo`. Gateway plain text only routes after you bind this thread with `/elephant create <name>`."
        )
    if not steps:
        steps.append("IM wiring looks healthy. Start it with `elephant gateway feishu start`. ")
    return tuple(steps)


def _render_discord_account_line(account: Mapping[str, object], *, prefix: str = "discord_account") -> str:
    allow_guild_ids = tuple(account.get("allow_guild_ids") or ())
    allow_channel_ids = tuple(account.get("allow_channel_ids") or ())
    parts = [
        str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
        f"enabled={'yes' if account.get('enabled') is not False else 'no'}",
        f"startup={account.get('startup_status') or '<unknown>'}",
        f"credentials={account.get('credentials_status') or '<unknown>'}",
        f"surface={account.get('surface') or '<unset>'}",
        f"bot_token_env_var={account.get('bot_token_env_var') or '<unset>'}",
        f"allow_guilds={len(allow_guild_ids)}",
        f"allow_channels={len(allow_channel_ids)}",
    ]
    credentials_error = str(account.get("credentials_error") or "").strip()
    if credentials_error:
        parts.append(f"error={credentials_error}")
    return f"{prefix}: " + " · ".join(parts)


def _feishu_async_status_lines(
    description: Mapping[str, object],
    *,
    prefix: str = "",
) -> tuple[str, ...]:
    recent_failures = tuple(description.get("recent_failures") or ())
    lines = [
        f"{prefix}async_delivery_enabled: {'yes' if description.get('async_delivery_enabled') else 'no'}",
        f"{prefix}queue_depth: {description.get('queue_depth') or 0}",
        f"{prefix}running_jobs: {description.get('running_jobs') or 0}",
        f"{prefix}worker_count: {description.get('worker_count') or 0}",
        f"{prefix}recent_failures: {len(recent_failures)}",
    ]
    for index, failure in enumerate(recent_failures[:3], start=1):
        if not isinstance(failure, Mapping):
            continue
        lines.append(
            f"{prefix}failure[{index}]: "
            f"{failure.get('account_id') or DEFAULT_GATEWAY_ACCOUNT_ID} · "
            f"conversation={failure.get('conversation_id') or '<unknown>'} · "
            f"message={failure.get('message_id') or '<unknown>'} · "
            f"summary={failure.get('failure_summary') or '<unknown>'}"
        )
    return tuple(lines)


def _discord_account_status_lines(
    description: Mapping[str, object],
    *,
    prefix: str = "",
) -> tuple[str, ...]:
    account_status = dict(description.get("account_status") or {})
    if not account_status:
        return ()
    blocked_account_ids = tuple(account_status.get("blocked_account_ids") or ())
    disabled_account_ids = tuple(account_status.get("disabled_account_ids") or ())
    return (
        f"{prefix}account_service_status: {account_status.get('service_status') or '<unknown>'}",
        f"{prefix}configured_accounts: {account_status.get('configured_accounts') or 0}",
        f"{prefix}enabled_accounts: {account_status.get('enabled_accounts') or 0}",
        f"{prefix}runnable_accounts: {account_status.get('runnable_accounts') or 0}",
        f"{prefix}blocked_accounts: {account_status.get('blocked_accounts') or 0}",
        f"{prefix}disabled_accounts: {account_status.get('disabled_accounts') or 0}",
        f"{prefix}blocked_account_ids: "
        + (", ".join(str(account_id) for account_id in blocked_account_ids if account_id) or "<none>"),
        f"{prefix}disabled_account_ids: "
        + (", ".join(str(account_id) for account_id in disabled_account_ids if account_id) or "<none>"),
    )


def _discord_portal_checklist() -> tuple[str, ...]:
    return (
        "Open Discord Developer Portal → OAuth2 → URL Generator and include the `bot` scope before inviting the app.",
        "Enable the Discord `MESSAGE_CONTENT` privileged intent for this bot before starting the gateway runtime.",
        "Grant these bot permissions in Discord: `View Channels` (`查看频道`), `Send Messages` (`发送消息`), `Send Messages in Threads` (`在子区内发送消息`), and `Read Message History` (`阅读消息历史记录`).",
    )


def _discord_next_steps(service) -> tuple[str, ...]:
    description = service.describe()
    accounts = tuple(description.get("accounts") or ())
    account_status = dict(description.get("account_status") or {})
    runtime = dict(description.get("runtime") or {})
    runtime_status = str(runtime.get("runtime_status") or "").strip().lower()
    runtime_target = str(runtime.get("target") or description.get("configured_transport") or "gateway")
    enabled_accounts = int(account_status.get("enabled_accounts") or 0)
    runnable_accounts = int(account_status.get("runnable_accounts") or 0)
    blocked_account_ids = tuple(account_status.get("blocked_account_ids") or ())
    service_status = str(account_status.get("service_status") or "").strip().lower()
    steps: list[str] = []
    if description.get("sdk_dependency_status") == "missing_optional_dependency":
        steps.append("Elephant Agent will auto-install Discord support when you run `elephant gateway discord start`.")
    missing_credentials = [
        account
        for account in accounts
        if isinstance(account, dict)
        and account.get("enabled") is not False
        and account.get("credentials_status") != "configured"
    ]
    if missing_credentials:
        env_vars = [
            str(account.get("bot_token_env_var"))
            for account in missing_credentials
            if str(account.get("bot_token_env_var") or "").strip()
        ]
        if env_vars:
            steps.append(
                "Configure the Discord bot token with `elephant gateway discord setup [account-id] --bot-token ...` or export these env vars manually: "
                + ", ".join(dict.fromkeys(env_vars))
            )
    if enabled_accounts == 0:
        steps.append(
            "Enable at least one Discord account for runtime starts by re-running `elephant gateway discord setup [account-id]` before starting the gateway runtime."
        )
    steps.append("Review the Discord developer portal checklist below before starting the gateway runtime.")
    if runtime_status == "running":
        if service_status == "degraded" and blocked_account_ids:
            steps.append(
                f"Discord gateway runtime is already running on `{runtime_target}` in degraded mode; blocked enabled accounts were skipped: {', '.join(str(account_id) for account_id in blocked_account_ids if account_id)}."
            )
        else:
            steps.append(f"Discord gateway runtime is already running on `{runtime_target}`.")
    elif service_status == "degraded" and runnable_accounts > 0:
        steps.append(
            "Discord wiring is partially ready. Start it with `elephant gateway discord start`; runnable enabled accounts will connect while blocked accounts are skipped."
        )
    elif service_status == "ready" and runnable_accounts > 0:
        steps.append("Discord wiring looks healthy. Start it with `elephant gateway discord start`.")
    return tuple(steps)


def _doctor_lines(service, args: Namespace) -> tuple[str, ...]:
    description = service.describe()
    control = dict(description.get("control") or {})
    lines = [
        "Elephant Agent Gateway doctor",
        f"im_gateway_dir: {args.state_dir}",
        f"cli_herd_dir: {args.cli_state_dir}",
        f"configured_transport: {description.get('configured_transport') or '<unset>'}",
        f"sdk_dependency_status: {description.get('sdk_dependency_status')}",
    ]
    lines.extend(_feishu_async_status_lines(description))
    if description.get("configured_transport_error"):
        lines.append(f"configured_transport_error: {description['configured_transport_error']}")
    for account in _selected_account_payloads(
        description,
        account_id=_resolved_cli_account_id(args),
        provider="feishu",
    ):
        lines.append(_render_feishu_account_line(account))
    lines.append(f"control_runtime_status: {control.get('runtime_status') or '<unknown>'}")
    if control.get("runtime_error"):
        lines.append(f"control_runtime_error: {control['runtime_error']}")
    known_elephants = tuple(control.get("known_elephants") or ())
    lines.append(
        "control_known_elephants: " + (", ".join(str(elephant) for elephant in known_elephants if elephant) or "<none>")
    )
    lines.append("next_steps:")
    lines.extend(f"- {step}" for step in _next_steps(service))
    return tuple(lines)


def _discord_doctor_lines(service, args: Namespace) -> tuple[str, ...]:
    description = service.describe()
    runtime = _mapping_payload(description.get("runtime"))
    control = _mapping_payload(description.get("control"))
    lines = [
        "Elephant Agent Gateway doctor",
        f"im_gateway_dir: {args.state_dir}",
        f"cli_herd_dir: {args.cli_state_dir}",
        f"configured_transport: {description.get('configured_transport') or '<unset>'}",
        f"sdk_dependency_status: {description.get('sdk_dependency_status') or '<n/a>'}",
        f"runtime_status: {runtime.get('runtime_status') or '<unknown>'}",
        f"control_runtime_status: {control.get('runtime_status') or '<unknown>'}",
        "required_intents: "
        + ", ".join(str(intent) for intent in tuple(description.get("required_intents") or ()) if intent),
    ]
    lines.extend(_discord_account_status_lines(description))
    if description.get("configured_transport_error"):
        lines.append(f"configured_transport_error: {description['configured_transport_error']}")
    if runtime.get("target"):
        lines.append(f"runtime_target: {runtime['target']}")
    if runtime.get("pid") is not None:
        lines.append(f"runtime_pid: {runtime['pid']}")
    if runtime.get("stale_pid_file"):
        lines.append("runtime_stale_pid_file: yes")
    if control.get("runtime_error"):
        lines.append(f"control_runtime_error: {control['runtime_error']}")
    known_elephants = tuple(control.get("known_elephants") or ())
    lines.append(
        "control_known_elephants: " + (", ".join(str(elephant) for elephant in known_elephants if elephant) or "<none>")
    )
    for account in _selected_account_payloads(
        description,
        account_id=_resolved_cli_account_id(args),
        provider="discord",
    ):
        lines.append(_render_discord_account_line(account))
    lines.append("discord_portal_checklist:")
    lines.extend(f"- {step}" for step in _discord_portal_checklist())
    lines.append("next_steps:")
    lines.extend(f"- {step}" for step in _discord_next_steps(service))
    return tuple(lines)


def _render_dingding_account_line(account: Mapping[str, object], *, prefix: str = "dingding_account") -> str:
    parts = [
        str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
        f"enabled={'yes' if account.get('enabled') is not False else 'no'}",
        f"surface={account.get('surface') or '<unset>'}",
    ]
    return f"{prefix}: " + " · ".join(parts)


def _dingding_next_steps(service) -> tuple[str, ...]:
    description = service.describe()
    accounts = tuple(description.get("accounts") or ())
    steps: list[str] = []
    if description.get("sdk_dependency_status") == "missing_optional_dependency":
        steps.append(
            "Elephant Agent will auto-install DingDing support when you run `elephant gateway dingding start`."
        )
    missing_credentials = [
        account
        for account in accounts
        if isinstance(account, dict)
        and account.get("enabled") is not False
        and account.get("credentials_status") != "configured"
    ]
    if missing_credentials:
        steps.append(
            "Configure DingDing credentials with `elephant gateway dingding setup` "
            "or set ELEPHANT_DINGDING_CLIENT_ID, ELEPHANT_DINGDING_CLIENT_SECRET, ELEPHANT_DINGDING_ROBOT_CODE env vars."
        )
    if not steps:
        steps.append("DingDing wiring looks healthy. Start it with `elephant gateway dingding start`.")
    return tuple(steps)


def _dingding_doctor_lines(service, args: Namespace) -> tuple[str, ...]:
    description = service.describe()
    control = dict(description.get("control") or {})
    lines = [
        "Elephant Agent Gateway doctor",
        f"im_gateway_dir: {args.state_dir}",
        f"cli_herd_dir: {args.cli_state_dir}",
        f"configured_transport: {description.get('configured_transport') or '<unset>'}",
        f"sdk_dependency_status: {description.get('sdk_dependency_status') or '<n/a>'}",
    ]
    if description.get("configured_transport_error"):
        lines.append(f"configured_transport_error: {description['configured_transport_error']}")
    lines.append(f"control_runtime_status: {control.get('runtime_status') or '<unknown>'}")
    if control.get("runtime_error"):
        lines.append(f"control_runtime_error: {control['runtime_error']}")
    for account in _selected_account_payloads(
        description,
        account_id=_resolved_cli_account_id(args),
        provider="dingding",
    ):
        lines.append(_render_dingding_account_line(account))
    lines.append("next_steps:")
    lines.extend(f"- {step}" for step in _dingding_next_steps(service))
    return tuple(lines)


def _render_weixin_account_line(account: Mapping[str, object], *, prefix: str = "weixin_account") -> str:
    parts = [
        str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
        f"enabled={'yes' if account.get('enabled') is not False else 'no'}",
        f"surface={account.get('surface') or '<unset>'}",
    ]
    wxhook_host = account.get("wxhook_host")
    wxhook_port = account.get("wxhook_port")
    if wxhook_host or wxhook_port:
        parts.append(f"wxhook={wxhook_host or '127.0.0.1'}:{wxhook_port or 8888}")
    return f"{prefix}: " + " · ".join(parts)


def _weixin_next_steps(service) -> tuple[str, ...]:
    description = service.describe()
    steps: list[str] = []
    if description.get("sdk_dependency_status") == "missing_optional_dependency":
        steps.append(
            "Elephant Agent will auto-install WeChat (iLink) support when you run `elephant gateway weixin start`."
        )
    if not steps:
        steps.append("WeChat wiring looks healthy. Start it with `elephant gateway weixin start`.")
    return tuple(steps)


def _weixin_doctor_lines(service, args: Namespace) -> tuple[str, ...]:
    description = service.describe()
    control = dict(description.get("control") or {})
    lines = [
        "Elephant Agent Gateway doctor",
        f"im_gateway_dir: {args.state_dir}",
        f"cli_herd_dir: {args.cli_state_dir}",
        f"configured_transport: {description.get('configured_transport') or '<unset>'}",
        f"sdk_dependency_status: {description.get('sdk_dependency_status') or '<n/a>'}",
    ]
    if description.get("configured_transport_error"):
        lines.append(f"configured_transport_error: {description['configured_transport_error']}")
    lines.append(f"control_runtime_status: {control.get('runtime_status') or '<unknown>'}")
    if control.get("runtime_error"):
        lines.append(f"control_runtime_error: {control['runtime_error']}")
    for account in _selected_account_payloads(
        description,
        account_id=_resolved_cli_account_id(args),
        provider="weixin",
    ):
        lines.append(_render_weixin_account_line(account))
    lines.append("next_steps:")
    lines.extend(f"- {step}" for step in _weixin_next_steps(service))
    return tuple(lines)


def _render_wecom_account_line(account: Mapping[str, object], *, prefix: str = "wecom_account") -> str:
    parts = [
        str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
        f"enabled={'yes' if account.get('enabled') is not False else 'no'}",
        f"surface={account.get('surface') or '<unset>'}",
    ]
    credentials_status = account.get("credentials_status")
    if credentials_status:
        parts.append(f"credentials={credentials_status}")
    return f"{prefix}: " + " · ".join(parts)


def _wecom_next_steps(service) -> tuple[str, ...]:
    description = service.describe()
    accounts = tuple(description.get("accounts") or ())
    steps: list[str] = []
    if description.get("sdk_dependency_status") == "missing_optional_dependency":
        steps.append("Elephant Agent will auto-install WeCom support when you run `elephant gateway wecom start`.")
    missing_credentials = [
        account
        for account in accounts
        if isinstance(account, dict)
        and account.get("enabled") is not False
        and account.get("credentials_status") != "configured"
    ]
    if missing_credentials:
        steps.append(
            "Configure WeCom credentials with `elephant gateway wecom setup` "
            "or set ELEPHANT_WECOM_BOT_ID and ELEPHANT_WECOM_SECRET env vars."
        )
    if not steps:
        steps.append("WeCom wiring looks healthy. Start it with `elephant gateway wecom start`.")
    return tuple(steps)


def _wecom_doctor_lines(service, args: Namespace) -> tuple[str, ...]:
    description = service.describe()
    control = dict(description.get("control") or {})
    lines = [
        "Elephant Agent Gateway doctor",
        f"im_gateway_dir: {args.state_dir}",
        f"cli_herd_dir: {args.cli_state_dir}",
        f"configured_transport: {description.get('configured_transport') or '<unset>'}",
        f"sdk_dependency_status: {description.get('sdk_dependency_status') or '<n/a>'}",
    ]
    if description.get("configured_transport_error"):
        lines.append(f"configured_transport_error: {description['configured_transport_error']}")
    lines.append(f"control_runtime_status: {control.get('runtime_status') or '<unknown>'}")
    if control.get("runtime_error"):
        lines.append(f"control_runtime_error: {control['runtime_error']}")
    for account in _selected_account_payloads(
        description,
        account_id=_resolved_cli_account_id(args),
        provider="wecom",
    ):
        lines.append(_render_wecom_account_line(account))
    lines.append("next_steps:")
    lines.extend(f"- {step}" for step in _wecom_next_steps(service))
    return tuple(lines)


def _doctor_service_lines(
    service_key: str,
    service,
) -> tuple[str, ...]:
    def render_account_line(account: Mapping[str, object]) -> str:
        parts = [
            str(account.get("account_id") or "<default>"),
            f"credentials={account.get('credentials_status')}",
            f"surface={account.get('surface')}",
        ]
        if account.get("enabled") is not None:
            parts.append(f"enabled={'yes' if account.get('enabled') is not False else 'no'}")
        if account.get("startup_status") is not None:
            parts.append(f"startup={account.get('startup_status')}")
        if account.get("event_path") is not None:
            parts.append(f"event_path={account.get('event_path')}")
        if account.get("bot_token_env_var") is not None:
            parts.append(f"bot_token_env_var={account.get('bot_token_env_var')}")
        allow_guild_ids = tuple(account.get("allow_guild_ids") or ())
        allow_channel_ids = tuple(account.get("allow_channel_ids") or ())
        if allow_guild_ids:
            parts.append(f"allow_guilds={len(allow_guild_ids)}")
        if allow_channel_ids:
            parts.append(f"allow_channels={len(allow_channel_ids)}")
        return f"service[{service_key}].account: " + " · ".join(parts)

    if service_key == "feishu":
        description = service.describe()
        lines = [
            f"service[{service_key}].configured_transport: {description.get('configured_transport') or '<unset>'}",
            f"service[{service_key}].sdk_dependency_status: {description.get('sdk_dependency_status') or '<n/a>'}",
        ]
        lines.extend(_feishu_async_status_lines(description, prefix=f"service[{service_key}]."))
        for account in tuple(description.get("accounts") or ()):
            if not isinstance(account, dict):
                continue
            lines.append(render_account_line(account))
        return tuple(lines)
    description = service.describe() if hasattr(service, "describe") else {}
    lines = [
        f"service[{service_key}].configured_transport: {description.get('configured_transport') or '<unset>'}",
    ]
    if description.get("configured_transport_error"):
        lines.append(
            f"service[{service_key}].configured_transport_error: {description.get('configured_transport_error')}"
        )
    if description.get("sdk_dependency_status") is not None:
        lines.append(f"service[{service_key}].sdk_dependency_status: {description.get('sdk_dependency_status')}")
    runtime = _mapping_payload(description.get("runtime"))
    if runtime:
        lines.append(f"service[{service_key}].runtime_status: {runtime.get('runtime_status') or '<unknown>'}")
        if runtime.get("target") is not None:
            lines.append(f"service[{service_key}].runtime_target: {runtime.get('target')}")
    for account in tuple(description.get("accounts") or ()):
        if not isinstance(account, dict):
            continue
        lines.append(render_account_line(account))
    return tuple(lines)


def _doctor_services_lines(app, services: Mapping[str, object], args: Namespace) -> tuple[str, ...]:
    lines = [
        "Elephant Agent Gateway doctor",
        f"im_gateway_dir: {args.state_dir}",
        f"cli_herd_dir: {args.cli_state_dir}",
        "registered_services: " + (", ".join(services.keys()) or "<none>"),
    ]
    lines.extend(
        line for service_key, service in services.items() for line in _doctor_service_lines(service_key, service)
    )
    if "feishu" in services:
        lines.append("next_steps:")
        lines.extend(f"- {step}" for step in _next_steps(services["feishu"]))
    elif "discord" in services:
        lines.append("next_steps:")
        lines.extend(f"- {step}" for step in _discord_next_steps(services["discord"]))
    elif "dingding" in services:
        lines.append("next_steps:")
        lines.extend(f"- {step}" for step in _dingding_next_steps(services["dingding"]))
    elif "weixin" in services:
        lines.append("next_steps:")
        lines.extend(f"- {step}" for step in _weixin_next_steps(services["weixin"]))
    elif "wecom" in services:
        lines.append("next_steps:")
        lines.extend(f"- {step}" for step in _wecom_next_steps(services["wecom"]))
    return tuple(lines)


def _service_runtime_status_summary(service: object, args: Namespace) -> tuple[str, str | None]:
    if not isinstance(service, GatewayManagedService):
        return "unavailable", "service is not a managed runtime"
    try:
        target = service.configured_runtime_target()
        runtime = service.managed_runtime(args=args, target=target)
        state = _runtime_state(runtime)
        return str(state["status"]), None
    except Exception as exc:
        return "unavailable", str(exc)


__all__ = [
    "_render_feishu_account_line",
    "_selected_account_payloads",
    "_next_steps",
    "_render_discord_account_line",
    "_feishu_async_status_lines",
    "_discord_account_status_lines",
    "_discord_portal_checklist",
    "_discord_next_steps",
    "_doctor_lines",
    "_discord_doctor_lines",
    "_render_dingding_account_line",
    "_dingding_next_steps",
    "_dingding_doctor_lines",
    "_render_weixin_account_line",
    "_weixin_next_steps",
    "_weixin_doctor_lines",
    "_render_wecom_account_line",
    "_wecom_next_steps",
    "_wecom_doctor_lines",
    "_doctor_service_lines",
    "_doctor_services_lines",
    "_service_runtime_status_summary",
]
