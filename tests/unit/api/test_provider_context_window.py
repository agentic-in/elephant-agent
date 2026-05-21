from __future__ import annotations

from types import SimpleNamespace
import unittest

from apps.api.api_runtime_provider_methods import _provider_profile_with_auto_context
from packages.auth import AuthProfile


class ProviderContextWindowTest(unittest.TestCase):
    def test_auto_context_window_falls_back_to_256k(self) -> None:
        class Provider:
            def detect_context_window(self, **_kwargs):
                return None

        profile = AuthProfile(
            profile_id="provider-openai-compatible",
            provider_id="openai-compatible",
            base_url="https://example.test/v1",
            default_model="unknown-chat-model",
            metadata={},
        )

        resolved = _provider_profile_with_auto_context(SimpleNamespace(model_provider=Provider()), profile)

        self.assertEqual(resolved.metadata["context_window_mode"], "auto")
        self.assertEqual(resolved.metadata["context_window_tokens"], "256000")


if __name__ == "__main__":
    unittest.main()
