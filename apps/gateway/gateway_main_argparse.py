"""Argparse tree construction for the gateway command surface."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from .gateway_main_parser import *  # noqa: F401,F403


def _add_message_subparser(
    parent_subparsers,
    *,
    common: ArgumentParser,
    service_key: str,
    adapter_label: str,
    conversation_description: str,
) -> None:
    """Attach the shared ``message`` subcommand to a per-adapter subparsers group.

    Every IM provider exposes the same ``message`` command so operators can send
    a one-off text through that adapter's outbound queue without touching the
    LLM. The flags are identical across providers; only the help text varies.
    """
    parser = parent_subparsers.add_parser(
        "message",
        parents=[common],
        help=(
            f"Send a one-off text message through the {adapter_label} gateway outbound queue "
            f"(connectivity test)."
        ),
    )
    _add_optional_account_argument(
        parser,
        help_text=(
            f"{adapter_label} account id owning the conversation. Omit to fall back to the single "
            f"registered {adapter_label} account."
        ),
    )
    parser.add_argument(
        "--conversation-id",
        dest="conversation_id",
        help=conversation_description,
    )
    parser.add_argument(
        "--elephant-id",
        dest="elephant_id",
        help="Lookup conversation by bound elephant id instead of passing --conversation-id explicitly.",
    )
    parser.add_argument(
        "--body",
        required=True,
        help="Message body. Use quotes for multi-word text.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help=(
            f"Wait for the {adapter_label} gateway to drain the queued row before returning "
            f"(up to --wait-timeout seconds)."
        ),
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=10.0,
        help="Maximum seconds to wait when --wait is set.",
    )
    parser.set_defaults(command_action="message", service_key=service_key)

def build_gateway_arg_parser(*, defaults: dict[str, Path]) -> ArgumentParser:
    common = ArgumentParser(add_help=False)
    _add_common_gateway_options(common, defaults=defaults)

    parser = ArgumentParser(prog="elephant gateway", description="Manage IM providers and accounts.")
    subparsers = parser.add_subparsers(dest="command")

    setup = subparsers.add_parser(
        "setup",
        parents=[common],
        help="Open interactive IM setup.",
    )
    setup.add_argument(
        "--default-elephant-id",
        default="",
        help="Prefill which elephant plain text should route to by default after setup.",
    )
    setup.add_argument(
        "--allow-skip",
        action="store_true",
        help="Allow the setup picker to exit without choosing an IM provider.",
    )
    setup.add_argument(
        "--prompt-title",
        default="💬 IM Setup",
        help="Title for the interactive IM setup picker.",
    )
    setup.add_argument(
        "--prompt-text",
        default="💬 Which IM should Elephant Agent configure right now?",
        help="Prompt text for the interactive IM setup picker.",
    )
    setup.set_defaults(command_action="setup")

    status = subparsers.add_parser(
        "status",
        parents=[common],
        help="Show status for all providers and accounts.",
    )
    status.set_defaults(command_action="status_all")

    doctor = subparsers.add_parser(
        "doctor",
        parents=[common],
        help="Run health checks for all providers and accounts.",
    )
    doctor.set_defaults(command_action="doctor_all")

    describe = subparsers.add_parser(
        "describe",
        parents=[common],
        help="Print resolved IM provider and account wiring as JSON.",
    )
    describe.set_defaults(command_action="describe_all")


    feishu = subparsers.add_parser("feishu", parents=[common], help="Manage Feishu accounts.")
    feishu.set_defaults(command_action="status", service_key="feishu")
    feishu_subparsers = feishu.add_subparsers(dest="feishu_command")

    feishu_setup = feishu_subparsers.add_parser(
        "setup",
        parents=[common],
        help="Add or update a Feishu account.",
    )
    _add_feishu_add_options(feishu_setup)
    feishu_setup.add_argument("--no-start", action="store_true", help="Only save config, do not start the adapter after setup.")
    feishu_setup.set_defaults(command_action="add_feishu", service_key="feishu", auto_start=True)

    feishu_remove = feishu_subparsers.add_parser(
        "remove",
        parents=[common],
        help="Remove a Feishu account.",
    )
    _add_required_account_argument(feishu_remove, help_text="Feishu account id to remove.")
    feishu_remove.set_defaults(command_action="remove_feishu", service_key="feishu")

    feishu_start = feishu_subparsers.add_parser(
        "start",
        parents=[common],
        help="Start all or one Feishu account.",
    )
    _add_feishu_start_options(feishu_start)
    feishu_start.set_defaults(command_action="start", service_key="feishu")

    feishu_status = feishu_subparsers.add_parser(
        "status",
        parents=[common],
        help="Show Feishu status.",
    )
    _add_feishu_status_options(feishu_status)
    feishu_status.set_defaults(command_action="status", service_key="feishu")

    feishu_stop = feishu_subparsers.add_parser(
        "stop",
        parents=[common],
        help="Stop all or one Feishu account.",
    )
    _add_feishu_stop_options(feishu_stop)
    feishu_stop.set_defaults(command_action="stop", service_key="feishu")

    feishu_restart = feishu_subparsers.add_parser(
        "restart",
        parents=[common],
        help="Restart all or one Feishu account.",
    )
    _add_feishu_restart_options(feishu_restart)
    feishu_restart.set_defaults(command_action="restart", service_key="feishu")

    feishu_logs = feishu_subparsers.add_parser(
        "logs",
        parents=[common],
        help="Show logs for one Feishu account.",
    )
    _add_feishu_logs_options(feishu_logs)
    feishu_logs.set_defaults(command_action="logs", service_key="feishu")

    feishu_describe = feishu_subparsers.add_parser(
        "describe",
        parents=[common],
        help="Print resolved Feishu account wiring as JSON.",
    )
    feishu_describe.set_defaults(command_action="describe", service_key="feishu")

    feishu_doctor = feishu_subparsers.add_parser(
        "doctor",
        parents=[common],
        help="Check Feishu health.",
    )
    _add_optional_account_argument(
        feishu_doctor,
        help_text="Feishu account id. Omit to inspect all Feishu accounts.",
    )
    feishu_doctor.set_defaults(command_action="doctor", service_key="feishu")

    _add_message_subparser(
        feishu_subparsers,
        common=common,
        service_key="feishu",
        adapter_label="feishu",
        conversation_description=(
            "Feishu conversation id (chat_id / open_chat_id). Omit to fall back to the single "
            "feishu elephant."
        ),
    )

    discord = subparsers.add_parser("discord", parents=[common], help="Manage Discord accounts.")
    discord.set_defaults(command_action="status", service_key="discord")
    discord_subparsers = discord.add_subparsers(dest="discord_command")

    discord_setup = discord_subparsers.add_parser(
        "setup",
        parents=[common],
        help="Add or update a Discord account.",
    )
    _add_discord_add_options(discord_setup)
    discord_setup.add_argument("--no-start", action="store_true", help="Only save config, do not start the adapter after setup.")
    discord_setup.set_defaults(command_action="add_discord", service_key="discord", auto_start=True)

    discord_remove = discord_subparsers.add_parser(
        "remove",
        parents=[common],
        help="Remove a Discord account.",
    )
    _add_required_account_argument(discord_remove, help_text="Discord account id to remove.")
    discord_remove.set_defaults(command_action="remove_discord", service_key="discord")

    discord_start = discord_subparsers.add_parser(
        "start",
        parents=[common],
        help="Start all or one Discord account.",
    )
    _add_discord_start_options(discord_start)
    discord_start.set_defaults(command_action="start", service_key="discord")

    discord_status = discord_subparsers.add_parser(
        "status",
        parents=[common],
        help="Show Discord status.",
    )
    _add_discord_status_options(discord_status)
    discord_status.set_defaults(command_action="status", service_key="discord")

    discord_stop = discord_subparsers.add_parser(
        "stop",
        parents=[common],
        help="Stop all or one Discord account.",
    )
    _add_discord_stop_options(discord_stop)
    discord_stop.set_defaults(command_action="stop", service_key="discord")

    discord_restart = discord_subparsers.add_parser(
        "restart",
        parents=[common],
        help="Restart all or one Discord account.",
    )
    _add_discord_restart_options(discord_restart)
    discord_restart.set_defaults(command_action="restart", service_key="discord")

    discord_logs = discord_subparsers.add_parser(
        "logs",
        parents=[common],
        help="Show logs for one Discord account.",
    )
    _add_discord_logs_options(discord_logs)
    discord_logs.set_defaults(command_action="logs", service_key="discord")

    discord_describe = discord_subparsers.add_parser(
        "describe",
        parents=[common],
        help="Print resolved Discord account wiring as JSON.",
    )
    discord_describe.set_defaults(command_action="describe", service_key="discord")

    discord_doctor = discord_subparsers.add_parser(
        "doctor",
        parents=[common],
        help="Check Discord health.",
    )
    _add_optional_account_argument(
        discord_doctor,
        help_text="Discord account id. Omit to inspect all Discord accounts.",
    )
    discord_doctor.set_defaults(command_action="doctor", service_key="discord")

    _add_message_subparser(
        discord_subparsers,
        common=common,
        service_key="discord",
        adapter_label="discord",
        conversation_description=(
            "Discord channel id. Omit to fall back to the single discord elephant."
        ),
    )

    dingding = subparsers.add_parser("dingding", parents=[common], help="Manage DingDing accounts.")
    dingding.set_defaults(command_action="status", service_key="dingding")
    dingding_subparsers = dingding.add_subparsers(dest="dingding_command")

    dingding_setup = dingding_subparsers.add_parser("setup", parents=[common], help="Add or update a DingDing account.")
    _add_dingding_add_options(dingding_setup)
    dingding_setup.add_argument("--no-start", action="store_true", help="Only save config, do not start the adapter after setup.")
    dingding_setup.set_defaults(command_action="add_dingding", service_key="dingding", auto_start=True)

    dingding_remove = dingding_subparsers.add_parser("remove", parents=[common], help="Remove a DingDing account.")
    _add_required_account_argument(dingding_remove, help_text="DingDing account id to remove.")
    dingding_remove.set_defaults(command_action="remove_dingding", service_key="dingding")

    dingding_start = dingding_subparsers.add_parser("start", parents=[common], help="Start all or one DingDing account.")
    _add_dingding_start_options(dingding_start)
    dingding_start.set_defaults(command_action="start", service_key="dingding")

    dingding_status = dingding_subparsers.add_parser("status", parents=[common], help="Show DingDing status.")
    _add_dingding_status_options(dingding_status)
    dingding_status.set_defaults(command_action="status", service_key="dingding")

    dingding_stop = dingding_subparsers.add_parser("stop", parents=[common], help="Stop all or one DingDing account.")
    _add_dingding_stop_options(dingding_stop)
    dingding_stop.set_defaults(command_action="stop", service_key="dingding")

    dingding_restart = dingding_subparsers.add_parser("restart", parents=[common], help="Restart all or one DingDing account.")
    _add_dingding_restart_options(dingding_restart)
    dingding_restart.set_defaults(command_action="restart", service_key="dingding")

    dingding_logs = dingding_subparsers.add_parser("logs", parents=[common], help="Show logs for one DingDing account.")
    _add_dingding_logs_options(dingding_logs)
    dingding_logs.set_defaults(command_action="logs", service_key="dingding")

    dingding_describe = dingding_subparsers.add_parser("describe", parents=[common], help="Print resolved DingDing account wiring as JSON.")
    dingding_describe.set_defaults(command_action="describe", service_key="dingding")

    dingding_doctor = dingding_subparsers.add_parser("doctor", parents=[common], help="Check DingDing health.")
    _add_optional_account_argument(dingding_doctor, help_text="DingDing account id. Omit to inspect all DingDing accounts.")
    dingding_doctor.set_defaults(command_action="doctor", service_key="dingding")

    weixin = subparsers.add_parser("weixin", parents=[common], help="Manage WeChat accounts.")
    weixin.set_defaults(command_action="status", service_key="weixin")
    weixin_subparsers = weixin.add_subparsers(dest="weixin_command")

    weixin_setup = weixin_subparsers.add_parser("setup", parents=[common], help="Add or update a WeChat account.")
    _add_weixin_add_options(weixin_setup)
    weixin_setup.add_argument("--no-start", action="store_true", help="Only save config, do not start the adapter after setup.")
    weixin_setup.set_defaults(command_action="add_weixin", service_key="weixin", auto_start=True)

    weixin_remove = weixin_subparsers.add_parser("remove", parents=[common], help="Remove a WeChat account.")
    _add_required_account_argument(weixin_remove, help_text="WeChat account id to remove.")
    weixin_remove.set_defaults(command_action="remove_weixin", service_key="weixin")

    weixin_start = weixin_subparsers.add_parser("start", parents=[common], help="Start all or one WeChat account.")
    _add_weixin_start_options(weixin_start)
    weixin_start.set_defaults(command_action="start", service_key="weixin")

    weixin_status = weixin_subparsers.add_parser("status", parents=[common], help="Show WeChat status.")
    _add_weixin_status_options(weixin_status)
    weixin_status.set_defaults(command_action="status", service_key="weixin")

    weixin_stop = weixin_subparsers.add_parser("stop", parents=[common], help="Stop all or one WeChat account.")
    _add_weixin_stop_options(weixin_stop)
    weixin_stop.set_defaults(command_action="stop", service_key="weixin")

    weixin_restart = weixin_subparsers.add_parser("restart", parents=[common], help="Restart all or one WeChat account.")
    _add_weixin_restart_options(weixin_restart)
    weixin_restart.set_defaults(command_action="restart", service_key="weixin")

    weixin_logs = weixin_subparsers.add_parser("logs", parents=[common], help="Show logs for one WeChat account.")
    _add_weixin_logs_options(weixin_logs)
    weixin_logs.set_defaults(command_action="logs", service_key="weixin")

    weixin_describe = weixin_subparsers.add_parser("describe", parents=[common], help="Print resolved WeChat account wiring as JSON.")
    weixin_describe.set_defaults(command_action="describe", service_key="weixin")

    weixin_doctor = weixin_subparsers.add_parser("doctor", parents=[common], help="Check WeChat health.")
    _add_optional_account_argument(weixin_doctor, help_text="WeChat account id. Omit to inspect all WeChat accounts.")
    weixin_doctor.set_defaults(command_action="doctor", service_key="weixin")

    _add_message_subparser(
        weixin_subparsers,
        common=common,
        service_key="weixin",
        adapter_label="weixin",
        conversation_description="WeChat conversation id (wxid or room id). Omit to fall back to the single weixin elephant.",
    )

    wecom = subparsers.add_parser("wecom", parents=[common], help="Manage WeCom accounts.")
    wecom.set_defaults(command_action="status", service_key="wecom")
    wecom_subparsers = wecom.add_subparsers(dest="wecom_command")

    wecom_setup = wecom_subparsers.add_parser("setup", parents=[common], help="Add or update a WeCom account.")
    _add_wecom_add_options(wecom_setup)
    wecom_setup.add_argument("--no-start", action="store_true", help="Only save config, do not start the adapter after setup.")
    wecom_setup.set_defaults(command_action="add_wecom", service_key="wecom", auto_start=True)

    wecom_remove = wecom_subparsers.add_parser("remove", parents=[common], help="Remove a WeCom account.")
    _add_required_account_argument(wecom_remove, help_text="WeCom account id to remove.")
    wecom_remove.set_defaults(command_action="remove_wecom", service_key="wecom")

    wecom_start = wecom_subparsers.add_parser("start", parents=[common], help="Start all or one WeCom account.")
    _add_wecom_start_options(wecom_start)
    wecom_start.set_defaults(command_action="start", service_key="wecom")

    wecom_status = wecom_subparsers.add_parser("status", parents=[common], help="Show WeCom status.")
    _add_wecom_status_options(wecom_status)
    wecom_status.set_defaults(command_action="status", service_key="wecom")

    wecom_stop = wecom_subparsers.add_parser("stop", parents=[common], help="Stop all or one WeCom account.")
    _add_wecom_stop_options(wecom_stop)
    wecom_stop.set_defaults(command_action="stop", service_key="wecom")

    wecom_restart = wecom_subparsers.add_parser("restart", parents=[common], help="Restart all or one WeCom account.")
    _add_wecom_restart_options(wecom_restart)
    wecom_restart.set_defaults(command_action="restart", service_key="wecom")

    wecom_logs = wecom_subparsers.add_parser("logs", parents=[common], help="Show logs for one WeCom account.")
    _add_wecom_logs_options(wecom_logs)
    wecom_logs.set_defaults(command_action="logs", service_key="wecom")

    wecom_describe = wecom_subparsers.add_parser("describe", parents=[common], help="Print resolved WeCom account wiring as JSON.")
    wecom_describe.set_defaults(command_action="describe", service_key="wecom")

    wecom_doctor = wecom_subparsers.add_parser("doctor", parents=[common], help="Check WeCom health.")
    _add_optional_account_argument(wecom_doctor, help_text="WeCom account id. Omit to inspect all WeCom accounts.")
    wecom_doctor.set_defaults(command_action="doctor", service_key="wecom")

    return parser
