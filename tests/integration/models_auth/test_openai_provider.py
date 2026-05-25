from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OPENAI_MODULE_PATH = ROOT / "packages" / "models" / "providers" / "openai.py"
SPEC = importlib.util.spec_from_file_location("packages.models.providers.openai", OPENAI_MODULE_PATH)
assert SPEC and SPEC.loader
OPENAI = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OPENAI
SPEC.loader.exec_module(OPENAI)

from packages.auth import InMemorySecretStore, ProfileCredentialResolver, SecretReference


class OpenAIProviderAdapterTests(unittest.TestCase):
    def test_openai_provider_uses_first_party_responses_transport(self) -> None:
        adapter = OPENAI.OpenAIProviderAdapter()

        manifest = adapter.manifest
        resolution = adapter.runtime_resolution(model_id="gpt-4.1", base_url="https://api.openai.com/v1")
        guide = adapter.setup_guide()

        self.assertEqual(manifest.provider_id, "openai")
        self.assertEqual(manifest.transport_id, "openai_responses")
        self.assertEqual(resolution.transport_id, "openai_responses")
        self.assertEqual(resolution.request_family, "responses")
        self.assertTrue(resolution.supports_streaming)
        self.assertTrue(resolution.supports_tools)
        self.assertFalse(resolution.supports_reasoning)
        self.assertEqual(resolution.capability_flags, ("chat",))
        self.assertIn("model_id", guide.required_config_keys)
        self.assertIn("Run a provider test or health flow", " ".join(guide.quickstart_steps))

    def test_openai_provider_exposes_reasoning_for_gpt5_models(self) -> None:
        adapter = OPENAI.OpenAIProviderAdapter()

        resolution = adapter.runtime_resolution(model_id="gpt-5.4", base_url="https://api.openai.com/v1")

        self.assertEqual(resolution.transport_id, "openai_responses")
        self.assertTrue(resolution.supports_reasoning)
        self.assertEqual(resolution.reasoning_efforts, ("minimal", "low", "medium", "high"))

    def test_openai_profile_builder_preserves_first_party_metadata(self) -> None:
        adapter = OPENAI.OpenAIProviderAdapter()
        reference = SecretReference(
            reference_id="secret-openai-token",
            provider_id="openai",
            secret_name="api_token",
            secret_key="api_key",
        )

        profile = adapter.profile_defaults(
            profile_id="auth-openai-default",
            secret_references=(reference,),
            priority=50,
            session_pin="session-123",
            cooldown_until=datetime(2026, 1, 1),
            metadata={"env": "prod"},
            model_id="gpt-4.1",
        )

        self.assertEqual(profile.provider_id, "openai")
        self.assertEqual(profile.transport_id, "openai_responses")
        self.assertEqual(profile.base_url, "https://api.openai.com/v1")
        self.assertEqual(profile.default_model, "gpt-4.1")
        self.assertEqual(profile.provider_kind, "first_party")
        self.assertEqual(profile.session_pin, "session-123")
        self.assertEqual(profile.metadata["env"], "prod")

    def test_openai_credentials_flow_reuses_shared_secret_resolution(self) -> None:
        adapter = OPENAI.OpenAIProviderAdapter()
        secret_store = InMemorySecretStore()
        reference = SecretReference(
            reference_id="secret-openai-token",
            provider_id="openai",
            secret_name="api_token",
            secret_key="api_key",
        )
        secret_store.put(reference.reference_id, "sk-test-openai")
        resolver = ProfileCredentialResolver(secret_store)
        profile = adapter.profile_defaults(
            profile_id="auth-openai-default",
            secret_references=(reference,),
        )

        credentials = resolver.resolve(profile)

        self.assertEqual(credentials.as_mapping(), {"api_key": "sk-test-openai"})
        self.assertNotIn("sk-test-openai", repr(credentials))

    def test_openai_adapter_metadata_is_exportable(self) -> None:
        adapter = OPENAI.OpenAIProviderAdapter()
        metadata = adapter.metadata()

        self.assertEqual(metadata["provider_id"], "openai")
        self.assertEqual(metadata["transport_id"], "openai_responses")
        self.assertIn("chat", metadata["capability_flags"])
        self.assertNotIn("reasoning", metadata["capability_flags"])
        self.assertIn("model_id", metadata["required_config_keys"])
        self.assertEqual(metadata["base_url"], "https://api.openai.com/v1")


if __name__ == "__main__":
    unittest.main()
