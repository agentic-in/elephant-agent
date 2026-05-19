from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .wizard import (
    WIZARD_BACK,
    WIZARD_CANCEL,
    WizardChoice,
    _WizardBackSignal,
    _WizardCancelSignal,
    _wizard_choice_prompt,
    _wizard_text_prompt,
)

if TYPE_CHECKING:
    from .runtime import CliRuntime

DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
MANUAL_MODEL_SENTINEL = "__manual_model__"
DEFAULT_PROVIDER_ID = "openai-compatible"
_MODEL_DISCOVERY_KEY_RETRY_EXCLUDED_PROVIDERS = frozenset({"openai-codex", "copilot", "qwen-oauth"})
_PLACEHOLDER_MODELS_BY_PROVIDER = {
    "openai-compatible": {"model-id", "Any OpenAI-compatible chat model"},
}


def _pf_text(language: str, english: str, chinese: str) -> str:
    return chinese if str(language or "").strip().lower() == "zh" else english


@dataclass(slots=True)
class ProviderSelectionState:
    provider_id: str
    base_url: str
    api_key: str | None
    model_id: str
    reasoning_effort: str | None
    context_window_mode: str
    context_window_tokens: int | None


def provider_setup_defaults(runtime: CliRuntime, provider_id: str) -> ProviderSelectionState:
    normalized_provider_id = str(provider_id or "").strip().lower() or DEFAULT_PROVIDER_ID
    try:
        guide = runtime.provider_setup_guide(normalized_provider_id)
    except LookupError:
        normalized_provider_id = DEFAULT_PROVIDER_ID
        guide = runtime.provider_setup_guide(normalized_provider_id)
    discovered = runtime.discovered_provider(normalized_provider_id)
    summary = dict(runtime.provider_summary())
    same_provider = str(summary.get("provider_id", "")).strip().lower() == normalized_provider_id
    base_url = str(
        (summary.get("base_url") if same_provider else None)
        or discovered.base_url
        or guide.suggested_base_url
        or ""
    ).strip()
    model_id = str(
        (summary.get("model_id") if same_provider else None)
        or discovered.default_model
        or guide.suggested_model_id
        or ""
    ).strip()
    context_window_tokens = None
    if same_provider and summary.get("context_window_tokens") is not None:
        try:
            context_window_tokens = int(summary["context_window_tokens"])
        except (TypeError, ValueError):
            context_window_tokens = None
    context_window_mode = str(
        (summary.get("context_window_mode") if same_provider else None)
        or "auto"
    )
    reasoning_effort = (
        str(summary.get("reasoning_effort")).strip()
        if same_provider and summary.get("reasoning_effort") is not None
        else None
    )
    return ProviderSelectionState(
        provider_id=normalized_provider_id,
        base_url=base_url,
        api_key=None,
        model_id=model_id,
        reasoning_effort=reasoning_effort or None,
        context_window_mode=context_window_mode,
        context_window_tokens=context_window_tokens,
    )


def _manual_model_default(provider_id: str, model_id: str | None) -> str | None:
    candidate = str(model_id or "").strip()
    if not candidate:
        return None
    placeholders = _PLACEHOLDER_MODELS_BY_PROVIDER.get(provider_id.strip().lower(), set())
    if candidate in placeholders:
        return None
    return candidate


def _should_retry_provider_key_on_model_discovery_failure(provider_id: str, auth_type: str) -> bool:
    normalized_provider = str(provider_id or "").strip().lower()
    normalized_auth_type = str(auth_type or "").strip().lower()
    return normalized_auth_type == "api_key" and normalized_provider not in _MODEL_DISCOVERY_KEY_RETRY_EXCLUDED_PROVIDERS


