"""Unit tests for GatewayMessageDeliverySurface."""

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

from packages.contracts.runtime import ExecutionResult
from packages.gateway_core.outbound_delivery import (
    GatewayMessageDeliverySurface,
    _try_parse_session_route,
)
from packages.gateway_core.outbound_queue import GatewayOutboundQueue


class ParseSessionRouteTest(unittest.TestCase):
    def test_valid_session_id(self):
        result = _try_parse_session_route("session:messaging.feishu:bot123@im.bot:user456@im.feishu")
        self.assertEqual(result, ("messaging.feishu", "bot123@im.bot", "user456@im.feishu"))

    def test_conversation_id_with_colons(self):
        result = _try_parse_session_route("session:messaging.weixin:bot@im.bot:conv:with:colons")
        self.assertEqual(result, ("messaging.weixin", "bot@im.bot", "conv:with:colons"))

    def test_invalid_prefix_returns_none(self):
        self.assertIsNone(_try_parse_session_route("episode:foo:bar:baz"))

    def test_too_few_parts_returns_none(self):
        self.assertIsNone(_try_parse_session_route("session:foo:bar"))


@dataclass(frozen=True)
class _FakeIdentityKey:
    adapter_id: str
    account_id: str
    conversation_id: str


@dataclass(frozen=True)
class _FakeIdentityRecord:
    key: _FakeIdentityKey
    elephant_id: str = ""


class _FakeIdentityStore:
    def __init__(self, records):
        self._records = records

    def list_records(self):
        return tuple(self._records)

    def lookup_by_elephant_id(self, elephant_id):
        return tuple(r for r in self._records if r.elephant_id == elephant_id)


class GatewayMessageDeliverySurfaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.queue = GatewayOutboundQueue(path=Path(self.tmp) / "outbound.json")

    def test_send_via_gateway_session(self):
        surface = GatewayMessageDeliverySurface(outbound_queue=self.queue)
        result = surface.send_message(
            session_id="session:messaging.feishu:bot@im.bot:user@im.feishu",
            body="Hello Zoey",
        )
        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(result.outcome, "queued")
        self.assertIn("messaging.feishu", result.summary)

        rows = self.queue.claim(adapter_id="messaging.feishu", limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].body, "Hello Zoey")
        self.assertEqual(rows[0].adapter_id, "messaging.feishu")
        self.assertEqual(rows[0].account_id, "bot@im.bot")
        self.assertEqual(rows[0].conversation_id, "user@im.feishu")

    def test_send_via_identity_store_fallback(self):
        """CLI session_id doesn't parse — falls back to identity store."""
        identity_store = _FakeIdentityStore(
            [
                _FakeIdentityRecord(
                    key=_FakeIdentityKey("messaging.feishu", "bot@im.bot", "zoey@im.feishu"),
                    elephant_id="elephant-001",
                ),
            ]
        )
        surface = GatewayMessageDeliverySurface(
            outbound_queue=self.queue,
            identity_store=identity_store,
            default_elephant_id="elephant-001",
        )
        result = surface.send_message(
            session_id="cli:local-session-xyz",
            body="Good night from CLI",
        )
        self.assertEqual(result.outcome, "queued")
        rows = self.queue.claim(adapter_id="messaging.feishu", limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].body, "Good night from CLI")
        self.assertEqual(rows[0].conversation_id, "zoey@im.feishu")

    def test_send_with_target_hint_filters_adapter(self):
        """Target hint selects the right adapter."""
        identity_store = _FakeIdentityStore(
            [
                _FakeIdentityRecord(
                    key=_FakeIdentityKey("messaging.feishu", "bot@feishu", "user@feishu"),
                    elephant_id="elephant-001",
                ),
                _FakeIdentityRecord(
                    key=_FakeIdentityKey("messaging.weixin", "bot@wx", "user@wx"),
                    elephant_id="elephant-001",
                ),
            ]
        )
        surface = GatewayMessageDeliverySurface(
            outbound_queue=self.queue,
            identity_store=identity_store,
            default_elephant_id="elephant-001",
        )
        result = surface.send_message(
            session_id="cli:local",
            body="WeChat message",
            target="weixin",
        )
        self.assertEqual(result.outcome, "queued")
        rows = self.queue.claim(adapter_id="messaging.weixin", limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].body, "WeChat message")

    def test_send_fails_without_identity_store_or_gateway_session(self):
        surface = GatewayMessageDeliverySurface(outbound_queue=self.queue)
        with self.assertRaises(ValueError):
            surface.send_message(
                session_id="cli:local",
                body="fail",
            )

    def test_send_with_metadata(self):
        surface = GatewayMessageDeliverySurface(outbound_queue=self.queue)
        result = surface.send_message(
            session_id="session:messaging.weixin:bot@im.bot:user@im.wechat",
            body="Good night",
            metadata={"intent": "goodnight"},
        )
        self.assertEqual(result.outcome, "queued")
        rows = self.queue.claim(adapter_id="messaging.weixin", limit=10)
        self.assertEqual(rows[0].metadata["intent"], "goodnight")
        self.assertEqual(rows[0].metadata["enqueued_via"], "tool.message.send")


if __name__ == "__main__":
    unittest.main()
