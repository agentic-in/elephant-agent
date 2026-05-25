from __future__ import annotations

from types import SimpleNamespace
import unittest

from packages.models.discovery import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    ProviderMetadataDiscoveryService,
    ProviderStateEvaluator,
    _hinted_models,
    heuristic_context_window,
)


class ProviderDiscoveryTest(unittest.TestCase):
    def test_unknown_context_window_fallback_is_256k(self) -> None:
        self.assertEqual(DEFAULT_CONTEXT_WINDOW_TOKENS, 256_000)
        self.assertEqual(heuristic_context_window("unknown-chat-model"), 256_000)

    def test_glm_context_window_heuristic_is_at_least_256k(self) -> None:
        self.assertGreaterEqual(heuristic_context_window("glm-5.1"), 256_000)

    def test_hinted_model_reasoning_resolution_failure_is_logged(self) -> None:
        class RuntimeResolver:
            def resolve(self, *_: object, **__: object) -> object:
                raise RuntimeError("resolver unavailable")

        with self.assertLogs("packages.models.discovery", level="DEBUG") as logs:
            models = _hinted_models("openai", runtime_resolver=RuntimeResolver())  # type: ignore[arg-type]

        self.assertTrue(models)
        self.assertIn("Failed to resolve reasoning efforts for hinted provider model", "\n".join(logs.output))

    def test_reasoning_efforts_discovery_failure_is_logged(self) -> None:
        class RuntimeResolver:
            def resolve(self, *_: object, **__: object) -> object:
                return SimpleNamespace(reasoning_efforts=("fallback",))

        service = ProviderMetadataDiscoveryService(runtime_resolver=RuntimeResolver())  # type: ignore[arg-type]
        service.discover_models = lambda **_: (_ for _ in ()).throw(RuntimeError("discovery unavailable"))  # type: ignore[method-assign]

        with self.assertLogs("packages.models.discovery", level="DEBUG") as logs:
            efforts = service.reasoning_efforts(
                provider_id="openai",
                model_id="gpt-5.4",
                base_url="https://api.example.test/v1",
                api_key=None,
            )

        self.assertEqual(efforts, ("fallback",))
        self.assertIn("Failed to discover provider models while resolving reasoning efforts", "\n".join(logs.output))

    def test_local_provider_reachability_failure_is_logged(self) -> None:
        service = ProviderMetadataDiscoveryService()
        service.discover_models = lambda **_: (_ for _ in ()).throw(RuntimeError("discovery unavailable"))  # type: ignore[method-assign]

        with self.assertLogs("packages.models.discovery", level="DEBUG") as logs:
            self.assertFalse(
                service.local_provider_reachable(
                    provider_id="ollama",
                    base_url="http://localhost:11434",
                )
            )

        self.assertIn("Failed to probe local provider reachability", "\n".join(logs.output))

    def test_provider_state_transport_resolution_failure_is_logged(self) -> None:
        class RuntimeResolver:
            def resolve(self, *_: object, **__: object) -> object:
                raise RuntimeError("resolver unavailable")

        evaluator = ProviderStateEvaluator(runtime_resolver=RuntimeResolver())  # type: ignore[arg-type]

        with self.assertLogs("packages.models.discovery", level="DEBUG") as logs:
            state = evaluator.evaluate(
                "openai-compatible",
                selected_profile=None,
                discovered_secret=None,
                base_url=None,
                default_model=None,
            )

        self.assertEqual(state.transport_display_name, "openai_chat_compatible")
        self.assertIn("Failed to resolve provider runtime state transport metadata", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
