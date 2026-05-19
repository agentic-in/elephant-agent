from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class SystemLayerResetMatrixTests(unittest.TestCase):
    def test_deleted_legacy_test_modules_are_gone(self) -> None:
        for relative_path in (
            "tests/e2e/voice/test_voice_preview.py",
            "tests/scenarios/planning/test_planning_scenarios.py",
            "tests/unit/intent/test_runtime.py",
            "tests/unit/goals",
            "tests/unit/planning/test_goal_graph_planner.py",
            "tests/unit/session/test_lineage.py",
            "packages/goals",
            "packages/evidence/intent_support.py",
            "packages/kernel/agent_run_support.py",
            "packages/kernel/intent_selection.py",
            "packages/kernel/intent_weak_assist.py",
            "packages/state/ELEPHANT.md",
            "apps/session_runtime_rows.py",
            "apps/session_runtime_storage.py",
        ):
            with self.subTest(path=relative_path):
                self.assertFalse((ROOT / relative_path).exists())

    def test_deleted_legacy_evidence_modules_are_gone(self) -> None:
        for relative_path in (
            "packages/evidence/recall_runtime_impl.py",
            "packages/evidence/recall_runtime_support.py",
            "packages/evidence/personal_model_support.py",
            "packages/evidence/memory_capture_support.py",
            "packages/evidence/memory_inventory.py",
        ):
            with self.subTest(path=relative_path):
                self.assertFalse((ROOT / relative_path).exists())

    def test_makefile_targets_reference_reset_lifecycle_surfaces(self) -> None:
        text = _read("Makefile")

        for target in (
            "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_operator_namespace_no_longer_exposes_public_dashboard_reads",
            "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_operator_dashboard_projection_is_empty_without_runtime_state",
            "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence",
            "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_default_provider_bad_request_hides_legacy_profile_field_names",
            "tests.e2e.gateway.test_gateway_adapter",
            "tests.integration.kernel.test_turn_lifecycle",
            "tests.integration.storage_system_layers.test_repository",
            "tests.integration.tools_skills.test_tools_and_skills_runtime",
            "tests.unit.recall.test_recall_scenarios",
            "tests.scenarios.continuity.test_continuity_scenarios",
            "tests.scenarios.companion.test_companion_scenarios",
        ):
            with self.subTest(target=target):
                self.assertIn(target, text)

    def test_storage_suite_pins_default_model_clean_schema_and_delete_boundaries(
        self,
    ) -> None:
        text = _read("tests/integration/storage_system_layers/test_repository.py")

        for marker in (
            "test_default_personal_model_creation_is_idempotent",
            "test_elephant_state_create_switch_list_and_delete_preserves_personal_model",
            "test_episode_loop_and_step_round_trip_without_legacy_evidence",
            "test_elephant_delete_removes_state_scoped_semantic_rows_only",
            "test_legacy_storage_methods_are_removed",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_loop_checkpoint_and_personal_model_growth_live_in_repository_methods_without_runtime_shims(
        self,
    ) -> None:
        checkpoint_text = _read("packages/kernel/loop_checkpoint_support.py")
        episode_runtime_text = _read("apps/episode_runtime.py")
        repository_methods_text = _read("packages/storage/repository_system_methods.py")

        self.assertIn("LoopCheckpointService", checkpoint_text)
        self.assertNotIn("AgentRunService", checkpoint_text)
        self.assertNotIn("same Elephant Agent agent run", checkpoint_text)

        self.assertIn("install_app_episode_runtime", episode_runtime_text)
        self.assertNotIn("profile_loader", episode_runtime_text)
        self.assertNotIn("MethodType", episode_runtime_text)

        for marker in (
            "upsert_loop_checkpoint",
            "load_latest_open_loop_checkpoint",
            "append_loop_checkpoint_step",
            "list_loop_checkpoint_steps",
            "upsert_personal_model_growth",
            "load_personal_model_growth",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, repository_methods_text)

        self.assertNotIn("upsert_agent_run", repository_methods_text)
        self.assertNotIn("load_latest_open_agent_run", repository_methods_text)
        self.assertNotIn("profile_growth", repository_methods_text)

    def test_kernel_and_context_suites_pin_state_query_and_compaction_coverage(
        self,
    ) -> None:
        kernel_text = _read("tests/integration/kernel/test_turn_lifecycle.py")
        context_text = _read("tests/unit/context/test_context_projection.py")

        for marker in (
            "test_kernel_turn_uses_state_query_without_goal_graph_dependency",
            "KernelSourceRequest",
            "state_query",
            "outcome.state.summary",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, kernel_text)

        for marker in (
            "test_compaction_preserves_head_and_tail_while_summarizing_middle",
            "test_message_compaction_preserves_roles_and_tool_results_in_tail",
            "CONTEXT COMPACTION - REFERENCE ONLY",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, context_text)

    def test_skill_dashboard_and_continuity_suites_pin_reset_acceptance_surfaces(
        self,
    ) -> None:
        skills_text = _read("tests/integration/tools_skills/test_tools_and_skills_runtime.py")
        api_text = _read("tests/e2e/api/test_api_surface.py")
        continuity_text = _read("tests/scenarios/continuity/test_continuity_scenarios.py")

        for marker in (
            "skill.suppressed",
            "skill.retired",
            "resolve_for_context",
            "test_skill_runtime_activate_rejects_suppressed_retired_and_state_blocked_skills",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, skills_text)

        self.assertIn("/v1/internal/dashboard", api_text)
        self.assertIn(
            "test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence",
            api_text,
        )
        self.assertIn("test_continuity_scenarios_index_is_stable", continuity_text)
        self.assertIn("test_state_continuity_fixture_declares_text_only_boundary", continuity_text)


if __name__ == "__main__":
    unittest.main()
