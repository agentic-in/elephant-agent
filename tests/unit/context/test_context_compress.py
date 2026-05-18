# ruff: noqa: E402

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.context.compress import split_for_compress
from packages.contracts.runtime import PromptMessage


def _tool_call_message(call_id: str) -> PromptMessage:
    return PromptMessage(
        role="assistant",
        content="",
        tool_calls=({"id": call_id, "name": "tool.echo"},),
    )


def _tool_result_message(call_id: str) -> PromptMessage:
    return PromptMessage(
        role="tool",
        content=f"result for {call_id}",
        tool_call_id=call_id,
        tool_name="tool.echo",
    )


class ContextCompressSplitTests(unittest.TestCase):
    def assert_provider_tool_pairs_valid(self, messages: tuple[PromptMessage, ...]) -> None:
        pending: set[str] = set()
        for message in messages:
            if pending:
                self.assertEqual(message.role, "tool")
                self.assertIn(message.tool_call_id, pending)
                pending.remove(message.tool_call_id)
                continue
            self.assertNotEqual(message.role, "tool")
            if message.role == "assistant" and message.tool_calls:
                pending = {
                    str(call.get("id") or call.get("call_id") or call.get("tool_call_id") or "").strip()
                    for call in message.tool_calls
                }
                pending.discard("")
                self.assertTrue(pending)
        self.assertFalse(pending)

    def test_aggressive_tail_keeps_tool_call_groups_atomic(self) -> None:
        messages: list[PromptMessage] = [PromptMessage(role="user", content="do many things")]
        for index in range(1, 7):
            call_id = f"call-{index}"
            messages.append(_tool_call_message(call_id))
            messages.append(_tool_result_message(call_id))
        messages.append(PromptMessage(role="assistant", content="final answer"))

        to_summarize, tail = split_for_compress(tuple(messages))

        self.assertGreater(len(to_summarize), 0)
        self.assert_provider_tool_pairs_valid(tail)
        self.assertIn(_tool_call_message("call-4"), tail)
        self.assertIn(_tool_result_message("call-4"), tail)

    def test_short_tool_turn_preserves_latest_group_not_orphan_result(self) -> None:
        messages = (
            PromptMessage(role="user", content="search docs " + ("payload " * 500)),
            _tool_call_message("call-short"),
            _tool_result_message("call-short"),
        )

        to_summarize, tail = split_for_compress(messages)

        self.assertEqual(to_summarize, messages[:1])
        self.assertEqual(tail, messages[1:])
        self.assert_provider_tool_pairs_valid(tail)

    def test_orphan_tool_messages_are_summarized_not_preserved(self) -> None:
        orphan = PromptMessage(
            role="tool",
            content="orphan result",
            tool_call_id="call-orphan",
            tool_name="tool.echo",
        )
        messages = (
            PromptMessage(role="user", content="start"),
            PromptMessage(role="assistant", content="older answer"),
            orphan,
            PromptMessage(role="assistant", content="final answer"),
        )

        to_summarize, tail = split_for_compress(messages)

        self.assertIn(orphan, to_summarize)
        self.assertNotIn(orphan, tail)
        self.assert_provider_tool_pairs_valid(tail)


if __name__ == "__main__":
    unittest.main()
