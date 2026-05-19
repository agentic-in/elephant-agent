"""Gateway parser provider option helpers."""

from __future__ import annotations

from argparse import SUPPRESS, ArgumentParser

from .gateway_main_parser_state import *  # noqa: F401,F403
from .gateway_main_parser_state import (
    SUPPORTED_DINGDING_TRANSPORTS,
    SUPPORTED_DISCORD_TRANSPORTS,
    SUPPORTED_FEISHU_TRANSPORTS,
    SUPPORTED_WECOM_TRANSPORTS,
    SUPPORTED_WEIXIN_TRANSPORTS,
)
from .gateway_main_runtime import *  # noqa: F401,F403
from .gateway_main_wizard import *  # noqa: F401,F403


def _add_discord_runtime_target_options(
    parser: ArgumentParser,
    *,
    include_account_id: bool = False,
) -> None:
    parser.set_defaults(runtime_target="configured")
    parser.add_argument(
        "--transport",
        dest="runtime_target",
        choices=("configured", "gateway"),
        default="configured",
        help=SUPPRESS,
    )
    if include_account_id:
        parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)


def _add_discord_start_options(parser: ArgumentParser) -> None:
    _add_discord_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="Discord account id. Omit to start all enabled accounts.",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Start the Discord gateway transport in a background process and return immediately.",
    )


def _add_discord_status_options(parser: ArgumentParser) -> None:
    _add_discord_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="Discord account id. Omit to inspect the provider-wide runtime and all accounts.",
    )


def _add_discord_stop_options(parser: ArgumentParser) -> None:
    _add_discord_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="Discord account id. Omit to stop the configured provider runtime.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for a graceful shutdown before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the process does not exit within --timeout.",
    )


def _add_discord_restart_options(parser: ArgumentParser) -> None:
    _add_discord_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="Discord account id. Omit to restart all enabled accounts on the configured runtime.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the previous process to exit before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the previous process does not exit within --timeout.",
    )


def _add_discord_logs_options(parser: ArgumentParser) -> None:
    _add_discord_runtime_target_options(parser, include_account_id=True)
    _add_required_account_argument(
        parser,
        help_text="Discord account id whose runtime log you want to inspect.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=80,
        help="Show the last N log lines before exiting or following. Use 0 to suppress the initial excerpt.",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep streaming appended log output until interrupted.",
    )
    parser.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved log file path and exit.",
    )


def _add_discord_add_options(parser: ArgumentParser) -> None:
    _add_optional_account_argument(
        parser,
        help_text="Discord account id. Omit to create or update the reserved `default` account.",
    )
    parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)
    parser.add_argument(
        "--transport",
        choices=SUPPORTED_DISCORD_TRANSPORTS,
        default=None,
        help="Configured transport to persist for this Discord account (defaults to existing or gateway).",
    )
    parser.add_argument(
        "--bot-token-env-var",
        default=None,
        help="Environment variable alias used to resolve the Discord bot token.",
    )
    parser.add_argument(
        "--bot-token",
        default=None,
        help="Optional raw Discord bot token to store in the local gateway secret file instead of profile.json.",
    )
    wizard_group = parser.add_mutually_exclusive_group()
    wizard_group.add_argument(
        "--wizard",
        dest="wizard",
        action="store_true",
        default=None,
        help="Force the interactive Discord setup wizard even when command-line flags are present.",
    )
    wizard_group.add_argument(
        "--no-wizard",
        dest="wizard",
        action="store_false",
        help="Skip the interactive wizard and write configuration directly from CLI arguments.",
    )
    parser.add_argument(
        "--allow-guild-id",
        action="append",
        default=None,
        help="Optional guild allowlist entry. Repeat to allow multiple guilds.",
    )
    parser.add_argument(
        "--allow-channel-id",
        action="append",
        default=None,
        help="Optional channel or parent-channel allowlist entry. Repeat to allow multiple channels.",
    )
    parser.add_argument(
        "--allow-group-chats",
        action="store_true",
        help="Allow the Discord control bridge to accept guild and group chats.",
    )
    enabled_group = parser.add_mutually_exclusive_group()
    enabled_group.add_argument(
        "--enabled",
        dest="enabled",
        action="store_true",
        default=None,
        help=SUPPRESS,
    )
    enabled_group.add_argument(
        "--disabled",
        dest="enabled",
        action="store_false",
        help=SUPPRESS,
    )
    account_enabled_group = parser.add_mutually_exclusive_group()
    account_enabled_group.add_argument(
        "--account-enabled",
        dest="account_enabled",
        action="store_true",
        default=None,
        help=SUPPRESS,
    )
    account_enabled_group.add_argument(
        "--account-disabled",
        dest="account_enabled",
        action="store_false",
        help=SUPPRESS,
    )


