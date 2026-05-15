from __future__ import annotations

import os
import json
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import threading
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api import create_app
from packages.auth import AuthProfile, ProviderAuthState, SecretReference
from packages.runtime_config import global_config_path_for_state_dir, load_global_config
from packages.contracts import (
    Episode,
    ExecutionResult,
    Fact,
    Loop,
    PersonalModel,
    PersonalModelGrowthState,
    SemanticIndexEntry,
    State,
    Step,
    StructuredTurnRecord,
    StructuredTurnSlot,
)
from packages.evidence import build_structured_turn_memory
from packages.kernel.loop_checkpoint_support import LoopCheckpointService
from packages.runtime_config import parse_global_config_text
from packages.runtime_layout import elephant_file_path


class _ProviderStubServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.state = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def openai_base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    @property
    def anthropic_base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "_ProviderStubServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            @staticmethod
            def _responses_input_text(value) -> str:
                if isinstance(value, str):
                    return value
                if isinstance(value, list):
                    texts: list[str] = []
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        content = item.get("content", ())
                        if isinstance(content, list):
                            for block in content:
                                if not isinstance(block, dict):
                                    continue
                                text = block.get("text")
                                if isinstance(text, str):
                                    texts.append(text)
                    return "".join(texts)
                return ""

            def do_POST(self) -> None:  # noqa: N802
                server_state = self.server.state  # type: ignore[attr-defined]
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body.decode("utf-8"))
                server_state.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "payload": payload,
                    }
                )
                if self.path == "/v1/chat/completions":
                    response = {
                        "id": "chatcmpl-stub",
                        "model": payload["model"],
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": f"live-chat:{payload['messages'][-1]['content']}",
                                }
                            }
                        ],
                        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                    }
                elif self.path == "/v1/responses":
                    content = f"live-response:{Handler._responses_input_text(payload.get('input'))}"
                    if payload.get("stream"):
                        midpoint = max(1, len(content) // 2)
                        events = (
                            ("response.output_text.delta", {"delta": content[:midpoint]}),
                            ("response.output_text.delta", {"delta": content[midpoint:]}),
                            (
                                "response.completed",
                                {
                                    "response": {
                                        "id": "resp-stub",
                                        "model": payload["model"],
                                        "output_text": content,
                                        "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
                                    }
                                },
                            ),
                        )
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        for event_name, event_payload in events:
                            self.wfile.write(f"event: {event_name}\n".encode("utf-8"))
                            self.wfile.write(f"data: {json.dumps(event_payload)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        return
                    response = {
                        "id": "resp-stub",
                        "model": payload["model"],
                        "output_text": content,
                        "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
                    }
                elif self.path == "/v1/messages":
                    response = {
                        "id": "msg-stub",
                        "model": payload["model"],
                        "content": [
                            {
                                "type": "text",
                                "text": f"live-anthropic:{payload['messages'][0]['content'][0]['text'].splitlines()[0]}",
                            }
                        ],
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 8, "output_tokens": 4},
                    }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                server_state = self.server.state  # type: ignore[attr-defined]
                server_state.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "payload": None,
                    }
                )
                if self.path == "/v1/models":
                    response = {
                        "data": [
                            {"id": "openai/gpt-4o-mini", "owned_by": "stub", "context_window": 128000},
                            {"id": "openai/gpt-4.1-mini", "owned_by": "stub"},
                        ]
                    }
                    encoded = json.dumps(response).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                self.send_response(404)
                self.end_headers()

        return Handler


