from __future__ import annotations

import unittest

from apps.api.api_tool_approval_policy import tool_approval_policy_match
from packages.tools import ToolDefinition, ToolSideEffectMetadata


class ToolApprovalPolicyTest(unittest.TestCase):
    def test_default_policy_matches_no_tools(self) -> None:
        definition = ToolDefinition(
            tool_id="tool.terminal.exec",
            display_name="Terminal",
            version="1",
            family="terminal",
            side_effects=ToolSideEffectMetadata(writes_state=True, approval_class="strict"),
        )

        self.assertEqual(tool_approval_policy_match(definition, {}), (False, "disabled"))

    def test_configured_tool_id_and_family_match(self) -> None:
        by_id = ToolDefinition(
            tool_id="tool.file.write",
            display_name="Write File",
            version="1",
            family="filesystem",
        )
        by_family = ToolDefinition(
            tool_id="tool.process.manage",
            display_name="Process",
            version="1",
            family="process",
        )
        config = {
            "enabled": True,
            "tool_ids": ["tool.file.write"],
            "families": ["process"],
        }

        self.assertEqual(tool_approval_policy_match(by_id, config), (True, "tool_id"))
        self.assertEqual(tool_approval_policy_match(by_family, config), (True, "family"))

    def test_mcp_keyword_match_respects_write_or_strict_scope(self) -> None:
        read_only = ToolDefinition(
            tool_id="mcp.filesystem.read",
            display_name="Read",
            version="1",
            family="filesystem",
            backend="mcp",
            metadata={"serverId": "filesystem", "toolName": "read"},
        )
        write_tool = ToolDefinition(
            tool_id="mcp.filesystem.write",
            display_name="Write",
            version="1",
            family="filesystem",
            backend="mcp",
            side_effects=ToolSideEffectMetadata(writes_state=True),
            metadata={"serverId": "filesystem", "toolName": "write"},
        )
        config = {
            "enabled": True,
            "mcp_keywords": ["filesystem"],
            "mcp_writes_or_strict_only": True,
        }

        self.assertEqual(tool_approval_policy_match(read_only, config), (False, "mcp_read_only"))
        self.assertEqual(
            tool_approval_policy_match(write_tool, config),
            (True, "mcp_keyword:filesystem"),
        )


if __name__ == "__main__":
    unittest.main()