def _add_feishu_runtime_target_options(
    parser: ArgumentParser,
    *,
    include_account_id: bool = False,
) -> None:
    parser.set_defaults(runtime_target="configured")
    parser.add_argument(
        "--transport",
        dest="runtime_target",
        choices=("configured", "long-connection"),
        default="configured",
        help=SUPPRESS,
    )
    if include_account_id:
        parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)


def _add_feishu_start_options(parser: ArgumentParser) -> None:
    _add_feishu_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="Feishu account id. Omit to use the configured runtime target.",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Start the Feishu transport in a background process and return immediately.",
    )
    _add_http_server_options(parser)


def _add_feishu_status_options(parser: ArgumentParser) -> None:
    _add_feishu_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="Feishu account id. Omit to inspect the provider-wide runtime and all accounts.",
    )


def _add_feishu_stop_options(parser: ArgumentParser) -> None:
    _add_feishu_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="Feishu account id. Omit to stop the configured provider runtime.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for a graceful shutdown before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the process does not exit within --timeout.",
    )


def _add_feishu_restart_options(parser: ArgumentParser) -> None:
    _add_feishu_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="Feishu account id. Omit to restart the configured provider runtime.",
    )
    _add_http_server_options(parser)
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the previous process to exit before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the previous process does not exit within --timeout.",
    )


def _add_feishu_logs_options(parser: ArgumentParser) -> None:
    _add_feishu_runtime_target_options(parser, include_account_id=True)
    _add_required_account_argument(
        parser,
        help_text="Feishu account id whose runtime log you want to inspect.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=80,
        help="Show the last N log lines before exiting or following. Use 0 to suppress the initial excerpt.",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep streaming appended log output until interrupted.",
    )
    parser.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved log file path and exit.",
    )


def _add_feishu_add_options(parser: ArgumentParser) -> None:
    _add_optional_account_argument(
        parser,
        help_text="Feishu account id. Omit to create or update the reserved `default` account.",
    )
    parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)
    parser.add_argument(
        "--transport",
        choices=SUPPORTED_FEISHU_TRANSPORTS,
        default=None,
        help="Configured transport to persist for this Feishu account (defaults to existing or long-connection).",
    )
    parser.add_argument(
        "--event-path",
        default=None,
        help="Webhook event path to persist for HTTP callback mode (defaults to existing or /feishu/events); long-connection does not use it directly.",
    )
    parser.add_argument(
        "--app-id-env-var",
        default=None,
        help="Environment variable alias used to resolve the Feishu App ID.",
    )
    parser.add_argument(
        "--app-secret-env-var",
        default=None,
        help="Environment variable alias used to resolve the Feishu App Secret / API key.",
    )
    parser.add_argument(
        "--app-id",
        "--api-id",
        dest="app_id",
        default=None,
        help="Optional raw Feishu App ID to store in the local gateway secret file instead of profile.json.",
    )
    parser.add_argument(
        "--app-secret",
        "--api-key",
        dest="app_secret",
        default=None,
        help="Optional raw Feishu App Secret / API key to store in the local gateway secret file instead of profile.json.",
    )
    wizard_group = parser.add_mutually_exclusive_group()
    wizard_group.add_argument(
        "--wizard",
        dest="wizard",
        action="store_true",
        default=None,
        help="Force the interactive Feishu setup wizard even when command-line flags are present.",
    )
    wizard_group.add_argument(
        "--no-wizard",
        dest="wizard",
        action="store_false",
        help="Skip the interactive wizard and write configuration directly from CLI arguments.",
    )
    enabled_group = parser.add_mutually_exclusive_group()
    enabled_group.add_argument(
        "--enabled",
        dest="enabled",
        action="store_true",
        default=None,
        help=SUPPRESS,
    )
    enabled_group.add_argument(
        "--disabled",
        dest="enabled",
        action="store_false",
        help=SUPPRESS,
    )
    parser.add_argument(
        "--allow-group-chats",
        action="store_true",
        help="Allow the Feishu control bridge to accept group chats.",
    )


