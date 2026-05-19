"""Gateway setup wizard helpers."""

from __future__ import annotations
from collections.abc import Sequence


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


from .gateway_main_wizard_ui import *  # noqa: F401,F403


def _run_interactive_feishu_wizard(
    *,
    account_id: str,
    transport: str,
    event_path: str,
    app_id_env_var: str,
    app_secret_env_var: str,
    app_id_value: str,
    app_secret_value: str,
    enabled: bool,
    allow_group_chats: bool,
) -> FeishuGatewayWizardState | None:
    state = FeishuGatewayWizardState(
        account_id=account_id,
        transport=transport,
        event_path=event_path,
        app_id_env_var=app_id_env_var,
        app_secret_env_var=app_secret_env_var,
        app_id_value=app_id_value,
        app_secret_value=app_secret_value,
        enabled=enabled,
        allow_group_chats=allow_group_chats,
    )
    steps = (
        "app_id_value",
        "app_secret_value",
    )
    step_index = 0
    while step_index < len(steps):
        step = steps[step_index]
        if step == "app_id_value":
            answer = _gateway_wizard_text_prompt(
                "Paste App ID",
                "Paste the Feishu App ID to store it in the local IM secret file. Leave blank to keep the current local value if one already exists.",
                default=None,
                allow_back=True,
                preserve_default_on_empty=False,
            )
            if answer is GATEWAY_WIZARD_BACK:
                return None
            state.app_id_value = str(answer).strip()
            step_index += 1
            continue
        if step == "app_secret_value":
            answer = _gateway_wizard_secret_prompt(
                "Paste App Secret",
                "Paste the Feishu App Secret / API key to store it in the local IM secret file.",
                allow_back=True,
            )
            if answer is GATEWAY_WIZARD_BACK:
                step_index -= 1
                continue
            state.app_secret_value = str(answer).strip()
            step_index += 1
            continue
    return state


def _run_interactive_discord_wizard(
    *,
    account_id: str,
    transport: str,
    bot_token_value: str,
    enabled: bool,
    account_enabled: bool,
    allow_group_chats: bool,
    allow_guild_ids: Sequence[str],
    allow_channel_ids: Sequence[str],
) -> DiscordGatewayWizardState | None:
    state = DiscordGatewayWizardState(
        account_id=account_id,
        transport=transport,
        bot_token_value=bot_token_value,
        enabled=enabled,
        account_enabled=account_enabled,
        allow_group_chats=allow_group_chats,
        allow_guild_ids=tuple(str(value).strip() for value in allow_guild_ids if str(value).strip()),
        allow_channel_ids=tuple(str(value).strip() for value in allow_channel_ids if str(value).strip()),
    )
    steps = ("bot_token_value",)
    step_index = 0
    while step_index < len(steps):
        step = steps[step_index]
        if step == "bot_token_value":
            answer = _gateway_wizard_secret_prompt(
                "Paste Bot Token",
                "Paste the Discord bot token to store it in the local IM secret file.",
                allow_back=True,
            )
            if answer is GATEWAY_WIZARD_BACK:
                return None
            state.bot_token_value = str(answer).strip()
            step_index += 1
            continue
    return state


def _print_gateway_dingding_wizard_intro() -> bool:
    print("🔔 Elephant Agent Gateway // DingDing setup")
    print("  - choose the DingDing account you want to wire")
    print("  - bind Client ID, Client Secret, and Robot Code")
    print("  - keep profile wiring and local credentials separate")
    return _confirm_gateway_wizard_intro()


def _print_gateway_weixin_wizard_intro() -> bool:
    print("🐧 Elephant Agent Gateway // WeChat setup")
    print("  - choose the WeChat account you want to wire")
    print("  - configure wxhook and callback server host/port")
    print("  - keep profile wiring and local credentials separate")
    return _confirm_gateway_wizard_intro()


def _print_gateway_wecom_wizard_intro() -> bool:
    print("💼 Elephant Agent Gateway // WeCom setup")
    print("  - choose the WeCom account you want to wire")
    print("  - bind Bot ID and Secret")
    print("  - keep profile wiring and local credentials separate")
    return _confirm_gateway_wizard_intro()