def _choose_model(
    runtime: CliRuntime,
    state: ProviderSelectionState,
    *,
    auth_type: str,
    allow_back: bool,
    language: str = "en",
) -> tuple[str, str | None] | _WizardBackSignal:
    models = ()
    retried_provider_key = False
    refreshed_api_key: str | None = None
    try:
        models = runtime.discover_provider_models(
            provider_id=state.provider_id,
            base_url=state.base_url or None,
            api_key=state.api_key,
        )
    except Exception:
        models = ()
    if not models and _should_retry_provider_key_on_model_discovery_failure(state.provider_id, auth_type):
        refreshed_key = _wizard_text_prompt(
            _pf_text(language, "Refresh The Provider Key", "重新输入模型服务密钥"),
            _pf_text(language, "Elephant Agent could not read the provider model catalog. Re-enter the provider key so it can retry live model discovery.", "Elephant Agent 读取不到模型列表。请重新输入密钥，让它重试实时模型发现。"),
            allow_back=allow_back,
            password=True,
        )
        if refreshed_key is WIZARD_BACK:
            return WIZARD_BACK
        entered_key = str(refreshed_key).strip()
        if entered_key:
            retried_provider_key = True
            refreshed_api_key = entered_key
            try:
                models = runtime.discover_provider_models(
                    provider_id=state.provider_id,
                    base_url=state.base_url or None,
                    api_key=entered_key,
                )
            except Exception:
                models = ()
    if models:
        model_choices = tuple(
            WizardChoice(
                value=model.model_id,
                label=model.model_id,
                detail=_model_detail(model.context_window_tokens, model.max_output_tokens),
            )
            for model in models
        ) + (
            WizardChoice(
                value=MANUAL_MODEL_SENTINEL,
                label=_pf_text(language, "Manual model id", "手动输入模型 ID"),
                detail=_pf_text(language, "Type a model id that is not advertised by the provider catalog.", "输入模型列表里没有展示的模型 ID。"),
            ),
        )
        default_value = (
            state.model_id
            if any(model.model_id == state.model_id for model in models)
            else models[0].model_id
        )
        answer = _wizard_choice_prompt(
            _pf_text(language, "Choose The Model", "选择模型"),
            _pf_text(language, "Pick the model Elephant Agent should use from this provider endpoint.", "从这个服务端点里选择 Elephant Agent 要使用的模型。"),
            model_choices,
            default=default_value,
            allow_back=allow_back,
        )
        if answer is WIZARD_CANCEL:
            return WIZARD_CANCEL
        if answer is WIZARD_BACK:
            return WIZARD_BACK
        selected = str(answer)
        if selected == MANUAL_MODEL_SENTINEL:
            manual = _wizard_text_prompt(
                "Type The Model Id",
                "Enter the exact model id Elephant Agent should use.",
                default=_manual_model_default(state.provider_id, state.model_id),
                allow_back=allow_back,
            )
            if manual is WIZARD_BACK:
                return WIZARD_BACK
            return str(manual).strip(), refreshed_api_key
        return selected, refreshed_api_key
    prompt = (
        "Elephant Agent still could not read the provider model catalog after retrying the provider key, so enter the exact model id manually."
        if retried_provider_key
        else "Elephant Agent could not read the provider model catalog here, so enter the exact model id manually."
    )
    answer = _wizard_text_prompt(
        _pf_text(language, "Choose The Model", "选择模型"),
        prompt,
        default=_manual_model_default(state.provider_id, state.model_id),
        allow_back=allow_back,
    )
    if answer is WIZARD_BACK:
        return WIZARD_BACK
    return str(answer).strip(), refreshed_api_key


def provider_choices(runtime: CliRuntime) -> tuple[WizardChoice, ...]:
    return tuple(
        WizardChoice(
            value=state.provider_id,
            label=state.display_name,
            detail=f"{state.status} via {state.source}",
            detail_style="accent-detail",
            selected_detail_style="accent-selected-detail",
        )
        for state in runtime.provider_inventory()
        if state.runtime_enabled
    )