def _add_dingding_runtime_target_options(
    parser: ArgumentParser,
    *,
    include_account_id: bool = False,
) -> None:
    parser.set_defaults(runtime_target="configured")
    parser.add_argument(
        "--transport",
        dest="runtime_target",
        choices=("configured", "stream"),
        default="configured",
        help=SUPPRESS,
    )
    if include_account_id:
        parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)


def _add_dingding_start_options(parser: ArgumentParser) -> None:
    _add_dingding_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="DingDing account id. Omit to start all enabled accounts.",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Start the DingDing gateway transport in a background process and return immediately.",
    )


def _add_dingding_status_options(parser: ArgumentParser) -> None:
    _add_dingding_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="DingDing account id. Omit to inspect the provider-wide runtime and all accounts.",
    )


def _add_dingding_stop_options(parser: ArgumentParser) -> None:
    _add_dingding_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="DingDing account id. Omit to stop the configured provider runtime.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for a graceful shutdown before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the process does not exit within --timeout.",
    )


def _add_dingding_restart_options(parser: ArgumentParser) -> None:
    _add_dingding_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="DingDing account id. Omit to restart all enabled accounts on the configured runtime.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the previous process to exit before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the previous process does not exit within --timeout.",
    )


def _add_dingding_logs_options(parser: ArgumentParser) -> None:
    _add_dingding_runtime_target_options(parser, include_account_id=True)
    _add_required_account_argument(
        parser,
        help_text="DingDing account id whose runtime log you want to inspect.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=80,
        help="Show the last N log lines before exiting or following. Use 0 to suppress the initial excerpt.",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep streaming appended log output until interrupted.",
    )
    parser.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved log file path and exit.",
    )


def _add_dingding_add_options(parser: ArgumentParser) -> None:
    _add_optional_account_argument(
        parser,
        help_text="DingDing account id. Omit to create or update the reserved `default` account.",
    )
    parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)
    parser.add_argument(
        "--transport",
        choices=SUPPORTED_DINGDING_TRANSPORTS,
        default=None,
        help="Configured transport to persist for this DingDing account (defaults to existing or stream).",
    )
    parser.add_argument(
        "--client-id-env-var",
        default=None,
        help="Environment variable alias used to resolve the DingDing Client ID.",
    )
    parser.add_argument(
        "--client-secret-env-var",
        default=None,
        help="Environment variable alias used to resolve the DingDing Client Secret.",
    )
    parser.add_argument(
        "--robot-code-env-var",
        default=None,
        help="Environment variable alias used to resolve the DingDing Robot Code.",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Optional raw DingDing Client ID to store in the local gateway secret file.",
    )
    parser.add_argument(
        "--client-secret",
        default=None,
        help="Optional raw DingDing Client Secret to store in the local gateway secret file.",
    )
    parser.add_argument(
        "--robot-code",
        default=None,
        help="Optional raw DingDing Robot Code to store in the local gateway secret file.",
    )
    wizard_group = parser.add_mutually_exclusive_group()
    wizard_group.add_argument(
        "--wizard",
        dest="wizard",
        action="store_true",
        default=None,
        help="Force the interactive DingDing setup wizard even when command-line flags are present.",
    )
    wizard_group.add_argument(
        "--no-wizard",
        dest="wizard",
        action="store_false",
        help="Skip the interactive wizard and write configuration directly from CLI arguments.",
    )
    parser.add_argument(
        "--allow-group-chats",
        action="store_true",
        help="Allow the DingDing control bridge to accept group chats.",
    )
    enabled_group = parser.add_mutually_exclusive_group()
    enabled_group.add_argument(
        "--enabled",
        dest="enabled",
        action="store_true",
        default=None,
        help=SUPPRESS,
    )
    enabled_group.add_argument(
        "--disabled",
        dest="enabled",
        action="store_false",
        help=SUPPRESS,
    )