def _run_interactive_dingding_wizard(
    *,
    account_id: str,
    transport: str,
    client_id_value: str,
    client_secret_value: str,
    robot_code_value: str,
    enabled: bool,
    allow_group_chats: bool,
) -> DingdingGatewayWizardState | None:
    state = DingdingGatewayWizardState(
        account_id=account_id,
        transport=transport,
        client_id_value=client_id_value,
        client_secret_value=client_secret_value,
        robot_code_value=robot_code_value,
        enabled=enabled,
        allow_group_chats=allow_group_chats,
    )
    steps = (
        "client_id_value",
        "client_secret_value",
        "robot_code_value",
    )
    step_index = 0
    while step_index < len(steps):
        step = steps[step_index]
        if step == "client_id_value":
            answer = _gateway_wizard_text_prompt(
                "Paste Client ID",
                "Paste the DingDing Client ID. Leave blank to keep the current value.",
                default=None,
                allow_back=True,
                preserve_default_on_empty=False,
            )
            if answer is GATEWAY_WIZARD_BACK:
                return None
            state.client_id_value = str(answer).strip()
            step_index += 1
            continue
        if step == "client_secret_value":
            answer = _gateway_wizard_secret_prompt(
                "Paste Client Secret",
                "Paste the DingDing Client Secret to store it in the local IM secret file.",
                allow_back=True,
            )
            if answer is GATEWAY_WIZARD_BACK:
                step_index -= 1
                continue
            state.client_secret_value = str(answer).strip()
            step_index += 1
            continue
        if step == "robot_code_value":
            answer = _gateway_wizard_text_prompt(
                "Paste Robot Code",
                "Paste the DingDing Robot Code (optional). Leave blank to skip.",
                default=None,
                allow_back=True,
                preserve_default_on_empty=False,
            )
            if answer is GATEWAY_WIZARD_BACK:
                step_index -= 1
                continue
            state.robot_code_value = str(answer).strip()
            step_index += 1
            continue
    return state


def _run_interactive_weixin_wizard(
    *,
    account_id: str,
    transport: str,
    wxhook_host: str,
    wxhook_port: int,
    callback_host: str,
    callback_port: int,
    enabled: bool,
    allow_group_chats: bool,
) -> WeixinGatewayWizardState | None:
    state = WeixinGatewayWizardState(
        account_id=account_id,
        transport=transport,
        wxhook_host=wxhook_host,
        wxhook_port=wxhook_port,
        callback_host=callback_host,
        callback_port=callback_port,
        enabled=enabled,
        allow_group_chats=allow_group_chats,
    )
    steps = (
        "wxhook_host",
        "callback_host",
    )
    step_index = 0
    while step_index < len(steps):
        step = steps[step_index]
        if step == "wxhook_host":
            answer = _gateway_wizard_text_prompt(
                "wxhook Server",
                "wxhook API address (host:port) for sending replies.",
                default=f"{state.wxhook_host}:{state.wxhook_port}",
                allow_back=True,
            )
            if answer is GATEWAY_WIZARD_BACK:
                return None
            parts = str(answer).strip().rsplit(":", 1)
            state.wxhook_host = parts[0]
            if len(parts) == 2 and parts[1].isdigit():
                state.wxhook_port = int(parts[1])
            step_index += 1
            continue
        if step == "callback_host":
            answer = _gateway_wizard_text_prompt(
                "Callback Server",
                "Callback server address (host:port) for receiving WeChat messages.",
                default=f"{state.callback_host}:{state.callback_port}",
                allow_back=True,
            )
            if answer is GATEWAY_WIZARD_BACK:
                step_index -= 1
                continue
            parts = str(answer).strip().rsplit(":", 1)
            state.callback_host = parts[0]
            if len(parts) == 2 and parts[1].isdigit():
                state.callback_port = int(parts[1])
            step_index += 1
            continue
    return state


def _run_interactive_wecom_wizard(
    *,
    account_id: str,
    transport: str,
    bot_id_value: str,
    secret_value: str,
    enabled: bool,
    allow_group_chats: bool,
) -> WecomGatewayWizardState | None:
    state = WecomGatewayWizardState(
        account_id=account_id,
        transport=transport,
        bot_id_value=bot_id_value,
        secret_value=secret_value,
        enabled=enabled,
        allow_group_chats=allow_group_chats,
    )
    steps = (
        "bot_id_value",
        "secret_value",
    )
    step_index = 0
    while step_index < len(steps):
        step = steps[step_index]
        if step == "bot_id_value":
            answer = _gateway_wizard_text_prompt(
                "Paste Bot ID",
                "Paste the WeCom AI Bot ID. Leave blank to keep the current value.",
                default=None,
                allow_back=True,
                preserve_default_on_empty=False,
            )
            if answer is GATEWAY_WIZARD_BACK:
                return None
            state.bot_id_value = str(answer).strip()
            step_index += 1
            continue
        if step == "secret_value":
            answer = _gateway_wizard_secret_prompt(
                "Paste Secret",
                "Paste the WeCom Bot Secret to store it in the local IM secret file.",
                allow_back=True,
            )
            if answer is GATEWAY_WIZARD_BACK:
                step_index -= 1
                continue
            state.secret_value = str(answer).strip()
            step_index += 1
            continue
    return state


__all__ = [
    "_run_interactive_feishu_wizard",
    "_run_interactive_discord_wizard",
    "_print_gateway_dingding_wizard_intro",
    "_print_gateway_weixin_wizard_intro",
    "_print_gateway_wecom_wizard_intro",
    "_run_interactive_dingding_wizard",
    "_run_interactive_weixin_wizard",
    "_run_interactive_wecom_wizard",
]
