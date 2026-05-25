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
from apps.cli.runtime_snapshot import (
    load_snapshot_session_context_epoch,
    restore_snapshot_state_focus,
)
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
from tests.unit.cli.runtime_cognition_test_base import RuntimeCognitionTestBase


class CliRuntimeCognitionTest(RuntimeCognitionTestBase):
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
        system_prompt = PromptEnvelope(
            frozen_prefix="\n".join(stable_lines)
        ).system_prompt()

        self.assertIn("### Runtime paths", system_prompt)
        self.assertIn(f"startup_cwd={startup_cwd.resolve()}", system_prompt)
        self.assertIn(
            f"elephant_workspace={(workspaces_dir / 'miles').resolve()}", system_prompt
        )
        self.assertNotIn("runtime-paths:", "\n".join(artifacts))

    def test_cli_context_capability_recovers_recent_loop_context_from_snapshot(
        self,
    ) -> None:
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

    def test_cli_context_capability_ignores_internal_startup_loops_in_recent_loop_context(
        self,
    ) -> None:
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

    def test_cli_context_does_not_duplicate_active_personal_model_behavior_contract(
        self,
    ) -> None:
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
        self.assertNotIn(
            "### Behaviors this person has asked you to keep", bundle.rendered_prompt
        )

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

    def test_frozen_session_context_epoch_reuses_stable_sections_without_turn_bodies(
        self,
    ) -> None:
        runtime = self._runtime()
        session = runtime.start()
        profile = runtime._load_profile(session.personal_model_id)
        initial_epoch = load_snapshot_session_context_epoch(
            runtime, session_id=session.episode_id
        )
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
        self.assertNotIn("### Who you are", bundle.prompt_envelope.frozen_prefix)
        self.assertIn("### Your own voice", bundle.prompt_envelope.frozen_prefix)
        self.assertEqual(bundle.prompt_envelope.session_snapshot, "")
        self.assertNotIn("FIRST INJECTIONS", bundle.prompt_envelope.loop_context)
        self.assertEqual(
            tuple(
                (message.role, message.content)
                for message in bundle.prompt_envelope.messages
            ),
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
        frozen_epoch = load_snapshot_session_context_epoch(
            runtime, session_id=session.episode_id
        )
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertTrue(frozen_epoch.frozen)
        self.assertEqual(frozen_epoch.base_loop_context, "")
        self.assertEqual(
            frozen_epoch.thread_focus, "No durable elephant focus is available yet."
        )
        self.assertEqual(frozen_epoch.frozen_skill_ids, ())
        self.assertEqual(
            len(frozen_epoch.frozen_skill_index), frozen_epoch.frozen_skill_count
        )
        self.assertTrue(len(frozen_epoch.frozen_tool_ids) > 0)
        self.assertEqual(
            frozen_epoch.frozen_tool_count,
            len(
                runtime.tool_runtime.list_tools(
                    audience="model", enabled_only=True, available_only=True
                )
            ),
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
        runtime.snapshot_path.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
        )

        frozen_epoch = load_snapshot_session_context_epoch(
            runtime, session_id=session.episode_id
        )

        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertEqual(frozen_epoch.base_loop_context, "- source_ref: turn:1")
        self.assertNotIn("do not keep this body", frozen_epoch.base_loop_context)

    def test_frozen_session_history_compacts_explicitly_without_rewriting_epoch_truth(
        self,
    ) -> None:
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
        runtime.snapshot_path.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
        )

        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            total_tokens=1024,
        )
        result = capability.compact_session_projection(
            session_id=session.episode_id, reason="manual"
        )
        bundle = capability.assemble(session, (), ())

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.compacted)
        rendered_messages = "\n".join(
            message.content for message in bundle.prompt_envelope.messages
        )
        self.assertNotIn("CONTEXT COMPACTION - REFERENCE ONLY", rendered_messages)
        self.assertIn("topic marker 42", rendered_messages)
        frozen_epoch = load_snapshot_session_context_epoch(
            runtime, session_id=session.episode_id
        )
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertEqual(frozen_epoch.compaction_count, 1)
        self.assertEqual(frozen_epoch.compacted_history_count, 32)
        self.assertEqual(frozen_epoch.history_messages[:2], long_history[:2])
        self.assertEqual(frozen_epoch.history_messages[-10:], long_history[-10:])
        self.assertIn(
            "## Handoff notes for recent tail", frozen_epoch.compacted_history_summary
        )
        self.assertGreater(frozen_epoch.context_projection_tokens, 0)
        self.assertEqual(frozen_epoch.context_projection_limit, 1024)
        payload = json.loads(runtime.snapshot_path.read_text(encoding="utf-8"))
        self.assertNotIn("history_lines", payload["session_context_epoch"])

    def test_compact_session_context_wires_projection_embedding_service(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        embedding_service = object()
        runtime.recall_runtime.retriever.evidence_retriever.embedding_service = (
            embedding_service
        )
        captured: dict[str, object] = {}

        class RecordingContextCapability:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            def compact_session_projection(self, **kwargs: object) -> str:
                captured["compact_kwargs"] = kwargs
                return "compacted"

        with mock.patch(
            "apps.cli.runtime_impl._CliContextCapability", RecordingContextCapability
        ):
            result = runtime.compact_session_context(
                session.episode_id, reason="usage", force=True
            )

        self.assertEqual(result, "compacted")
        self.assertIs(captured["embedding_service"], embedding_service)
        self.assertEqual(
            captured["compact_kwargs"],
            {"session_id": session.episode_id, "reason": "usage", "force": True},
        )

    def test_projection_relevance_scorer_was_removed_from_context_public_contract(
        self,
    ) -> None:
        runtime = self._runtime()
        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            embedding_service=object(),
        )

        self.assertFalse(hasattr(capability, "_projection_relevance_scorer"))

    def test_snapshot_history_messages_use_actual_turn_transcript_without_legacy_lines(
        self,
    ) -> None:
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
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="PREFIX", session_snapshot="SNAPSHOT"
                ),
            ),
            turn_messages=turn_messages,
        )

        payload = json.loads(runtime.snapshot_path.read_text(encoding="utf-8"))
        epoch_payload = payload["session_context_epoch"]
        self.assertNotIn("history_lines", epoch_payload)
        roles = [message["role"] for message in epoch_payload["history_messages"]]
        self.assertEqual(roles, ["user", "assistant", "tool", "assistant"])
        self.assertEqual(
            epoch_payload["history_messages"][1]["tool_calls"][0]["name"],
            "tool.web.search",
        )
        self.assertEqual(
            epoch_payload["history_messages"][2]["tool_name"], "tool.web.search"
        )
        self.assertEqual(
            epoch_payload["history_messages"][2]["tool_call_id"], "call-real-1"
        )
        self.assertIn(
            "summary: search result", epoch_payload["history_messages"][2]["content"]
        )

    def test_high_usage_turn_compacts_snapshot_after_current_transcript_is_appended(
        self,
    ) -> None:
        runtime = self._runtime()
        session = runtime.start()
        observed_events: list[dict[str, object]] = []
        runtime.set_kernel_event_observer(observed_events.append)
        huge_prompt = "oversized completed request " + ("payload " * 5000)
        captured_compress_metadata: dict[str, str] = {}

        def generate_response(
            *, profile, session, context, prompt, model_role="strong"
        ):
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
            return mock.Mock(
                summary="oversized completed request was handled; continue from the completed answer."
            )

        with (
            mock.patch.object(
                type(runtime), "active_provider_context_window", return_value=1024
            ),
            mock.patch.object(
                type(runtime.model_provider), "generate", side_effect=generate_response
            ),
            mock.patch(
                "apps.reflect.runner.run_reflect_agent", side_effect=run_reflect_agent
            ),
        ):
            outcome = runtime.explain_next_step(
                session_id=session.episode_id,
                prompt=huge_prompt,
            )

        compact_stages = [
            stage for stage in outcome.stages if stage.stage == "context-compact"
        ]
        self.assertEqual(len(compact_stages), 1)
        self.assertIn("reason=usage", compact_stages[0].detail)
        self.assertTrue(observed_events)
        frozen_epoch = load_snapshot_session_context_epoch(
            runtime, session_id=session.episode_id
        )
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertEqual(frozen_epoch.compaction_count, 1)
        self.assertIn("Reference summary:", frozen_epoch.frozen_prefix)
        self.assertIn(
            "oversized completed request", frozen_epoch.compacted_history_summary
        )
        self.assertIn(
            "oversized completed request",
            captured_compress_metadata["compressed_messages"],
        )
        history = tuple(message.content for message in frozen_epoch.history_messages)
        self.assertIn("completed answer", history)
        self.assertNotIn(huge_prompt, history)

    def test_snapshot_state_focus_restore_rejects_legacy_skill_candidate_scores(
        self,
    ) -> None:
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


if __name__ == "__main__":
    unittest.main()
