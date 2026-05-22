from __future__ import annotations

import unittest

from packages.models.discovery import DEFAULT_CONTEXT_WINDOW_TOKENS, heuristic_context_window


class ProviderDiscoveryTest(unittest.TestCase):
    def test_unknown_context_window_fallback_is_256k(self) -> None:
        self.assertEqual(DEFAULT_CONTEXT_WINDOW_TOKENS, 256_000)
        self.assertEqual(heuristic_context_window("unknown-chat-model"), 256_000)

    def test_glm_context_window_heuristic_is_at_least_256k(self) -> None:
        self.assertGreaterEqual(heuristic_context_window("glm-5.1"), 256_000)


if __name__ == "__main__":
    unittest.main()
