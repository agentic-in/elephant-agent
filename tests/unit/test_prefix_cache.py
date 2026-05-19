from __future__ import annotations

import unittest

from packages.tools.runtime import InMemoryToolRegistry, ToolDefinition


class ToolOrderingStabilityTest(unittest.TestCase):
    def test_list_returns_sorted_by_tool_id(self) -> None:
        registry = InMemoryToolRegistry()
        registry.register(ToolDefinition(tool_id="tool.zebra", display_name="Zebra", version="1"))
        registry.register(ToolDefinition(tool_id="tool.alpha", display_name="Alpha", version="1"))
        registry.register(ToolDefinition(tool_id="tool.mid", display_name="Mid", version="1"))

        result = registry.list()
        ids = [d.tool_id for d in result]
        self.assertEqual(ids, ["tool.alpha", "tool.mid", "tool.zebra"])

    def test_list_stable_after_re_registration(self) -> None:
        registry = InMemoryToolRegistry()
        registry.register(ToolDefinition(tool_id="b", display_name="B", version="1"))
        registry.register(ToolDefinition(tool_id="a", display_name="A", version="1"))
        first = [d.tool_id for d in registry.list()]

        registry.register(ToolDefinition(tool_id="a", display_name="A-updated", version="2"))
        second = [d.tool_id for d in registry.list()]
        self.assertEqual(first, second)


class PrefixCacheHashTest(unittest.TestCase):
    def test_same_inputs_produce_same_hash(self) -> None:
        from packages.kernel.generation_context import _prefix_input_hash
        h1 = _prefix_input_hash("prefix", ("fact1", "fact2"), ("resume",), "skills")
        h2 = _prefix_input_hash("prefix", ("fact1", "fact2"), ("resume",), "skills")
        self.assertEqual(h1, h2)

    def test_different_facts_produce_different_hash(self) -> None:
        from packages.kernel.generation_context import _prefix_input_hash
        h1 = _prefix_input_hash("prefix", ("fact1",), ("resume",), "skills")
        h2 = _prefix_input_hash("prefix", ("fact1", "fact2"), ("resume",), "skills")
        self.assertNotEqual(h1, h2)

    def test_cache_invalidation(self) -> None:
        from packages.kernel.generation_context import _prefix_cache, invalidate_prefix_cache
        _prefix_cache["test-ep"] = ("hash123", "cached prefix")
        invalidate_prefix_cache("test-ep")
        self.assertNotIn("test-ep", _prefix_cache)


class AnthropicCacheControlTest(unittest.TestCase):
    def test_official_anthropic_uses_content_blocks_with_cache_control(self) -> None:
        from packages.models.providers.anthropic import AnthropicMessagesRequest
        req = AnthropicMessagesRequest(
            request_id="r1", provider_id="anthropic", transport_id="anthropic_messages",
            request_family="anthropic_messages", model_id="claude-4", base_url="https://api.anthropic.com/v1",
            endpoint_path="/v1/messages", headers={}, system="test system prompt",
            messages=(), max_tokens=1024,
            tools=({"name": "tool_a", "input_schema": {}}, {"name": "tool_b", "input_schema": {}}),
        )
        payload = req.as_mapping()
        self.assertIsInstance(payload["system"], list)
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})
        tools = payload["tools"]
        self.assertIn("cache_control", tools[-1])
        self.assertNotIn("cache_control", tools[0])

    def test_non_anthropic_provider_uses_plain_string(self) -> None:
        from packages.models.providers.anthropic import AnthropicMessagesRequest
        req = AnthropicMessagesRequest(
            request_id="r1", provider_id="minimax-cn", transport_id="anthropic_messages",
            request_family="anthropic_messages", model_id="model-x", base_url="https://api.minimaxi.com/anthropic",
            endpoint_path="/v1/messages", headers={}, system="test system prompt",
            messages=(), max_tokens=1024,
            tools=({"name": "tool_a", "input_schema": {}},),
        )
        payload = req.as_mapping()
        self.assertIsInstance(payload["system"], str)
        self.assertNotIn("cache_control", payload["tools"][0])


if __name__ == "__main__":
    unittest.main()
