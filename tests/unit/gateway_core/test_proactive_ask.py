"""Unit tests for delivery-agnostic proactive ask helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from packages.gateway_core import proactive_ask


class _FailingRepository:
    def load_state(self, state_id: str) -> object:
        raise RuntimeError(f"state unavailable: {state_id}")

    def load_personal_model_runtime_state(self, personal_model_id: str) -> object:
        raise RuntimeError(f"profile unavailable: {personal_model_id}")


def test_personal_model_id_logs_state_load_failure_and_falls_back_to_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session_store = SimpleNamespace(lookup=lambda _session_id: SimpleNamespace(profile_id="pm-1"))
    app = SimpleNamespace(
        repository=_FailingRepository(),
        core=SimpleNamespace(dependencies=SimpleNamespace(session_store=session_store)),
    )
    record = SimpleNamespace(state_id="state-1", session_id="session-1")

    with caplog.at_level(logging.DEBUG, logger="packages.gateway_core.proactive_ask"):
        personal_model_id = proactive_ask._personal_model_id(app, record)

    assert personal_model_id == "pm-1"
    assert "Failed to load state state-1" in caplog.text
    assert "state unavailable: state-1" in caplog.text


def test_profile_timezone_name_logs_profile_load_failure_and_uses_environment(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEPHANT_TIMEZONE", "UTC")

    with caplog.at_level(logging.DEBUG, logger="packages.gateway_core.proactive_ask"):
        timezone_name = proactive_ask._profile_timezone_name(_FailingRepository(), "pm-1")

    assert timezone_name == "UTC"
    assert "Failed to load personal model runtime state pm-1" in caplog.text
    assert "profile unavailable: pm-1" in caplog.text