def run_provider_selection_wizard(
    runtime: CliRuntime,
    *,
    initial_state: ProviderSelectionState,
    allow_back: bool = False,
    provider_locked: bool = False,
    language: str = "en",
) -> ProviderSelectionState | _WizardBackSignal | _WizardCancelSignal:
    state = ProviderSelectionState(
        provider_id=initial_state.provider_id,
        base_url=initial_state.base_url,
        api_key=initial_state.api_key,
        model_id=initial_state.model_id,
        reasoning_effort=initial_state.reasoning_effort,
        context_window_mode=initial_state.context_window_mode,
        context_window_tokens=initial_state.context_window_tokens,
    )
    steps = [
        "provider_id",
        "base_url",
        "api_key",
        "model",
        "reasoning_effort",
        "context_window_mode",
        "context_window_tokens",
    ]
    if provider_locked:
        steps.remove("provider_id")
    step_index = 0

    def _go_back() -> bool:
        nonlocal step_index
        if step_index <= 0:
            return False
        step_index -= 1
        return True

    while step_index < len(steps):
        step = steps[step_index]
        if step == "provider_id":
            answer = _wizard_choice_prompt(
                _pf_text(language, "Choose A Provider", "选择模型服务"),
                _pf_text(language, "Where should Elephant Agent think from next?", "Elephant Agent 接下来应该从哪里思考？"),
                provider_choices(runtime),
                default=state.provider_id,
                allow_back=allow_back,
            )
            if answer is WIZARD_CANCEL:
                return WIZARD_CANCEL
            if answer is WIZARD_BACK:
                if not _go_back():
                    return WIZARD_BACK
                continue
            selected_provider = str(answer)
            if selected_provider != state.provider_id:
                state = provider_setup_defaults(runtime, selected_provider)
            step_index += 1
            continue

        guide = runtime.provider_setup_guide(state.provider_id)
        discovered = runtime.discovered_provider(state.provider_id)
        summary = dict(runtime.provider_summary())
        same_provider = str(summary.get("provider_id", "")).strip().lower() == state.provider_id
        summary_base_url = str(summary.get("base_url") or "").strip()
        discovered_base_url = str(getattr(discovered, "base_url", "") or "").strip()
        state_base_url = str(state.base_url or "").strip()
        supports_custom_base_url = "base_url" in guide.required_config_keys
        known_base_url = summary_base_url if same_provider and summary_base_url else discovered_base_url
        same_endpoint = (
            not supports_custom_base_url
            or (bool(state_base_url) and bool(known_base_url) and state_base_url == known_base_url)
        )
        discovered_secret_reusable = discovered.status in {"authenticated", "configured"} and (
            not supports_custom_base_url or same_endpoint
        )
        has_resolved_secret = (
            same_provider and same_endpoint and summary.get("secret_status") in {"stored", "not-required"}
        ) or discovered_secret_reusable

        if step == "base_url":
            if "base_url" not in guide.required_config_keys:
                step_index += 1
                continue
            answer = _wizard_text_prompt(
                _pf_text(language, "Set The Endpoint", "设置接口地址"),
                _pf_text(language, "What endpoint should Elephant Agent call?", "Elephant Agent 应该调用哪个接口？"),
                default=state.base_url,
                allow_back=allow_back and step_index > 0,
            )
            if answer is WIZARD_CANCEL:
                return WIZARD_CANCEL
            if answer is WIZARD_BACK:
                if not _go_back():
                    return WIZARD_BACK
                continue
            state.base_url = str(answer).strip()
            step_index += 1
            continue

        if step == "api_key":
            if (
                not guide.required_secret_keys
                or guide.auth_type in {"oauth_external", "oauth_device_code", "external_process"}
            ):
                state.api_key = None
                step_index += 1
                continue
            if has_resolved_secret:
                answer = _wizard_choice_prompt(
                    "Provider Key",
                    "An API key is already stored for this provider.",
                    (
                        WizardChoice(value="keep", label="Keep existing key", detail="Skip re-entry"),
                        WizardChoice(value="replace", label="Enter a new key", detail="Overwrite the stored key"),
                    ),
                    default="keep",
                    allow_back=allow_back and step_index > 0,
                )
                if answer is WIZARD_BACK:
                    if not _go_back():
                        return WIZARD_BACK
                    continue
                if answer == "keep":
                    state.api_key = None
                    step_index += 1
                    continue
            answer = _wizard_text_prompt(
                "Store The Provider Key",
                "Enter the provider key. Elephant Agent stores it encrypted and will not ask again next time.",
                default=None,
                allow_back=allow_back and step_index > 0,
                password=True,
            )
            if answer is WIZARD_CANCEL:
                return WIZARD_CANCEL
            if answer is WIZARD_BACK:
                if not _go_back():
                    return WIZARD_BACK
                continue
            entered = str(answer).strip()
            if entered:
                state.api_key = entered
                step_index += 1
                continue
            continue

        if step == "model":
            answer = _choose_model(
                runtime,
                state,
                auth_type=guide.auth_type,
                allow_back=allow_back and step_index > 0,
                language=language,
            )
            if answer is WIZARD_CANCEL:
                return WIZARD_CANCEL
            if answer is WIZARD_BACK:
                if not _go_back():
                    return WIZARD_BACK
                continue
            model_id, refreshed_api_key = answer
            state.model_id = model_id
            if refreshed_api_key is not None:
                state.api_key = refreshed_api_key
            available_efforts = runtime.provider_reasoning_efforts(
                provider_id=state.provider_id,
                model_id=state.model_id,
                base_url=state.base_url or None,
                api_key=state.api_key,
            )
            if state.reasoning_effort and state.reasoning_effort not in available_efforts:
                state.reasoning_effort = None
            step_index += 1
            continue

        if step == "reasoning_effort":
            available_efforts = runtime.provider_reasoning_efforts(
                provider_id=state.provider_id,
                model_id=state.model_id,
                base_url=state.base_url or None,
                api_key=state.api_key,
            )
            if not available_efforts:
                state.reasoning_effort = None
                step_index += 1
                continue
            answer = _wizard_choice_prompt(
                "Choose Reasoning Effort",
                "How much reasoning effort should Elephant Agent request for this model?",
                (
                    WizardChoice(
                        value="",
                        label=_pf_text(language, "Provider default", "服务默认"),
                        detail=_pf_text(language, "Let the provider choose its default reasoning budget.", "让模型服务使用默认推理预算。"),
                    ),
                    *tuple(
                        WizardChoice(
                            value=effort,
                            label=effort,
                            detail=f"Use {effort} reasoning effort for supported turns.",
                        )
                        for effort in available_efforts
                    ),
                ),
                default=state.reasoning_effort or "",
                allow_back=allow_back and step_index > 0,
            )
            if answer is WIZARD_CANCEL:
                return WIZARD_CANCEL
            if answer is WIZARD_BACK:
                if not _go_back():
                    return WIZARD_BACK
                continue
            selected = str(answer).strip()
            state.reasoning_effort = selected or None
            step_index += 1
            continue

        if step == "context_window_mode":
            detected = runtime.detect_provider_context_window(
                provider_id=state.provider_id,
                model_id=state.model_id,
                base_url=state.base_url or None,
                api_key=state.api_key,
            )
            auto_value = detected or state.context_window_tokens or DEFAULT_CONTEXT_WINDOW_TOKENS
            answer = _wizard_choice_prompt(
                _pf_text(language, "Choose The Context Window", "选择上下文窗口"),
                _pf_text(language, "How should Elephant Agent size the context budget?", "Elephant Agent 应该怎样设置上下文预算？"),
                (
                    WizardChoice(
                        value="auto",
                        label="Auto-detect",
                        detail=f"Use live endpoint metadata when available ({_format_context_tokens(auto_value)}).",
                    ),
                    WizardChoice(
                        value="manual",
                        label="Manual entry",
                        detail="Type this model's context window yourself.",
                    ),
                ),
                default=state.context_window_mode or "auto",
                allow_back=allow_back and step_index > 0,
            )
            if answer is WIZARD_CANCEL:
                return WIZARD_CANCEL
            if answer is WIZARD_BACK:
                if not _go_back():
                    return WIZARD_BACK
                continue
            state.context_window_mode = str(answer)
            if state.context_window_mode == "auto":
                state.context_window_tokens = auto_value
            step_index += 1
            continue

        if step == "context_window_tokens":
            if state.context_window_mode != "manual":
                step_index += 1
                continue
            detected = runtime.detect_provider_context_window(
                provider_id=state.provider_id,
                model_id=state.model_id,
                base_url=state.base_url or None,
                api_key=state.api_key,
            )
            default_tokens = str(state.context_window_tokens or detected or DEFAULT_CONTEXT_WINDOW_TOKENS)
            answer = _wizard_text_prompt(
                _pf_text(language, "Enter The Context Window", "输入上下文窗口"),
                _pf_text(language, "How many tokens of context should Elephant Agent budget for this model?", "Elephant Agent 应该为这个模型预留多少上下文 token？"),
                default=default_tokens,
                allow_back=allow_back and step_index > 0,
            )
            if answer is WIZARD_CANCEL:
                return WIZARD_CANCEL
            if answer is WIZARD_BACK:
                if not _go_back():
                    return WIZARD_BACK
                continue
            try:
                parsed = int(str(answer).strip().replace(",", ""))
            except ValueError:
                continue
            if parsed <= 0:
                continue
            state.context_window_tokens = parsed
            step_index += 1
            continue

    return state


def _format_context_tokens(value: int) -> str:
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000}M"
    if value >= 1_000 and value % 1_000 == 0:
        return f"{value // 1_000}K"
    if value >= 1024:
        return f"{round(value / 1024)}K"
    return str(value)


def _model_detail(context_window_tokens: int | None, max_output_tokens: int | None) -> str:
    bits = []
    if context_window_tokens is not None:
        bits.append(f"context {_format_context_tokens(context_window_tokens)}")
    if max_output_tokens is not None:
        bits.append(f"output {_format_context_tokens(max_output_tokens)}")
    if not bits:
        return "Live /v1/models entry"
    return " · ".join(bits)
