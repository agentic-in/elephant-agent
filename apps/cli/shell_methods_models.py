from __future__ import annotations

from .provider_flow import provider_setup_defaults
from .wizard import WIZARD_BACK, WIZARD_CANCEL


def _append_models(self, args: list[str]) -> None:
    action = args[0] if args else "configure"
    provider = dict(self.runtime.provider_summary())
    provider_id = str(provider.get("provider_id") or "")
    if provider_id in {"", "preview"}:
        self._append_entry("recovery", "Models", "Configure a provider first with /providers.")
        return
    if action in {"list", "ls"}:
        try:
            models = self.runtime.discover_provider_models(provider_id=provider_id)
        except Exception as error:
            self._append_entry("recovery", "Models", str(error))
            return
        lines = [
            (
                f"{model.model_id} | context={model.context_window_tokens or '<unknown>'} | "
                f"output={model.max_output_tokens or '<unknown>'}"
            )
            for model in models
        ] or ["<empty>"]
        lines.extend(
            [
                "",
                "/providers - open the unified provider and model setup flow",
                "/providers status - inspect the active provider and model posture",
            ]
        )
        self._append_entry("notice", "Models", "\n".join(lines))
        return
    if action == "status":
        self._append_entry(
            "status",
            "Model",
            "\n".join(
                [
                    f"provider_id: {provider_id}",
                    f"model: {provider.get('model_id') or provider.get('default_model') or '<unset>'}",
                    f"embedding_bootstrap_status: {provider.get('embedding_bootstrap_status') or '<unset>'}",
                    f"context_window_tokens: {provider.get('context_window_tokens') or '<unset>'}",
                    f"context_window_mode: {provider.get('context_window_mode') or '<unset>'}",
                    f"reasoning_effort: {provider.get('reasoning_effort') or '<unset>'}",
                    f"reasoning_efforts: {', '.join(provider.get('reasoning_efforts', ())) or '<none>'}",
                    f"supports_streaming: {provider.get('supports_streaming', '<unknown>')}",
                ]
            ),
        )
        return
    session = self.runtime.inspect_session(self.session_id)
    profile = self.runtime.inspect_profile(session.personal_model_id)
    initial_state = provider_setup_defaults(self.runtime, provider_id)
    initial_state.base_url = str(provider.get("base_url") or initial_state.base_url)
    initial_state.model_id = str(provider.get("model_id") or provider.get("default_model") or initial_state.model_id)
    initial_state.reasoning_effort = (
        str(provider.get("reasoning_effort")).strip()
        if provider.get("reasoning_effort") is not None
        else initial_state.reasoning_effort
    ) or None
    initial_state.context_window_mode = str(provider.get("context_window_mode") or initial_state.context_window_mode)
    if provider.get("context_window_tokens") is not None:
        try:
            initial_state.context_window_tokens = int(provider["context_window_tokens"])
        except (TypeError, ValueError):
            initial_state.context_window_tokens = initial_state.context_window_tokens
    from . import shell as _shell_module

    configured = _shell_module.run_provider_selection_wizard(
        self.runtime,
        initial_state=initial_state,
        allow_back=True,
        provider_locked=True,
    )
    if configured is WIZARD_BACK or configured is WIZARD_CANCEL:
        self._append_entry("notice", "Models", "Model setup cancelled.")
        return
    self.runtime.set_default_provider(
        provider_id=configured.provider_id,
        profile_id=profile.state.profile_id,
        display_name=profile.state.display_name,
        mode=profile.state.mode,
        base_url=configured.base_url,
        model_id=configured.model_id,
        api_key=configured.api_key,
        context_window_tokens=configured.context_window_tokens,
        context_window_mode=configured.context_window_mode,
        reasoning_effort=configured.reasoning_effort,
    )
    self._append_entry(
        "status",
        "Model updated",
        "\n".join(
            [
                f"provider_id: {configured.provider_id}",
                f"model: {configured.model_id}",
                f"context_window_tokens: {configured.context_window_tokens or '<unset>'}",
                f"context_window_mode: {configured.context_window_mode}",
                f"reasoning_effort: {configured.reasoning_effort or '<unset>'}",
            ]
        ),
    )


__all__ = ["_append_models"]
