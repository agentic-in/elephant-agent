from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from apps.gateway.runtime_capabilities import GatewayContextCapability
from packages.runtime_layout import elephant_file_path
from packages.context import (
    SessionContextEpoch,
    next_session_context_epoch,
)
from packages.context.epoch_store import FileEpochStore, InMemoryEpochStore
from packages.contracts.layers import Episode
from packages.contracts.runtime import ContextBundle, EventEnvelope, ExecutionResult, PersonalModelRuntimeState, PromptMessage, PromptEnvelope
from packages.state import CompanionSettings, build_loaded_profile_from_state, render_user_profile_text
from packages.state import write_elephant_identity_file


class GatewayContextHistoryTest(unittest.TestCase):
    def _loaded_profile(self):
        return build_loaded_profile_from_state(
            PersonalModelRuntimeState(
                profile_id="you",
                display_name="Zoey",
                mode="companion",
            ),
            manifest={},
            companion=CompanionSettings(personality_preset="companion"),
            profile_dir="",
            manifest_path=None,
            elephant_identity_text="You are Zoey, a steady companion.",
            user_profile_text=render_user_profile_text(preferred_name="xunzhuo"),
        )

    def test_gateway_context_uses_shared_session_epoch_projection(self) -> None:
        session = Episode(
            episode_id="episode:wx",
            state_id="state:test",
            personal_model_id="you",
            entry_surface="test",
            elephant_id="zoey",
            status="open",
            started_at=datetime(2026, 5, 7, 3, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 7, 3, 2, tzinfo=timezone.utc),
        )
        epoch_store = InMemoryEpochStore()
        epoch_store.save(
            SessionContextEpoch(
                session_id=session.episode_id,
                frozen=True,
                frozen_prefix="FROZEN PREFIX",
                session_snapshot="SESSION SNAPSHOT",
                history_messages=(
                    PromptMessage(role="user", content="工作好忙"),
                    PromptMessage(role="assistant", content="你是想倒倒苦水说一下在忙什么，还是就想有人知道你今天很忙？"),
                ),
            ),
        )
        capability = GatewayContextCapability(
            self._loaded_profile(),
            epoch_store=epoch_store,
        )

        bundle = capability.assemble(session, (), ())

        envelope = bundle.prompt_envelope
        self.assertEqual(envelope.frozen_prefix, "FROZEN PREFIX")
        self.assertEqual(envelope.session_snapshot, "")
        self.assertEqual(tuple(message.role for message in envelope.messages), ("user", "assistant"))
        self.assertEqual(envelope.messages[0].content, "工作好忙")
        self.assertIn("倒倒苦水", envelope.messages[1].content)

    def test_gateway_context_reads_authored_elephant_file_before_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_root = Path(tmpdir)
            write_elephant_identity_file(
                elephant_file_path("zoey", install_root=install_root),
                "<!-- hidden metadata -->\n\nZoey is playful, precise, and alive.",
            )
            session = Episode(
                episode_id="episode:wx",
                state_id="state:zoey",
                personal_model_id="you",
                entry_surface="test",
                elephant_id="",
                status="open",
                started_at=datetime(2026, 5, 7, 3, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 7, 3, 2, tzinfo=timezone.utc),
            )
            capability = GatewayContextCapability(
                self._loaded_profile(),
                install_root=install_root,
            )

            bundle = capability.assemble(session, (), ())

        rendered = bundle.prompt_envelope.frozen_prefix
        self.assertIn("Zoey is playful, precise, and alive.", rendered)
        self.assertNotIn("You are Zoey, a steady companion.", rendered)
        self.assertNotIn("hidden metadata", rendered)

    def test_session_epoch_persists_with_epoch_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileEpochStore(Path(tmpdir))
            store.save(
                SessionContextEpoch(
                    session_id="episode:wx",
                    frozen=True,
                    frozen_prefix="FROZEN PREFIX",
                    history_messages=(PromptMessage(role="user", content="ping"),),
                ),
            )
            store.save(
                SessionContextEpoch(
                    session_id="episode:wx:preflight",
                    frozen=True,
                    history_messages=(PromptMessage(role="user", content="preflight"),),
                ),
            )
            epoch = store.load("episode:wx")
            preflight_epoch = store.load("episode:wx:preflight")

        self.assertIsNotNone(epoch)
        assert epoch is not None
        self.assertEqual(epoch.session_id, "episode:wx")
        self.assertEqual(epoch.frozen_prefix, "FROZEN PREFIX")
        self.assertIsNotNone(preflight_epoch)
        assert preflight_epoch is not None
        self.assertEqual(preflight_epoch.history_messages[0].content, "preflight")

    def test_im_idle_gap_resets_projection_tail_before_appending_new_burst(self) -> None:
        base = datetime(2026, 5, 7, 3, 0, tzinfo=timezone.utc)
        session = Episode(
            episode_id="episode:wx",
            state_id="state:test",
            personal_model_id="you",
            entry_surface="test",
            elephant_id="zoey",
            status="open",
            started_at=base,
            updated_at=base,
        )
        existing = SessionContextEpoch(
            session_id=session.episode_id,
            frozen=True,
            compacted_history_summary="old morning summary",
            history_messages=(
                PromptMessage(
                    role="user",
                    content="早上第一句",
                    metadata={"projection_surface": "im", "created_at": base.isoformat()},
                ),
            ),
        )
        evening = base + timedelta(hours=10)

        updated = next_session_context_epoch(
            existing,
            session=session,
            event=EventEnvelope(
                event_id="gateway:event-2",
                event_type="turn.received",
                episode_id=session.episode_id,
                source="gateway:feishu",
                payload={"content": "晚上新话题", "delivery_surface": "feishu-long-connection"},
            ),
            execution=ExecutionResult(
                execution_id="exec:2",
                episode_id=session.episode_id,
                outcome="completed",
                summary="晚上新回复",
            ),
            context=None,
            turn_messages=(
                PromptMessage(role="user", content="晚上新话题"),
                PromptMessage(role="assistant", content="晚上新回复"),
            ),
            now=evening,
        )

        self.assertEqual(updated.compacted_history_summary, "")
        self.assertEqual(tuple(message.content for message in updated.history_messages), ("晚上新话题", "晚上新回复"))
        self.assertEqual(updated.history_messages[0].metadata["projection_surface"], "im")

    def test_existing_session_epoch_does_not_refresh_frozen_prefix_on_normal_turn(self) -> None:
        """Frozen prefix only refreshes on episode open, not on normal turns."""
        session = Episode(
            episode_id="episode:wx",
            state_id="state:test",
            personal_model_id="you",
            entry_surface="test",
            elephant_id="zoey",
            status="open",
            started_at=datetime(2026, 5, 7, 3, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 7, 3, 2, tzinfo=timezone.utc),
        )
        existing = SessionContextEpoch(
            session_id=session.episode_id,
            frozen=True,
            frozen_prefix="old PM facts",
            session_snapshot="old snapshot",
            compacted_history_summary="older summary",
            history_messages=(PromptMessage(role="user", content="existing tail"),),
        )
        context = ContextBundle(
            bundle_id="bundle:test",
            episode_id=session.episode_id,
            rendered_prompt="",
            prompt_envelope=PromptEnvelope(
                frozen_prefix="new PM facts",
                session_snapshot="new snapshot",
                loop_context="new loop",
                messages=(),
            ),
        )

        updated = next_session_context_epoch(
            existing,
            session=session,
            event=None,
            execution=None,
            context=context,
            turn_messages=(),
        )

        # Frozen prefix does NOT refresh on normal turns (only on episode open)
        self.assertEqual(updated.frozen_prefix, "old PM facts")
        self.assertEqual(updated.compacted_history_summary, "older summary")
        self.assertEqual(tuple(message.content for message in updated.history_messages), ("existing tail",))

    def test_internal_proactive_prompt_is_not_appended_to_session_epoch(self) -> None:
        session = Episode(
            episode_id="episode:wx",
            state_id="state:test",
            personal_model_id="you",
            entry_surface="test",
            elephant_id="zoey",
            status="open",
            started_at=datetime(2026, 5, 7, 3, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 7, 3, 2, tzinfo=timezone.utc),
        )
        existing = SessionContextEpoch(
            session_id=session.episode_id,
            frozen=True,
            history_messages=(PromptMessage(role="user", content="工作好忙"),),
        )

        updated = next_session_context_epoch(
            existing,
            session=session,
            event=EventEnvelope(
                event_id="gateway-idle-proactive:test",
                event_type="turn.internal",
                episode_id=session.episode_id,
                source="gateway:messaging.weixin",
                payload={"content": "internal proactive prompt"},
            ),
            execution=ExecutionResult(
                execution_id="exec:1",
                episode_id=session.episode_id,
                outcome="completed",
                summary="想问你一个自然的问题",
            ),
            context=None,
            turn_messages=(
                PromptMessage(role="user", content="internal proactive prompt"),
                PromptMessage(role="assistant", content="想问你一个自然的问题"),
            ),
        )

        self.assertEqual(updated.history_messages, existing.history_messages)


if __name__ == "__main__":
    unittest.main()
