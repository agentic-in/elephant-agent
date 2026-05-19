from __future__ import annotations

import unittest
from unittest import mock

from apps.cli.provider_flow import (
    ProviderSelectionState,
    provider_setup_defaults,
    run_provider_selection_wizard,
)


class ProviderFlowWizardTests(unittest.TestCase):
    def test_provider_setup_defaults_falls_back_from_preview_to_default_provider(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.side_effect = [
            LookupError("preview is not a real provider"),
            mock.Mock(
                suggested_base_url="https://api.openai.com/v1",
                suggested_model_id="gpt-4.1-mini",
            ),
        ]
        runtime.discovered_provider.return_value = mock.Mock(
            base_url="https://api.openai.com/v1",
            default_model="gpt-4.1-mini",
        )
        runtime.provider_summary.return_value = {"provider_id": "preview"}

        state = provider_setup_defaults(runtime, "preview")

        self.assertEqual(state.provider_id, "openai-compatible")
        self.assertEqual(state.base_url, "https://api.openai.com/v1")
        self.assertEqual(state.model_id, "gpt-4.1-mini")

    def test_oauth_provider_skips_session_override_prompt(self) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("model_id",),
            required_secret_keys=("api_key",),
            auth_type="oauth_external",
        )
        runtime.discovered_provider.return_value = mock.Mock(status="authenticated", source="codex-cli")
        runtime.provider_summary.return_value = {
            "provider_id": "openai-codex",
            "secret_status": "stored",
        }
        runtime.discover_provider_models.return_value = (
            mock.Mock(
                model_id="gpt-5.4",
                context_window_tokens=128000,
                max_output_tokens=16384,
            ),
        )
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch(
                "apps.cli.provider_flow._wizard_choice_prompt",
                side_effect=("gpt-5.4", "auto"),
            ),
            mock.patch("apps.cli.provider_flow._wizard_text_prompt") as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="openai-codex",
                    base_url="https://chatgpt.com/backend-api/codex",
                    api_key=None,
                    model_id="gpt-5.4",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertEqual(result.provider_id, "openai-codex")
        self.assertEqual(result.model_id, "gpt-5.4")
        text_prompt.assert_not_called()

    def test_discovered_copilot_credentials_skip_key_prompt(self) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("model_id",),
            required_secret_keys=("api_key",),
            auth_type="api_key",
        )
        runtime.discovered_provider.return_value = mock.Mock(status="authenticated", source="gh-cli")
        runtime.provider_summary.return_value = {
            "provider_id": "copilot",
            "secret_status": "stored",
        }
        runtime.discover_provider_models.return_value = (
            mock.Mock(
                model_id="gpt-5.4",
                context_window_tokens=128000,
                max_output_tokens=16384,
            ),
        )
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch("apps.cli.provider_flow._wizard_choice_prompt", side_effect=("keep", "gpt-5.4", "auto")),
            mock.patch("apps.cli.provider_flow._wizard_text_prompt") as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="copilot",
                    base_url="https://api.githubcopilot.com",
                    api_key=None,
                    model_id="gpt-5.4",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertEqual(result.provider_id, "copilot")
        self.assertEqual(result.model_id, "gpt-5.4")
        text_prompt.assert_not_called()

    def test_provider_wizard_uses_one_model_prompt(self) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("model_id",),
            required_secret_keys=("api_key",),
            auth_type="oauth_external",
        )
        runtime.discovered_provider.return_value = mock.Mock(status="authenticated", source="codex-cli")
        runtime.provider_summary.return_value = {
            "provider_id": "openai-codex",
            "secret_status": "stored",
        }
        runtime.discover_provider_models.return_value = (
            mock.Mock(
                model_id="gpt-5.4",
                context_window_tokens=128000,
                max_output_tokens=16384,
            ),
            mock.Mock(
                model_id="gpt-5.4-mini",
                context_window_tokens=128000,
                max_output_tokens=16384,
            ),
        )
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with mock.patch(
            "apps.cli.provider_flow._wizard_choice_prompt",
            side_effect=("gpt-5.4-mini", "auto"),
        ) as choice_prompt:
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="openai-codex",
                    base_url="https://chatgpt.com/backend-api/codex",
                    api_key=None,
                    model_id="gpt-5.4",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertEqual(result.model_id, "gpt-5.4-mini")
        self.assertEqual(choice_prompt.call_count, 2)

    def test_openai_compatible_prompts_for_key_again_when_base_url_changes(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("base_url", "model_id"),
            required_secret_keys=("api_key",),
            auth_type="api_key",
        )
        runtime.discovered_provider.return_value = mock.Mock(status="requires-setup", source="none")
        runtime.provider_summary.return_value = {
            "provider_id": "openai-compatible",
            "secret_status": "stored",
            "base_url": "https://old.example.test/v1",
        }
        runtime.discover_provider_models.return_value = (
            mock.Mock(
                model_id="openai/gpt-4o-mini",
                context_window_tokens=128000,
                max_output_tokens=16384,
            ),
        )
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch(
                "apps.cli.provider_flow._wizard_choice_prompt",
                side_effect=("openai/gpt-4o-mini", "auto"),
            ),
            mock.patch(
                "apps.cli.provider_flow._wizard_text_prompt",
                side_effect=("https://new.example.test/v1", "sk-new-key"),
            ) as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="openai-compatible",
                    base_url="https://new.example.test/v1",
                    api_key=None,
                    model_id="openai/gpt-4o-mini",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertEqual(result.api_key, "sk-new-key")
        self.assertEqual(text_prompt.call_count, 2)

    def test_openai_compatible_configured_state_still_prompts_for_key_when_endpoint_changes(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("base_url", "model_id"),
            required_secret_keys=("api_key",),
            auth_type="api_key",
        )
        runtime.discovered_provider.return_value = mock.Mock(
            status="configured",
            source="profile",
            base_url="https://old.example.test/v1",
        )
        runtime.provider_summary.return_value = {
            "provider_id": "copilot",
            "secret_status": "stored",
            "base_url": "https://api.githubcopilot.com",
        }
        runtime.discover_provider_models.return_value = (
            mock.Mock(
                model_id="openai/gpt-4o-mini",
                context_window_tokens=128000,
                max_output_tokens=16384,
            ),
        )
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch(
                "apps.cli.provider_flow._wizard_choice_prompt",
                side_effect=("openai/gpt-4o-mini", "auto"),
            ),
            mock.patch(
                "apps.cli.provider_flow._wizard_text_prompt",
                side_effect=("https://new.example.test/v1", "sk-new-key"),
            ) as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="openai-compatible",
                    base_url="https://new.example.test/v1",
                    api_key=None,
                    model_id="openai/gpt-4o-mini",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertEqual(result.api_key, "sk-new-key")
        self.assertEqual(text_prompt.call_count, 2)

    def test_openai_compatible_reuses_configured_key_when_endpoint_matches(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("base_url", "model_id"),
            required_secret_keys=("api_key",),
            auth_type="api_key",
        )
        runtime.discovered_provider.return_value = mock.Mock(
            status="configured",
            source="profile",
            base_url="https://same.example.test/v1",
        )
        runtime.provider_summary.return_value = {
            "provider_id": "other-provider",
            "secret_status": "missing",
            "base_url": "https://irrelevant.example.test/v1",
        }
        runtime.discover_provider_models.return_value = (
            mock.Mock(
                model_id="openai/gpt-4o-mini",
                context_window_tokens=128000,
                max_output_tokens=16384,
            ),
        )
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch(
                "apps.cli.provider_flow._wizard_choice_prompt", side_effect=("keep", "openai/gpt-4o-mini", "auto")
            ),
            mock.patch(
                "apps.cli.provider_flow._wizard_text_prompt",
                side_effect=("https://same.example.test/v1",),
            ) as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="openai-compatible",
                    base_url="https://same.example.test/v1",
                    api_key=None,
                    model_id="openai/gpt-4o-mini",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertIsNone(result.api_key)
        self.assertEqual(text_prompt.call_count, 1)

    def test_api_key_provider_retries_key_before_manual_model_when_catalog_is_unavailable(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("model_id",),
            required_secret_keys=("api_key",),
            auth_type="api_key",
        )
        runtime.discovered_provider.return_value = mock.Mock(
            status="configured",
            source="profile",
            base_url="https://openrouter.ai/api/v1",
        )
        runtime.provider_summary.return_value = {
            "provider_id": "openrouter",
            "secret_status": "stored",
            "base_url": "https://openrouter.ai/api/v1",
        }
        runtime.discover_provider_models.side_effect = [
            (),
            (
                mock.Mock(
                    model_id="openai/gpt-4o-mini",
                    context_window_tokens=128000,
                    max_output_tokens=16384,
                ),
            ),
            (
                mock.Mock(
                    model_id="openai/gpt-4o-mini",
                    context_window_tokens=128000,
                    max_output_tokens=16384,
                ),
            ),
        ]
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch(
                "apps.cli.provider_flow._wizard_choice_prompt", side_effect=("keep", "openai/gpt-4o-mini", "auto")
            ),
            mock.patch(
                "apps.cli.provider_flow._wizard_text_prompt",
                side_effect=("sk-refreshed-key",),
            ) as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key=None,
                    model_id="openai/gpt-4o-mini",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertEqual(result.api_key, "sk-refreshed-key")
        self.assertEqual(runtime.discover_provider_models.call_count, 2)
        text_prompt.assert_called_once()

    def test_copilot_keeps_manual_model_flow_when_catalog_is_unavailable(self) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("model_id",),
            required_secret_keys=("api_key",),
            auth_type="api_key",
        )
        runtime.discovered_provider.return_value = mock.Mock(status="authenticated", source="gh-cli", base_url="")
        runtime.provider_summary.return_value = {
            "provider_id": "copilot",
            "secret_status": "stored",
            "base_url": "",
        }
        runtime.discover_provider_models.return_value = ()
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch("apps.cli.provider_flow._wizard_choice_prompt", side_effect=("keep", "auto")),
            mock.patch(
                "apps.cli.provider_flow._wizard_text_prompt",
                side_effect=("gpt-5.4",),
            ) as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="copilot",
                    base_url="https://api.githubcopilot.com",
                    api_key=None,
                    model_id="gpt-5.4",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertIsNone(result.api_key)
        self.assertEqual(result.model_id, "gpt-5.4")
        self.assertEqual(runtime.discover_provider_models.call_count, 1)
        self.assertEqual(text_prompt.call_count, 1)

    def test_stored_api_key_prompts_keep_or_replace(self) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("model_id",),
            required_secret_keys=("api_key",),
            auth_type="api_key",
        )
        runtime.discovered_provider.return_value = mock.Mock(status="configured", source="profile")
        runtime.provider_summary.return_value = {"provider_id": "deepseek", "secret_status": "stored"}
        runtime.discover_provider_models.return_value = (
            mock.Mock(model_id="deepseek-reasoner", context_window_tokens=128000, max_output_tokens=16384),
        )
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch(
                "apps.cli.provider_flow._wizard_choice_prompt", side_effect=("keep", "deepseek-reasoner", "auto")
            ),
            mock.patch("apps.cli.provider_flow._wizard_text_prompt") as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="deepseek",
                    base_url="https://api.deepseek.com/v1",
                    api_key=None,
                    model_id="deepseek-reasoner",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertIsNone(result.api_key)
        text_prompt.assert_not_called()

    def test_stored_api_key_replace_prompts_for_new_key(self) -> None:
        runtime = mock.Mock()
        runtime.provider_setup_guide.return_value = mock.Mock(
            required_config_keys=("model_id",),
            required_secret_keys=("api_key",),
            auth_type="api_key",
        )
        runtime.discovered_provider.return_value = mock.Mock(status="configured", source="profile")
        runtime.provider_summary.return_value = {"provider_id": "deepseek", "secret_status": "stored"}
        runtime.discover_provider_models.return_value = (
            mock.Mock(model_id="deepseek-reasoner", context_window_tokens=128000, max_output_tokens=16384),
        )
        runtime.provider_reasoning_efforts.return_value = ()
        runtime.detect_provider_context_window.return_value = 128000

        with (
            mock.patch(
                "apps.cli.provider_flow._wizard_choice_prompt", side_effect=("replace", "deepseek-reasoner", "auto")
            ),
            mock.patch(
                "apps.cli.provider_flow._wizard_text_prompt",
                side_effect=("sk-new-deepseek-key",),
            ) as text_prompt,
        ):
            result = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id="deepseek",
                    base_url="https://api.deepseek.com/v1",
                    api_key=None,
                    model_id="deepseek-reasoner",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
                allow_back=True,
                provider_locked=True,
            )

        self.assertEqual(result.api_key, "sk-new-deepseek-key")
        text_prompt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
