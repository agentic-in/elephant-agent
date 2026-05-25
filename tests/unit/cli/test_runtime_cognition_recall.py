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


class CliRuntimeCognitionRecallTest(RuntimeCognitionTestBase):
    def test_durable_recall_capability_prefers_work_item_aware_continuity_retrieval(
        self,
    ) -> None:
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

        capability = _DurableRecallCapability(
            recall_runtime=runtime.recall_runtime, repository=runtime.repository
        )
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
        self.assertNotIn(
            "Publish the release artifacts.", continuity.reengagement_prompt
        )
        self.assertIn("initiative=gentle", continuity.continuity_summary)

    def test_planning_recall_evidence_recovery_falls_back_to_episode_scoped_steps(
        self,
    ) -> None:
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

        with mock.patch.object(
            runtime.recall_runtime, "retrieve_evidence", return_value=empty_retrieval
        ):
            recovery = runtime._planning_recall_evidence_recovery(session)

        self.assertEqual(
            tuple(evidence.evidence_id for evidence in recovery.recall_items),
            ("step:evidence-fallback",),
        )
        self.assertEqual(recovery.scope_episode_ids, (session.episode_id,))

    def test_prepare_session_surface_kicks_off_embedding_steadyup(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        embedding_service = (
            runtime.recall_runtime.retriever.evidence_retriever.embedding_service
        )

        with mock.patch.object(
            embedding_service, "steady_async", return_value=True
        ) as steady_async:
            runtime.prepare_session_surface(session.episode_id)

        steady_async.assert_called_once_with()

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

        self.assertIn(
            "Recently surfaced notes: Prefers direct updates over filler.", summary
        )
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
        self.assertIn(
            f"elephant_workspace={runtime.paths.elephant_file_path('miles').resolve()}",
            bundle.rendered_prompt,
        )
        self.assertIn(
            f"elephant_workspace={runtime.paths.elephant_file_path('miles').resolve()}",
            bundle.prompt_envelope.system_prompt(),
        )

    def test_cli_context_only_lists_launch_directory_rule_files_for_on_demand_reading(
        self,
    ) -> None:
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

        self.assertNotIn(
            "### Launch Directory Context", bundle.prompt_envelope.frozen_prefix
        )
        self.assertNotIn(
            f"Current absolute path: `{startup_dir.resolve()}`",
            bundle.prompt_envelope.frozen_prefix,
        )
        self.assertNotIn(
            "Launch-directory rule files are available for on-demand reading:",
            bundle.prompt_envelope.frozen_prefix,
        )
        self.assertNotIn(
            f"- `{startup_dir / 'AGENTS.md'}`", bundle.prompt_envelope.frozen_prefix
        )
        self.assertNotIn(".elephant.md", bundle.prompt_envelope.frozen_prefix)
        self.assertNotIn(
            "Loaded launch-directory project context files:",
            bundle.prompt_envelope.frozen_prefix,
        )
        self.assertNotIn(
            "Always treat the current repo as the primary analysis target.",
            bundle.prompt_envelope.frozen_prefix,
        )
        self.assertNotIn(
            "Use launch-directory docs before generic fallbacks.",
            bundle.prompt_envelope.frozen_prefix,
        )
        self.assertIn(f"startup_cwd={startup_dir.resolve()}", bundle.rendered_prompt)
        self.assertNotIn(
            f"startup_cwd={startup_dir.resolve()}",
            bundle.prompt_envelope.system_prompt(),
        )
        self.assertIn("startup_cwd=", bundle.prompt_envelope.system_prompt())
        self.assertNotIn(
            f"startup_cwd={startup_dir.resolve()}",
            bundle.prompt_envelope.user_prelude(),
        )
        self.assertIn(
            f"elephant_workspace={runtime.paths.elephant_file_path('miles').resolve()}",
            bundle.rendered_prompt,
        )

    def test_explain_next_step_persists_assistant_outcome_as_decision_memory(
        self,
    ) -> None:
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
        self.assertNotIn(
            "### Carrying context forward", outcome.context.rendered_prompt
        )
        self.assertNotIn(
            "recovered-evidence-summary: no durable recall_items",
            outcome.context.rendered_prompt,
        )
        self.assertFalse(any(evidence.kind == "decision" for evidence in recall_items))
        steps = runtime.repository.list_steps()
        self.assertTrue(any(step.episode_id == session.episode_id for step in steps))
        self.assertTrue(
            any(outcome.execution.summary in step.summary for step in steps)
        )
        self.assertEqual(runtime.inspect_experiences(session_id=session.episode_id), ())

    def test_explain_next_step_updates_personal_model_growth_from_level_zero_to_level_one(
        self,
    ) -> None:
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

    def test_generate_opening_reply_uses_internal_turn_without_growth_side_effects(
        self,
    ) -> None:
        runtime = self._runtime()
        session = runtime.start()

        with mock.patch.object(
            type(runtime.model_provider), "active_profile", return_value=object()
        ):
            with mock.patch.object(
                CliRuntime, "_run_turn", return_value=mock.sentinel.outcome
            ) as run_turn:
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
        self.assertEqual(
            kwargs["event_payload"]["summary"],
            "startup opening (Opened elephant atlas)",
        )
        self.assertEqual(kwargs["event_payload"]["allow_embeddings"], "false")

    def test_generate_opening_reply_keeps_wake_episode_open(self) -> None:
        runtime = self._runtime()
        session = runtime.start()

        def generate_response(
            *, profile, session, context, prompt, model_role="strong"
        ):
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
            mock.patch.object(
                type(runtime.model_provider), "active_profile", return_value=object()
            ),
            mock.patch.object(
                type(runtime), "active_provider_context_window", return_value=128_000
            ),
            mock.patch.object(
                type(runtime), "voice_doctor", return_value={"status": "not_configured"}
            ),
            mock.patch.object(
                type(runtime.model_provider), "generate", side_effect=generate_response
            ),
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
        self.assertEqual(
            runtime.repository.list_learning_jobs(episode_id=session.episode_id), ()
        )

    def test_cli_turn_continues_from_next_episode_without_reopening_closed_parent(
        self,
    ) -> None:
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

        transition = runtime.open_next_episode(
            session.episode_id, reason="wake_boundary"
        )
        outcome = runtime.explain_next_step(
            session_id=transition.episode.episode_id, prompt="continue this wake thread"
        )

        stored_parent = runtime.repository.load_episode(session.episode_id)
        self.assertIsNotNone(stored_parent)
        assert stored_parent is not None
        stored_child = runtime.repository.load_episode(transition.episode.episode_id)
        self.assertIsNotNone(stored_child)
        assert stored_child is not None
        self.assertNotEqual(outcome.episode.status, "closed")
        self.assertEqual(stored_parent.status, "closed")
        self.assertEqual(stored_child.parent_episode_id, session.episode_id)
        self.assertEqual(
            stored_child.metadata.get("opening_resume_snapshot"), "final parent summary"
        )
        self.assertEqual(
            runtime.repository.list_learning_jobs(episode_id=session.episode_id), ()
        )
        self.assertEqual(
            runtime.repository.list_learning_jobs(
                episode_id=transition.episode.episode_id
            ),
            (),
        )

    def test_state_focus_runtime_status_surfaces_loaded_runtime_state(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        embedding_service = (
            runtime.recall_runtime.retriever.evidence_retriever.embedding_service
        )

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
