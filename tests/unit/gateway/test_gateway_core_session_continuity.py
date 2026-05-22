from __future__ import annotations

import tempfile
import threading
import time
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from packages.gateway_core import (
    FileGatewayIdentityStore,
    FileGatewaySessionStore,
    GatewayAccountRef,
    GatewayConversationRef,
    GatewayCoreDependencies,
    GatewayCoreService,
    GatewayIdentityKey,
    GatewayIdentityRecord,
    GatewayInboundMessage,
    GatewayRouteState,
    GatewaySenderRef,
    InMemoryGatewayIdentityStore,
    InMemoryGatewaySessionStore,
)
from packages.security.runtime import SecurityPolicy


class GatewayCoreSessionContinuityTest(unittest.TestCase):
    def _core(self) -> GatewayCoreService:
        self.identity_store = InMemoryGatewayIdentityStore()
        self.session_store = InMemoryGatewaySessionStore()
        return GatewayCoreService(
            GatewayCoreDependencies(
                identity_store=self.identity_store,
                session_store=self.session_store,
                security_policy=SecurityPolicy.default(),
                default_profile_id="you",
            )
        )

    def _inbound(self, conversation_id: str = "chat-1") -> GatewayInboundMessage:
        return GatewayInboundMessage(
            event_id="evt-1",
            account=GatewayAccountRef(adapter_id="messaging.weixin", account_id="wx-account"),
            conversation=GatewayConversationRef(conversation_id=conversation_id, chat_type="direct"),
            sender=GatewaySenderRef(external_user_id="wx-user"),
            body="hello",
        )

    def test_rebinding_existing_conversation_preserves_episode_pin(self) -> None:
        core = self._core()
        key = GatewayIdentityKey(
            adapter_id="messaging.weixin",
            account_id="wx-account",
            conversation_id="chat-1",
        )
        now = datetime(2026, 5, 7, tzinfo=timezone.utc)
        self.session_store.save(
            GatewayRouteState(
                session_id="episode:pinned",
                profile_id="you",
                status="active",
                started_at=now,
                updated_at=now,
            )
        )
        self.identity_store.save(
            GatewayIdentityRecord(
                mapping_id="mapping:wx",
                key=key,
                session_id="episode:pinned",
                state_id="state:zoey",
                elephant_id="zoey",
                episode_id="episode:pinned",
                created_at=now,
                updated_at=now,
            )
        )

        rebound = core.bind_elephant(self._inbound(), elephant_id="zoey", state_id="state:zoey")

        self.assertEqual(rebound.session_id, "episode:pinned")
        self.assertEqual(rebound.episode_id, "episode:pinned")
        routed = core.route_inbound(self._inbound())
        self.assertEqual(routed.identity.episode_id, "episode:pinned")
        self.assertEqual(routed.session.session_id, "episode:pinned")

    def test_file_identity_store_lookup_waits_for_inflight_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileGatewayIdentityStore(path=Path(tmpdir) / "gateway-identities.json")
            key = GatewayIdentityKey(
                adapter_id="messaging.weixin",
                account_id="wx-account",
                conversation_id="chat-1",
            )
            record = GatewayIdentityRecord(
                mapping_id="mapping:wx",
                key=key,
                session_id="session:wx-account:chat-1",
                state_id="state:zoey",
                elephant_id="zoey",
                episode_id="episode:pinned",
                created_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
            )
            started = threading.Event()
            release = threading.Event()
            errors: list[BaseException] = []
            lookup_result: list[GatewayIdentityRecord | None] = []
            original_write = FileGatewayIdentityStore._write_records
            first_write = True

            def slow_write(inner_store, records):
                nonlocal first_write
                if first_write:
                    first_write = False
                    inner_store.path.parent.mkdir(parents=True, exist_ok=True)
                    inner_store.path.write_text("[", encoding="utf-8")
                    started.set()
                    release.wait(timeout=2.0)
                original_write(inner_store, records)

            def writer() -> None:
                try:
                    store.save(record)
                except BaseException as exc:
                    errors.append(exc)

            def reader() -> None:
                try:
                    lookup_result.append(store.lookup(key))
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(FileGatewayIdentityStore, "_write_records", autospec=True, side_effect=slow_write):
                writer_thread = threading.Thread(target=writer)
                writer_thread.start()
                self.assertTrue(started.wait(timeout=1.0))

                reader_thread = threading.Thread(target=reader)
                reader_thread.start()
                time.sleep(0.05)
                self.assertFalse(errors)
                self.assertEqual(lookup_result, [])

                release.set()
                writer_thread.join(timeout=1.0)
                reader_thread.join(timeout=1.0)

            self.assertFalse(errors)
            self.assertEqual(len(lookup_result), 1)
            self.assertIsNotNone(lookup_result[0])
            self.assertEqual(lookup_result[0].mapping_id, "mapping:wx")

    def test_file_session_store_lookup_waits_for_inflight_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileGatewaySessionStore(path=Path(tmpdir) / "gateway-sessions.json")
            session = GatewayRouteState(
                session_id="session:wx-account:chat-1",
                profile_id="you",
                status="active",
                started_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
            )
            started = threading.Event()
            release = threading.Event()
            errors: list[BaseException] = []
            lookup_result: list[GatewayRouteState | None] = []
            original_write = FileGatewaySessionStore._write_records
            first_write = True

            def slow_write(inner_store, records):
                nonlocal first_write
                if first_write:
                    first_write = False
                    inner_store.path.parent.mkdir(parents=True, exist_ok=True)
                    inner_store.path.write_text("[", encoding="utf-8")
                    started.set()
                    release.wait(timeout=2.0)
                original_write(inner_store, records)

            def writer() -> None:
                try:
                    store.save(session)
                except BaseException as exc:
                    errors.append(exc)

            def reader() -> None:
                try:
                    lookup_result.append(store.lookup(session.session_id))
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(FileGatewaySessionStore, "_write_records", autospec=True, side_effect=slow_write):
                writer_thread = threading.Thread(target=writer)
                writer_thread.start()
                self.assertTrue(started.wait(timeout=1.0))

                reader_thread = threading.Thread(target=reader)
                reader_thread.start()
                time.sleep(0.05)
                self.assertFalse(errors)
                self.assertEqual(lookup_result, [])

                release.set()
                writer_thread.join(timeout=1.0)
                reader_thread.join(timeout=1.0)

            self.assertFalse(errors)
            self.assertEqual(len(lookup_result), 1)
            self.assertIsNotNone(lookup_result[0])
            self.assertEqual(lookup_result[0].session_id, session.session_id)


if __name__ == "__main__":
    unittest.main()
