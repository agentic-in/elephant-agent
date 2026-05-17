# ruff: noqa: E402

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.cli.runtime import CliRuntime, _CliContextCapability, _DurableRecallCapability
from apps.cli.runtime_snapshot import load_snapshot_session_context_epoch, restore_snapshot_state_focus
from packages.contracts import (
    ContextBundle,
    Episode,
    EventEnvelope,
    ExecutionResult,
    Fact,
    Loop,
    PersonalModelGrowthState,
    PromptEnvelope,
    PromptMessage,
    Step,
)
from packages.contracts.runtime import (
    EmbeddingIndexPolicy,
    EvidenceRetrievalRequest,
    EvidenceRetrievalResult,
    LoopState,
    RecallEvidence,
    RecallReasons,
    StateFocusDecision,
)
from packages.state import render_user_profile_text
from packages.state.loader import write_profile_manifest
from packages.state.persistence import load_persisted_canonical_state
from packages.skills import (
    FetchedSkillBundle,
    SkillSearchEntry,
    builtin_site_skill_catalog_entries,
    operator_prompt_skill_catalog_entries,
)


class CliRuntimeCognitionTest(unittest.TestCase):
    def test_runtime_paths_are_stable_system_prefix_not_turn_attachments(self) -> None:
        class _EmptyRepository:
            def list_states(self, *, status: str) -> tuple[object, ...]:
                del status
                return ()

            def current_state(self) -> None:
                return None

            def load_latest_open_loop_checkpoint(self, episode_id: str) -> None:
                del episode_id
                return None

        startup_cwd = Path("/tmp/elephant-start")
        workspaces_dir = Path("/tmp/elephant-workspaces")
        session = Episode(
            episode_id="episode-1",
            state_id="state-1",
            personal_model_id="profile-1",
            entry_surface="cli",
            status="open",
            started_at=datetime.now(timezone.utc),
            elephant_id="miles",
        )
        capability = _CliContextCapability(
            profile_loader=object(),  # type: ignore[arg-type]
            repository=_EmptyRepository(),  # type: ignore[arg-type]
            workspaces_dir=workspaces_dir,
            startup_cwd=startup_cwd,
        )

        stable_lines = capability._capability_stable_prefix_lines(session=session, loaded=object())  # type: ignore[arg-type]
        artifacts = capability._capability_artifacts(session, object(), work_items=(), recall_items=())  # type: ignore[arg-type]
        system_prompt = PromptEnvelope(frozen_prefix="\n".join(stable_lines)).system_prompt()

        self.assertIn("### Runtime paths", system_prompt)
        self.assertIn(f"startup_cwd={startup_cwd.resolve()}", system_prompt)
        self.assertIn(f"elephant_workspace={(workspaces_dir / 'miles').resolve()}", system_prompt)
        self.assertNotIn("runtime-paths:", "\n".join(artifacts))

    def _runtime(
        self,
        *,
        profile_payload: dict[str, object] | None = None,
        seed_charter: bool = True,
    ) -> CliRuntime:
        """Build a CliRuntime with identity seeded into the DB.

        ``profile_payload`` is a dict that mirrors the legacy ``profile.json``
        shape. Identity flows through the DB now — not from a filesystem
        manifest — so we translate the payload into the equivalent runtime
        calls (``update_identity``, ``update_companion_settings``,
        ``update_identity_state``).
        """
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        state_dir = root / "state"
        payload = profile_payload or {
            "profile_id": "profile-companion",
            "display_name": "Elephant Agent",
            "mode": "companion",
        }
        runtime = CliRuntime.create(state_dir=state_dir)
        profile_id = str(payload["profile_id"])
        display_name = payload.get("display_name")
        mode = payload.get("mode")
        if display_name or mode:
            runtime.update_identity(
                profile_id=profile_id,
                display_name=str(display_name) if display_name else None,
                mode=str(mode) if mode else None,
            )
        companion_payload = payload.get("companion")
        if isinstance(companion_payload, dict):
            runtime.update_companion_settings(
                profile_id=profile_id,
                personality_preset=str(companion_payload.get("personality_preset") or "") or None,
                initiative=str(companion_payload.get("initiative") or "") or None,
                notes=tuple(companion_payload.get("notes") or ()) or None,
            )
        if seed_charter:
            runtime.update_identity_state(
                profile_id=profile_id,
                elephant_identity_text="Stay durable and grounded.",
            )
        return runtime

    def test_cli_context_capability_recovers_recent_loop_context_from_snapshot(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        runtime.snapshot_path.write_text(
            json.dumps(
                {
                    "session": {"session_id": session.episode_id},
                    "event": {"payload": {"message": "continue the launch plan"}},
                    "execution": {"summary": "I will recover the active launch work."},
                }
            ),
            encoding="utf-8",
        )

        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
        )
        bundle = capability.assemble(session, (), ())

        self.assertNotIn("## Recent turn context", bundle.rendered_prompt)
        self.assertNotIn("## What's in play right now", bundle.rendered_prompt)
        self.assertNotIn("continue the launch plan", bundle.rendered_prompt)
        self.assertNotIn("recover the active launch work", bundle.rendered_prompt)

    def test_open_next_episode_indexes_closed_episode_summary(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        indexed: list[Episode] = []

        class _Indexer:
            def index_episode_exit(self, episode: Episode) -> None:
                indexed.append(episode)

        object.__setattr__(runtime, "_semantic_summary_indexer", _Indexer())

        next_episode = runtime.open_next_episode(
            session.episode_id,
            reason="shell_clear",
            summary="/clear requested a fresh Episode",
        ).episode

        self.assertEqual(next_episode.parent_episode_id, session.episode_id)
        self.assertEqual(len(indexed), 1)
        self.assertEqual(indexed[0].episode_id, session.episode_id)
        self.assertEqual(indexed[0].status, "closed")
        self.assertEqual(indexed[0].exit_summary, "/clear requested a fresh Episode")

    def test_cli_context_capability_ignores_internal_startup_loops_in_recent_loop_context(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        runtime.snapshot_path.write_text(
            json.dumps(
                {
                    "session": {"session_id": session.episode_id},
                    "event": {
                        "event_type": "turn.internal",
                        "source": "cli.startup",
                        "payload": {"message": "startup opening"},
                    },
                    "execution": {"summary": "steady welcome"},
                }
            ),
            encoding="utf-8",
        )

        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
        )
        bundle = capability.assemble(session, (), ())

        self.assertNotIn("startup opening", bundle.rendered_prompt)
        self.assertNotIn("steady welcome", bundle.rendered_prompt)

    def test_cli_context_does_not_duplicate_active_personal_model_behavior_contract(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
        )

        bundle = capability.assemble(session, (), ())

        self.assertNotIn("personal-model-behavior-contract", bundle.rendered_prompt)
        self.assertNotIn("### Behaviors this person has asked you to keep", bundle.rendered_prompt)

    def test_open_next_episode_keeps_parent_link(self) -> None:
        runtime = self._runtime()
        parent = runtime.start()

        resumed = runtime.open_next_episode(parent.episode_id).episode

        self.assertEqual(resumed.parent_episode_id, parent.episode_id)

    def test_multiple_next_episodes_keep_lineage(self) -> None:
        runtime = self._runtime()
        parent = runtime.start()

        first_child = runtime.open_next_episode(parent.episode_id).episode
        second_child = runtime.open_next_episode(parent.episode_id).episode

        self.assertEqual(first_child.parent_episode_id, parent.episode_id)
        self.assertEqual(second_child.parent_episode_id, parent.episode_id)
        self.assertNotEqual(first_child.episode_id, second_child.episode_id)

    def test_frozen_session_context_epoch_reuses_stable_sections_without_turn_bodies(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        profile = runtime._load_profile(session.personal_model_id)
        initial_epoch = load_snapshot_session_context_epoch(runtime, session_id=session.episode_id)
        self.assertIsNotNone(initial_epoch)
        assert initial_epoch is not None
        self.assertTrue(initial_epoch.frozen)
        initial_prefix = initial_epoch.frozen_prefix

        first_context = ContextBundle(
            bundle_id="bundle:first",
            episode_id=session.episode_id,
            prompt_envelope=PromptEnvelope(
                frozen_prefix="FIRST PREFIX",
                session_snapshot="FIRST SNAPSHOT",
                loop_context="FIRST INJECTIONS",
            ),
        )
        runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.episode_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.episode_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=first_context,
        )
        runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:second",
                episode_id=session.episode_id,
                outcome="ok",
                summary="second reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:second",
                event_type="turn.received",
                episode_id=session.episode_id,
                source="cli",
                payload={"message": "second ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:second",
                episode_id=session.episode_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="SECOND PREFIX",
                    session_snapshot="SECOND SNAPSHOT",
                    loop_context="SECOND INJECTIONS",
                ),
            ),
        )

        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
        )
        bundle = capability.assemble(session, (), ())

        self.assertEqual(bundle.prompt_envelope.frozen_prefix, initial_prefix)
        self.assertIn("### Who you are", bundle.prompt_envelope.frozen_prefix)
        self.assertEqual(bundle.prompt_envelope.session_snapshot, "")
        self.assertNotIn("FIRST INJECTIONS", bundle.prompt_envelope.loop_context)
        self.assertEqual(
            tuple((message.role, message.content) for message in bundle.prompt_envelope.messages),
            (
                ("user", "first ask"),
                ("assistant", "first reply"),
                ("user", "second ask"),
                ("assistant", "second reply"),
            ),
        )
        self.assertNotIn("FIRST PREFIX", bundle.prompt_envelope.combined_prompt())
        self.assertNotIn("SECOND PREFIX", bundle.prompt_envelope.combined_prompt())
        self.assertNotIn("SECOND INJECTIONS", bundle.prompt_envelope.loop_context)
        frozen_epoch = load_snapshot_session_context_epoch(runtime, session_id=session.episode_id)
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertTrue(frozen_epoch.frozen)
        self.assertEqual(frozen_epoch.base_loop_context, "")
        self.assertEqual(frozen_epoch.thread_focus, "No durable elephant focus is available yet.")
        self.assertEqual(frozen_epoch.frozen_skill_ids, ())
        self.assertEqual(len(frozen_epoch.frozen_skill_index), frozen_epoch.frozen_skill_count)
        self.assertTrue(len(frozen_epoch.frozen_tool_ids) > 0)
        self.assertEqual(
            frozen_epoch.frozen_tool_count,
            len(runtime.tool_runtime.list_tools(audience="model", enabled_only=True, available_only=True)),
        )
        self.assertEqual(
            frozen_epoch.frozen_skill_count,
            0,
        )
        self.assertEqual(
            frozen_epoch.frozen_skill_ids,
            (),
        )
        self.assertNotIn("ascii-art", frozen_epoch.frozen_skill_ids)
        self.assertNotIn("docker-management", frozen_epoch.frozen_skill_ids)
        self.assertEqual(frozen_epoch.frozen_skill_index, ())
        self.assertEqual(frozen_epoch.frozen_skill_disclosures, ())
        self.assertEqual(frozen_epoch.latest_skill_disclosures, ())

    def test_frozen_base_loop_context_restores_refs_only(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        profile = runtime._load_profile(session.personal_model_id)

        runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.episode_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.episode_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:first",
                episode_id=session.episode_id,
                prompt_envelope=PromptEnvelope(frozen_prefix="FIRST PREFIX"),
            ),
        )
        snapshot = json.loads(runtime.snapshot_path.read_text(encoding="utf-8"))
        snapshot["session_context_epoch"]["base_loop_context"] = "\n".join(
            (
                "## LoopContext",
                "- do not keep this body",
                "- source_ref: turn:1",
                "refs: artifact:1",
            )
        )
        runtime.snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")

        frozen_epoch = load_snapshot_session_context_epoch(runtime, session_id=session.episode_id)

        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertEqual(frozen_epoch.base_loop_context, "- source_ref: turn:1")
        self.assertNotIn("do not keep this body", frozen_epoch.base_loop_context)

    def test_frozen_skill_index_honors_profile_skill_disable_overrides(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        profile = runtime._load_profile(session.personal_model_id)
        runtime.set_skill_enabled("ascii-art", False, session_id=session.episode_id)

        runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.episode_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.episode_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:first",
                episode_id=session.episode_id,
                prompt_envelope=PromptEnvelope(frozen_prefix="FIRST PREFIX"),
            ),
        )

        frozen_epoch = load_snapshot_session_context_epoch(runtime, session_id=session.episode_id)
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertNotIn("ascii-art", frozen_epoch.frozen_skill_ids)
        self.assertEqual(frozen_epoch.frozen_skill_ids, ())

    def test_frozen_session_history_compacts_explicitly_without_rewriting_epoch_truth(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        profile = runtime._load_profile(session.personal_model_id)
        runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.episode_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.episode_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:first",
                episode_id=session.episode_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="FIRST PREFIX",
                    session_snapshot="FIRST SNAPSHOT",
                    loop_context="FIRST INJECTIONS",
                ),
            ),
        )
        long_history = tuple(
            PromptMessage(
                role="user" if index % 2 == 0 else "assistant",
                content=(
                    f"topic marker {index} asking about projection compaction and durable evidence "
                    f"with enough detail to consume prompt budget"
                    if index % 2 == 0
                    else f"topic marker {index} response covering implementation, validation, and follow-up state"
                ),
            )
            for index in range(44)
        )
        snapshot = json.loads(runtime.snapshot_path.read_text(encoding="utf-8"))
        snapshot["session_context_epoch"]["history_messages"] = [
            {"role": message.role, "content": message.content}
            for message in long_history
        ]
        runtime.snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")

        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            total_tokens=1024,
        )
        result = capability.compact_session_projection(session_id=session.episode_id, reason="manual")
        bundle = capability.assemble(session, (), ())

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.compacted)
        rendered_messages = "\n".join(message.content for message in bundle.prompt_envelope.messages)
        self.assertNotIn("CONTEXT COMPACTION - REFERENCE ONLY", rendered_messages)
        self.assertIn("topic marker 42", rendered_messages)
        frozen_epoch = load_snapshot_session_context_epoch(runtime, session_id=session.episode_id)
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertEqual(frozen_epoch.compaction_count, 1)
        self.assertEqual(frozen_epoch.compacted_history_count, 32)
        self.assertEqual(frozen_epoch.history_messages[:2], long_history[:2])
        self.assertEqual(frozen_epoch.history_messages[-10:], long_history[-10:])
        self.assertIn("## Handoff notes for recent tail", frozen_epoch.compacted_history_summary)
        self.assertGreater(frozen_epoch.context_projection_tokens, 0)
        self.assertEqual(frozen_epoch.context_projection_limit, 1024)
        payload = json.loads(runtime.snapshot_path.read_text(encoding="utf-8"))
        self.assertNotIn("history_lines", payload["session_context_epoch"])

    def test_compact_session_context_wires_projection_embedding_service(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        embedding_service = object()
        runtime.recall_runtime.retriever.evidence_retriever.embedding_service = embedding_service
        captured: dict[str, object] = {}

        class RecordingContextCapability:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            def compact_session_projection(self, **kwargs: object) -> str:
                captured["compact_kwargs"] = kwargs
                return "compacted"

        with mock.patch("apps.cli.runtime_impl._CliContextCapability", RecordingContextCapability):
            result = runtime.compact_session_context(session.episode_id, reason="usage", force=True)

        self.assertEqual(result, "compacted")
        self.assertIs(captured["embedding_service"], embedding_service)
        self.assertEqual(captured["compact_kwargs"], {"session_id": session.episode_id, "reason": "usage", "force": True})

    def test_projection_relevance_scorer_was_removed_from_context_public_contract(self) -> None:
        runtime = self._runtime()
        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            embedding_service=object(),
        )

        self.assertFalse(hasattr(capability, "_projection_relevance_scorer"))

    def test_snapshot_history_messages_use_actual_turn_transcript_without_legacy_lines(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        profile = runtime._load_profile(session.personal_model_id)
        turn_messages = (
            PromptMessage(role="user", content="search docs"),
            PromptMessage(
                role="assistant",
                content="",
                tool_calls=(
                    {
                        "id": "call-real-1",
                        "name": "tool.web.search",
                        "arguments": {"query": "elephant"},
                    },
                ),
            ),
            PromptMessage(
                role="tool",
                content="tool: tool.web.search\narguments: query=elephant\noutcome: ok\nsummary: search result",
                tool_call_id="call-real-1",
                tool_name="tool.web.search",
            ),
            PromptMessage(role="assistant", content="final answer"),
        )

        runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:tool-trace",
                episode_id=session.episode_id,
                outcome="ok",
                summary="final answer",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:tool-trace",
                event_type="turn.received",
                episode_id=session.episode_id,
                source="cli",
                payload={"message": "search docs"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:tool-trace",
                episode_id=session.episode_id,
                prompt_envelope=PromptEnvelope(frozen_prefix="PREFIX", session_snapshot="SNAPSHOT"),
            ),
            turn_messages=turn_messages,
        )

        payload = json.loads(runtime.snapshot_path.read_text(encoding="utf-8"))
        epoch_payload = payload["session_context_epoch"]
        self.assertNotIn("history_lines", epoch_payload)
        roles = [message["role"] for message in epoch_payload["history_messages"]]
        self.assertEqual(roles, ["user", "assistant", "tool", "assistant"])
        self.assertEqual(epoch_payload["history_messages"][1]["tool_calls"][0]["name"], "tool.web.search")
        self.assertEqual(epoch_payload["history_messages"][2]["tool_name"], "tool.web.search")
        self.assertEqual(epoch_payload["history_messages"][2]["tool_call_id"], "call-real-1")
        self.assertIn("summary: search result", epoch_payload["history_messages"][2]["content"])

    def test_high_usage_turn_compacts_snapshot_after_current_transcript_is_appended(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        observed_events: list[dict[str, object]] = []
        runtime.set_kernel_event_observer(observed_events.append)
        huge_prompt = "oversized completed request " + ("payload " * 5000)
        captured_compress_metadata: dict[str, str] = {}

        def generate_response(*, profile, session, context, prompt, model_role="strong"):
            if "Create a compact structured handoff summary" in prompt:
                return ExecutionResult(
                    execution_id=f"exec:{session.episode_id}:summary",
                    episode_id=session.episode_id,
                    outcome="ok",
                    summary="[CONTEXT COMPACTION - REFERENCE ONLY]\nActive State Focus: oversized request completed.",
                    prompt_tokens=240,
                    completion_tokens=24,
                    total_tokens=264,
                )
            return ExecutionResult(
                execution_id=f"exec:{session.episode_id}:answer",
                episode_id=session.episode_id,
                outcome="ok",
                summary="completed answer",
                prompt_tokens=900,
                completion_tokens=20,
                total_tokens=920,
            )

        def run_reflect_agent(_runtime, job, *, explicit_features, persist_result):
            self.assertEqual(explicit_features, ("compress",))
            self.assertFalse(persist_result)
            captured_compress_metadata.update(dict(job.metadata))
            return mock.Mock(summary="oversized completed request was handled; continue from the completed answer.")

        with (
            mock.patch.object(type(runtime), "active_provider_context_window", return_value=1024),
            mock.patch.object(type(runtime.model_provider), "generate", side_effect=generate_response),
            mock.patch("apps.reflect.runner.run_reflect_agent", side_effect=run_reflect_agent),
        ):
            outcome = runtime.explain_next_step(
                session_id=session.episode_id,
                prompt=huge_prompt,
            )

        compact_stages = [stage for stage in outcome.stages if stage.stage == "context-compact"]
        self.assertEqual(len(compact_stages), 1)
        self.assertIn("reason=usage", compact_stages[0].detail)
        self.assertTrue(observed_events)
        frozen_epoch = load_snapshot_session_context_epoch(runtime, session_id=session.episode_id)
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertEqual(frozen_epoch.compaction_count, 1)
        self.assertIn("Reference summary:", frozen_epoch.frozen_prefix)
        self.assertIn("oversized completed request", frozen_epoch.compacted_history_summary)
        self.assertIn("oversized completed request", captured_compress_metadata["compressed_messages"])
        history = tuple(message.content for message in frozen_epoch.history_messages)
        self.assertIn("completed answer", history)
        self.assertNotIn(huge_prompt, history)

    def test_frozen_session_context_epoch_tracks_latest_skill_disclosure_reason(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        profile = runtime._load_profile(session.personal_model_id)

        runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:skill-disclosure",
                episode_id=session.episode_id,
                outcome="ok",
                summary="used the selected skill",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:skill-disclosure",
                event_type="turn.received",
                episode_id=session.episode_id,
                source="cli",
                payload={"message": "Use the ASCII art skill."},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=StateFocusDecision(
                focus_family="execution",
                confidence=0.92,
            ),
            context=ContextBundle(
                bundle_id="bundle:skill-disclosure",
                episode_id=session.episode_id,
                artifact_ids=("skill:ascii-art",),
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="FIRST PREFIX",
                    session_snapshot="FIRST SNAPSHOT",
                    loop_context="Selected skill: ASCII Art (ascii-art)",
                ),
            ),
        )

        frozen_epoch = load_snapshot_session_context_epoch(runtime, session_id=session.episode_id)
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertEqual(frozen_epoch.frozen_skill_disclosures, ())
        self.assertEqual(len(frozen_epoch.latest_skill_disclosures), 1)
        self.assertEqual(frozen_epoch.latest_skill_disclosures[0].skill_id, "ascii-art")
        self.assertIn(
            "explicit skill overlay",
            frozen_epoch.latest_skill_disclosures[0].reason,
        )

    def test_snapshot_state_focus_restore_rejects_legacy_skill_candidate_scores(self) -> None:
        snapshot = {
            "state_focus": {
                "state_focus": "execution",
                "confidence": 0.9,
                "candidate_scores": (
                    {
                        "candidate_id": "ascii-art",
                        "kind": "skill",
                        "label": "ASCII Art",
                        "total_score": 0.88,
                    },
                ),
            }
        }

        with self.assertRaises(ValueError):
            restore_snapshot_state_focus(snapshot)

    def test_durable_recall_capability_prefers_work_item_aware_continuity_retrieval(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        runtime.repository.upsert_loop(
            Loop(
                loop_id="loop:test",
                episode_id=session.episode_id,
                state_id=session.state_id,
                personal_model_id=session.personal_model_id,
                trigger_type="test",
                status="completed",
                started_at=datetime.now(timezone.utc),
            )
        )
        runtime.repository.upsert_step(
            Step(
                step_id="evidence-work",
                loop_id="loop:test",
                episode_id=session.episode_id,
                state_id=session.state_id,
                personal_model_id=session.personal_model_id,
                phase="acting",
                action="procedural",
                status="completed",
                sequence=1,
                summary="The next step is to continue by publishing the release artifacts.",
                metadata={"work_item_ids": "state-release"},
                created_at=datetime.now(timezone.utc),
            )
        )
        runtime.repository.upsert_step(
            Step(
                step_id="evidence-noise",
                loop_id="loop:test",
                episode_id=session.episode_id,
                state_id=session.state_id,
                personal_model_id=session.personal_model_id,
                phase="acting",
                action="episodic",
                status="completed",
                sequence=2,
                summary="We mentioned the next step casually in another note.",
                created_at=datetime.now(timezone.utc),
            )
        )

        capability = _DurableRecallCapability(recall_runtime=runtime.recall_runtime, repository=runtime.repository)
        retrieval = capability.retrieve_evidence(
            EvidenceRetrievalRequest(
                episode_id=session.episode_id,
                personal_model_id=session.personal_model_id,
                elephant_id=session.elephant_id,
                lineage_episode_ids=(session.episode_id,),
                query="next step",
                scopes=("episode",),
                limit=5,
                allow_embeddings=False,
            )
        )
        results = tuple(candidate.evidence for candidate in retrieval.candidates)

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].evidence_id, "step:evidence-work")

    def test_inspect_continuity_surfaces_reengagement_guidance(self) -> None:
        runtime = self._runtime(
            profile_payload={
                "profile_id": "profile-companion",
                "display_name": "Elephant Agent",
                "mode": "companion",
                "companion": {
                    "initiative": "proactive",
                    "notes": ["check in after quiet gaps"],
                },
            }
        )
        session = runtime.start()
        state = runtime.ensure_elephant_state(session)
        runtime.repository.upsert_state(
            replace(
                state,
                current_context_note="Publish the release artifacts.",
            )
        )

        continuity = runtime.inspect_continuity(session_id=session.episode_id)

        self.assertEqual(continuity.reengagement_style, "gentle-presence")
        self.assertIn("preserve the active elephant", continuity.reengagement_prompt)
        self.assertNotIn("Publish the release artifacts.", continuity.reengagement_prompt)
        self.assertIn("initiative=gentle", continuity.continuity_summary)

    def test_planning_recall_evidence_recovery_falls_back_to_episode_scoped_steps(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        runtime.repository.upsert_loop(
            Loop(
                loop_id="loop:test",
                episode_id=session.episode_id,
                state_id=session.state_id,
                personal_model_id=session.personal_model_id,
                trigger_type="test",
                status="completed",
                started_at=datetime.now(timezone.utc),
            )
        )
        runtime.repository.upsert_step(
            Step(
                step_id="evidence-fallback",
                loop_id="loop:test",
                episode_id=session.episode_id,
                state_id=session.state_id,
                personal_model_id=session.personal_model_id,
                phase="acting",
                action="procedural",
                status="completed",
                sequence=1,
                summary="Resume by reopening the release checklist.",
                created_at=datetime.now(timezone.utc),
            )
        )
        empty_request = EvidenceRetrievalRequest(
            episode_id=session.episode_id,
            personal_model_id=session.personal_model_id,
            elephant_id=session.elephant_id,
            lineage_episode_ids=(session.episode_id,),
            query="resume continuity next step",
            scopes=("episode",),
            latency_mode="fast",
            limit=8,
        )
        empty_retrieval = EvidenceRetrievalResult(
            request=empty_request,
            scope_episode_ids=(session.episode_id,),
            scope_reason="fallback coverage",
            candidates=(),
            recall_reasons=RecallReasons(scope_reason="fallback coverage"),
            index_policy=EmbeddingIndexPolicy(
                model_id="test",
                lexical_index_version="test",
                embedding_index_version="test",
            ),
        )

        with mock.patch.object(runtime.recall_runtime, "retrieve_evidence", return_value=empty_retrieval):
            recovery = runtime._planning_recall_evidence_recovery(session)

        self.assertEqual(tuple(evidence.evidence_id for evidence in recovery.recall_items), ("step:evidence-fallback",))
        self.assertEqual(recovery.scope_episode_ids, (session.episode_id,))

    def test_prepare_session_surface_kicks_off_embedding_steadyup(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        embedding_service = runtime.recall_runtime.retriever.evidence_retriever.embedding_service

        with mock.patch.object(embedding_service, "steady_async", return_value=True) as steady_async:
            runtime.prepare_session_surface(session.episode_id)

        steady_async.assert_called_once_with()

    def test_skill_catalog_does_not_kick_off_embedding_steadyup_for_passive_ui_reads(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        embedding_service = runtime.recall_runtime.retriever.evidence_retriever.embedding_service

        with mock.patch.object(embedding_service, "steady_async", return_value=True) as steady_async:
            runtime.skill_catalog(session_id=session.episode_id)

        steady_async.assert_not_called()

    def test_cli_context_capability_surfaces_enabled_tools_and_scoped_skills(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        now = datetime.now(timezone.utc)
        for skill_id in ("apple-notes", "gif-search", "huggingface-hub", "imessage"):
            index_id = skill_id.replace("-", "_")
            runtime.repository.upsert_personal_model_fact(
                Fact(
                    fact_id=f"fact:skill:{index_id}",
                    personal_model_id=session.personal_model_id,
                    lens="world",
                    text=f"Skill affinity: {skill_id}",
                    confidence=0.9,
                    committed_at=now,
                    source="pm_agent_promote",
                    status="active",
                    metadata={
                        "topic": f"world.skills.affinity.{index_id}",
                        "skill_id": skill_id,
                        "index_id": index_id,
                        "projection_policy": "include",
                    },
                )
            )

        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            tool_runtime=runtime.tool_runtime,
            skill_runtime=runtime.skill_runtime,
            install_root=runtime.paths.home_dir,
        )
        bundle = capability.assemble(session, (), ())

        self.assertNotIn("available-tools:", bundle.rendered_prompt)
        self.assertNotIn("Message Send", bundle.rendered_prompt)
        self.assertNotIn("active-skills:", bundle.rendered_prompt)
        self.assertNotIn("- ### Capability Disclosure", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn("skill-routing:", bundle.prompt_envelope.frozen_prefix)
        self.assertIn("Skill index (", bundle.rendered_prompt)
        self.assertIn("episode-frozen entries", bundle.rendered_prompt)
        self.assertNotIn("shown=24", bundle.rendered_prompt)
        self.assertNotIn("hidden=", bundle.rendered_prompt)
        self.assertNotIn(str(runtime.paths.installed_skills_dir), bundle.rendered_prompt)
        self.assertNotIn(str(runtime.paths.authored_skills_dir), bundle.rendered_prompt)
        self.assertIn("- apple -", bundle.rendered_prompt)
        self.assertIn("Apple Notes", bundle.rendered_prompt)
        self.assertIn("GIF Search", bundle.rendered_prompt)
        self.assertIn("Hugging Face Hub", bundle.rendered_prompt)
        self.assertIn("iMessage", bundle.rendered_prompt)
        self.assertNotIn("Complete guide to what Elephant Agent is", bundle.rendered_prompt)
        self.assertNotIn("skill-routing:", bundle.rendered_prompt)

    def test_recently_surfaced_notes_skip_profile_snapshot_fragments(self) -> None:
        from apps.cli.runtime_cognition import _recall_summary_artifact

        now = datetime.now(timezone.utc)
        summary = _recall_summary_artifact(
            (
                RecallEvidence(
                    evidence_id="evidence-profile",
                    episode_id="episode-1",
                    kind="semantic",
                    content="Preferred name: xunzhuo Current work: 正站在一个岔路口 Current city: 成都 MBTI: INFJ",
                    created_at=now,
                ),
                RecallEvidence(
                    evidence_id="evidence-name",
                    episode_id="episode-1",
                    kind="semantic",
                    content="Preferred name: xunzhuo",
                    created_at=now,
                ),
                RecallEvidence(
                    evidence_id="evidence-real",
                    episode_id="episode-1",
                    kind="semantic",
                    content="Prefers direct updates over filler.",
                    created_at=now,
                ),
            )
        )

        self.assertIn("Recently surfaced notes: Prefers direct updates over filler.", summary)
        self.assertNotIn("Preferred name", summary)
        self.assertNotIn("Current work", summary)

    def test_cli_context_injects_default_workspace_path(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="miles")

        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            install_root=runtime.paths.home_dir,
            workspaces_dir=runtime.paths.workspaces_dir,
        )
        bundle = capability.assemble(session, (), ())

        self.assertIn("runtime-paths:", bundle.rendered_prompt)
        self.assertIn("### Runtime paths", bundle.prompt_envelope.system_prompt())
        self.assertNotIn("runtime-paths:", bundle.prompt_envelope.user_prelude())
        self.assertIn(f"elephant_workspace={runtime.paths.elephant_file_path('miles').resolve()}", bundle.rendered_prompt)
        self.assertIn(f"elephant_workspace={runtime.paths.elephant_file_path('miles').resolve()}", bundle.prompt_envelope.system_prompt())

    def test_cli_context_only_lists_launch_directory_rule_files_for_on_demand_reading(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="miles")

        with tempfile.TemporaryDirectory() as tempdir:
            startup_dir = Path(tempdir)
            (startup_dir / ".elephant.md").write_text(
                "Use launch-directory docs before generic fallbacks.\n",
                encoding="utf-8",
            )
            (startup_dir / "AGENTS.md").write_text(
                "Always treat the current repo as the primary analysis target.\n",
                encoding="utf-8",
            )
            capability = _CliContextCapability(
                profile_loader=runtime.profile_loader,
                repository=runtime.repository,
                prompt_mode="full",
                snapshot_path=runtime.snapshot_path,
                install_root=runtime.paths.home_dir,
                workspaces_dir=runtime.paths.workspaces_dir,
                startup_cwd=startup_dir,
            )
            bundle = capability.assemble(session, (), ())

        self.assertNotIn("### Launch Directory Context", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn(f"Current absolute path: `{startup_dir.resolve()}`", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn("Launch-directory rule files are available for on-demand reading:", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn(f"- `{startup_dir / 'AGENTS.md'}`", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn(".elephant.md", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn("Loaded launch-directory project context files:", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn("Always treat the current repo as the primary analysis target.", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn("Use launch-directory docs before generic fallbacks.", bundle.prompt_envelope.frozen_prefix)
        self.assertIn(f"startup_cwd={startup_dir.resolve()}", bundle.rendered_prompt)
        self.assertNotIn(f"startup_cwd={startup_dir.resolve()}", bundle.prompt_envelope.system_prompt())
        self.assertIn("startup_cwd=", bundle.prompt_envelope.system_prompt())
        self.assertNotIn(f"startup_cwd={startup_dir.resolve()}", bundle.prompt_envelope.user_prelude())
        self.assertIn(f"elephant_workspace={runtime.paths.elephant_file_path('miles').resolve()}", bundle.rendered_prompt)

    def test_installing_skill_package_does_not_eagerly_expand_generation_context(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")
        skill_dir = Path(runtime.paths.state_dir) / "test-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: Search Skill",
                    "description: Helps Elephant Agent search and synthesize local context.",
                    "---",
                    "",
                    "# Search Skill",
                    "",
                    "Always search before editing, then summarize the hits before acting.",
                ]
            ),
            encoding="utf-8",
        )

        with mock.patch.dict("os.environ", {"ELEPHANT_SKILL_PATHS": str(runtime.paths.state_dir)}):
            object.__setattr__(runtime, "skill_hub", runtime.skill_hub.__class__())
            runtime.install_skill_source("custom-1:test-skill", session_id=session.episode_id)

        installed_entry = runtime.inspect_skill("test-skill", session_id=session.episode_id)
        self.assertEqual(Path(installed_entry.entry_path), runtime.paths.installed_skills_dir / "custom-1" / "test-skill" / "SKILL.md")
        self.assertTrue(Path(installed_entry.entry_path).exists())
        self.assertEqual(installed_entry.metadata.get("source_reference"), "custom-1:test-skill")
        self.assertEqual(installed_entry.metadata.get("install_action"), "install")
        self.assertEqual(installed_entry.metadata.get("install_requester"), "operator")

        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            tool_runtime=runtime.tool_runtime,
            skill_runtime=runtime.skill_runtime,
            install_root=runtime.paths.home_dir,
        )
        bundle = capability.assemble(session, (), ())

        self.assertNotIn("Search Skill", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn("Always search before editing", bundle.prompt_envelope.frozen_prefix)

    def test_enabled_shelf_skill_enters_prompt_index_without_runtime_install(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")
        skill_dir = runtime.paths.installed_skills_dir / "manual" / "shelf-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: Shelf Skill",
                    "skill_id: shelf-skill",
                    "description: Manually materialized skill that should stay discoverable.",
                    "---",
                    "",
                    "# Shelf Skill",
                    "",
                    "Use this when the operator wants a manually dropped skill package.",
                ]
            ),
            encoding="utf-8",
        )
        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            tool_runtime=runtime.tool_runtime,
            skill_runtime=runtime.skill_runtime,
            install_root=runtime.paths.home_dir,
        )

        with mock.patch("apps.cli.runtime_cognition.build_launch_directory_context", return_value=(), create=True):
            bundle = capability.assemble(session, (), ())

            self.assertNotIn("Shelf Skill", bundle.rendered_prompt)
            self.assertFalse(any(skill.skill_id == "shelf-skill" for skill in runtime.skill_catalog(session_id=session.episode_id)))

            loaded = runtime._load_profile(session.personal_model_id)
            manifest = dict(loaded.manifest)
            manifest["skill_overrides"] = {"shelf-skill": {"enabled": False}}
            write_profile_manifest(Path(loaded.profile_dir), manifest)

            disabled_bundle = capability.assemble(session, (), ())

        self.assertNotIn("Shelf Skill", disabled_bundle.prompt_envelope.frozen_prefix)

        listed = runtime.tool_runtime.invoke(
            "tool.skill.list",
            {"limit": 128},
            session_id=session.episode_id,
        )
        viewed = runtime.tool_runtime.invoke(
            "tool.skill.view",
            {"skill_id": "shelf-skill"},
            session_id=session.episode_id,
        )

        self.assertIn("shelf-skill | Shelf Skill | source=elephant-installed", listed.summary)
        self.assertIn("skill_id: shelf-skill", viewed.summary)
        self.assertIn("enabled: False", viewed.summary)
        self.assertIn("installed: True", viewed.summary)

    def test_explain_next_step_persists_assistant_outcome_as_decision_memory(self) -> None:
        runtime = self._runtime()
        session = runtime.start()

        outcome = runtime.explain_next_step(
            session_id=session.episode_id,
            prompt="What should we do next for the release?",
        )
        recall_items = runtime.inspect_recall_evidence(session.episode_id)

        # The rendered-prompt surface must not revive the old mutable
        # "Where things stand" State projection. Stable Personal Model
        # context stays visible without mixing in per-turn State summaries.
        self.assertNotIn("### Where things stand", outcome.context.rendered_prompt)
        self.assertNotIn("### Carrying context forward", outcome.context.rendered_prompt)
        self.assertNotIn("recovered-evidence-summary: no durable recall_items", outcome.context.rendered_prompt)
        self.assertFalse(any(evidence.kind == "decision" for evidence in recall_items))
        steps = runtime.repository.list_steps()
        self.assertTrue(any(step.episode_id == session.episode_id for step in steps))
        self.assertTrue(any(outcome.execution.summary in step.summary for step in steps))
        self.assertEqual(runtime.inspect_experiences(session_id=session.episode_id), ())

    def test_explain_next_step_updates_personal_model_growth_from_level_zero_to_level_one(self) -> None:
        runtime = self._runtime()
        session = runtime.start()

        first = runtime.explain_next_step(
            session_id=session.episode_id,
            prompt="Introduce yourself and keep the thread durable.",
        )
        first_growth = runtime.inspect_growth(session_id=session.episode_id)

        self.assertEqual(first.execution.outcome, "ok")
        self.assertEqual(first_growth.level, 0)
        self.assertEqual(first_growth.state.growth_score, 40)
        self.assertEqual(first_growth.progress_percent, 40)
        self.assertEqual(first_growth.state.total_dialogues, 1)
        self.assertGreater(first_growth.state.total_tokens, 0)
        self.assertEqual(first_growth.state.total_experiences, 1)
        self.assertEqual(first_growth.state.active_days, 1)

        second = runtime.explain_next_step(
            session_id=session.episode_id,
            prompt="Keep going and carry the next step forward.",
        )
        second_growth = runtime.inspect_growth(session_id=session.episode_id)

        self.assertEqual(second.execution.outcome, "ok")
        self.assertEqual(second_growth.level, 1)
        self.assertGreaterEqual(second_growth.state.growth_score, 100)
        self.assertEqual(second_growth.state.total_dialogues, 2)
        self.assertEqual(second_growth.state.total_experiences, 2)

    def test_generate_opening_reply_returns_none_without_active_provider(self) -> None:
        runtime = self._runtime()
        session = runtime.start()

        outcome = runtime.generate_opening_reply(
            session_id=session.episode_id,
            prompt="Open the wake surface proactively before the user sends a new message.",
            opening_label="Opened elephant atlas",
        )

        self.assertIsNone(outcome)

    def test_generate_opening_reply_uses_internal_turn_without_growth_side_effects(self) -> None:
        runtime = self._runtime()
        session = runtime.start()

        with mock.patch.object(type(runtime.model_provider), "active_profile", return_value=object()):
            with mock.patch.object(CliRuntime, "_run_turn", return_value=mock.sentinel.outcome) as run_turn:
                outcome = runtime.generate_opening_reply(
                    session_id=session.episode_id,
                    prompt="Open the wake surface proactively before the user sends a new message.",
                    opening_label="Opened elephant atlas",
                )

        self.assertIs(outcome, mock.sentinel.outcome)
        _, kwargs = run_turn.call_args
        self.assertEqual(kwargs["event_type"], "turn.internal")
        self.assertEqual(kwargs["source"], "cli.startup")
        self.assertFalse(kwargs["record_input_event"])
        self.assertFalse(kwargs["record_outcome_event"])
        self.assertFalse(kwargs["capture_experience"])
        self.assertFalse(kwargs["apply_growth"])
        self.assertEqual(kwargs["event_payload"]["summary"], "startup opening (Opened elephant atlas)")
        self.assertEqual(kwargs["event_payload"]["allow_embeddings"], "false")

    def test_generate_opening_reply_keeps_wake_episode_open(self) -> None:
        runtime = self._runtime()
        session = runtime.start()

        def generate_response(*, profile, session, context, prompt, model_role="strong"):
            return ExecutionResult(
                execution_id=f"exec:{session.episode_id}:startup",
                episode_id=session.episode_id,
                outcome="ok",
                summary="startup reply",
                prompt_tokens=64,
                completion_tokens=8,
                total_tokens=72,
            )

        with (
            mock.patch.object(type(runtime.model_provider), "active_profile", return_value=object()),
            mock.patch.object(type(runtime), "active_provider_context_window", return_value=128_000),
            mock.patch.object(type(runtime), "voice_doctor", return_value={"status": "not_configured"}),
            mock.patch.object(type(runtime.model_provider), "generate", side_effect=generate_response),
        ):
            outcome = runtime.generate_opening_reply(
                session_id=session.episode_id,
                prompt="Open the wake surface proactively before the user sends a new message.",
                opening_label="Opened elephant atlas",
            )

        self.assertIsNotNone(outcome)
        stored = runtime.repository.load_episode(session.episode_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertNotEqual(stored.status, "closed")
        self.assertEqual(runtime.repository.list_learning_jobs(episode_id=session.episode_id), ())

    def test_cli_turn_continues_from_next_episode_without_reopening_closed_parent(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        episode = runtime.repository.load_episode(session.episode_id)
        self.assertIsNotNone(episode)
        assert episode is not None
        runtime.repository.upsert_episode(
            replace(
                episode,
                status="closed",
                ended_at=datetime.now(timezone.utc),
                exit_summary="final parent summary",
                metadata={**dict(episode.metadata), "closed_reason": "final_response"},
            )
        )

        transition = runtime.open_next_episode(session.episode_id, reason="wake_boundary")
        outcome = runtime.explain_next_step(session_id=transition.episode.episode_id, prompt="continue this wake thread")

        stored_parent = runtime.repository.load_episode(session.episode_id)
        self.assertIsNotNone(stored_parent)
        assert stored_parent is not None
        stored_child = runtime.repository.load_episode(transition.episode.episode_id)
        self.assertIsNotNone(stored_child)
        assert stored_child is not None
        self.assertNotEqual(outcome.episode.status, "closed")
        self.assertEqual(stored_parent.status, "closed")
        self.assertEqual(stored_child.parent_episode_id, session.episode_id)
        self.assertEqual(stored_child.metadata.get("opening_resume_snapshot"), "final parent summary")
        self.assertEqual(runtime.repository.list_learning_jobs(episode_id=session.episode_id), ())
        self.assertEqual(runtime.repository.list_learning_jobs(episode_id=transition.episode.episode_id), ())

    def test_state_focus_runtime_status_surfaces_loaded_runtime_state(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        embedding_service = runtime.recall_runtime.retriever.evidence_retriever.embedding_service

        health = mock.Mock(
            status="ready",
            summary="local embedding root is available; model weights are already steady in evidence",
            metadata={"runtime_state": "loaded"},
        )

        with mock.patch.object(embedding_service, "health", return_value=health):
            status = runtime.state_focus_runtime_status()

        self.assertEqual(status["health_status"], "ready")
        self.assertEqual(status["runtime_state"], "loaded")
        self.assertTrue(status["embedding_ready"])

    def test_shared_elephant_authored_skill_shelf_supports_cross_profile_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as authored_dir:
            with mock.patch.dict("os.environ", {"ELEPHANT_AUTHORED_SKILLS_DIR": authored_dir}, clear=False):
                runtime_a = self._runtime()
                session_a = runtime_a.create_elephant(elephant_id="atlas")
                runtime_a.create_experience_skill(
                    skill_id="shared-search",
                    display_name="Shared Search",
                    summary="Search before editing.",
                    instruction_text="Always search local files before editing files.",
                    session_id=session_a.episode_id,
                )

                runtime_b = self._runtime(
                    profile_payload={
                        "profile_id": "profile-other",
                        "display_name": "Other Elephant Agent",
                        "mode": "grow",
                    }
                )
                matches = runtime_b.search_skill_hub("shared search")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].source_id, "elephant-authored")
        self.assertEqual(matches[0].skill_id, "shared-search")

    def test_create_experience_skill_surfaces_in_skill_hub_listing(self) -> None:
        with tempfile.TemporaryDirectory() as authored_dir:
            with mock.patch.dict("os.environ", {"ELEPHANT_AUTHORED_SKILLS_DIR": authored_dir}, clear=False):
                runtime = self._runtime()
                session = runtime.create_elephant(elephant_id="atlas")
                runtime.create_experience_skill(
                    skill_id="experience-shell-recovery",
                    display_name="Experience Shell Recovery",
                    summary="Recover shell work after a failed command.",
                    instruction_text="Re-run the command, inspect stderr, then summarize the fix.",
                    session_id=session.episode_id,
                )
                listed = runtime.search_skill_hub("experience shell")
                inspected = runtime.inspect_skill("experience-shell-recovery", session_id=session.episode_id)

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].skill_id, "experience-shell-recovery")
        self.assertEqual(inspected.display_name, "Experience Shell Recovery")
        self.assertTrue(inspected.metadata.get("installed"))

    def test_search_skill_sources_queries_external_sources(self) -> None:
        runtime = self._runtime()
        with mock.patch.object(
            runtime.skill_search_hub,
            "search",
            return_value=(
                SkillSearchEntry(
                    skill_id="bounded-retrieval",
                    display_name="Bounded Retrieval",
                    summary="Searches public skills for bounded retrieval workflows.",
                    source_id="github",
                    source_label="GitHub",
                    reference="github:openai/skills/bounded-retrieval",
                    install_reference="github:openai/skills/bounded-retrieval",
                    trust_level="trusted",
                ),
            ),
        ) as search:
            searched = runtime.search_skill_sources("bounded retrieval")

        search.assert_called_once_with("bounded retrieval", source=None, limit=12)
        self.assertEqual(len(searched), 1)
        self.assertEqual(searched[0].reference, "github:openai/skills/bounded-retrieval")
        self.assertEqual(searched[0].trust_level, "trusted")

    def test_inspect_skill_source_can_inspect_remote_search_reference_without_installing(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")
        remote_dir = Path(runtime.paths.state_dir) / "remote-skill"
        remote_dir.mkdir(parents=True, exist_ok=True)
        (remote_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: Remote Notes",
                    "skill_id: remote-notes",
                    "description: Use Apple Notes from a fetched remote skill.",
                    "---",
                    "",
                    "# Remote Notes",
                    "",
                    "Open Notes and create a note with AppleScript when direct CLI tools are unavailable.",
                ]
            ),
            encoding="utf-8",
        )
        with mock.patch.object(
            runtime.skill_search_hub,
            "fetch",
            return_value=FetchedSkillBundle(
                skill_id="remote-notes",
                source_id="github",
                source_label="GitHub",
                reference="github:openai/skills/remote-notes",
                install_reference="github:openai/skills/remote-notes",
                package_path=str(remote_dir),
                trust_level="trusted",
            ),
        ):
            with self.assertRaises(KeyError):
                runtime.inspect_skill(
                    "github:openai/skills/remote-notes",
                    session_id=session.episode_id,
                )
            inspected = runtime.inspect_skill_source(
                "github:openai/skills/remote-notes",
                session_id=session.episode_id,
            )

        self.assertEqual(inspected.display_name, "Remote Notes")
        self.assertEqual(inspected.metadata.get("hub_reference"), "github:openai/skills/remote-notes")
        self.assertEqual(inspected.metadata.get("source_reference"), "github:openai/skills/remote-notes")
        self.assertEqual(inspected.metadata.get("install_reference"), "github:openai/skills/remote-notes")
        self.assertEqual(inspected.metadata.get("trust_level"), "trusted")
        self.assertIn("AppleScript", inspected.instruction_text)

    def test_inspect_skill_can_read_builtin_skill_package_without_installing(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        listed = runtime.list_skill_hub(limit=64)
        inspected = runtime.inspect_skill(
            "apple-notes",
            session_id=session.episode_id,
        )

        self.assertTrue(any(entry.skill_id == "apple-notes" for entry in listed))
        self.assertEqual(inspected.display_name, "Apple Notes")
        self.assertTrue(inspected.metadata.get("installed"))
        self.assertIn("memo notes --help", inspected.instruction_text)
        self.assertIn("open -a Notes", inspected.instruction_text)

    def test_operator_profile_surface_can_inspect_and_update_profile_surface(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        inspected_profile = runtime.inspect_profile_surface(session.episode_id)
        updated_profile = runtime.patch_profile_surface(
            session.episode_id,
            {
                "display_name": "Atlas",
                "personality_preset": "operator",
                "initiative": "proactive",
                "elephant_identity_text": "Stay concise, direct, and durable for Atlas.",
                "user_fields": {
                    "preferred_name": "xunzhuo",
                    "current_work": "Software engineer",
                },
                "user_text": "Prefers direct updates and wants long-horizon context preserved.",
                "relationship_text": "Keep responses concise and grounded.",
            },
        )

        self.assertEqual(inspected_profile.identity.display_name, "Atlas")
        self.assertEqual(updated_profile.identity.display_name, "Atlas")
        self.assertEqual(updated_profile.identity.personality_preset, "operator")
        self.assertEqual(updated_profile.identity.initiative, "proactive")
        self.assertEqual(updated_profile.user.preferred_name, "xunzhuo")
        self.assertIn("Prefers direct updates and wants long-horizon context preserved.", updated_profile.user.durable_notes)
        self.assertIn("Keep responses concise and grounded.", updated_profile.relationship.continuity_notes)
        user = runtime.inspect_user(session_id=session.episode_id)
        self.assertIn("current_work:Software engineer", user.biography_fragments)
        self.assertEqual(
            user.durable_notes,
            ("Prefers direct updates and wants long-horizon context preserved.",),
        )

    def test_operator_profile_surface_accepts_scoped_user_fields(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        updated = runtime.patch_profile_surface(
            session.episode_id,
            {
                "user_text": "\n".join(
                    (
                        "Preferred name: xunzhuo",
                        "Current work: Software engineer",
                        "Remember: Prefers direct progress updates.",
                    )
                ),
            },
        )

        self.assertEqual(updated.user.preferred_name, "xunzhuo")
        user = runtime.inspect_user(session_id=session.episode_id)
        self.assertIn("current_work:Software engineer", user.biography_fragments)
        self.assertEqual(user.durable_notes, ("Prefers direct progress updates.",))

    def test_operator_profile_surface_persists_structured_biography_fields_in_profile_summary(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        runtime.patch_profile_surface(
            session.episode_id,
            {
                "user_fields": {
                    "mbti": "INFJ",
                    "assistant_mbti_preference": "ENFP",
                },
            },
        )
        updated = runtime.patch_profile_surface(
            session.episode_id,
            {
                "relationship_append": False,
                "user_append": False,
                "user_fields": {
                    "name": "Xunzhuo",
                    "country_of_origin": "China",
                    "employer": "Tencent",
                },
            },
        )

        self.assertEqual(updated.user.preferred_name, "Xunzhuo")
        for fragment in (
            "country_of_origin:China",
            "employer:Tencent",
            "mbti:INFJ",
            "assistant_mbti_preference:ENFP",
        ):
            self.assertIn(fragment, updated.user.biography_fragments)
        user = runtime.inspect_user(session_id=session.episode_id)
        self.assertEqual(user.preferred_name, "Xunzhuo")
        for fragment in (
            "country_of_origin:China",
            "employer:Tencent",
            "mbti:INFJ",
            "assistant_mbti_preference:ENFP",
        ):
            self.assertIn(fragment, user.biography_fragments)

    def test_operator_profile_surface_can_update_identity_posture(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        updated = runtime.patch_profile_surface(
            session.episode_id,
            {
                "personality_preset": "operator",
                "initiative": "proactive",
            },
        )

        self.assertEqual(updated.identity.personality_preset, "operator")
        self.assertEqual(updated.identity.initiative, "proactive")
        identity = runtime.inspect_identity(session_id=session.episode_id)
        self.assertEqual(identity.personality_preset, "operator")
        self.assertEqual(identity.initiative, "proactive")

    def test_personal_model_update_tool_runtime_uses_refreshed_canonical_state_surface(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        assert runtime.model_provider.tool_runtime is not None
        updated = runtime.model_provider.tool_runtime.invoke(
            "tool.personal_model.update",
            {
                "action": "remember",
                "lens": "pulse",
                "topic": "pulse.chapter.work.role",
                "text": "The user's current work is Software engineer.",
                "reason": "user explicitly stated current work",
            },
            session_id=session.episode_id,
        )

        self.assertEqual(updated.outcome, "success")
        self.assertIn("status: active", updated.summary)
        facts = runtime.repository.list_personal_model_facts(
            personal_model_id=session.personal_model_id,
            status="active",
        )
        self.assertTrue(any("Software engineer" in fact.text for fact in facts))

    def test_profile_persistence_syncs_canonical_owner_records_and_ledgers(self) -> None:
        runtime = self._runtime(
            profile_payload={
                "profile_id": "profile-companion",
                "display_name": "Elephant Agent",
                "mode": "companion",
                "locale": "zh-CN",
                "timezone": "Asia/Shanghai",
            },
            seed_charter=False,
        )
        profile_id = runtime.current_profile().state.profile_id

        runtime.update_identity_state(
            profile_id=profile_id,
            elephant_identity_text="Stay calm, durable, and exact.",
        )
        persisted = load_persisted_canonical_state(runtime.repository, profile_id)
        elephant_identity = persisted.elephant_identity
        user_profile = persisted.user_profile
        relationship = persisted.relationship

        self.assertIsNotNone(elephant_identity)
        self.assertIsNotNone(user_profile)
        self.assertIsNotNone(relationship)
        assert elephant_identity is not None
        assert user_profile is not None
        assert relationship is not None
        self.assertEqual(elephant_identity.elephant_identity_text, "Stay calm, durable, and exact.")
        self.assertIsNotNone(runtime.repository.load_elephant_identity_for_profile(profile_id))
        facts = runtime.repository.list_personal_model_facts(personal_model_id=profile_id, status="active")
        self.assertFalse(any(fact.metadata.get("canonical_component") in {"user-profile", "relationship"} for fact in facts))

        runtime.update_user_state(
            profile_id=profile_id,
            text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Build Elephant Agent",
                boundaries="Prefer direct updates.",
            ),
        )
        persisted = load_persisted_canonical_state(runtime.repository, profile_id)
        user_profile = persisted.user_profile
        relationship = persisted.relationship

        assert user_profile is not None
        assert relationship is not None
        self.assertEqual(user_profile.preferred_name, "Bit")
        self.assertIn("current_work:Build Elephant Agent", user_profile.biography_fragments)

        runtime.update_identity_state(
            profile_id=profile_id,
            personality_preset="operator",
            initiative="proactive",
        )
        persisted = load_persisted_canonical_state(runtime.repository, profile_id)
        elephant_identity = persisted.elephant_identity
        relationship = persisted.relationship

        assert elephant_identity is not None
        assert relationship is not None
        self.assertEqual(elephant_identity.personality_preset, "operator")
        self.assertEqual(elephant_identity.initiative, "proactive")
        self.assertIn("initiative:proactive", relationship.expectations)

    def test_create_elephant_starts_without_legacy_goal_seed(self) -> None:
        runtime = self._runtime()

        session = runtime.create_elephant(elephant_id="atlas")

        elephant_state = runtime.repository.load_state("state:atlas")

        self.assertIsNotNone(elephant_state)
        assert elephant_state is not None
        self.assertEqual(elephant_state.state_id, "state:atlas")

    def test_cli_context_capability_surfaces_active_loop_checkpoint(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        now = datetime.now(timezone.utc)
        runtime.repository.upsert_loop_checkpoint(
            LoopState(
                run_id=f"loop:{session.episode_id}:pending",
                episode_id=session.episode_id,
                source_event_id="event-old",
                prompt="Audit the long-horizon loop design.",
                status="pending",
                phase="waiting",
                step_count=4,
                model_turn_count=2,
                tool_call_count=2,
                max_model_turns=24,
                max_wall_time_seconds=180,
                created_at=now,
                updated_at=now,
                waiting_reason="model-turn-budget",
                continuation_prompt="Continue the same Elephant Agent loop checkpoint from its durable checkpoint.",
                last_summary="Collected Elephant Agent and OpenClaw reference points.",
            )
        )
        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            tool_runtime=runtime.tool_runtime,
        )

        bundle = capability.assemble(session, (), ())

        self.assertIn("active-loop-checkpoint:", bundle.rendered_prompt)
        self.assertIn("Audit the long-horizon loop design", bundle.rendered_prompt)
        self.assertIn("Collected Elephant Agent and OpenClaw reference points", bundle.rendered_prompt)

    def test_delete_elephant_clears_sessions_and_memories_for_that_elephant(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        deleted_sessions = runtime.delete_elephant("atlas")

        self.assertEqual(deleted_sessions, 1)
        self.assertIsNone(runtime.repository.load_episode_state(session.episode_id))
        self.assertEqual(runtime.recall_runtime.store.list(session.episode_id, include_inactive=True), ())
        self.assertIsNotNone(runtime.repository.load_personal_model(session.personal_model_id))
        self.assertIsNone(runtime.repository.load_state("state:atlas"))
        self.assertEqual(runtime.list_herd(), ())

    def test_delete_all_elephants_clears_state_rows_and_preserves_personal_model(self) -> None:
        runtime = self._runtime()
        alpha = runtime.create_elephant(elephant_id="alpha")
        beta = runtime.create_elephant(elephant_id="beta")

        deleted_elephants, deleted_sessions = runtime.delete_all_elephants()

        self.assertEqual(deleted_elephants, 2)
        self.assertEqual(deleted_sessions, 2)
        self.assertEqual(runtime.list_herd(), ())
        with runtime.repository.connection() as connection:
            profile_rows = connection.execute(
                """
                SELECT personal_model_id
                FROM personal_models
                WHERE personal_model_id IN (?, ?)
                ORDER BY personal_model_id ASC
                """,
                (alpha.personal_model_id, beta.personal_model_id),
            ).fetchall()

        self.assertEqual([tuple(row) for row in profile_rows], [("you",)])

    def test_create_elephant_reuses_personal_model_without_clearing_growth(self) -> None:
        runtime = self._runtime()
        original = runtime.create_elephant(elephant_id="atlas")
        runtime.repository.upsert_personal_model_growth(
            PersonalModelGrowthState(
                profile_id=original.personal_model_id,
                growth_score=480,
                total_dialogues=12,
                total_tokens=3400,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        runtime.repository.delete_episodes((original.episode_id,))

        self.assertIsNotNone(runtime.repository.load_personal_model(original.personal_model_id))
        stale_growth = runtime.repository.load_personal_model_growth(original.personal_model_id)
        self.assertIsNotNone(stale_growth)
        assert stale_growth is not None
        self.assertEqual(stale_growth.growth_score, 480)

        recreated = runtime.create_elephant(elephant_id="atlas")

        self.assertEqual(recreated.personal_model_id, original.personal_model_id)
        refreshed_growth = runtime.repository.load_personal_model_growth(recreated.personal_model_id)
        self.assertIsNotNone(refreshed_growth)
        assert refreshed_growth is not None
        self.assertEqual(refreshed_growth.growth_score, 480)
        elephant_state = runtime.state_for_elephant("atlas")
        self.assertIsNotNone(elephant_state)
        assert elephant_state is not None
        self.assertEqual(elephant_state.elephant_name, "Atlas")

    def test_elephants_get_isolated_elephant_identity_under_one_personal_model(self) -> None:
        runtime = self._runtime()
        alpha = runtime.create_elephant(elephant_id="alpha")
        beta = runtime.create_elephant(elephant_id="beta")

        alpha_state = runtime.state_for_elephant("alpha")
        beta_state = runtime.state_for_elephant("beta")
        root_profile = runtime.current_profile()

        self.assertEqual(alpha.personal_model_id, beta.personal_model_id)
        self.assertIsNotNone(alpha_state)
        self.assertIsNotNone(beta_state)
        assert alpha_state is not None
        assert beta_state is not None
        self.assertEqual(alpha_state.elephant_name, "Alpha")
        self.assertEqual(beta_state.elephant_name, "Beta")
        self.assertEqual(alpha_state.personal_model_id, "you")
        self.assertEqual(beta_state.personal_model_id, "you")
        self.assertEqual(root_profile.state.display_name, "Elephant Agent")
        self.assertIsNone(root_profile.elephant_identity_text)

    def test_start_session_keeps_the_requested_profile_binding(self) -> None:
        runtime = self._runtime(
            profile_payload={
                "profile_id": "profile-companion",
                "display_name": "elephant",
                "mode": "companion",
            }
        )
        session = runtime.start()

        inspected = runtime.inspect_session(session.episode_id)
        continuity = runtime.inspect_continuity(session_id=session.episode_id)

        self.assertEqual(inspected.personal_model_id, "you")
        self.assertEqual(continuity.profile.state.display_name, "you")
        self.assertFalse((runtime.paths.home_dir / "profiles" / "elephant%3Anova" / "profile.json").exists())

    def test_explain_next_step_does_not_mutate_profile_without_management_tools(self) -> None:
        runtime = self._runtime(
            profile_payload={
                "profile_id": "profile-companion",
                "display_name": "Elephant Agent",
                "mode": "companion",
                "companion": {"initiative": "gentle"},
            }
        )
        session = runtime.start()

        outcome = runtime.explain_next_step(
            session_id=session.episode_id,
            prompt="Call me Bit. I'm building durable agent systems. Please keep replies concise and grounded for future turns.",
        )
        user = runtime.inspect_user(session_id=session.episode_id)
        relationship = runtime.inspect_relationship(session_id=session.episode_id)

        self.assertIsNone(user.preferred_name)
        self.assertEqual(user.communication_preferences, ())
        self.assertEqual(user.biography_fragments, ())
        self.assertEqual(relationship.continuity_notes, ())
        self.assertEqual(outcome.state.current_context_note, "")