def _add_weixin_runtime_target_options(
    parser: ArgumentParser,
    *,
    include_account_id: bool = False,
) -> None:
    parser.set_defaults(runtime_target="configured")
    parser.add_argument(
        "--transport",
        dest="runtime_target",
        choices=("configured", "ilink"),
        default="configured",
        help=SUPPRESS,
    )
    if include_account_id:
        parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)


def _add_weixin_start_options(parser: ArgumentParser) -> None:
    _add_weixin_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="WeChat account id. Omit to start all enabled accounts.",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Start the WeChat gateway transport in a background process and return immediately.",
    )


def _add_weixin_status_options(parser: ArgumentParser) -> None:
    _add_weixin_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="WeChat account id. Omit to inspect the provider-wide runtime and all accounts.",
    )


def _add_weixin_stop_options(parser: ArgumentParser) -> None:
    _add_weixin_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="WeChat account id. Omit to stop the configured provider runtime.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for a graceful shutdown before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the process does not exit within --timeout.",
    )


def _add_weixin_restart_options(parser: ArgumentParser) -> None:
    _add_weixin_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="WeChat account id. Omit to restart all enabled accounts on the configured runtime.",
    )
    _add_http_server_options(parser)
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the previous process to exit before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the previous process does not exit within --timeout.",
    )


def _add_weixin_logs_options(parser: ArgumentParser) -> None:
    _add_weixin_runtime_target_options(parser, include_account_id=True)
    _add_required_account_argument(
        parser,
        help_text="WeChat account id whose runtime log you want to inspect.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=80,
        help="Show the last N log lines before exiting or following. Use 0 to suppress the initial excerpt.",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep streaming appended log output until interrupted.",
    )
    parser.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved log file path and exit.",
    )


def _add_weixin_add_options(parser: ArgumentParser) -> None:
    _add_optional_account_argument(
        parser,
        help_text="WeChat account id. Omit to create or update the reserved `default` account.",
    )
    parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)
    parser.add_argument(
        "--transport",
        choices=SUPPORTED_WEIXIN_TRANSPORTS,
        default=None,
        help="Configured transport to persist for this WeChat account (defaults to existing or ilink).",
    )
    parser.add_argument(
        "--wxhook-host",
        default=None,
        help=SUPPRESS,
    )
    wizard_group = parser.add_mutually_exclusive_group()
    wizard_group.add_argument(
        "--wizard",
        dest="wizard",
        action="store_true",
        default=None,
        help="Force the interactive WeChat setup wizard even when command-line flags are present.",
    )
    wizard_group.add_argument(
        "--no-wizard",
        dest="wizard",
        action="store_false",
        help="Skip the interactive wizard and write configuration directly from CLI arguments.",
    )
    parser.add_argument(
        "--allow-group-chats",
        action="store_true",
        help="Allow the WeChat control bridge to accept group chats.",
    )
    enabled_group = parser.add_mutually_exclusive_group()
    enabled_group.add_argument(
        "--enabled",
        dest="enabled",
        action="store_true",
        default=None,
        help=SUPPRESS,
    )
    enabled_group.add_argument(
        "--disabled",
        dest="enabled",
        action="store_false",
        help=SUPPRESS,
    )


def _add_wecom_runtime_target_options(
    parser: ArgumentParser,
    *,
    include_account_id: bool = False,
) -> None:
    parser.set_defaults(runtime_target="configured")
    parser.add_argument(
        "--transport",
        dest="runtime_target",
        choices=("configured", "websocket"),
        default="configured",
        help=SUPPRESS,
    )
    if include_account_id:
        parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)


def _add_wecom_start_options(parser: ArgumentParser) -> None:
    _add_wecom_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="WeCom account id. Omit to start all enabled accounts.",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Start the WeCom gateway transport in a background process and return immediately.",
    )


def _add_wecom_status_options(parser: ArgumentParser) -> None:
    _add_wecom_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="WeCom account id. Omit to inspect the provider-wide runtime and all accounts.",
    )


def _add_wecom_stop_options(parser: ArgumentParser) -> None:
    _add_wecom_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="WeCom account id. Omit to stop the configured provider runtime.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for a graceful shutdown before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the process does not exit within --timeout.",
    )


