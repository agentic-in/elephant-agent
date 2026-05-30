from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.e2e.api.api_surface_test_base import APISurfaceTestBase
from packages.contracts import PersonalModelGrowthState
from packages.contracts.runtime import PersonalModelRuntimeState
from packages.runtime_layout import elephant_file_path


class APISurfaceE2ETest(APISurfaceTestBase):
    def test_episode_create_preserves_existing_personal_model_identity(self) -> None:
        self.app.repository.upsert_personal_model_runtime_state(
            PersonalModelRuntimeState(
                profile_id="you",
                display_name="You",
                mode="companion",
                preferences=("desktop", "native"),
                enabled_capabilities=("voice", "personal_model"),
                learning_intensity="high",
            )
        )

        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "you",
                    "display_name": "Chat",
                    "mode": "companion",
                    "elephant_id": "mother-elephant",
                    "preferences": [],
                    "enabled_capabilities": [],
                    "episode_id": "session-preserve-you",
                }
            ),
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.payload["episode"]["episode_id"], "session-preserve-you")
        self.assertEqual(created.payload["personal_model"]["display_name"], "You")
        personal_model = self.app.repository.load_personal_model_runtime_state("you")
        self.assertIsNotNone(personal_model)
        assert personal_model is not None
        self.assertEqual(personal_model.display_name, "You")
        self.assertEqual(personal_model.preferences, ("desktop", "native"))
        self.assertEqual(personal_model.enabled_capabilities, ("voice", "personal_model"))
        self.assertEqual(personal_model.learning_intensity, "high")

    def test_episode_lifecycle_inspection_and_next(self) -> None:
        legacy_sessions = self.app.dispatch("GET", "/v1/sessions/session-1")
        self.assertEqual(legacy_sessions.status_code, 404)

        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "elephant_id": "elephant-1",
                    "provider_profile": self._provider_profile(
                        profile_id="provider-openrouter",
                        base_url=self.stub.openai_base_url,
                        extra_headers={"x-tenant": "elephant"},
                    ),
                    "episode_id": "session-1",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.payload["episode"]["episode_id"], "session-1")

        inspected = self.app.dispatch("GET", "/v1/episodes/session-1")
        self.assertEqual(inspected.status_code, 200)
        self.assertEqual(inspected.payload["episode"]["status"], "open")
        self.assertEqual(inspected.payload["lineage"], [inspected.payload["episode"]])
        self.assertEqual(inspected.payload["latest_loop"], None)
        self.assertEqual(inspected.payload["progression"]["ring_index"], 1)
        self.assertEqual(inspected.payload["progression"]["stage_title"], "learning the path")

        interrupted = self.app.dispatch(
            "POST",
            "/v1/episodes/session-1/interrupt",
            body=self._body({"interruption_state": "user-paused"}),
        )
        self.assertEqual(interrupted.status_code, 200)
        self.assertEqual(interrupted.payload["episode"]["status"], "paused")

        next_episode = self.app.dispatch(
            "POST",
            "/v1/episodes/session-1/next",
            body=self._body({"child_episode_id": "session-2"}),
        )
        self.assertEqual(next_episode.status_code, 200)
        self.assertEqual(next_episode.payload["episode"]["episode_id"], "session-2")
        self.assertEqual(next_episode.payload["parent_episode"]["episode_id"], "session-1")
        self.assertEqual(
            [item["episode_id"] for item in next_episode.payload["lineage"]],
            ["session-1", "session-2"],
        )

    def test_kernel_backed_turn_execution_and_controlled_tool_path(self) -> None:
        self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "elephant_id": "elephant-1",
                    "provider_profile": self._provider_profile(
                        profile_id="provider-openrouter",
                        base_url=self.stub.openai_base_url,
                        extra_headers={"x-tenant": "elephant"},
                    ),
                    "episode_id": "session-turn",
                }
            ),
        )
        turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-turn/loops",
            body=self._body(
                {
                    "prompt": "What should we do next?",
                    "state_query": "Continue the release plan",
                }
            ),
        )
        self.assertEqual(turn.status_code, 200)
        self.assertEqual(turn.payload["episode"]["episode_id"], "session-turn")
        self.assertEqual(turn.payload["outcome"]["event"]["episode_id"], "session-turn")
        self.assertEqual(turn.payload["outcome"]["event"]["payload"]["state_query"], "Continue the release plan")
        self.assertEqual(turn.payload["outcome"]["state"]["elephant_id"], "elephant-1")
        self.assertNotIn("active_task", turn.payload["outcome"]["state"])
        self.assertGreaterEqual(len(turn.payload["outcome"]["stages"]), 6)
        self.assertGreaterEqual(len(turn.payload["outcome"]["steps"]), 6)
        self.assertGreaterEqual(turn.payload["inspection"]["recall_count"], 0)
        self.assertGreaterEqual(turn.payload["inspection"]["telemetry_count"], 1)
        self.assertEqual(turn.payload["inspection"]["progression"]["stage_title"], "learning the path")
        self.assertTrue(
            turn.payload["outcome"]["execution"]["summary"].startswith(
                "live-chat:What should we do next?"
            )
        )
        self.assertIn("transport=openai_chat_compatible", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertIn("credential_keys=api_key", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertEqual(turn.payload["inspection"]["provider_profile"]["profile_id"], "provider-openrouter")

        tool_turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-turn/loops",
            body=self._body(
                {
                    "prompt": "Run the controlled path",
                    "tool_name": "tool.skill.list",
                    "tool_arguments": {"limit": 3},
                }
            ),
        )
        self.assertEqual(tool_turn.status_code, 200)
        self.assertEqual(tool_turn.payload["outcome"]["execution"]["outcome"], "success")
        self.assertIn("skill", tool_turn.payload["outcome"]["execution"]["side_effects"])
        self.assertNotEqual(tool_turn.payload["outcome"]["execution"]["summary"].strip(), "<empty>")
        self.assertEqual(tool_turn.payload["latest_loop"]["request"]["tool_name"], "tool.skill.list")
        self.assertEqual(tool_turn.payload["inspection"]["latest_loop"]["request"]["tool_name"], "tool.skill.list")

        code_turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-turn/loops",
            body=self._body(
                {
                    "prompt": "Run code after approval",
                    "tool_name": "tool.code.execute",
                    "tool_arguments": {"code": "print('hello api tool')"},
                }
            ),
        )
        self.assertEqual(code_turn.status_code, 200)
        self.assertEqual(code_turn.payload["outcome"]["execution"]["outcome"], "deferred")
        self.assertIn("Execution surfaces", code_turn.payload["outcome"]["execution"]["summary"])
        code_records = [
            record
            for record in self.app.tool_runtime.list_executions()
            if record.invocation.session_id == "session-turn"
            and record.invocation.tool_id == "tool.code.execute"
        ]
        self.assertEqual(code_records[-1].approval.decision, "deferred")
        self.assertIn("explicit-approval", code_records[-1].approval.required_controls)
        self.assertEqual(code_turn.payload["latest_loop"]["request"]["tool_name"], "tool.code.execute")
        self.assertEqual(code_turn.payload["inspection"]["latest_loop"]["request"]["tool_name"], "tool.code.execute")

        clarify_turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-turn/loops",
            body=self._body(
                {
                    "prompt": "Use beta",
                    "tool_name": "tool.clarify",
                    "tool_arguments": {
                        "question": "Which target?",
                        "choices": ["alpha", "beta"],
                        "user_response": "beta",
                    },
                }
            ),
        )
        self.assertEqual(clarify_turn.status_code, 200)
        self.assertEqual(clarify_turn.payload["outcome"]["execution"]["outcome"], "success")
        self.assertIn("user_response: beta", clarify_turn.payload["outcome"]["execution"]["summary"])
        self.assertEqual(clarify_turn.payload["latest_loop"]["request"]["tool_name"], "tool.clarify")

        inspect = self.app.dispatch("GET", "/v1/episodes/session-turn")
        self.assertEqual(inspect.status_code, 200)
        self.assertEqual(inspect.payload["latest_loop"]["request"]["tool_name"], "tool.clarify")
        self.assertEqual(inspect.payload["lineage"][0]["episode_id"], "session-turn")
        self.assertTrue(inspect.payload["recall_items"])
        self.assertEqual(inspect.payload["recall_items"][0]["source_kind"], "step")

        for method, route in (
            ("GET", "/v1/episodes/session-turn/goals"),
            ("POST", "/v1/episodes/session-turn/goals"),
            ("GET", "/v1/episodes/session-turn/goals/work-launch"),
            ("PATCH", "/v1/episodes/session-turn/goals/work-launch"),
        ):
            with self.subTest(method=method, route=route):
                self.assertEqual(self.app.dispatch(method, route, body=self._body({})).status_code, 404)

        profile_surface = self.app.dispatch("GET", "/v1/episodes/session-turn/profile")
        self.assertEqual(profile_surface.status_code, 200)
        self.assertEqual(profile_surface.payload["personal_model"]["profile_id"], "profile-companion")

        work_surface = self.app.dispatch("GET", "/v1/episodes/session-turn/activity")
        self.assertEqual(work_surface.status_code, 404)

        recall_surface = self.app.dispatch("GET", "/v1/episodes/session-turn/recall/evidence")
        self.assertEqual(recall_surface.status_code, 200)
        self.assertTrue(recall_surface.payload["evidence"])

        procedure_surface = self.app.dispatch("GET", "/v1/episodes/session-turn/procedure")
        self.assertEqual(procedure_surface.status_code, 404)

        audit_surface = self.app.dispatch("GET", "/v1/episodes/session-turn/audit")
        self.assertEqual(audit_surface.status_code, 404)

    def test_api_chat_runtime_exposes_model_tools_and_skill_context(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-api-tools",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "elephant_id": "elephant-api-tools",
                    "episode_id": "session-api-tools",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        session = self.app.repository.load_episode_state("session-api-tools")
        self.assertIsNotNone(session)

        model_visible = {
            tool.tool_id
            for tool in self.app.tool_runtime.list_tools(
                audience="model",
                enabled_only=True,
                available_only=True,
            )
        }
        self.assertIn("tool.skill.list", model_visible)
        self.assertIn("tool.skill.view", model_visible)
        self.assertIn("tool.personal_model.search", model_visible)
        self.assertIn("tool.personal_model.update", model_visible)
        self.assertIn("tool.personal_model.questions", model_visible)
        self.assertNotIn("tool.evidence.recall", model_visible)
        self.assertNotIn("tool.evidence.note", model_visible)
        self.assertNotIn("tool.skill.manage", model_visible)

        bundle = self.app.context.assemble(session, (), ())
        self.assertIn("### Understanding tools", bundle.prompt_envelope.frozen_prefix)
        self.assertIn("Use `tool.personal_model.search`", bundle.rendered_prompt)

        result = self.app.kernel.dependencies.tools.invoke(
            "tool.skill.list",
            {"limit": 4},
            session_id=session.episode_id,
        )
        self.assertEqual(result.outcome, "success")
        self.assertIn("skill", result.side_effects)
        self.assertNotEqual(result.summary.strip(), "<empty>")

    def test_api_chat_runtime_defers_high_risk_local_tool_side_effects(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-api-approval",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "elephant_id": "elephant-api-approval",
                    "episode_id": "session-api-approval",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        target = Path(self.tempdir.name) / "approval-should-not-write.txt"

        file_write = self.app.tool_runtime.invoke(
            "tool.file.write",
            {"path": str(target), "content": "unsafe write\n"},
            session_id="session-api-approval",
            requester="model",
        )
        terminal = self.app.tool_runtime.invoke(
            "tool.terminal.exec",
            {"command": f"printf terminal-write > {target}"},
            session_id="session-api-approval",
            requester="model",
        )

        self.assertEqual(file_write.outcome, "deferred")
        self.assertEqual(terminal.outcome, "deferred")
        self.assertFalse(target.exists())
        deferred = [
            record
            for record in self.app.tool_runtime.list_executions()
            if record.invocation.session_id == "session-api-approval"
        ]
        self.assertEqual([record.approval.decision for record in deferred], ["deferred", "deferred"])
        self.assertTrue(all(not record.approved for record in deferred))

    def test_canonical_state_routes_expose_identity_user_relationship_and_continuity(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-state",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "elephant_id": "elephant-state",
                    "episode_id": "session-state",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        identity = self.app.dispatch("GET", "/v1/episodes/session-state/identity")
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.payload["identity"]["display_name"], "Elephant Agent")

        updated_identity = self.app.dispatch(
            "PATCH",
            "/v1/episodes/session-state/identity",
            body=self._body(
                {
                    "display_name": "Atlas",
                    "personality_preset": "operator",
                    "initiative": "proactive",
                    "elephant_identity_text": "Stay durable and exact.",
                }
            ),
        )
        self.assertEqual(updated_identity.status_code, 200)
        self.assertEqual(updated_identity.payload["identity"]["display_name"], "Atlas")
        self.assertEqual(updated_identity.payload["identity"]["personality_preset"], "operator")
        self.assertEqual(updated_identity.payload["identity"]["initiative"], "proactive")

        updated_user = self.app.dispatch(
            "PATCH",
            "/v1/episodes/session-state/user",
            body=self._body(
                {
                    "fields": {
                        "preferred_name": "Bit",
                        "current_work": "Build Elephant Agent",
                        "boundaries": "Prefer direct updates.",
                    }
                }
            ),
        )
        self.assertEqual(updated_user.status_code, 200)
        self.assertEqual(updated_user.payload["user"]["preferred_name"], "Bit")
        self.assertIn("current_work:Build Elephant Agent", updated_user.payload["user"]["biography_fragments"])

        updated_relationship = self.app.dispatch(
            "PATCH",
            "/v1/episodes/session-state/relationship",
            body=self._body({"text": "Keep replies concise and grounded."}),
        )
        self.assertEqual(updated_relationship.status_code, 200)
        self.assertIn(
            "Keep replies concise and grounded.",
            updated_relationship.payload["relationship"]["continuity_notes"],
        )

        continuity = self.app.dispatch("GET", "/v1/episodes/session-state/continuity")
        self.assertEqual(continuity.status_code, 200)
        self.assertEqual(continuity.payload["personal_model"]["profile_id"], "profile-state")
        self.assertEqual(continuity.payload["identity"]["display_name"], "Atlas")
        self.assertEqual(continuity.payload["user"]["preferred_name"], "Bit")
        self.assertIn(
            "Keep replies concise and grounded.",
            continuity.payload["relationship"]["continuity_notes"],
        )
        self.assertIn("wake_action", continuity.payload)
        self.assertIn("wake_summary", continuity.payload)
        self.assertIn("continuity", continuity.payload)

    def test_elephant_management_routes_create_update_delete_state_file_and_level(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/herd",
            body=self._body(
                {
                    "display_name": "Atlas",
                    "elephant_identity_text": "# Elephant Identity: Atlas\n\n- Calm operator vibe.",
                }
            ),
        )

        self.assertEqual(created.status_code, 201)
        state = self.app.repository.load_state("state:atlas")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.elephant_name, "Atlas")
        state_file = elephant_file_path("atlas", install_root=Path(self.tempdir.name)) / "ELEPHANT.md"
        self.assertTrue(state_file.exists())
        self.assertIn("Calm operator vibe", state_file.read_text(encoding="utf-8"))

        updated = self.app.dispatch(
            "PATCH",
            "/v1/herd/atlas",
            body=self._body(
                {
                    "display_name": "Atlas Prime",
                    "personality_preset": "operator",
                    "initiative": "proactive",
                    "elephant_identity_text": "# Elephant Identity: Atlas Prime\n\n- Direct review vibe.",
                }
            ),
        )
        self.assertEqual(updated.status_code, 200)
        refreshed_state = self.app.repository.load_state("state:atlas")
        self.assertIsNotNone(refreshed_state)
        assert refreshed_state is not None
        self.assertEqual(refreshed_state.elephant_name, "Atlas Prime")
        self.assertEqual(refreshed_state.working_style, "operator")
        self.assertEqual(refreshed_state.initiative, "proactive")
        self.assertIn("Direct review vibe", state_file.read_text(encoding="utf-8"))

        self.app.repository.upsert_personal_model_growth(
            PersonalModelGrowthState(
                profile_id="you",
                growth_score=480,
                total_dialogues=12,
                total_tokens=3400,
                created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
        )
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/herd")
        self.assertEqual(dashboard.status_code, 200)
        elephant = next(row for row in dashboard.payload["dashboard"]["herd"] if row["elephant_id"] == "atlas")
        self.assertEqual(elephant["elephant_name"], "Atlas Prime")
        self.assertIn("level", elephant)
        self.assertIn("checkpoint_label", elephant)
        self.assertNotIn("growth_score", elephant)
        self.assertIn("Direct review vibe", elephant["elephant_identity_file"]["text"])

        deleted = self.app.dispatch("DELETE", "/v1/herd/atlas")
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(self.app.repository.load_state("state:atlas"))
        self.assertFalse(state_file.exists())

    def test_turn_without_seed_graph_does_not_form_a_goal_from_prompt_alone(self) -> None:
        self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "episode_id": "session-auto-work",
                }
            ),
        )

        turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-auto-work/loops",
            body=self._body({"prompt": "Implement the current-work lifecycle in Elephant Agent."}),
        )

        self.assertEqual(turn.status_code, 200)
        self.assertNotIn("goals", turn.payload["inspection"])
        self.assertNotIn("work_items", turn.payload["inspection"])
        self.assertNotIn("active_task", turn.payload["outcome"]["state"])
        self.assertIn("current-work lifecycle", turn.payload["outcome"]["event"]["payload"]["message"])

    def test_turn_does_not_mutate_profile_without_explicit_profile_surface(self) -> None:
        self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-turn-profile-guard",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "episode_id": "session-turn-profile-guard",
                }
            ),
        )

        turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-turn-profile-guard/loops",
            body=self._body(
                {
                    "prompt": "Call me Bit. I'm building durable agent systems. Please keep replies concise and grounded for future turns.",
                }
            ),
        )
        self.assertEqual(turn.status_code, 200)

        continuity = self.app.dispatch("GET", "/v1/episodes/session-turn-profile-guard/continuity")
        self.assertEqual(continuity.status_code, 200)
        self.assertIsNone(continuity.payload["user"]["preferred_name"])
        self.assertEqual(continuity.payload["user"]["communication_preferences"], [])
        self.assertEqual(continuity.payload["user"]["biography_fragments"], [])
        self.assertEqual(continuity.payload["relationship"]["continuity_notes"], [])

    def test_turn_without_seed_graph_uses_explicit_state_query(self) -> None:
        self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-companion-explicit",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "episode_id": "session-explicit-work",
                }
            ),
        )

        turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-explicit-work/loops",
            body=self._body(
                {
                    "prompt": "Implement the current-work lifecycle in Elephant Agent.",
                    "state_query": "Implement the current-work lifecycle in Elephant Agent.",
                }
            ),
        )

        self.assertEqual(turn.status_code, 200)
        self.assertNotIn("active_task", turn.payload["outcome"]["state"])
        self.assertIn("current-work lifecycle", turn.payload["outcome"]["event"]["payload"]["state_query"].lower())


















if __name__ == "__main__":
    unittest.main()
