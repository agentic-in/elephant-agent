import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from apps.api.api_runtime_internal_methods import _step_event_content, _step_event_type
from packages.contracts.layers import Episode, State
from packages.contracts.runtime import (
    ContextBundle,
    ExecutionResult,
    PromptEnvelope,
    PromptMessage,
)
from packages.kernel import KernelService, KernelSourceRequest
from packages.kernel.loop_checkpoint_support import (
    LoopCheckpointBudget,
    LoopCheckpointService,
)
from packages.kernel.runtime_support import (
    _TextToolCall,
    _build_clock,
    _deduplicate_tool_calls,
    _provider_system_prompt_for_recording,
    _should_parallelize_tool_batch,
    _tool_result_preview,
)
from packages.tools.tool_result_storage import (
    ToolResultBudgetConfig,
    enforce_tool_observation_budget,
    maybe_persist_tool_result,
)


class RuntimeSupportBudgetTest(unittest.TestCase):
    def test_dashboard_maps_effective_user_query_as_visible_user_query(self) -> None:
        effective_step = SimpleNamespace(
            action="effective_user_query",
            status="completed",
            metadata={
                "effective_user_query": "raw question\n\nCurrent-turn recall support:\n- [note] remembered\n",
                "raw_user_query": "raw question",
            },
            payload_refs=(),
            summary="model user query assembled",
        )
        source_step = SimpleNamespace(
            action="record_input",
            status="completed",
            metadata={"user_query": "raw question"},
            payload_refs=(),
            summary="source item ingested",
        )

        self.assertEqual(_step_event_type(effective_step), "user_query")
        self.assertIn("Current-turn recall support:", _step_event_content(effective_step, {}))
        self.assertEqual(_step_event_type(source_step), "source_input")
        self.assertEqual(_step_event_content(source_step, {}), "raw question")

    def test_agent_loop_budget_defaults_extend_model_turns_and_use_large_result_budgets(
        self,
    ) -> None:
        budget = LoopCheckpointBudget()

        self.assertEqual(budget.max_model_turns, 100)
        self.assertEqual(budget.max_wall_time_seconds, 28_800)
        self.assertEqual(budget.tool_result_preview_chars, 1_500)
        self.assertEqual(budget.tool_result_turn_budget_chars, 200_000)
        self.assertEqual(budget.tool_result_persist_threshold_chars, 100_000)

        run = LoopCheckpointService().start_loop(
            session_id="session-1",
            source_event_id="event-1",
            prompt="inspect the runtime",
        )

        self.assertEqual(run.max_model_turns, 100)
        self.assertEqual(run.max_wall_time_seconds, 28_800)

    def test_context_prompt_step_preserves_full_provider_system_prompt(self) -> None:
        system_prompt = "\n".join(
            (
                "system prompt :: frozen_prefix",
                "FIRST PREFIX",
                "system prompt :: session_snapshot",
                "x" * 15_000,
                "LAST LINE",
            )
        )
        run = LoopCheckpointService().start_loop(
            episode_id="session-1",
            source_event_id="event-1",
            prompt="inspect the runtime",
        )

        _, step = LoopCheckpointService().record_context_prompt(run, system_prompt=system_prompt)

        self.assertEqual(step.kind, "context_prompt")
        self.assertEqual(step.title, "provider system prompt")
        self.assertEqual(step.content, system_prompt)
        self.assertIn("\nLAST LINE", step.content)

    def test_recorded_provider_system_prompt_excludes_loop_context(self) -> None:
        context = ContextBundle(
            bundle_id="bundle-1",
            episode_id="episode-1",
            prompt_envelope=PromptEnvelope(
                frozen_prefix="system prompt :: frozen_prefix",
                session_snapshot="system prompt :: session_snapshot",
                loop_context="## Turn attachments\nruntime-paths: startup_cwd=/tmp/start",
                messages=(
                    PromptMessage(role="system", content="system prompt :: extra message"),
                    PromptMessage(role="user", content="hello"),
                ),
            ),
            rendered_prompt=(
                "system prompt :: frozen_prefix\n\n## Turn attachments\nruntime-paths: startup_cwd=/tmp/start"
            ),
        )

        recorded = _provider_system_prompt_for_recording(context)

        self.assertIn("system prompt :: frozen_prefix", recorded)
        self.assertIn("system prompt :: session_snapshot", recorded)
        self.assertIn("system prompt :: extra message", recorded)
        self.assertNotIn("## Turn attachments", recorded)
        self.assertNotIn("runtime-paths: startup_cwd=/tmp/start", recorded)

    def test_checkpoint_step_ids_are_deterministic_for_same_run_and_index(self) -> None:
        service = LoopCheckpointService()
        run = service.start_loop(
            session_id="session-1",
            source_event_id="event-1",
            prompt="inspect the runtime",
        )

        _, first = service.record_context_prompt(run, system_prompt="alpha")
        _, replay = service.record_context_prompt(run, system_prompt="beta")
        updated_run, tool_step = service.record_tool_step(
            run,
            tool_name="tool.file.read",
            arguments={"path": "README.md"},
            result=ExecutionResult(
                execution_id="exec-1",
                episode_id="session-1",
                outcome="ok",
                summary="done",
            ),
        )

        self.assertEqual(first.step_index, 1)
        self.assertEqual(replay.step_index, 1)
        self.assertEqual(first.step_id, replay.step_id)
        self.assertEqual(first.step_id, f"loop-step:{run.run_id}:1")
        self.assertEqual(tool_step.step_id, f"loop-step:{run.run_id}:{updated_run.step_count}")

    def test_tool_result_preview_keeps_full_summary_when_under_budget(self) -> None:
        summary = f"  {'x' * 2_000}  "

        preview = _tool_result_preview(summary, preview_chars=3_000)

        self.assertEqual(preview, summary.strip())
        self.assertNotIn("[truncated]", preview)

    def test_large_tool_result_persists_full_output_with_inline_preview(self) -> None:
        with TemporaryDirectory() as tmpdir:
            stored = maybe_persist_tool_result(
                "x" * 256,
                tool_name="tool.web.search",
                tool_use_id="tool:session:web-search",
                config=ToolResultBudgetConfig(result_size_chars=100, preview_size_chars=64),
                storage_dir=Path(tmpdir),
            )

            self.assertIn("<persisted-output", stored)
            self.assertIn("[truncated]", stored)
            path_line = next(line for line in stored.splitlines() if line.startswith("Read the file"))
            stored_path = Path(path_line.rsplit(" ", 1)[-1])
            self.assertEqual(stored_path.read_text(encoding="utf-8"), "x" * 256)

    def test_observation_budget_persists_largest_observations(self) -> None:
        observations = [
            f"tool: tool.web.search\nsummary: {'a' * 2_000}",
            f"tool: tool.web.extract\nsummary: {'b' * 2_000}",
        ]

        with TemporaryDirectory() as tmpdir:
            budgeted = enforce_tool_observation_budget(
                list(observations),
                config=ToolResultBudgetConfig(turn_budget_chars=1_500, preview_size_chars=300),
                storage_dir=Path(tmpdir),
            )

        self.assertLess(sum(len(item) for item in budgeted), sum(len(item) for item in observations))
        self.assertIn("<persisted-output", "\n".join(budgeted))

    def test_deduplicates_identical_tool_calls_within_one_model_turn(self) -> None:
        calls = (
            _TextToolCall("tool.web.search", {"query": "a"}),
            _TextToolCall("tool.web.search", {"query": "a"}),
            _TextToolCall("tool.web.search", {"query": "b"}),
        )

        deduped = _deduplicate_tool_calls(calls)

        self.assertEqual(deduped, (calls[0], calls[2]))

    def test_parallelizes_read_only_tool_batches(self) -> None:
        calls = (
            _TextToolCall("tool.file.read", {"path": "packages/kernel/runtime_impl.py"}),
            _TextToolCall("tool.file.search", {"query": "_execute_model_tool_loop"}),
            _TextToolCall("tool.web.search", {"query": "elephant agent"}),
        )

        self.assertTrue(_should_parallelize_tool_batch(calls))

    def test_parallel_tool_batch_rejects_clarify(self) -> None:
        calls = (
            _TextToolCall("tool.web.search", {"query": "elephant agent"}),
            _TextToolCall("tool.clarify", {"question": "Which source?"}),
        )

        self.assertFalse(_should_parallelize_tool_batch(calls))

    def test_parallel_tool_batch_rejects_side_effecting_tools(self) -> None:
        calls = (
            _TextToolCall("tool.file.read", {"path": "README.md"}),
            _TextToolCall("tool.file.write", {"path": "notes.txt", "content": "x"}),
        )

        self.assertFalse(_should_parallelize_tool_batch(calls))

    def test_parallel_tool_batch_rejects_file_read_without_path(self) -> None:
        calls = (
            _TextToolCall("tool.file.read", {}),
            _TextToolCall("tool.web.search", {"query": "elephant agent"}),
        )

        self.assertFalse(_should_parallelize_tool_batch(calls))

    def test_parallel_tool_batch_allows_background_sub_agent_start_calls(self) -> None:
        calls = (
            _TextToolCall("tool.sub_agents", {"action": "start", "task": "inspect core"}),
            _TextToolCall("tool.sub_agents", {"action": "start", "task": "inspect tools"}),
        )

        self.assertTrue(_should_parallelize_tool_batch(calls))

    def test_parallel_tool_batch_rejects_blocking_sub_loop_checkpoint_calls(
        self,
    ) -> None:
        calls = (
            _TextToolCall("tool.sub_agents", {"action": "run", "task": "inspect core"}),
            _TextToolCall("tool.sub_agents", {"action": "run", "task": "inspect tools"}),
        )

        self.assertFalse(_should_parallelize_tool_batch(calls))

    def test_clock_uses_user_timezone_before_environment_fallback(self) -> None:
        session = Episode(
            episode_id="episode-1",
            state_id="state:test",
            personal_model_id="profile-1",
            entry_surface="test",
            elephant_id="elephant-1",
            status="open",
            started_at=datetime(2026, 4, 27, 23, 30, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 27, 23, 30, tzinfo=timezone.utc),
        )
        with mock.patch.dict("os.environ", {"ELEPHANT_TIMEZONE": "America/Los_Angeles"}, clear=False):
            clock = _build_clock(
                "Asia/Shanghai",
                now=datetime(2026, 4, 28, 0, 30, tzinfo=timezone.utc),
            )

        self.assertEqual(clock.timezone_name, "CST")
        self.assertEqual(clock.local_date, "2026-04-28")

    def test_clock_uses_configured_environment_timezone_before_utc(self) -> None:
        session = Episode(
            episode_id="episode-1",
            state_id="state:test",
            personal_model_id="profile-1",
            entry_surface="test",
            elephant_id="elephant-1",
            status="open",
            started_at=datetime(2026, 4, 27, 23, 30, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 27, 23, 30, tzinfo=timezone.utc),
        )

        with mock.patch.dict("os.environ", {"ELEPHANT_TIMEZONE": "Asia/Shanghai"}, clear=False):
            clock = _build_clock(
                None,
                now=datetime(2026, 4, 28, 0, 30, tzinfo=timezone.utc),
            )

        self.assertEqual(clock.timezone_name, "CST")
        self.assertEqual(clock.local_date, "2026-04-28")

    def test_state_projection_does_not_mutate_continuation_note_per_turn(self) -> None:
        state = State(
            state_id="state-1",
            personal_model_id="profile-1",
            state_anchor="elephant:state-1",
            current_context_note="Resume the dashboard redesign from the prior episode.",
        )
        execution = ExecutionResult(
            execution_id="exec-1",
            episode_id="episode-1",
            outcome="ok",
            summary="Completed the cleanup.\n" + ("Detailed completion evidence. " * 40),
        )

        updated = KernelService(dependencies=SimpleNamespace())._refresh_state_projection(
            state,
            request=KernelSourceRequest(route_id="episode-1", prompt="Continue"),
            execution=execution,
            current=datetime(2026, 4, 28, tzinfo=timezone.utc),
        )

        self.assertEqual(
            updated.current_context_note,
            "Resume the dashboard redesign from the prior episode.",
        )
        self.assertLessEqual(len(updated.summary), 480)
        self.assertNotIn("\n", updated.summary)


if __name__ == "__main__":
    unittest.main()