def _add_wecom_restart_options(parser: ArgumentParser) -> None:
    _add_wecom_runtime_target_options(parser, include_account_id=True)
    _add_optional_account_argument(
        parser,
        help_text="WeCom account id. Omit to restart all enabled accounts on the configured runtime.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the previous process to exit before failing or forcing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL when the previous process does not exit within --timeout.",
    )


def _add_wecom_logs_options(parser: ArgumentParser) -> None:
    _add_wecom_runtime_target_options(parser, include_account_id=True)
    _add_required_account_argument(
        parser,
        help_text="WeCom account id whose runtime log you want to inspect.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=80,
        help="Show the last N log lines before exiting or following. Use 0 to suppress the initial excerpt.",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep streaming appended log output until interrupted.",
    )
    parser.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved log file path and exit.",
    )


def _add_wecom_add_options(parser: ArgumentParser) -> None:
    _add_optional_account_argument(
        parser,
        help_text="WeCom account id. Omit to create or update the reserved `default` account.",
    )
    parser.add_argument("--account-id", dest="account_id_flag", help=SUPPRESS)
    parser.add_argument(
        "--transport",
        choices=SUPPORTED_WECOM_TRANSPORTS,
        default=None,
        help="Configured transport to persist for this WeCom account (defaults to existing or websocket).",
    )
    parser.add_argument(
        "--bot-id-env-var",
        default=None,
        help="Environment variable alias used to resolve the WeCom Bot ID.",
    )
    parser.add_argument(
        "--secret-env-var",
        default=None,
        help="Environment variable alias used to resolve the WeCom Secret.",
    )
    parser.add_argument(
        "--bot-id",
        default=None,
        help="Optional raw WeCom Bot ID to store in the local gateway secret file.",
    )
    parser.add_argument(
        "--secret",
        default=None,
        help="Optional raw WeCom Secret to store in the local gateway secret file.",
    )
    wizard_group = parser.add_mutually_exclusive_group()
    wizard_group.add_argument(
        "--wizard",
        dest="wizard",
        action="store_true",
        default=None,
        help="Force the interactive WeCom setup wizard even when command-line flags are present.",
    )
    wizard_group.add_argument(
        "--no-wizard",
        dest="wizard",
        action="store_false",
        help="Skip the interactive wizard and write configuration directly from CLI arguments.",
    )
    parser.add_argument(
        "--allow-group-chats",
        action="store_true",
        help="Allow the WeCom control bridge to accept group chats.",
    )
    enabled_group = parser.add_mutually_exclusive_group()
    enabled_group.add_argument(
        "--enabled",
        dest="enabled",
        action="store_true",
        default=None,
        help=SUPPRESS,
    )
    enabled_group.add_argument(
        "--disabled",
        dest="enabled",
        action="store_false",
        help=SUPPRESS,
    )


__all__ = [
    "_add_discord_runtime_target_options",
    "_add_discord_start_options",
    "_add_discord_status_options",
    "_add_discord_stop_options",
    "_add_discord_restart_options",
    "_add_discord_logs_options",
    "_add_discord_add_options",
    "_add_feishu_runtime_target_options",
    "_add_feishu_start_options",
    "_add_feishu_status_options",
    "_add_feishu_stop_options",
    "_add_feishu_restart_options",
    "_add_feishu_logs_options",
    "_add_feishu_add_options",
    "_add_dingding_runtime_target_options",
    "_add_dingding_start_options",
    "_add_dingding_status_options",
    "_add_dingding_stop_options",
    "_add_dingding_restart_options",
    "_add_dingding_logs_options",
    "_add_dingding_add_options",
    "_add_weixin_runtime_target_options",
    "_add_weixin_start_options",
    "_add_weixin_status_options",
    "_add_weixin_stop_options",
    "_add_weixin_restart_options",
    "_add_weixin_logs_options",
    "_add_weixin_add_options",
    "_add_wecom_runtime_target_options",
    "_add_wecom_start_options",
    "_add_wecom_status_options",
    "_add_wecom_stop_options",
    "_add_wecom_restart_options",
    "_add_wecom_logs_options",
    "_add_wecom_add_options",
]
