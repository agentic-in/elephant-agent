from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from packages.contracts import ElephantIdentityRecord
from packages.contracts.layers import State
from packages.state.loader import load_runtime_profile
from packages.state.persistence import _sync_elephant_identity, resolve_runtime_state


class StatePersistenceResolutionTests(unittest.TestCase):
    def test_resolve_runtime_state_uses_bounded_elephant_query(self) -> None:
        repository = _Repository(
            (
                _state("state:atlas", elephant_id="atlas", state_anchor="elephant:atlas"),
            )
        )

        resolved = resolve_runtime_state(
            repository,  # type: ignore[arg-type]
            personal_model_id="you",
            elephant_id="atlas",
            required=True,
        )

        self.assertEqual(resolved.state_id, "state:atlas")
        self.assertEqual(
            repository.list_state_calls,
            [{"personal_model_id": "you", "elephant_id": "atlas", "status": "active"}],
        )
        self.assertEqual(repository.current_state_calls, 0)

    def test_resolve_runtime_state_uses_bounded_anchor_query(self) -> None:
        repository = _Repository(
            (
                _state("state:atlas", elephant_id="atlas", state_anchor="elephant:atlas"),
            )
        )

        resolved = resolve_runtime_state(
            repository,  # type: ignore[arg-type]
            state_anchor="elephant:atlas",
        )

        self.assertEqual(resolved.state_id, "state:atlas")
        self.assertEqual(
            repository.list_state_calls,
            [{"state_anchor": "elephant:atlas", "status": "active"}],
        )

    def test_sync_elephant_identity_uses_bounded_elephant_query(self) -> None:
        repository = _Repository(
            (
                _state("state:atlas", elephant_id="atlas", state_anchor="elephant:atlas"),
            )
        )

        state_id = _sync_elephant_identity(
            repository,  # type: ignore[arg-type]
            ElephantIdentityRecord(
                elephant_id="atlas",
                profile_id="you",
                display_name="Atlas",
                identity_mode="companion",
                personality_preset="steady",
                initiative="proactive",
                relational_stance="clear",
                working_style_contract="direct",
                elephant_identity_text="Stay exact.",
            ),
            synced_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
        )

        self.assertEqual(state_id, "state:atlas")
        self.assertEqual(
            repository.list_state_calls,
            [{"personal_model_id": "you", "elephant_id": "atlas"}],
        )
        self.assertEqual(repository.upserted_states[0].elephant_name, "Atlas")

    def test_load_runtime_profile_logs_stub_persisted_state_failure(self) -> None:
        repository = _Repository(())

        with (
            patch(
                "packages.state.persistence.load_persisted_canonical_state",
                side_effect=RuntimeError("canonical state unavailable"),
            ),
            self.assertLogs("packages.state.loader", level="DEBUG") as logs,
        ):
            loaded = load_runtime_profile(repository, personal_model_id="you")  # type: ignore[arg-type]

        self.assertEqual(loaded.state.display_name, "Elephant Agent")
        self.assertIn(
            "Failed to load persisted canonical state for stub runtime profile",
            "\n".join(logs.output),
        )


class _Repository:
    def __init__(self, states: tuple[State, ...]) -> None:
        self.states = {state.state_id: state for state in states}
        self.list_state_calls: list[dict[str, object]] = []
        self.upserted_states: list[State] = []
        self.current_state_calls = 0

    def load_state(self, state_id: str) -> State | None:
        return self.states.get(state_id)

    def load_episode(self, episode_id: str) -> None:
        del episode_id
        return None

    def list_states(self, **kwargs: object) -> tuple[State, ...]:
        self.list_state_calls.append(dict(kwargs))
        states = tuple(self.states.values())
        for key, expected in kwargs.items():
            states = tuple(
                state
                for state in states
                if getattr(state, key) == expected
            )
        return states

    def current_state(self) -> None:
        self.current_state_calls += 1
        return None

    def upsert_state(self, state: State, *, updated_at: datetime | None = None) -> None:
        del updated_at
        self.upserted_states.append(state)
        self.states[state.state_id] = replace(state)


def _state(
    state_id: str,
    *,
    elephant_id: str,
    state_anchor: str,
) -> State:
    return State(
        state_id=state_id,
        personal_model_id="you",
        state_anchor=state_anchor,
        elephant_id=elephant_id,
        elephant_name=elephant_id.title(),
    )


if __name__ == "__main__":
    unittest.main()
