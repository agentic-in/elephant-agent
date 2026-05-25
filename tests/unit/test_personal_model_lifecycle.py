"""Tests for lifecycle metadata on Personal Model writes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from packages.contracts import Fact, Step
from packages.evidence import recall_time_range_from_payload
from packages.storage import RuntimeStorageRepository
from packages.tools.handlers_personal_model import (
    run_personal_model_search,
    run_personal_model_update,
)
from packages.tools.runtime import ToolInvocation, ToolRuntimeContext
from packages.understanding import PersonalModelUnderstandingSurface
from packages.understanding.personal_model_governance import protected_topic_metadata


class PersonalModelLifecycleTest(unittest.TestCase):
    def test_index_claim_failure_is_logged(self) -> None:
        class Indexer:
            def index_personal_model_claim(self, fact: Fact) -> None:
                del fact
                raise RuntimeError("index unavailable")

        surface = PersonalModelUnderstandingSurface(
            repository=object(), semantic_summary_indexer=Indexer()
        )

        with self.assertLogs("packages.understanding.runtime", level="DEBUG") as logs:
            surface._index_claim(_fact())

        self.assertIn("Failed to index Personal Model claim", "\n".join(logs.output))

    def test_deactivate_claim_index_failures_are_logged(self) -> None:
        class ListFailRepository:
            def list_semantic_index_entries(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("index list unavailable")

            def upsert_semantic_index_entry(self, entry: object) -> None:
                del entry

        surface = PersonalModelUnderstandingSurface(repository=ListFailRepository())
        with self.assertLogs("packages.understanding.runtime", level="DEBUG") as logs:
            surface._deactivate_claim_index(
                personal_model_id="you", fact_id="claim:1", status="retired"
            )
        self.assertIn(
            "Failed to list semantic index entries for claim deactivation",
            "\n".join(logs.output),
        )

        class UpsertFailRepository:
            def list_semantic_index_entries(self, **_: object) -> tuple[object, ...]:
                return (SimpleNamespace(source_id="claim:1", metadata={}),)

            def upsert_semantic_index_entry(self, entry: object) -> None:
                del entry
                raise RuntimeError("index upsert unavailable")

        surface = PersonalModelUnderstandingSurface(repository=UpsertFailRepository())
        with self.assertLogs("packages.understanding.runtime", level="DEBUG") as logs:
            surface._deactivate_claim_index(
                personal_model_id="you", fact_id="claim:1", status="retired"
            )
        self.assertIn(
            "Failed to mark semantic index entry deleted", "\n".join(logs.output)
        )

    def test_search_side_channel_failures_are_logged(self) -> None:
        class Repository:
            def ensure_default_personal_model(
                self, personal_model_id: str = "you"
            ) -> None:
                del personal_model_id

            def load_episode_state(self, session_id: str) -> object:
                del session_id
                return SimpleNamespace(personal_model_id="you")

            def list_personal_model_facts(self, **_: object) -> tuple[Fact, ...]:
                return (_fact(),)

            def touch_fact_access(self, fact_ids: tuple[str, ...]) -> None:
                del fact_ids
                raise RuntimeError("touch unavailable")

        surface = PersonalModelUnderstandingSurface(repository=Repository())

        with self.assertLogs("packages.understanding.runtime", level="DEBUG") as logs:
            result = surface.search_personal_model(
                "session", query="all", personal_model_id="you"
            )

        self.assertEqual(result["match_status"], "strong_match")
        self.assertIn(
            "Failed to touch Personal Model fact access metadata",
            "\n".join(logs.output),
        )

    def test_semantic_query_failures_are_logged(self) -> None:
        class Repository:
            def list_semantic_index_entries(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("index unavailable")

        surface = PersonalModelUnderstandingSurface(repository=Repository())
        with self.assertLogs("packages.understanding.runtime", level="DEBUG") as logs:
            self.assertIsNone(
                surface._indexed_query_dimensions(
                    owner_scope="personal_model", personal_model_id="you"
                )
            )
        self.assertIn(
            "Failed to inspect Personal Model semantic index dimensions",
            "\n".join(logs.output),
        )

        class EmbeddingService:
            def embed_text(self, *_: object, **__: object) -> object:
                raise RuntimeError("embedding unavailable")

        surface = PersonalModelUnderstandingSurface(
            repository=object(), embedding_service=EmbeddingService()
        )
        with self.assertLogs("packages.understanding.runtime", level="DEBUG") as logs:
            self.assertEqual(surface._query_vector("hello", dimensions=256), ((), None))
        self.assertIn(
            "Failed to embed Personal Model search query", "\n".join(logs.output)
        )

    def test_last_night_expr_crosses_into_today_early_morning(self) -> None:
        resolved = recall_time_range_from_payload(
            {"expr": "last_night", "timezone": "Asia/Shanghai"},
            now=datetime(2026, 5, 9, 9, 51, tzinfo=timezone.utc),
        )

        assert resolved is not None
        payload = resolved.payload()
        self.assertEqual(payload["start_at"], "2026-05-08T18:00+08:00")
        self.assertEqual(payload["end_at"], "2026-05-09T06:00+08:00")
        self.assertEqual(payload["search_start_at"], "2026-05-08T17:00+08:00")
        self.assertEqual(payload["search_end_at"], "2026-05-09T08:00+08:00")

    def test_iso_date_expr_resolves_to_local_day_window(self) -> None:
        resolved = recall_time_range_from_payload(
            {"expr": "2026-05-13", "timezone": "Asia/Shanghai"},
            now=datetime(2026, 5, 14, 9, 51, tzinfo=timezone.utc),
        )

        assert resolved is not None
        payload = resolved.payload()
        self.assertEqual(payload["start_at"], "2026-05-13T00:00+08:00")
        self.assertEqual(payload["end_at"], "2026-05-14T00:00+08:00")
        self.assertEqual(payload["label"], "2026-05-13")

    def test_init_user_profile_topics_are_system_protected_prompt_facts(self) -> None:
        for topic in (
            "identity.anchor.name.preferred",
            "identity.style.language.first",
            "pulse.chapter.work.role",
            "world.places.city.current",
            "identity.anchor.gender.self_description",
            "identity.anchor.birth.date",
            "identity.anchor.age.current",
            "identity.character.mbti.type",
            "identity.style.hobbies.personal",
            "identity.style.companion.posture",
            "identity.body.safety.boundary",
            "identity.character.rhythm.pressure",
            "identity.character.rhythm.recovery",
            "identity.character.decision.compass",
        ):
            with self.subTest(topic=topic):
                metadata = protected_topic_metadata(topic)
                self.assertEqual(metadata["protected"], "system")
                self.assertEqual(metadata["projection_policy"], "core_prompt")
                self.assertEqual(metadata["protected_reason"], "init_core_profile")

    def test_recall_searches_steps_with_hard_time_range(self) -> None:
        now = datetime(2026, 5, 9, 20, 0, tzinfo=timezone.utc)

        class _Repo:
            def ensure_default_personal_model(self, personal_model_id="you"):
                return None

            def load_episode_state(self, _session_id):
                return type(
                    "_Episode", (), {"personal_model_id": "you", "state_id": "state-1"}
                )()

            def current_state(self):
                return type("_State", (), {"state_id": "state-1"})()

            def list_episodes(self, **kwargs):
                return ()

            def list_semantic_index_entries(self, **kwargs):
                return ()

            def list_steps(self, *, loop_id=None):
                return (
                    Step(
                        step_id="step-noise",
                        loop_id="loop-1",
                        episode_id="old-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="acting",
                        action="reply",
                        status="completed",
                        sequence=1,
                        created_at=datetime(2026, 5, 9, 8, 0, tzinfo=timezone.utc),
                        summary="早上聊了完全不同的话题。",
                    ),
                    Step(
                        step_id="step-hit",
                        loop_id="loop-1",
                        episode_id="old-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="acting",
                        action="reply",
                        status="completed",
                        sequence=2,
                        created_at=now,
                        summary="讨论家庭边界，以及男友母亲带来的关系压力。",
                    ),
                )

        result = PersonalModelUnderstandingSurface(
            repository=_Repo()
        ).recall_personal_model(
            "session-life",
            query="男友母亲",
            time_range={
                "start_at": "2026-05-09T18:00:00+00:00",
                "end_at": "2026-05-09T23:59:59+00:00",
                "label": "tonight",
            },
        )

        hits = tuple(result.get("hits") or ())
        self.assertEqual(len(hits), 1)
        self.assertIn("男友母亲", str(hits[0].get("content") or ""))
        self.assertEqual(result["resolved_time_range"]["label"], "tonight")

    def test_conversation_discover_requires_time_range(self) -> None:
        class _Repo:
            def ensure_default_personal_model(self, personal_model_id="you"):
                return None

            def load_episode_state(self, _session_id):
                return type(
                    "_Episode",
                    (),
                    {
                        "episode_id": "current-session",
                        "personal_model_id": "you",
                        "state_id": "state-1",
                    },
                )()

            def current_state(self):
                return type("_State", (), {"state_id": "state-1"})()

            def list_episodes(self, **kwargs):
                return ()

            def list_semantic_index_entries(self, **kwargs):
                return ()

            def list_steps(self, *, loop_id=None):
                return ()

        result = PersonalModelUnderstandingSurface(
            repository=_Repo()
        ).search_conversation(
            "current-session",
            query="家庭",
            mode="discover",
        )

        self.assertTrue(result["requires_time_range"])
        self.assertEqual(tuple(result["ranges"]), ())
        self.assertIn("expr", result["guidance"])
        self.assertIn("start_at", result["guidance"])

    def test_conversation_discover_accepts_iso_date_expr(self) -> None:
        class _Repo:
            def ensure_default_personal_model(self, personal_model_id="you"):
                return None

            def load_episode_state(self, _session_id):
                return type(
                    "_Episode",
                    (),
                    {
                        "episode_id": "current-session",
                        "personal_model_id": "you",
                        "state_id": "state-1",
                    },
                )()

            def current_state(self):
                return type("_State", (), {"state_id": "state-1"})()

            def list_episodes(self, **kwargs):
                return ()

            def list_semantic_index_entries(self, **kwargs):
                return ()

            def list_steps(self, *, loop_id=None):
                return ()

        result = PersonalModelUnderstandingSurface(
            repository=_Repo()
        ).search_conversation(
            "current-session",
            mode="discover",
            time_range={"expr": "2026-05-13", "timezone": "Asia/Shanghai"},
        )

        self.assertNotIn("requires_time_range", result)
        self.assertEqual(
            result["resolved_time_range"]["start_at"], "2026-05-13T00:00+08:00"
        )
        self.assertEqual(
            result["resolved_time_range"]["end_at"], "2026-05-14T00:00+08:00"
        )

    def test_conversation_search_excludes_current_episode_by_default(self) -> None:
        now = datetime(2026, 5, 9, 1, 0, tzinfo=timezone.utc)

        class _Repo:
            def ensure_default_personal_model(self, personal_model_id="you"):
                return None

            def load_episode_state(self, _session_id):
                return type(
                    "_Episode",
                    (),
                    {
                        "episode_id": "current-session",
                        "personal_model_id": "you",
                        "state_id": "state-1",
                    },
                )()

            def current_state(self):
                return type("_State", (), {"state_id": "state-1"})()

            def list_episodes(self, **kwargs):
                return ()

            def list_semantic_index_entries(self, **kwargs):
                return ()

            def list_steps(self, *, loop_id=None):
                return (
                    Step(
                        step_id="step-current",
                        loop_id="loop-current",
                        episode_id="current-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="observation",
                        action="record_input",
                        status="completed",
                        sequence=1,
                        created_at=now,
                        summary="source item ingested",
                        metadata={
                            "event_type": "turn.received",
                            "user_query": "当前这轮也提到了家庭。",
                        },
                    ),
                    Step(
                        step_id="step-old",
                        loop_id="loop-old",
                        episode_id="old-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="observation",
                        action="record_input",
                        status="completed",
                        sequence=2,
                        created_at=now,
                        summary="source item ingested",
                        metadata={
                            "event_type": "turn.received",
                            "user_query": "昨晚我们聊了家庭边界。",
                        },
                    ),
                )

        result = PersonalModelUnderstandingSurface(
            repository=_Repo()
        ).search_conversation(
            "current-session",
            query="家庭",
            time_range={
                "start_at": "2026-05-09T00:00:00+00:00",
                "end_at": "2026-05-09T02:00:00+00:00",
            },
            mode="recall",
        )

        contents = "\n".join(
            str(hit.get("content") or "") for hit in tuple(result.get("hits") or ())
        )
        self.assertIn("昨晚我们聊了家庭边界", contents)
        self.assertNotIn("当前这轮", contents)

    def test_conversation_discover_returns_copyable_range_and_user_anchor_first(
        self,
    ) -> None:
        now = datetime(2026, 5, 9, 1, 20, tzinfo=timezone.utc)

        class _Repo:
            def ensure_default_personal_model(self, personal_model_id="you"):
                return None

            def load_episode_state(self, _session_id):
                return type(
                    "_Episode",
                    (),
                    {
                        "episode_id": "current-session",
                        "personal_model_id": "you",
                        "state_id": "state-1",
                    },
                )()

            def current_state(self):
                return type("_State", (), {"state_id": "state-1"})()

            def list_episodes(self, **kwargs):
                return ()

            def list_semantic_index_entries(self, **kwargs):
                return ()

            def list_steps(self, *, loop_id=None):
                return (
                    Step(
                        step_id="step-assistant",
                        loop_id="loop-old",
                        episode_id="old-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="acting",
                        action="emit_response",
                        status="completed",
                        sequence=1,
                        created_at=now,
                        summary="家庭边界需要慢慢处理。",
                        metadata={"assistant_response": "家庭边界需要慢慢处理。"},
                    ),
                    Step(
                        step_id="step-user",
                        loop_id="loop-old",
                        episode_id="old-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="observation",
                        action="record_input",
                        status="completed",
                        sequence=2,
                        created_at=now,
                        summary="source item ingested",
                        metadata={
                            "event_type": "turn.received",
                            "user_query": "我说了一个家庭边界的具体场景。",
                        },
                    ),
                )

        result = PersonalModelUnderstandingSurface(
            repository=_Repo()
        ).search_conversation(
            "current-session",
            query="家庭边界",
            time_range={
                "start_at": "2026-05-09T00:00:00+00:00",
                "end_at": "2026-05-09T02:00:00+00:00",
                "timezone": "Asia/Shanghai",
            },
            mode="discover",
            bucket="hour",
        )

        ranges = tuple(result.get("ranges") or ())
        self.assertEqual(len(ranges), 1)
        self.assertIn("time_range", ranges[0])
        self.assertEqual(ranges[0]["anchors"][0]["kind"], "turn:user")
        self.assertIn("家庭边界的具体场景", ranges[0]["anchors"][0]["text"])

    def test_recall_filters_tool_steps_and_internal_opening_prompts(self) -> None:
        now = datetime(2026, 5, 9, 1, 0, tzinfo=timezone.utc)

        class _Repo:
            def ensure_default_personal_model(self, personal_model_id="you"):
                return None

            def load_episode_state(self, _session_id):
                return type(
                    "_Episode", (), {"personal_model_id": "you", "state_id": "state-1"}
                )()

            def current_state(self):
                return type("_State", (), {"state_id": "state-1"})()

            def list_episodes(self, **kwargs):
                return ()

            def list_semantic_index_entries(self, **kwargs):
                return ()

            def list_steps(self, *, loop_id=None):
                return (
                    Step(
                        step_id="step-tool",
                        loop_id="loop-1",
                        episode_id="old-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="acting",
                        action="call_tool",
                        status="completed",
                        sequence=1,
                        created_at=now,
                        summary="tool result mentions family but is not conversation",
                        metadata={
                            "tool_name": "tool.conversation.search",
                            "tool_result": "家庭 recall test report",
                        },
                    ),
                    Step(
                        step_id="step-internal",
                        loop_id="loop-1",
                        episode_id="old-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="observation",
                        action="record_input",
                        status="completed",
                        sequence=2,
                        created_at=now,
                        summary="source item ingested",
                        metadata={
                            "event_type": "turn.internal",
                            "user_query": "Write Iris's first message about family.",
                        },
                    ),
                    Step(
                        step_id="step-user",
                        loop_id="loop-1",
                        episode_id="old-session",
                        state_id="state-1",
                        personal_model_id="you",
                        phase="observation",
                        action="record_input",
                        status="completed",
                        sequence=3,
                        created_at=now,
                        summary="source item ingested",
                        metadata={
                            "event_type": "turn.received",
                            "user_query": "我们昨晚聊了家庭权力结构。",
                        },
                    ),
                )

        result = PersonalModelUnderstandingSurface(
            repository=_Repo()
        ).recall_personal_model(
            "session-life",
            query="家庭",
            time_range={
                "start_at": "2026-05-08T18:00:00+00:00",
                "end_at": "2026-05-09T06:00:00+00:00",
            },
        )

        contents = "\n".join(
            str(hit.get("content") or "") for hit in tuple(result.get("hits") or ())
        )
        self.assertIn("家庭权力结构", contents)
        self.assertNotIn("tool result", contents)
        self.assertNotIn("Write Iris", contents)


def _fact() -> Fact:
    return Fact(
        fact_id="claim:1",
        personal_model_id="you",
        lens="world",
        text="User likes concise examples.",
        confidence=0.8,
        committed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source="user_explicit",
        metadata={"topic": "world.preference.examples"},
    )


if __name__ == "__main__":
    unittest.main()
