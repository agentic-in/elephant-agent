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


class CliRuntimeCognitionSkillTest(RuntimeCognitionTestBase):
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

        frozen_epoch = load_snapshot_session_context_epoch(
            runtime, session_id=session.episode_id
        )
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertNotIn("ascii-art", frozen_epoch.frozen_skill_ids)
        self.assertEqual(frozen_epoch.frozen_skill_ids, ())

    def test_frozen_session_context_epoch_tracks_latest_skill_disclosure_reason(
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

        frozen_epoch = load_snapshot_session_context_epoch(
            runtime, session_id=session.episode_id
        )
        self.assertIsNotNone(frozen_epoch)
        assert frozen_epoch is not None
        self.assertEqual(frozen_epoch.frozen_skill_disclosures, ())
        self.assertEqual(len(frozen_epoch.latest_skill_disclosures), 1)
        self.assertEqual(frozen_epoch.latest_skill_disclosures[0].skill_id, "ascii-art")
        self.assertIn(
            "explicit skill overlay",
            frozen_epoch.latest_skill_disclosures[0].reason,
        )

    def test_skill_catalog_does_not_kick_off_embedding_steadyup_for_passive_ui_reads(
        self,
    ) -> None:
        runtime = self._runtime()
        session = runtime.start()
        embedding_service = (
            runtime.recall_runtime.retriever.evidence_retriever.embedding_service
        )

        with mock.patch.object(
            embedding_service, "steady_async", return_value=True
        ) as steady_async:
            runtime.skill_catalog(session_id=session.episode_id)

        steady_async.assert_not_called()

    def test_cli_context_capability_surfaces_enabled_tools_and_scoped_skills(
        self,
    ) -> None:
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
        self.assertNotIn(
            "- ### Capability Disclosure", bundle.prompt_envelope.frozen_prefix
        )
        self.assertNotIn("skill-routing:", bundle.prompt_envelope.frozen_prefix)
        self.assertIn("Skill index (", bundle.rendered_prompt)
        self.assertIn("episode-frozen entries", bundle.rendered_prompt)
        self.assertNotIn("shown=24", bundle.rendered_prompt)
        self.assertNotIn("hidden=", bundle.rendered_prompt)
        self.assertNotIn(
            str(runtime.paths.installed_skills_dir), bundle.rendered_prompt
        )
        self.assertNotIn(str(runtime.paths.authored_skills_dir), bundle.rendered_prompt)
        self.assertIn("- apple -", bundle.rendered_prompt)
        self.assertIn("Apple Notes", bundle.rendered_prompt)
        self.assertIn("GIF Search", bundle.rendered_prompt)
        self.assertIn("Hugging Face Hub", bundle.rendered_prompt)
        self.assertIn("iMessage", bundle.rendered_prompt)
        self.assertNotIn(
            "Complete guide to what Elephant Agent is", bundle.rendered_prompt
        )
        self.assertNotIn("skill-routing:", bundle.rendered_prompt)

    def test_installing_skill_package_does_not_eagerly_expand_generation_context(
        self,
    ) -> None:
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

        with mock.patch.dict(
            "os.environ", {"ELEPHANT_SKILL_PATHS": str(runtime.paths.state_dir)}
        ):
            object.__setattr__(runtime, "skill_hub", runtime.skill_hub.__class__())
            runtime.install_skill_source(
                "custom-1:test-skill", session_id=session.episode_id
            )

        installed_entry = runtime.inspect_skill(
            "test-skill", session_id=session.episode_id
        )
        self.assertEqual(
            Path(installed_entry.entry_path),
            runtime.paths.installed_skills_dir / "custom-1" / "test-skill" / "SKILL.md",
        )
        self.assertTrue(Path(installed_entry.entry_path).exists())
        self.assertEqual(
            installed_entry.metadata.get("source_reference"), "custom-1:test-skill"
        )
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
        self.assertNotIn(
            "Always search before editing", bundle.prompt_envelope.frozen_prefix
        )

    def test_enabled_shelf_skill_enters_prompt_index_without_runtime_install(
        self,
    ) -> None:
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

        with mock.patch(
            "apps.cli.runtime_cognition.build_launch_directory_context",
            return_value=(),
            create=True,
        ):
            bundle = capability.assemble(session, (), ())

            self.assertNotIn("Shelf Skill", bundle.rendered_prompt)
            self.assertFalse(
                any(
                    skill.skill_id == "shelf-skill"
                    for skill in runtime.skill_catalog(session_id=session.episode_id)
                )
            )

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

        self.assertIn(
            "shelf-skill | Shelf Skill | source=elephant-installed", listed.summary
        )
        self.assertIn("skill_id: shelf-skill", viewed.summary)
        self.assertIn("enabled: False", viewed.summary)
        self.assertIn("installed: True", viewed.summary)

    def test_shared_elephant_authored_skill_shelf_supports_cross_profile_reuse(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as authored_dir:
            with mock.patch.dict(
                "os.environ",
                {"ELEPHANT_AUTHORED_SKILLS_DIR": authored_dir},
                clear=False,
            ):
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
            with mock.patch.dict(
                "os.environ",
                {"ELEPHANT_AUTHORED_SKILLS_DIR": authored_dir},
                clear=False,
            ):
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
                inspected = runtime.inspect_skill(
                    "experience-shell-recovery", session_id=session.episode_id
                )

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
        self.assertEqual(
            searched[0].reference, "github:openai/skills/bounded-retrieval"
        )
        self.assertEqual(searched[0].trust_level, "trusted")

    def test_inspect_skill_source_can_inspect_remote_search_reference_without_installing(
        self,
    ) -> None:
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
        self.assertEqual(
            inspected.metadata.get("hub_reference"), "github:openai/skills/remote-notes"
        )
        self.assertEqual(
            inspected.metadata.get("source_reference"),
            "github:openai/skills/remote-notes",
        )
        self.assertEqual(
            inspected.metadata.get("install_reference"),
            "github:openai/skills/remote-notes",
        )
        self.assertEqual(inspected.metadata.get("trust_level"), "trusted")
        self.assertIn("AppleScript", inspected.instruction_text)

    def test_inspect_skill_can_read_builtin_skill_package_without_installing(
        self,
    ) -> None:
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
