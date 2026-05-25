from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
import threading
import time
import unittest

from apps.gateway import (
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    FEISHU_ADAPTER_ID,
    FeishuGatewayService,
)
import apps.gateway.__main__ as gateway_main
from packages.contracts.layers import Episode
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterFeishuAsyncRuntimeE2ETests(GatewayAdapterTestBase):
    def test_feishu_async_long_connection_serializes_same_conversation(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        first_started = threading.Event()
        first_release = threading.Event()
        second_started = threading.Event()

        def track_shared_runtime(inbound, _session_id: str) -> None:
            prompt = inbound.body
            if prompt == "first message":
                first_started.set()
                first_release.wait(timeout=2.0)
            else:
                second_started.set()

        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            on_call=track_shared_runtime,
        )

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_serial_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[str] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
            async_worker_count=2,
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_serial",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        try:
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-serial-1",
                    message_id="om_serial_1",
                    chat_id="oc_serial",
                    text="first message",
                ),
                account_id="ops-feishu",
            )
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-serial-2",
                    message_id="om_serial_2",
                    chat_id="oc_serial",
                    text="second message",
                ),
                account_id="ops-feishu",
            )

            self.assertTrue(first_started.wait(timeout=1.0))
            time.sleep(0.15)
            self.assertFalse(second_started.is_set())
            first_release.set()
            self.assertTrue(second_started.wait(timeout=1.0))
            self._wait_until(
                lambda: len(shared_runtime_calls) == 2 and len(requests) == 5,
                message="expected serialized same-conversation jobs to finish with two placeholders and two replies",
            )
            self.assertEqual([call["prompt"] for call in shared_runtime_calls], ["first message", "second message"])
        finally:
            first_release.set()
            service.shutdown_async_processing()

    def test_feishu_async_long_connection_runs_different_conversations_in_parallel(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        first_started = threading.Event()
        second_started = threading.Event()
        release_runtime = threading.Event()

        def track_parallel_runtime(inbound, _session_id: str) -> None:
            if inbound.conversation_id == "oc_parallel_1":
                first_started.set()
            elif inbound.conversation_id == "oc_parallel_2":
                second_started.set()
            release_runtime.wait(timeout=2.0)

        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            on_call=track_parallel_runtime,
        )

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_parallel_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.ops_session = Episode(
                    episode_id="session-ops",
                    state_id="state:test",
                    personal_model_id="elephant:ops",
                    entry_surface="test",
                    elephant_id="ops",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[str] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(elephant_id="demo"),
                    SimpleNamespace(elephant_id="ops"),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_session
                if elephant_id == "ops":
                    return self.ops_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_session.episode_id:
                    return self.demo_session
                if session_id == self.ops_session.episode_id:
                    return self.ops_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
            async_worker_count=2,
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_parallel_1",
            elephant_id="demo",
            session_id="session-demo",
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_parallel_2",
            elephant_id="ops",
            session_id="session-ops",
        )

        try:
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-parallel-1",
                    message_id="om_parallel_1",
                    chat_id="oc_parallel_1",
                    text="parallel demo",
                ),
                account_id="ops-feishu",
            )
            service.accept_long_connection_event(
                self._feishu_message_event(
                    event_id="evt-parallel-2",
                    message_id="om_parallel_2",
                    chat_id="oc_parallel_2",
                    text="parallel ops",
                ),
                account_id="ops-feishu",
            )

            self._wait_until(
                lambda: first_started.is_set() and second_started.is_set(),
                timeout=30.0,
                message="expected both parallel conversations to enter the shared runtime before release",
            )
            release_runtime.set()
            self._wait_until(
                lambda: len(shared_runtime_calls) == 2 and len(requests) == 5,
                message="expected both conversations to run in parallel and complete",
            )
            self.assertCountEqual(
                [call["prompt"] for call in shared_runtime_calls],
                ["parallel demo", "parallel ops"],
            )
        finally:
            release_runtime.set()
            service.shutdown_async_processing()

    def test_feishu_async_long_connection_failure_marks_job_and_surfaces_doctor_status(self) -> None:
        app, _, _ = self._build()

        def fail_shared_runtime(_inbound, _session_id: str) -> None:
            raise RuntimeError("simulated async crash")

        self._install_shared_runtime_stub(app, on_call=fail_shared_runtime)
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_failure_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: FakeCliRuntime(),
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_failure_1",
            elephant_id="demo",
            session_id="session-demo",
        )

        try:
            with self.assertLogs("apps.gateway.feishu_impl", level="ERROR") as failure_logs:
                service.accept_long_connection_event(
                    self._feishu_message_event(
                        event_id="evt-failure-1",
                        message_id="om_failure_1",
                        chat_id="oc_failure_1",
                        text="please fail",
                    ),
                    account_id="ops-feishu",
                )

                self._wait_until(
                    lambda: len(tuple(service.describe().get("recent_failures") or ())) == 1,
                    message="expected async failure to be recorded",
                )
                self._wait_until(
                    lambda: len(requests) == 3,
                    message="expected placeholder and failure replies",
                )
            self.assertTrue(
                any(
                    record.getMessage()
                    == "Feishu async job failed for account=ops-feishu conversation=oc_failure_1 message=om_failure_1"
                    and record.exc_info is not None
                    for record in failure_logs.records
                ),
                "expected async failure to be logged with exception context",
            )
            description = service.describe()
            self.assertTrue(description["async_delivery_enabled"])
            self.assertEqual(description["queue_depth"], 0)
            self.assertEqual(description["running_jobs"], 0)
            self.assertEqual(len(tuple(description["recent_failures"])), 1)

            doctor_lines = gateway_main._doctor_lines(
                service,
                SimpleNamespace(
                    profile_dir=str(self.profile_dir),
                    state_dir=str(self.state_dir),
                    cli_profile_dir=str(self.profile_dir),
                    cli_state_dir=str(self.state_dir),
                ),
            )
            self.assertIn("async_delivery_enabled: yes", doctor_lines)
            self.assertIn("recent_failures: 1", doctor_lines)
        finally:
            service.shutdown_async_processing()

    def test_feishu_async_long_connection_recovers_incomplete_jobs_on_startup(self) -> None:
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": f"om_recovered_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[str] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        seeded_service = FeishuGatewayService(
            app=app,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        assert seeded_service.adapter is not None
        assert seeded_service.async_job_store is not None
        seeded_payload = self._feishu_message_event(
            event_id="evt-recovery-1",
            message_id="om_recovery_1",
            chat_id="oc_recovery_1",
            text="recover me",
        )
        seeded_inbound = seeded_service.adapter.normalize_event(
            seeded_payload,
            account_id="ops-feishu",
            transport="long-connection",
        )
        seeded_key, _, seeded_created = seeded_service.async_job_store.create_or_get(
            account_id=seeded_inbound.account_id,
            conversation_id=seeded_inbound.conversation_id,
            event_id="evt-recovery-1",
            message_id="om_recovery_1",
            payload=seeded_payload,
            transport="long-connection",
        )
        self.assertTrue(seeded_created)
        seeded_service.async_job_store.mark_running(seeded_key)

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_recovery_1",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        try:
            service._ensure_async_workers()
            self._wait_until(
                lambda: len(shared_runtime_calls) == 1 and len(requests) == 3,
                message="expected recovered async job to resume on startup",
            )
            recovered_record = service.async_job_store.get(seeded_key)
            assert recovered_record is not None
            self.assertEqual(recovered_record.status, "completed")
            self.assertEqual([call["prompt"] for call in shared_runtime_calls], ["recover me"])
        finally:
            service.shutdown_async_processing()


if __name__ == "__main__":
    unittest.main()