class APISurfaceE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.stub = _ProviderStubServer().start()
        self._previous_openrouter_secret = os.environ.get("ELEPHANT_OPENROUTER_API_KEY")
        self._previous_openai_secret = os.environ.get("ELEPHANT_OPENAI_API_KEY")
        self._previous_anthropic_secret = os.environ.get("ELEPHANT_ANTHROPIC_API_KEY")
        os.environ["ELEPHANT_OPENROUTER_API_KEY"] = "sk-api-test-123"
        os.environ["ELEPHANT_OPENAI_API_KEY"] = "sk-openai-test-456"
        os.environ["ELEPHANT_ANTHROPIC_API_KEY"] = "sk-anthropic-test-789"
        self.app = create_app(
            database_path=Path(self.tempdir.name) / "api.sqlite3",
            install_root=Path(self.tempdir.name),
        )

    def tearDown(self) -> None:
        if self._previous_openrouter_secret is None:
            os.environ.pop("ELEPHANT_OPENROUTER_API_KEY", None)
        else:
            os.environ["ELEPHANT_OPENROUTER_API_KEY"] = self._previous_openrouter_secret
        if self._previous_openai_secret is None:
            os.environ.pop("ELEPHANT_OPENAI_API_KEY", None)
        else:
            os.environ["ELEPHANT_OPENAI_API_KEY"] = self._previous_openai_secret
        if self._previous_anthropic_secret is None:
            os.environ.pop("ELEPHANT_ANTHROPIC_API_KEY", None)
        else:
            os.environ["ELEPHANT_ANTHROPIC_API_KEY"] = self._previous_anthropic_secret
        self.stub.close()
        self.tempdir.cleanup()

    def _provider_profile(
        self,
        *,
        profile_id: str = "provider-openrouter",
        provider_id: str = "openai-compatible",
        base_url: str | None = None,
        default_model: str | None = "openai/gpt-4o-mini",
        reference_id: str = "secret-openrouter-token",
        env_var: str = "ELEPHANT_OPENROUTER_API_KEY",
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "profile_id": profile_id,
            "provider_id": provider_id,
            "secret_references": [
                {
                    "reference_id": reference_id,
                    "provider_id": provider_id,
                    "secret_name": "api_token",
                    "secret_key": "api_key",
                    "metadata": {"env_var": env_var},
                }
            ],
        }
        if base_url is not None:
            payload["base_url"] = base_url
        if default_model is not None:
            payload["default_model"] = default_model
        if extra_headers:
            payload["extra_headers"] = extra_headers
        return payload

    def test_session_lifecycle_inspection_and_resume(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
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
                    "session_id": "session-1",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.payload["session"]["session_id"], "session-1")

        inspected = self.app.dispatch("GET", "/v1/sessions/session-1")
        self.assertEqual(inspected.status_code, 200)
        self.assertEqual(inspected.payload["session"]["status"], "active")
        self.assertEqual(inspected.payload["lineage"], [inspected.payload["session"]])
        self.assertEqual(inspected.payload["latest_turn"], None)
        self.assertEqual(inspected.payload["progression"]["ring_index"], 1)
        self.assertEqual(inspected.payload["progression"]["stage_title"], "learning the path")

        interrupted = self.app.dispatch(
            "POST",
            "/v1/sessions/session-1/interrupt",
            body=self._body({"interruption_state": "user-paused"}),
        )
        self.assertEqual(interrupted.status_code, 200)
        self.assertEqual(interrupted.payload["session"]["status"], "interrupted")

        resumed = self.app.dispatch(
            "POST",
            "/v1/sessions/session-1/resume",
            body=self._body({"child_session_id": "session-2"}),
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.payload["session"]["session_id"], "session-2")
        self.assertEqual(resumed.payload["parent"]["session_id"], "session-1")
        self.assertEqual(
            [item["session_id"] for item in resumed.payload["lineage"]],
            ["session-1", "session-2"],
        )

    def test_kernel_backed_turn_execution_and_controlled_tool_path(self) -> None:
        self.app.dispatch(
            "POST",
            "/v1/sessions",
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
                    "session_id": "session-turn",
                }
            ),
        )
        turn = self.app.dispatch(
            "POST",
            "/v1/sessions/session-turn/turns",
            body=self._body(
                {
                    "prompt": "What should we do next?",
                    "state_query": "Continue the release plan",
                }
            ),
        )
        self.assertEqual(turn.status_code, 200)
        self.assertEqual(turn.payload["session"]["session_id"], "session-turn")
        self.assertEqual(turn.payload["outcome"]["event"]["session_id"], "session-turn")
        self.assertEqual(turn.payload["outcome"]["event"]["payload"]["state_query"], "Continue the release plan")
        self.assertEqual(turn.payload["outcome"]["state"]["elephant_id"], "elephant-1")
        self.assertNotIn("active_task", turn.payload["outcome"]["state"])
        self.assertGreaterEqual(len(turn.payload["outcome"]["stages"]), 6)
        self.assertGreaterEqual(len(turn.payload["outcome"]["steps"]), 6)
        self.assertEqual(turn.payload["inspection"]["memory_count"], 0)
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
            "/v1/sessions/session-turn/turns",
            body=self._body(
                {
                    "prompt": "Run the controlled path",
                    "tool_name": "tool.code.execute",
                    "tool_arguments": {"code": "print('hello api tool')"},
                }
            ),
        )
        self.assertEqual(tool_turn.status_code, 200)
        self.assertEqual(tool_turn.payload["outcome"]["execution"]["outcome"], "success")
        self.assertEqual(tool_turn.payload["outcome"]["execution"]["side_effects"], ["code", "python", "sandbox"])
        self.assertIn("hello api tool", tool_turn.payload["outcome"]["execution"]["summary"])
        self.assertEqual(tool_turn.payload["latest_turn"]["request"]["tool_name"], "tool.code.execute")
        self.assertEqual(tool_turn.payload["inspection"]["latest_turn"]["request"]["tool_name"], "tool.code.execute")

        clarify_turn = self.app.dispatch(
            "POST",
            "/v1/sessions/session-turn/turns",
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
        self.assertEqual(clarify_turn.payload["latest_turn"]["request"]["tool_name"], "tool.clarify")

        inspect = self.app.dispatch("GET", "/v1/sessions/session-turn")
        self.assertEqual(inspect.status_code, 200)
        self.assertEqual(inspect.payload["latest_turn"]["request"]["tool_name"], "tool.clarify")
        self.assertEqual(inspect.payload["lineage"][0]["session_id"], "session-turn")
        self.assertEqual(inspect.payload["memories"], [])

        for method, route in (
            ("GET", "/v1/sessions/session-turn/goals"),
            ("POST", "/v1/sessions/session-turn/goals"),
            ("GET", "/v1/sessions/session-turn/goals/work-launch"),
            ("PATCH", "/v1/sessions/session-turn/goals/work-launch"),
        ):
            with self.subTest(method=method, route=route):
                self.assertEqual(self.app.dispatch(method, route, body=self._body({})).status_code, 404)

        profile_surface = self.app.dispatch("GET", "/v1/sessions/session-turn/profile")
        self.assertEqual(profile_surface.status_code, 200)
        self.assertEqual(profile_surface.payload["profile"]["profile_id"], "profile-companion")

        work_surface = self.app.dispatch("GET", "/v1/sessions/session-turn/activity")
        self.assertEqual(work_surface.status_code, 404)

        memory_surface = self.app.dispatch("GET", "/v1/sessions/session-turn/memory")
        self.assertEqual(memory_surface.status_code, 200)
        self.assertEqual(memory_surface.payload["memory"]["memories"], [])

        procedure_surface = self.app.dispatch("GET", "/v1/sessions/session-turn/procedure")
        self.assertEqual(procedure_surface.status_code, 404)

        audit_surface = self.app.dispatch("GET", "/v1/sessions/session-turn/audit")
        self.assertEqual(audit_surface.status_code, 404)

    def test_api_chat_runtime_exposes_model_tools_and_skill_context(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-api-tools",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "elephant_id": "elephant-api-tools",
                    "session_id": "session-api-tools",
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
        self.assertNotIn("tool.memory.recall", model_visible)
        self.assertNotIn("tool.memory.note", model_visible)
        self.assertNotIn("tool.skill.manage", model_visible)

        bundle = self.app.context.assemble(session, (), ())
        self.assertIn("### Memory tools", bundle.prompt_envelope.frozen_prefix)
        self.assertIn("Use `tool.personal_model.search`", bundle.rendered_prompt)

        result = self.app.kernel.dependencies.tools.invoke(
            "tool.skill.list",
            {"limit": 4},
            session_id=session.episode_id,
        )
        self.assertEqual(result.outcome, "success")
        self.assertIn("skill", result.side_effects)
        self.assertNotEqual(result.summary.strip(), "<empty>")

    def test_canonical_state_routes_expose_identity_user_relationship_and_continuity(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-state",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "elephant_id": "elephant-state",
                    "session_id": "session-state",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        identity = self.app.dispatch("GET", "/v1/sessions/session-state/identity")
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.payload["identity"]["display_name"], "Elephant Agent")

        updated_identity = self.app.dispatch(
            "PATCH",
            "/v1/sessions/session-state/identity",
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
            "/v1/sessions/session-state/user",
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
            "/v1/sessions/session-state/relationship",
            body=self._body({"text": "Keep replies concise and grounded."}),
        )
        self.assertEqual(updated_relationship.status_code, 200)
        self.assertIn(
            "Keep replies concise and grounded.",
            updated_relationship.payload["relationship"]["continuity_notes"],
        )

        continuity = self.app.dispatch("GET", "/v1/sessions/session-state/continuity")
        self.assertEqual(continuity.status_code, 200)
        self.assertEqual(continuity.payload["profile"]["profile_id"], "profile-state")
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
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "session_id": "session-auto-work",
                }
            ),
        )

        turn = self.app.dispatch(
            "POST",
            "/v1/sessions/session-auto-work/turns",
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
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-turn-profile-guard",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "session_id": "session-turn-profile-guard",
                }
            ),
        )

        turn = self.app.dispatch(
            "POST",
            "/v1/sessions/session-turn-profile-guard/turns",
            body=self._body(
                {
                    "prompt": "Call me Bit. I'm building durable agent systems. Please keep replies concise and grounded for future turns.",
                }
            ),
        )
        self.assertEqual(turn.status_code, 200)

        continuity = self.app.dispatch("GET", "/v1/sessions/session-turn-profile-guard/continuity")
        self.assertEqual(continuity.status_code, 200)
        self.assertIsNone(continuity.payload["user"]["preferred_name"])
        self.assertEqual(continuity.payload["user"]["communication_preferences"], [])
        self.assertEqual(continuity.payload["user"]["biography_fragments"], [])
        self.assertEqual(continuity.payload["relationship"]["continuity_notes"], [])

    def test_turn_without_seed_graph_uses_explicit_state_query(self) -> None:
        self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-companion-explicit",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "session_id": "session-explicit-work",
                }
            ),
        )

        turn = self.app.dispatch(
            "POST",
            "/v1/sessions/session-explicit-work/turns",
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

    def test_openai_provider_profile_uses_first_party_runtime_resolution(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-openai",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "provider_profile": self._provider_profile(
                        profile_id="provider-openai",
                        provider_id="openai",
                        base_url=self.stub.openai_base_url,
                        default_model=None,
                        reference_id="secret-openai-token",
                        env_var="ELEPHANT_OPENAI_API_KEY",
                    ),
                    "session_id": "session-openai",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        turn = self.app.dispatch(
            "POST",
            "/v1/sessions/session-openai/turns",
            body=self._body({"prompt": "Summarize the next release step."}),
        )
        self.assertEqual(turn.status_code, 200)
        self.assertTrue(
            turn.payload["outcome"]["execution"]["summary"].startswith(
                "live-response:Summarize the next release step."
            )
        )
        self.assertIn("transport=openai_responses", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertIn("credential_keys=api_key", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertEqual(turn.payload["inspection"]["provider_profile"]["provider_id"], "openai")

    def test_anthropic_provider_profile_uses_native_messages_runtime(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-anthropic",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "provider_profile": self._provider_profile(
                        profile_id="provider-anthropic",
                        provider_id="anthropic",
                        base_url=self.stub.anthropic_base_url,
                        default_model=None,
                        reference_id="secret-anthropic-token",
                        env_var="ELEPHANT_ANTHROPIC_API_KEY",
                    ),
                    "session_id": "session-anthropic",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        turn = self.app.dispatch(
            "POST",
            "/v1/sessions/session-anthropic/turns",
            body=self._body({"prompt": "Explain the provider boundary."}),
        )
        self.assertEqual(turn.status_code, 200)
        self.assertEqual(
            turn.payload["outcome"]["execution"]["summary"],
            "live-anthropic:Explain the provider boundary.",
        )
        self.assertIn("transport=anthropic_messages", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertIn("credential_keys=api_key", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertEqual(turn.payload["inspection"]["provider_profile"]["transport_id"], "anthropic_messages")

    def test_provider_onboarding_and_default_provider_flow(self) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-openrouter",
            base_url=self.stub.openai_base_url,
            reference_id="secret-openrouter-token",
            extra_headers={"x-tenant": "elephant"},
        )

        listed = self.app.dispatch("GET", "/v1/providers")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.payload["active_provider"]["provider_id"], "preview")
        self.assertTrue(any(item["provider_id"] == "openai-compatible" for item in listed.payload["providers"]))

        setup = self.app.dispatch("GET", "/v1/providers/setup/openai-compatible")
        self.assertEqual(setup.status_code, 200)
        self.assertIn("base_url", setup.payload["guide"]["required_config_keys"])
        self.assertIn("model_id", setup.payload["guide"]["required_config_keys"])

        models = self.app.dispatch(
            "POST",
            "/v1/providers/models",
            body=self._body({"providerId": "openai-compatible", "baseUrl": self.stub.openai_base_url}),
        )
        self.assertEqual(models.status_code, 200)
        self.assertEqual(models.payload["providerId"], "openai-compatible")
        self.assertIn("openai/gpt-4o-mini", [model["model_id"] for model in models.payload["models"]])

        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)
        self.assertEqual(defaulted.payload["provider_profile"]["provider_id"], "openai-compatible")
        self.assertEqual(defaulted.payload["provider_profile"]["base_url"], self.stub.openai_base_url)
        self.assertEqual(defaulted.payload["active_provider"]["provider_id"], "openai-compatible")
        self.assertEqual(defaulted.payload["active_provider"]["model_id"], "openai/gpt-4o-mini")
        self.assertEqual(defaulted.payload["active_provider"]["context_window_tokens"], 128000)
        self.assertEqual(defaulted.payload["active_provider"]["context_window_mode"], "auto")
        self.assertIn(defaulted.payload["active_provider"]["embedding_bootstrap_status"], {"ready", "pending", "downloading"})
        config = load_global_config(
            global_config_path_for_state_dir(self.app.repository.database_path.parent),
            state_dir=self.app.repository.database_path.parent,
        )
        provider_config = config["models"]["provider"]
        self.assertEqual(
            provider_config["provider_id"],
            "openai-compatible",
        )
        self.assertEqual(
            provider_config["default_model"],
            "openai/gpt-4o-mini",
        )
        self.assertEqual(
            provider_config["metadata"]["context_window_tokens"],
            128000,
        )

        keys = self.app.dispatch("GET", "/v1/providers/keys")
        self.assertEqual(keys.status_code, 200)
        self.assertTrue(any(key["referenceId"] == "secret-openrouter-token" for key in keys.payload["keys"]))
        saved_key = self.app.dispatch(
            "PATCH",
            "/v1/providers/keys/secret-openrouter-token",
            body=self._body({"value": "sk-updated-provider-key"}),
        )
        self.assertEqual(saved_key.status_code, 200)
        self.assertTrue(saved_key.payload["hasValue"])

        initial_embedding = self.app.dispatch("GET", "/v1/providers/embeddings")
        self.assertEqual(initial_embedding.status_code, 200)
        self.assertEqual(initial_embedding.payload["embedding_provider"]["source"], "local-default")
        external_embedding = self.app.dispatch(
            "POST",
            "/v1/providers/embeddings",
            body=self._body(
                {
                    "source": "openai-compatible",
                    "baseUrl": self.stub.openai_base_url,
                    "modelId": "text-embedding-3-large",
                    "dimensions": 1536,
                    "apiKey": "sk-embedding-test",
                }
            ),
        )
        self.assertEqual(external_embedding.status_code, 200)
        self.assertEqual(external_embedding.payload["embedding_provider"]["source"], "configured")
        self.assertEqual(external_embedding.payload["embedding_provider"]["model_id"], "text-embedding-3-large")
        self.assertEqual(external_embedding.payload["embedding_provider"]["secret_status"], "stored")
        local_embedding = self.app.dispatch(
            "POST",
            "/v1/providers/embeddings",
            body=self._body({"source": "elephant-embed"}),
        )
        self.assertEqual(local_embedding.status_code, 200)
        self.assertEqual(local_embedding.payload["embedding_provider"]["source"], "local-default")
        self.assertIn(
            local_embedding.payload["embedding_provider"]["embedding_bootstrap_status"],
            {"ready", "pending", "downloading"},
        )

        doctor = self.app.dispatch("GET", "/v1/providers/doctor")
        self.assertEqual(doctor.status_code, 200)
        self.assertEqual(doctor.payload["status"], "ready")
        self.assertEqual(doctor.payload["active_provider"]["provider_id"], "openai-compatible")
        self.assertIn("runtime", [check["check"] for check in doctor.payload["checks"]])
        self.assertIn("embedding_bootstrap", [check["check"] for check in doctor.payload["checks"]])

        test = self.app.dispatch(
            "POST",
            "/v1/providers/test",
            body=self._body({"prompt": "Summarize the provider setup."}),
        )
        self.assertEqual(test.status_code, 200)
        self.assertEqual(test.payload["result"]["summary"], "live-chat:Summarize the provider setup.")

        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-defaulted",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "session_id": "session-defaulted",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        turn = self.app.dispatch(
            "POST",
            "/v1/sessions/session-defaulted/turns",
            body=self._body({"prompt": "What should we do next?"}),
        )
        self.assertEqual(turn.status_code, 200)
        execution = (
            turn.payload["outcome"].execution
            if hasattr(turn.payload["outcome"], "execution")
            else turn.payload["outcome"]["execution"]
        )
        execution_summary = execution.summary if hasattr(execution, "summary") else execution["summary"]
        self.assertTrue(
            execution_summary.startswith(
                "live-chat:What should we do next?"
            )
        )
        inspection = turn.payload["inspection"]
        provider_profile = (
            inspection.provider_profile
            if hasattr(inspection, "provider_profile")
            else inspection["provider_profile"]
        )
        provider_id = (
            provider_profile.provider_id
            if hasattr(provider_profile, "provider_id")
            else provider_profile["provider_id"]
        )
        self.assertEqual(provider_id, "openai-compatible")
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/usage")
        self.assertEqual(dashboard.status_code, 200)
        usage = dashboard.payload["dashboard"]["operations"]["usage"]
        self.assertGreaterEqual(usage["summary"]["runtimeStepUsageEvents"], 1)
        self.assertTrue(usage["tokenEvents"])

    def test_api_runtime_restores_active_provider_from_profile_manifest(self) -> None:
        root = Path(self.tempdir.name) / "restored-runtime"
        state_dir = root / "state"
        profile_dir = root / "profile"
        state_dir.mkdir(parents=True)
        profile_dir.mkdir(parents=True)
        config_path = global_config_path_for_state_dir(state_dir)
        config_path.write_text(
            json.dumps(
                {
                    "runtime": {
                        "state_dir": str(state_dir),
                        "default_profile_id": "default",
                    },
                    "models": {
                        "default_provider_source": "config",
                        "provider": self._provider_profile(
                            profile_id="provider-openrouter",
                            base_url=self.stub.openai_base_url,
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )
        app = create_app(database_path=state_dir / "elephant.sqlite3", install_root=root)

        doctor = app.dispatch("GET", "/v1/providers/doctor")

        self.assertEqual(doctor.status_code, 200)
        self.assertEqual(doctor.payload["status"], "ready")
        self.assertEqual(doctor.payload["active_provider"]["source"], "configured")
        self.assertEqual(doctor.payload["active_provider"]["provider_id"], "openai-compatible")
        self.assertEqual(doctor.payload["active_provider"]["model_id"], "openai/gpt-4o-mini")
        self.assertNotIn("strong_model", doctor.payload["active_provider"])
        self.assertNotIn("weak_model", doctor.payload["active_provider"])

    def test_default_provider_profile_stays_non_blocking(self) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-openrouter",
            base_url=self.stub.openai_base_url,
        )

        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)
        self.assertEqual(defaulted.payload["active_provider"]["model_id"], "openai/gpt-4o-mini")
        self.assertNotIn("state_focus_mode", defaulted.payload["active_provider"])
        self.assertIn(
            defaulted.payload["active_provider"]["embedding_bootstrap_status"],
            {"ready", "pending", "downloading"},
        )

        doctor = self.app.dispatch("GET", "/v1/providers/doctor")
        self.assertEqual(doctor.status_code, 200)
        bootstrap_check = next(
            check for check in doctor.payload["checks"] if check["check"] == "embedding_bootstrap"
        )
        self.assertIn(bootstrap_check["status"], {"ready", "pending", "downloading"})
        self.assertEqual(doctor.payload["status"], "ready")

    def test_operator_dashboard_projection_is_empty_without_runtime_state(self) -> None:
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/overview")
        self.assertEqual(dashboard.status_code, 200)
        projection = dashboard.payload["dashboard"]
        self.assertEqual(projection["meta"]["database_path"], str(self.app.repository.database_path))
        self.assertEqual(
            projection["meta"]["query_contract"],
            [
                "Internal dashboard inspection is centered on Personal Model claims, PM history/source rows, Questions, Elephant State, Episode, Step, semantic recall, and provider status.",
                "Dashboard management bridges may operate skills, tools, MCP, cron, gateway, provider, and settings controls; durable user understanding remains Personal Model claims.",
                "Episode resume comes from State.current_context_note copied into Episode metadata at Episode open; live work belongs in Episode, Step, recall, or explicit task tools.",
                "Runtime trace starts from Episode and renders ordered Step facts rather than profile/session summaries.",
            ],
        )
        self.assertEqual(projection["herd"], [])
        self.assertEqual(projection["personal_models"], [])
        self.assertEqual(projection["states"], [])
        self.assertEqual(projection["runtime"]["episodes"], [])
        self.assertEqual(projection["runtime"]["learning_jobs"], [])
        self.assertEqual(projection["learning"]["jobs"], [])
        self.assertEqual(projection["learning"]["summary"]["total"], 0)
        self.assertEqual(projection["evidence"]["records"], [])
        self.assertEqual(projection["overview"]["counts"]["personal_models"], 0)
        self.assertEqual(projection["overview"]["counts"]["states"], 0)
        self.assertNotIn("records", projection["overview"]["counts"])
        self.assertEqual(projection["semantic_index_health"]["entry_count"], 0)
        self.assertIn("providers", projection)
        self.assertIn("operations", projection)
        self.assertNotIn("sessions", projection)
        self.assertNotIn("stateLanes", projection)
        self.assertNotIn("memoryLayers", projection)
        self.assertNotIn("providerProfiles", projection)
        self.assertNotIn("intent", json.dumps(projection["overview"], sort_keys=True).lower())

    def test_gateway_dashboard_cards_configure_im_accounts(self) -> None:
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/gateway")
        self.assertEqual(dashboard.status_code, 200)
        services = dashboard.payload["dashboard"]["operations"]["gateway"]["services"]
        service_ids = {service["service"] for service in services}
        self.assertEqual(services[0]["service"], "weixin")
        self.assertGreaterEqual(service_ids, {"weixin", "feishu", "discord", "dingding", "wecom"})
        self.assertIn("QR", services[0]["setupNote"])
        self.assertFalse(next(service for service in services if service["service"] == "feishu")["configured"])

        configured = self.app.dispatch(
            "POST",
            "/v1/operator/gateway",
            body=self._body(
                {
                    "service": "feishu",
                    "action": "configure",
                    "config": {
                        "accountId": "ops-feishu",
                        "transport": "long-connection",
                        "eventPath": "/hooks/feishu",
                        "enabled": True,
                        "allowGroupChats": True,
                        "secrets": {
                            "app_id": "cli-feishu-app",
                            "app_secret": "cli-feishu-secret",
                        },
                    },
                }
            ),
        )
        self.assertEqual(configured.status_code, 200)
        self.assertEqual(configured.payload["action"], "configured")
        manifest_path = Path(configured.payload["profileManifestPath"])
        manifest = load_global_config(manifest_path, state_dir=self.app.repository.database_path.parent)
        feishu = manifest["gateway"]["adapters"]["feishu"]
        self.assertTrue(feishu["enabled"])
        self.assertTrue(feishu["control"]["allow_group_chats"])
        account = feishu["accounts"][0]
        self.assertEqual(account["account_id"], "ops-feishu")
        self.assertEqual(account["event_path"], "/hooks/feishu")
        self.assertNotIn("cli-feishu-secret", json.dumps(manifest))
        self.assertEqual(
            [ref["metadata"]["env_var"] for ref in account["secret_references"]],
            ["ELEPHANT_FEISHU_OPS_FEISHU_APP_ID", "ELEPHANT_FEISHU_OPS_FEISHU_APP_SECRET"],
        )
        secret_file = Path(self.tempdir.name) / "gateway-local-secrets.json"
        local_secrets = json.loads(secret_file.read_text(encoding="utf-8"))
        self.assertEqual(local_secrets["ELEPHANT_FEISHU_OPS_FEISHU_APP_ID"], "cli-feishu-app")
        self.assertEqual(local_secrets["ELEPHANT_FEISHU_OPS_FEISHU_APP_SECRET"], "cli-feishu-secret")

        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/gateway")
        self.assertEqual(refreshed.status_code, 200)
        refreshed_feishu = next(
            service
            for service in refreshed.payload["dashboard"]["operations"]["gateway"]["services"]
            if service["service"] == "feishu"
        )
        self.assertTrue(refreshed_feishu["configured"])
        self.assertEqual(refreshed_feishu["accountCount"], 1)
        self.assertTrue(all(field["hasValue"] for field in refreshed_feishu["secretFields"]))

        with patch(
            "apps.api.api_runtime_console_ops.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ) as run_mock:
            started = self.app.dispatch(
                "POST",
                "/v1/operator/gateway",
                body=self._body({"service": "feishu", "action": "start", "accountId": "ops-feishu", "transport": "long-connection"}),
            )
        self.assertEqual(started.status_code, 200)
        command = run_mock.call_args.args[0]
        self.assertIn("--state-dir", command)
        self.assertEqual(command[command.index("--state-dir") + 1], str(Path(self.tempdir.name)))
        self.assertIn("--cli-state-dir", command)
        self.assertEqual(command[command.index("--cli-state-dir") + 1], str(Path(self.tempdir.name)))
        self.assertNotIn("--profile-dir", command)
        self.assertNotIn("--cli-profile-dir", command)

    def test_internal_dashboard_exposes_cli_linked_control_surfaces(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-console",
                    "display_name": "Console Elephant",
                    "mode": "companion",
                    "session_id": "session-console",
                    "preferences": ["brief"],
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        elephant_root = elephant_file_path("profile-console", install_root=Path(self.tempdir.name))
        elephant_root.mkdir(parents=True, exist_ok=True)
        (elephant_root / "ELEPHANT.md").write_text(
            "# Elephant Identity: Console Elephant\n\n- Stay exact.\n- Render this as markdown.\n",
            encoding="utf-8",
        )
        loop_service = LoopCheckpointService()
        proactive_prompt = "Open the wake surface proactively before the user sends a new message."
        proactive_loop = loop_service.start_loop(
            episode_id="session-console",
            source_event_id="event-console-startup",
            prompt=proactive_prompt,
        )
        self.app.repository.upsert_loop_checkpoint(proactive_loop)
        proactive_loop, proactive_context_step = loop_service.record_context_prompt(
            proactive_loop,
            system_prompt="Startup system prompt for Console Elephant.",
        )
        self.app.repository.upsert_loop_checkpoint(proactive_loop)
        self.app.repository.append_loop_checkpoint_step(proactive_context_step)
        proactive_loop, proactive_model_step = loop_service.record_model_turn(
            proactive_loop,
            summary="Bit, I already have the release State in view.",
            response_text="Bit, I already have the release State in view.",
        )
        self.app.repository.upsert_loop_checkpoint(proactive_loop)
        self.app.repository.append_loop_checkpoint_step(proactive_model_step)
        proactive_loop = loop_service.complete(
            proactive_loop,
            summary="Bit, I already have the release State in view.",
        )
        self.app.repository.upsert_loop_checkpoint(proactive_loop)
        fallback_proactive_loop = loop_service.start_loop(
            session_id="session-console",
            source_event_id="event-console-startup-summary",
            prompt=proactive_prompt,
        )
        self.app.repository.upsert_loop_checkpoint(fallback_proactive_loop)
        fallback_proactive_loop, fallback_proactive_context_step = loop_service.record_context_prompt(
            fallback_proactive_loop,
            system_prompt="Startup summary-only system prompt for Console Elephant.",
        )
        self.app.repository.upsert_loop_checkpoint(fallback_proactive_loop)
        self.app.repository.append_loop_checkpoint_step(fallback_proactive_context_step)
        fallback_proactive_loop = loop_service.complete(
            fallback_proactive_loop,
            summary="Bit, I am ready with the context already open.",
        )
        self.app.repository.upsert_loop_checkpoint(fallback_proactive_loop)

        run = loop_service.start_loop(
            episode_id="session-console",
            source_event_id="event-console",
            prompt="Show my current elephant memory.",
        )
        self.app.repository.upsert_loop_checkpoint(run)
        run, context_step = loop_service.record_context_prompt(
            run,
            system_prompt="System prompt for Console Elephant.",
        )
        self.app.repository.upsert_loop_checkpoint(run)
        self.app.repository.append_loop_checkpoint_step(context_step)
        run, model_step = loop_service.record_model_turn(
            run,
            summary="I can inspect persisted memory layers.",
            response_text="I can inspect persisted memory layers and show the elephant profile.",
        )
        self.app.repository.upsert_loop_checkpoint(run)
        self.app.repository.append_loop_checkpoint_step(model_step)
        run, tool_step = loop_service.record_tool_step(
            run,
            tool_name="memory.inspect",
            arguments={"profile_id": "profile-console"},
            result=ExecutionResult(
                execution_id="tool-console",
                episode_id="session-console",
                outcome="ok",
                summary="Memory inspection returned the Console Elephant profile.",
            ),
        )
        self.app.repository.upsert_loop_checkpoint(run)
        self.app.repository.append_loop_checkpoint_step(tool_step)
        run = loop_service.complete(run, summary="Done.")
        self.app.repository.upsert_loop_checkpoint(run)
        self.app.memory_runtime.record_memory(
            build_structured_turn_memory(
                StructuredTurnRecord(
                    turn_id="turn-console-structured",
                    episode_id="session-console",
                    source="api.test",
                    observation=StructuredTurnSlot(
                        summary="User asked to inspect current elephant memory.",
                        detail=("user_message:Show my current elephant memory.",),
                        provenance="runtime.turn_transcript",
                    ),
                    reasoning=StructuredTurnSlot(
                        summary="Inspect durable memory layers before answering.",
                        detail=("decision:memory inspection is the relevant evidence path",),
                        provenance="runtime.decision_summary",
                    ),
                    action=StructuredTurnSlot(
                        summary="Called memory.inspect.",
                        detail=("tool_call:memory.inspect args=profile_id id=call-console",),
                        provenance="runtime.turn_transcript",
                    ),
                    outcome=StructuredTurnSlot(
                        summary="Returned the elephant profile memory view.",
                        detail=("assistant_response:I can inspect persisted memory layers and show the elephant profile.",),
                        provenance="runtime.turn_transcript",
                    ),
                    personal_model_id="profile-console",
                    source_event_id="event-console",
                    work_item_ids=("work-console",),
                )
            )
        )
        checkpoint_loop = self.app.repository.load_loop(run.run_id)
        self.assertIsNotNone(checkpoint_loop)
        assert checkpoint_loop is not None
        self.app.repository.upsert_step(
            Step(
                step_id="step:console-usage",
                loop_id=checkpoint_loop.loop_id,
                episode_id=checkpoint_loop.episode_id,
                state_id=checkpoint_loop.state_id,
                personal_model_id=checkpoint_loop.personal_model_id,
                phase="acting",
                action="record_usage",
                status="completed",
                sequence=99,
                created_at=datetime.now(timezone.utc),
                summary="Usage reported by the provider.",
                metadata={
                    "provider_id": "openai-compatible",
                    "model_id": "openai/gpt-4o-mini",
                    "prompt_tokens": "20",
                    "completion_tokens": "8",
                    "total_tokens": "28",
                    "cached_prompt_tokens": 5,
                    "cache_creation_prompt_tokens": 2,
                    "cache_usage_reported": True,
                },
            )
        )

        payload = self._dashboard_sections("herd", "skills", "tools", "usage", "logs", "settings")
        operations = payload["operations"]
        self.assertEqual(payload["meta"]["database_path"], str(self.app.repository.database_path))
        self.assertNotIn("sessions", payload)
        self.assertNotIn("memoryLayers", json.dumps(payload, sort_keys=True))
        self.assertIn("profileManifest", operations["settings"])
        self.assertIn("globalConfigPath", operations["settings"])
        self.assertIn("globalConfig", operations["settings"])
        self.assertNotIn("eggStateFiles", operations["settings"])
        self.assertNotIn("eggStateFilesDir", operations["settings"])
        self.assertNotIn("models.state_focus_mode", json.dumps(operations["settings"], sort_keys=True))
        elephant = next(row for row in payload["herd"] if row["elephant_id"] == "profile-console")
        self.assertEqual(elephant["elephant_identity_file"]["path"], str(elephant_root / "ELEPHANT.md"))
        self.assertTrue(elephant["elephant_identity_file"]["exists"])
        self.assertIn("- Stay exact.", elephant["elephant_identity_file"]["text"])
        self.assertTrue(operations["skills"])
        self.assertTrue(operations["tools"])
        self.assertIn("mcp", operations)
        self.assertEqual(operations["mcp"]["tools"], [])
        self.assertIsInstance(operations["logs"], list)
        self.assertEqual(operations["usage"]["summary"]["runtimeStepUsageEvents"], 1)
        self.assertEqual(operations["usage"]["tokenEvents"][0]["cacheHitRateLabel"], "25.0%")

        patched = self.app.dispatch(
            "PATCH",
            "/v1/operator/settings",
            body=self._body(
                {
                    "profileManifest": {
                        "profile_id": "profile-console",
                        "display_name": "Console Elephant",
                        "mode": "companion",
                        "preferences": ["brief", "json"],
                    }
                }
            ),
        )
        self.assertEqual(patched.status_code, 200)
        profile_json = Path(patched.payload["profileManifestPath"])
        self.assertTrue(profile_json.exists())
        patched_config = load_global_config(profile_json, state_dir=self.app.repository.database_path.parent)
        self.assertEqual(patched_config["runtime"]["state_dir"], str(self.app.repository.database_path.parent))

        global_config = self.app.dispatch(
            "PATCH",
            "/v1/operator/config",
            body=self._body({"yamlText": "dashboard:\n  host: 127.0.0.1\n  port: 9777\n"}),
        )
        self.assertEqual(global_config.status_code, 200)
        self.assertEqual(global_config.payload["settings"]["globalConfig"]["dashboard"]["port"], 9777)
        self.assertTrue(Path(global_config.payload["globalConfigPath"]).exists())

        skill_id = operations["skills"][0]["skillId"]
        toggled = self.app.dispatch(
            "PATCH",
            f"/v1/operator/skills/{skill_id}",
            body=self._body({"enabled": False}),
        )
        self.assertEqual(toggled.status_code, 200)
        manifest = load_global_config(profile_json, state_dir=self.app.repository.database_path.parent)
        self.assertFalse(manifest["extensions"]["skill_overrides"][skill_id]["enabled"])
        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/skills")
        refreshed_skill = next(
            skill for skill in refreshed.payload["dashboard"]["operations"]["skills"] if skill["skillId"] == skill_id
        )
        self.assertFalse(refreshed_skill["enabled"])

        tool_id = operations["tools"][0]["toolId"]
        toggled_tool = self.app.dispatch(
            "PATCH",
            f"/v1/operator/tools/{tool_id}",
            body=self._body({"enabled": False}),
        )
        self.assertEqual(toggled_tool.status_code, 200)
        manifest = load_global_config(profile_json, state_dir=self.app.repository.database_path.parent)
        self.assertFalse(manifest["extensions"]["tool_overrides"][tool_id]["enabled"])
        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/tools")
        refreshed_tool = next(
            tool for tool in refreshed.payload["dashboard"]["operations"]["tools"] if tool["toolId"] == tool_id
        )
        self.assertFalse(refreshed_tool["enabled"])

        created_mcp_tool = self.app.dispatch(
            "POST",
            "/v1/operator/mcp/tools",
            body=self._body(
                {
                    "serverId": "filesystem",
                    "toolName": "read_file",
                    "serverLabel": "Filesystem",
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/demo"],
                    "env": {"ALLOW": "1"},
                    "displayName": "Read File",
                    "description": "Read a file from the mounted elephant file area.",
                    "family": "filesystem",
                    "defaultEnabled": True,
                    "riskClass": "medium",
                    "approvalClass": "standard",
                    "readsState": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                    "metadata": {"origin": "dashboard"},
                }
            ),
        )
        self.assertEqual(created_mcp_tool.status_code, 201)
        self.assertEqual(created_mcp_tool.payload["runtimeStatus"], "runtime_reloaded")
        global_config_path = Path(created_mcp_tool.payload["globalConfigPath"])
        stored_global_config = parse_global_config_text(global_config_path.read_text(encoding="utf-8"))
        self.assertEqual(stored_global_config["mcp_servers"]["filesystem"]["command"], "npx")
        self.assertIn("read_file", stored_global_config["mcp_servers"]["filesystem"]["tools"])
        runtime_tool = self.app.tool_runtime.describe("mcp.filesystem.read_file")
        self.assertIsNotNone(runtime_tool)
        self.assertTrue(runtime_tool.enabled)
        self.assertEqual(runtime_tool.audience, "model")

        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/tools")
        custom_mcp_tool = next(
            tool for tool in refreshed.payload["dashboard"]["operations"]["mcp"]["tools"] if tool["toolKey"] == "filesystem:read_file"
        )
        self.assertEqual(custom_mcp_tool["displayName"], "Read File")
        self.assertTrue(custom_mcp_tool["enabled"])
        self.assertEqual(custom_mcp_tool["serverId"], "filesystem")

        updated_mcp_tool = self.app.dispatch(
            "PATCH",
            "/v1/operator/mcp/tools",
            body=self._body(
                {
                    "serverId": "filesystem",
                    "toolName": "read_file",
                    "displayName": "Read File (updated)",
                    "description": "Read a file from the configured MCP server.",
                    "touchesSecrets": True,
                    "metadata": {"origin": "dashboard", "edited": True},
                }
            ),
        )
        self.assertEqual(updated_mcp_tool.status_code, 200)
        self.assertEqual(updated_mcp_tool.payload["runtimeStatus"], "runtime_reloaded")
        stored_global_config = parse_global_config_text(global_config_path.read_text(encoding="utf-8"))
        self.assertEqual(
            stored_global_config["mcp_servers"]["filesystem"]["tools"]["read_file"]["display_name"],
            "Read File (updated)",
        )
        self.assertTrue(
            stored_global_config["mcp_servers"]["filesystem"]["tools"]["read_file"]["touches_secrets"]
        )
        runtime_tool = self.app.tool_runtime.describe("mcp.filesystem.read_file")
        self.assertEqual(runtime_tool.display_name, "Read File (updated)")
        self.assertTrue(runtime_tool.side_effects.touches_secrets)

        toggled_mcp_tool = self.app.dispatch(
            "PATCH",
            "/v1/operator/mcp/tools/enabled",
            body=self._body(
                {
                    "serverId": "filesystem",
                    "toolName": "read_file",
                    "enabled": False,
                }
            ),
        )
        self.assertEqual(toggled_mcp_tool.status_code, 200)
        self.assertEqual(toggled_mcp_tool.payload["runtimeStatus"], "runtime_reloaded")
        stored_global_config = parse_global_config_text(global_config_path.read_text(encoding="utf-8"))
        self.assertFalse(stored_global_config["mcp_overrides"]["filesystem:read_file"]["enabled"])
        self.assertFalse(self.app.tool_runtime.describe("mcp.filesystem.read_file").enabled)
        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/tools")
        custom_mcp_tool = next(
            tool for tool in refreshed.payload["dashboard"]["operations"]["mcp"]["tools"] if tool["toolKey"] == "filesystem:read_file"
        )
        self.assertFalse(custom_mcp_tool["enabled"])

        deleted_mcp_tool = self.app.dispatch(
            "DELETE",
            "/v1/operator/mcp/tools",
            body=self._body(
                {
                    "serverId": "filesystem",
                    "toolName": "read_file",
                }
            ),
        )
        self.assertEqual(deleted_mcp_tool.status_code, 200)
        self.assertEqual(deleted_mcp_tool.payload["runtimeStatus"], "runtime_reloaded")
        stored_global_config = parse_global_config_text(global_config_path.read_text(encoding="utf-8"))
        self.assertNotIn("filesystem", stored_global_config.get("mcp_servers", {}))
        self.assertNotIn("filesystem:read_file", stored_global_config.get("mcp_overrides", {}))
        self.assertIsNone(self.app.tool_runtime.describe("mcp.filesystem.read_file"))
        refreshed = self.app.dispatch("GET", "/v1/internal/dashboard/tools")
        self.assertNotIn(
            "filesystem",
            {server["serverId"] for server in refreshed.payload["dashboard"]["operations"]["mcp"]["servers"]},
        )

    def test_operator_mcp_server_sync_persists_multiple_tools_and_deletes_server(self) -> None:
        synced_server = self.app.dispatch(
            "POST",
            "/v1/operator/mcp/servers",
            body=self._body(
                {
                    "serverId": "km",
                    "serverLabel": "KM",
                    "transport": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer demo"},
                    "tools": [
                        {
                            "name": "list_articles",
                            "description": "List KM articles.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"author": {"type": "string"}},
                            },
                        },
                        {
                            "name": "get_user",
                            "description": "Get one KM user profile.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"staffname": {"type": "string"}},
                                "required": ["staffname"],
                            },
                        },
                    ],
                }
            ),
        )
        self.assertEqual(synced_server.status_code, 201)
        self.assertEqual(synced_server.payload["toolCount"], 2)
        global_config_path = Path(synced_server.payload["globalConfigPath"])
        stored_global_config = parse_global_config_text(global_config_path.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(stored_global_config["mcp_servers"]["km"]["tools"].keys()),
            ["get_user", "list_articles"],
        )
        self.assertIsNotNone(self.app.tool_runtime.describe("mcp.km.list_articles"))
        self.assertIsNotNone(self.app.tool_runtime.describe("mcp.km.get_user"))

        toggled = self.app.dispatch(
            "PATCH",
            "/v1/operator/mcp/tools/enabled",
            body=self._body(
                {
                    "serverId": "km",
                    "toolName": "get_user",
                    "enabled": False,
                }
            ),
        )
        self.assertEqual(toggled.status_code, 200)
        stored_global_config = parse_global_config_text(global_config_path.read_text(encoding="utf-8"))
        self.assertFalse(stored_global_config["mcp_overrides"]["km:get_user"]["enabled"])

        resynced_server = self.app.dispatch(
            "PATCH",
            "/v1/operator/mcp/servers",
            body=self._body(
                {
                    "serverId": "km",
                    "serverLabel": "KM",
                    "transport": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer demo"},
                    "tools": [
                        {
                            "name": "list_articles",
                            "description": "List KM articles (updated).",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"author": {"type": "string"}},
                            },
                        }
                    ],
                }
            ),
        )
        self.assertEqual(resynced_server.status_code, 200)
        self.assertEqual(resynced_server.payload["toolCount"], 1)
        stored_global_config = parse_global_config_text(global_config_path.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(stored_global_config["mcp_servers"]["km"]["tools"].keys()),
            ["list_articles"],
        )
        self.assertNotIn("km:get_user", stored_global_config.get("mcp_overrides", {}))
        self.assertIsNone(self.app.tool_runtime.describe("mcp.km.get_user"))
        self.assertIsNotNone(self.app.tool_runtime.describe("mcp.km.list_articles"))

        deleted_server = self.app.dispatch(
            "DELETE",
            "/v1/operator/mcp/servers",
            body=self._body({"serverId": "km"}),
        )
        self.assertEqual(deleted_server.status_code, 200)
        stored_global_config = parse_global_config_text(global_config_path.read_text(encoding="utf-8"))
        self.assertNotIn("km", stored_global_config.get("mcp_servers", {}))
        self.assertIsNone(self.app.tool_runtime.describe("mcp.km.list_articles"))

    def test_internal_dashboard_surfaces_configured_external_skill_shelves(self) -> None:
        external_root = Path(self.tempdir.name) / ".agents" / "skills"
        skill_dir = external_root / "personal-journal"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                (
                    "---",
                    "name: Personal Journal",
                    "description: Helps review personal journal notes and recurring preferences.",
                    "---",
                    "Use this skill when the user asks to review personal journal notes.",
                )
            ),
            encoding="utf-8",
        )
        configured = self.app.dispatch(
            "PATCH",
            "/v1/operator/config",
            body=self._body({"config": {"skills": {"external_dirs": [str(external_root)]}}}),
        )
        self.assertEqual(configured.status_code, 200)
        now = datetime.now(timezone.utc)
        self.app.repository.upsert_personal_model(
            PersonalModel(
                personal_model_id="you",
                display_name="You",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        self.app.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact:skills:personal-journal",
                personal_model_id="you",
                lens="world",
                text="Personal journal review fits the user's recurring reflection workflow.",
                confidence=0.82,
                committed_at=now,
                source="user_explicit",
                metadata={
                    "topic": "world.skills.affinity.personal_journal",
                    "skill_id": "personal-journal",
                    "projection_policy": "skill_shelf_candidate",
                },
            )
        )

        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/skills")
        self.assertEqual(dashboard.status_code, 200)
        skills = dashboard.payload["dashboard"]["operations"]["skills"]
        affinities = dashboard.payload["dashboard"]["operations"]["skill_affinities"]
        external = next(skill for skill in skills if skill["skillId"] == "personal-journal")

        self.assertEqual(external["sourceId"], "agents")
        self.assertEqual(external["source"], "Agents")
        self.assertFalse(external["toggleable"])
        self.assertFalse(external["enabled"])
        self.assertIn("Use this skill", external["instructionText"])
        self.assertEqual(affinities[0]["skillId"], "personal-journal")
        self.assertEqual(affinities[0]["activeCount"], 1)
        self.assertEqual(
            dashboard.payload["dashboard"]["operations"]["settings"]["globalConfig"]["skills"]["external_dirs"],
            [str(external_root)],
        )

    def test_operator_mcp_discover_supports_stdio_and_remote_headers(self) -> None:
        observed_remote_config: dict[str, object] = {}

        def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
            self.assertEqual(kwargs.get("cwd"), ROOT)
            if "--stdio" in command:
                self.assertIn("--env", command)
                self.assertIn("ALLOW=1", command)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        {
                            "status": "ok",
                            "durationMs": 123,
                            "tools": [
                                {
                                    "name": "read_file",
                                    "description": "Read one file.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"path": {"type": "string"}},
                                        "required": ["path"],
                                    },
                                    "options": [{"property": "path", "required": True}],
                                }
                            ],
                        }
                    ),
                    stderr="",
                )
            config_path = Path(command[command.index("--config") + 1])
            observed_remote_config.update(json.loads(config_path.read_text(encoding="utf-8")))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "status": "ok",
                        "durationMs": 88,
                        "tools": [
                            {
                                "name": "ping",
                                "description": "Ping the remote MCP server.",
                                "inputSchema": {"type": "object", "properties": {}},
                                "options": [],
                            }
                        ],
                    }
                ),
                stderr="",
            )

        with patch("apps.api.api_runtime_console_ops.subprocess.run", side_effect=fake_run):
            discovered_stdio = self.app.dispatch(
                "POST",
                "/v1/operator/mcp/discover",
                body=self._body(
                    {
                        "serverId": "filesystem",
                        "transport": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/demo"],
                        "env": {"ALLOW": "1"},
                    }
                ),
            )
            self.assertEqual(discovered_stdio.status_code, 200)
            self.assertEqual(discovered_stdio.payload["status"], "ok")
            self.assertEqual(discovered_stdio.payload["toolCount"], 1)
            self.assertEqual(discovered_stdio.payload["tools"][0]["name"], "read_file")
            self.assertEqual(discovered_stdio.payload["tools"][0]["requiredFields"], ["path"])

            discovered_remote = self.app.dispatch(
                "POST",
                "/v1/operator/mcp/discover",
                body=self._body(
                    {
                        "serverId": "remote-demo",
                        "transport": "streamable-http",
                        "url": "https://example.com/mcp",
                        "headers": {"Authorization": "Bearer demo"},
                    }
                ),
            )
            self.assertEqual(discovered_remote.status_code, 200)
            self.assertEqual(discovered_remote.payload["transport"], "streamable-http")
            self.assertEqual(discovered_remote.payload["toolCount"], 1)
            self.assertEqual(discovered_remote.payload["tools"][0]["name"], "ping")
            self.assertEqual(
                observed_remote_config["mcpServers"]["remote-demo"]["headers"]["Authorization"],
                "Bearer demo",
            )
            self.assertEqual(
                observed_remote_config["mcpServers"]["remote-demo"]["transportType"],
                "streamable-http",
            )

    def test_internal_dashboard_keeps_durable_state_after_episode_delete(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-orphan",
                    "display_name": "Orphan Elephant",
                    "mode": "companion",
                    "session_id": "session-orphan",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        deleted_sessions = self.app.repository.delete_episodes(("session-orphan",))

        self.assertEqual(deleted_sessions, 1)
        self.assertIsNotNone(self.app.repository.load_personal_model("profile-orphan"))
        console = self.app.dispatch("GET", "/v1/internal/console")
        self.assertEqual(console.status_code, 404)
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/overview")
        self.assertEqual(dashboard.status_code, 200)
        payload = dashboard.payload["dashboard"]
        self.assertNotIn("sessions", payload)
        self.assertIn("profile-orphan", [elephant["personal_model_id"] for elephant in payload["herd"]])
        self.assertIn("state:profile-orphan", [state["state_id"] for state in payload["states"]])
        self.assertEqual(payload["overview"]["counts"]["episodes"], 0)

    def test_internal_dashboard_excludes_personal_model_growth_state_lanes(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-stale-growth",
                    "display_name": "Fresh Elephant",
                    "mode": "companion",
                    "session_id": "session-stale-growth",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        self.app.repository.upsert_personal_model_growth(
            PersonalModelGrowthState(
                profile_id="profile-stale-growth",
                growth_score=480,
                total_dialogues=12,
                total_tokens=3400,
                created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
        )

        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/herd")

        self.assertEqual(dashboard.status_code, 200)
        elephant = next(
            elephant for elephant in dashboard.payload["dashboard"]["herd"]
            if elephant["elephant_id"] == "profile-stale-growth"
        )
        self.assertNotIn("growth_score", elephant)
        self.assertNotIn("memoryLayers", json.dumps(dashboard.payload["dashboard"], sort_keys=True))

    def test_operator_namespace_no_longer_exposes_public_dashboard_reads(self) -> None:
        dashboard = self.app.dispatch("GET", "/v1/operator/dashboard")
        console = self.app.dispatch("GET", "/v1/operator/console")

        self.assertEqual(dashboard.status_code, 404)
        self.assertEqual(console.status_code, 404)

    def test_wsgi_get_request_with_no_content_length_returns_without_blocking(self) -> None:
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        body = b"".join(
            self.app(
                {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": "/healthz",
                    "wsgi.input": BytesIO(b""),
                    "CONTENT_LENGTH": "",
                },
                start_response,
            )
        )

        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(json.loads(body.decode("utf-8")), {"status": "ok", "service": "elephant-api"})

    def test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence(self) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-dashboard",
            base_url=self.stub.openai_base_url,
            reference_id="secret-dashboard-token",
            extra_headers={"x-tenant": "elephant"},
        )
        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)

        now = datetime.now(timezone.utc)
        personal_model = PersonalModel(
            personal_model_id="personal-model-dashboard",
            display_name="Dashboard Personal Model",
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.app.repository.upsert_personal_model(personal_model)
        self.app.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact-dashboard-preferred-name",
                personal_model_id=personal_model.personal_model_id,
                lens="identity",
                text="Bit",
                confidence=1.0,
                committed_at=now,
                source="user_explicit",
                metadata={"topic": "identity.anchor.name.preferred"},
            )
        )
        self.app.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact-dashboard-work",
                personal_model_id=personal_model.personal_model_id,
                lens="pulse",
                text="Building durable agent systems.",
                confidence=0.92,
                committed_at=now,
                source="pm_agent_promote",
                source_episode_ids=("episode-dashboard",),
                metadata={"topic": "pulse.chapter.work.role"},
            )
        )
        self.app.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact-dashboard-style",
                personal_model_id=personal_model.personal_model_id,
                lens="identity",
                text="Prefers concise, grounded replies.",
                confidence=0.91,
                committed_at=now,
                source="pm_agent_promote",
                source_episode_ids=("episode-dashboard",),
                metadata={"topic": "identity.style.response.concise"},
            )
        )
        state = State(
            state_id="state-dashboard",
            personal_model_id=personal_model.personal_model_id,
            state_anchor="elephant-dashboard",
            status="active",
            elephant_id="elephant-dashboard",
            elephant_name="Elephant Agent Prime",
            capability_boundaries=("inspect", "ground"),
            surface_bindings=("cli", "dashboard"),
            summary="Investigating the T9 dashboard rewrite.",
            current_context_note="Investigating the T9 dashboard rewrite.",
            created_at=now,
            updated_at=now,
        )
        self.app.repository.upsert_state(state)
        self.app.repository.switch_state(state.state_id, selected_at=now)
        episode = Episode(
            episode_id="episode-dashboard",
            state_id=state.state_id,
            personal_model_id=personal_model.personal_model_id,
            entry_surface="dashboard-test",
            status="open",
            started_at=now,
            ended_at=now,
            exit_summary="Dashboard inspection episode closed cleanly.",
        )
        self.app.repository.upsert_episode(episode)
        loop = Loop(
            loop_id="loop-dashboard",
            episode_id=episode.episode_id,
            state_id=state.state_id,
            personal_model_id=personal_model.personal_model_id,
            trigger_type="manual",
            status="completed",
            started_at=now,
            ended_at=now,
            summary="Validated the internal dashboard projection.",
            outcome="success",
        )
        self.app.repository.upsert_loop(loop)
        step = Step(
            step_id="step-dashboard",
            loop_id=loop.loop_id,
            episode_id=episode.episode_id,
            state_id=state.state_id,
            personal_model_id=personal_model.personal_model_id,
            phase="reasoning",
            action="inspect_dashboard",
            status="completed",
            sequence=0,
            created_at=now,
            summary="Checked the canonical inspection payload.",
            outcome="payload rendered",
            payload_refs=("payload:dashboard",),
            metadata={
                "execution_id": "execution-dashboard",
                "provider_id": "openai-compatible",
                "model_id": "openai/gpt-4o-mini",
                "assistant_reasoning": "Inspect provider posture before opening the dashboard trace.",
                "prompt_tokens": "42",
                "completion_tokens": "11",
                "total_tokens": "53",
            },
        )
        self.app.repository.upsert_step(step)
        learning_job = self.app.repository.enqueue_learning_job(
            job_type="episode_boundary_learning",
            trigger="exit",
            personal_model_id=personal_model.personal_model_id,
            state_id=state.state_id,
            episode_id=episode.episode_id,
            loop_id=loop.loop_id,
            summary="Dashboard learning job completed.",
            metadata={"source": "dashboard-test"},
        )
        claimed_learning_job = self.app.repository.claim_learning_job(worker_id="dashboard-worker")
        assert claimed_learning_job is not None
        self.app.repository.write_learning_job_result(
            claimed_learning_job.job_id,
            {
                "job_id": learning_job.job_id,
                "status": "completed",
                "summary": "Dashboard learning result.",
                "pm_facts": {"created_refs": ["fact-dashboard-style"]},
                "questions": {"created_ids": []},
            },
            worker_id="dashboard-worker",
            progress_detail="Dashboard learning result persisted.",
        )
        self.app.repository.complete_learning_job(
            claimed_learning_job.job_id,
            worker_id="dashboard-worker",
            finished_at=now,
            progress_detail="Dashboard learning result persisted.",
        )
        self.app.repository.upsert_auth_profile(
            AuthProfile(
                profile_id="provider-embedding-openai-compatible",
                provider_id="openai-compatible-embed",
                transport_id="openai-compatible",
                base_url=self.stub.openai_base_url,
                default_model="text-embedding-3-small",
                auth_method="api_key",
                provider_kind="embedding",
                secret_references=(
                    SecretReference(
                        reference_id="secret-embedding-dashboard",
                        provider_id="openai-compatible-embed",
                        secret_name="api_token",
                        secret_key="api_key",
                        metadata={
                            "storage": "local-vault",
                            "scope": "embedding-provider",
                            "env_var": "OPENAI_API_KEY",
                        },
                    ),
                ),
                metadata={"embedding_active": "true", "dimensions": "1536", "configured_from": "test"},
            )
        )
        self.app.repository.upsert_semantic_index_entry(
            SemanticIndexEntry(
                semantic_index_entry_id="semantic-dashboard",
                owner_scope="personal_model",
                source_record_id="fact-dashboard-style",
                provider_id="openai-compatible",
                model_id="text-embedding-3-small",
                dimensions=1536,
                content_hash="hash-dashboard-component",
                personal_model_id=personal_model.personal_model_id,
                backend="sqlite-vec",
                vector_ref="vec://dashboard-component",
                status="indexed",
                created_at=now,
                updated_at=now,
            )
        )
        self.app.repository.upsert_provider_auth_state(
            ProviderAuthState(
                provider_id="copilot",
                auth_type="api_key",
                status="authenticated",
                source="gh-cli",
                transport_id="openai_responses",
                provider_kind="aggregator",
                base_url="https://api.githubcopilot.com",
                default_model="gpt-5.4",
                runtime_enabled=True,
                summary="authenticated via gh-cli",
                metadata={"reasoning_efforts": "minimal,low,medium,high"},
                discovered_at=now,
                updated_at=now,
            )
        )

        projection = self._dashboard_sections("overview", "personal-models", "runtime", "reflect", "evidence", "providers", "usage")
        self.assertEqual(projection["overview"]["counts"]["personal_models"], 1)
        self.assertEqual(projection["overview"]["counts"]["states"], 1)
        self.assertEqual(projection["overview"]["counts"]["episodes"], 1)
        self.assertEqual(projection["overview"]["counts"]["loops"], 1)
        self.assertEqual(projection["overview"]["counts"]["steps"], 1)
        self.assertNotIn("records", projection["overview"]["counts"])
        self.assertEqual(projection["overview"]["counts"]["learning_jobs"], 1)
        self.assertEqual(projection["overview"]["counts"]["learning_jobs_completed"], 1)
        self.assertNotIn("groundings", projection["overview"]["counts"])
        self.assertNotIn("memory_entries", projection["overview"]["counts"])
        self.assertNotIn("reflection_proposals", projection["overview"]["counts"])
        self.assertNotIn("skill_affinities", projection["overview"]["counts"])
        self.assertEqual(projection["overview"]["counts"]["semantic_index_entries"], 1)
        self.assertNotIn("embedding_provider_configs", projection["overview"]["counts"])
        self.assertEqual(projection["overview"]["counts"]["provider_auth_states"], 0)
        self.assertEqual(projection["overview"]["current_state_id"], state.state_id)
        self.assertEqual(
            projection["overview"]["current_personal_model_id"],
            "you",
        )
        self.assertNotIn("active_task", projection["herd"][0])
        self.assertNotIn("next_step", projection["herd"][0])
        self.assertNotIn("blockers", projection["states"][0])
        personal_model_row = projection["personal_models"][0]
        self.assertEqual(personal_model_row["component_records"], [])
        self.assertEqual(personal_model_row["memory_entries"], [])
        self.assertEqual(personal_model_row["states"][0]["state_id"], state.state_id)
        self.assertEqual(personal_model_row["user_preferred_name"], "Bit")
        self.assertEqual(personal_model_row["user_card"]["preferred_name"], "Bit")
        self.assertEqual(personal_model_row["user_card"]["current_work"], "Building durable agent systems.")
        overview_only = self._dashboard_section("overview")
        self.assertEqual(overview_only["personal_models"][0]["user_preferred_name"], "Bit")
        component_rows = {
            component["component_key"]: component
            for component in personal_model_row["understanding_components"]
        }
        self.assertEqual(component_rows["identity"]["status"], "active")
        self.assertEqual(component_rows["identity"]["claim_count"], 2)
        self.assertEqual(component_rows["pulse"]["claim_count"], 1)
        self.assertEqual(component_rows["world"]["status"], "empty")
        self.assertEqual(personal_model_row["personal_model_fact_count"], 3)
        personal_model_fact_text = {fact["text"] for fact in personal_model_row["personal_model_facts"]}
        self.assertIn("Prefers concise, grounded replies.", personal_model_fact_text)
        self.assertNotIn("State-only tool test memory", json.dumps(personal_model_row, sort_keys=True))
        self.assertNotIn("Display name: Miles", json.dumps(personal_model_row, sort_keys=True))
        self.assertNotIn("reflection_proposals", personal_model_row)
        self.assertNotIn("skill_affinities", personal_model_row)
        self.assertEqual(personal_model_row["semantic_index_entries"][0]["semantic_index_entry_id"], "semantic-dashboard")
        self.assertEqual(projection["runtime"]["episodes"][0]["episode_id"], episode.episode_id)
        self.assertEqual(projection["runtime"]["episodes"][0]["loop_count"], 1)
        self.assertEqual(projection["runtime"]["episodes"][0]["step_count"], 1)
        self.assertEqual(projection["learning"]["summary"]["completed"], 1)
        self.assertEqual(projection["learning"]["jobs"][0]["job_id"], learning_job.job_id)
        self.assertEqual(projection["learning"]["jobs"][0]["result_record_count"], 0)
        self.assertEqual(projection["learning"]["jobs"][0]["result_records"], [])
        self.assertEqual(projection["learning"]["jobs"][0]["result_status"], "completed")
        self.assertEqual(projection["learning"]["jobs"][0]["learning_result"]["summary"], "Dashboard learning result.")
        self.assertEqual(
            projection["runtime"]["episode_traces"][0]["timeline"][0]["detail"]["assistant_reasoning"],
            "Inspect provider posture before opening the dashboard trace.",
        )
        usage = projection["operations"]["usage"]
        self.assertEqual(usage["summary"]["runtimeStepUsageEvents"], 1)
        self.assertEqual(usage["summary"]["usageEvents"], 1)
        self.assertEqual(usage["summary"]["totalTokens"], 53)
        self.assertEqual(usage["tokenEvents"][0]["source"], "runtime_step")
        self.assertEqual(usage["tokenTrend"][0]["totalTokens"], 53)
        self.assertEqual(usage["eggUsage"][0]["eggName"], "Elephant Agent Prime")
        self.assertEqual(projection["evidence"]["records"], [])
        self.assertEqual(projection["evidence"]["groundings"], [])
        self.assertEqual(projection["evidence"]["memory_entries"], [])
        self.assertNotIn("reflection_proposals", projection["evidence"])
        self.assertNotIn("skill_affinities", projection["evidence"])
        self.assertEqual(projection["semantic_index_health"]["entry_count"], 1)
        self.assertNotIn("embedding_configs", projection["providers"])
        self.assertEqual(projection["providers"]["embedding_provider"]["source"], "configured")
        self.assertEqual(
            projection["providers"]["embedding_provider"]["model_id"],
            "text-embedding-3-small",
        )
        self.assertEqual(
            projection["providers"]["active_provider"]["model_id"],
            "openai/gpt-4o-mini",
        )
        self.assertNotIn("state_focus_mode", projection["providers"]["active_provider"])
        self.assertNotIn("strong_model", projection["providers"]["active_provider"])
        self.assertNotIn("weak_model", projection["providers"]["active_provider"])
        self.assertNotIn("state_focus_mode", json.dumps(projection["providers"]["doctor"], sort_keys=True))
        self.assertNotIn("stateLanes", projection)
        self.assertNotIn("sessions", projection)
        self.assertNotIn("memoryLayers", projection)
        serialized = json.dumps(projection, sort_keys=True)
        self.assertNotIn("sk-live-123", serialized)

    def test_internal_dashboard_projection_ignores_legacy_session_graph_rows(self) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-dashboard",
            base_url=self.stub.openai_base_url,
            reference_id="secret-dashboard-token",
            extra_headers={"x-tenant": "elephant"},
        )
        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)
        created = self.app.dispatch(
            "POST",
            "/v1/sessions",
            body=self._body(
                {
                    "profile_id": "profile-dashboard-legacy",
                    "display_name": "Legacy lane",
                    "mode": "companion",
                    "session_id": "session-dashboard-legacy",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/overview")
        self.assertEqual(dashboard.status_code, 200)
        projection = dashboard.payload["dashboard"]
        self.assertEqual(projection["overview"]["counts"]["states"], 1)
        self.assertNotIn("records", projection["overview"]["counts"])
        self.assertEqual(projection["herd"][0]["elephant_id"], "profile-dashboard-legacy")
        self.assertEqual(projection["states"][0]["state_id"], "state:profile-dashboard-legacy")
        self.assertNotIn("stateLanes", projection)
        self.assertNotIn("sessions", projection)
        self.assertNotIn("ops", projection)
        self.assertNotIn("memoryLayers", projection)

    def test_default_provider_bad_request_hides_legacy_profile_field_names(self) -> None:
        response = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": "invalid"}),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.payload["detail"],
            "provider_profile must be an object describing the default provider configuration",
        )

    def _dashboard_section(self, section: str) -> dict[str, Any]:
        response = self.app.dispatch("GET", f"/v1/internal/dashboard/{section}")
        self.assertEqual(response.status_code, 200)
        return response.payload["dashboard"]

    def _dashboard_sections(self, *sections: str) -> dict[str, Any]:
        top_level_keys = {
            "overview": ("overview", "herd", "states", "personal_models", "runtime", "learning"),
            "personal-models": ("personal_models",),
            "herd": ("herd", "states"),
            "runtime": ("herd", "states", "runtime"),
            "reflect": ("learning",),
            "chat": ("overview", "herd", "states", "personal_models", "runtime"),
            "evidence": ("evidence", "semantic_index_health"),
            "providers": ("providers",),
        }
        operation_keys = {
            "providers": ("models",),
            "skills": ("skills", "skill_affinities", "settings"),
            "tools": ("tools", "mcp", "settings"),
            "gateway": ("gateway",),
            "cron": ("cron",),
            "settings": ("settings",),
            "usage": ("usage",),
            "logs": ("logs",),
            "usage-logs": ("usage", "logs"),
        }
        merged = self._dashboard_section(sections[0])
        for section in sections[1:]:
            payload = self._dashboard_section(section)
            for key in top_level_keys.get(section, ()):
                merged[key] = payload[key]
            merged_operations = dict(merged.get("operations", {}))
            for operation_key in operation_keys.get(section, ()):
                merged_operations[operation_key] = payload["operations"][operation_key]
            merged["operations"] = merged_operations
        return merged

    @staticmethod
    def _body(payload: dict[str, object]) -> bytes:
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
