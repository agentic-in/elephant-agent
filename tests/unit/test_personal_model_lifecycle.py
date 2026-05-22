"""Tests for lifecycle metadata on Personal Model writes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from packages.contracts import Fact, Step
from packages.evidence import recall_time_range_from_payload
from packages.storage import RuntimeStorageRepository
from packages.tools.handlers_personal_model import run_personal_model_search, run_personal_model_update
from packages.tools.runtime import ToolInvocation, ToolRuntimeContext
from packages.understanding import PersonalModelUnderstandingSurface
from packages.understanding.personal_model_governance import protected_topic_metadata


class PersonalModelLifecycleTest(unittest.TestCase):
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
                return type("_Episode", (), {"personal_model_id": "you", "state_id": "state-1"})()

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

        result = PersonalModelUnderstandingSurface(repository=_Repo()).recall_personal_model(
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
                return type("_Episode", (), {"episode_id": "current-session", "personal_model_id": "you", "state_id": "state-1"})()

            def current_state(self):
                return type("_State", (), {"state_id": "state-1"})()

            def list_episodes(self, **kwargs):
                return ()

            def list_semantic_index_entries(self, **kwargs):
                return ()

            def list_steps(self, *, loop_id=None):
                return ()

        result = PersonalModelUnderstandingSurface(repository=_Repo()).search_conversation(
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
                return type("_Episode", (), {"episode_id": "current-session", "personal_model_id": "you", "state_id": "state-1"})()

            def current_state(self):
                return type("_State", (), {"state_id": "state-1"})()

            def list_episodes(self, **kwargs):
                return ()

            def list_semantic_index_entries(self, **kwargs):
                return ()

            def list_steps(self, *, loop_id=None):
                return ()

        result = PersonalModelUnderstandingSurface(repository=_Repo()).search_conversation(
            "current-session",
            mode="discover",
            time_range={"expr": "2026-05-13", "timezone": "Asia/Shanghai"},
        )

        self.assertNotIn("requires_time_range", result)
        self.assertEqual(result["resolved_time_range"]["start_at"], "2026-05-13T00:00+08:00")
        self.assertEqual(result["resolved_time_range"]["end_at"], "2026-05-14T00:00+08:00")

    def test_conversation_search_excludes_current_episode_by_default(self) -> None:
        now = datetime(2026, 5, 9, 1, 0, tzinfo=timezone.utc)

        class _Repo:
            def ensure_default_personal_model(self, personal_model_id="you"):
                return None

            def load_episode_state(self, _session_id):
                return type("_Episode", (), {"episode_id": "current-session", "personal_model_id": "you", "state_id": "state-1"})()

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
                        metadata={"event_type": "turn.received", "user_query": "当前这轮也提到了家庭。"},
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
                        metadata={"event_type": "turn.received", "user_query": "昨晚我们聊了家庭边界。"},
                    ),
                )

        result = PersonalModelUnderstandingSurface(repository=_Repo()).search_conversation(
            "current-session",
            query="家庭",
            time_range={"start_at": "2026-05-09T00:00:00+00:00", "end_at": "2026-05-09T02:00:00+00:00"},
            mode="recall",
        )

        contents = "\n".join(str(hit.get("content") or "") for hit in tuple(result.get("hits") or ()))
        self.assertIn("昨晚我们聊了家庭边界", contents)
        self.assertNotIn("当前这轮", contents)

    def test_conversation_discover_returns_copyable_range_and_user_anchor_first(self) -> None:
        now = datetime(2026, 5, 9, 1, 20, tzinfo=timezone.utc)

        class _Repo:
            def ensure_default_personal_model(self, personal_model_id="you"):
                return None

            def load_episode_state(self, _session_id):
                return type("_Episode", (), {"episode_id": "current-session", "personal_model_id": "you", "state_id": "state-1"})()

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
                        metadata={"event_type": "turn.received", "user_query": "我说了一个家庭边界的具体场景。"},
                    ),
                )

        result = PersonalModelUnderstandingSurface(repository=_Repo()).search_conversation(
            "current-session",
            query="家庭边界",
            time_range={"start_at": "2026-05-09T00:00:00+00:00", "end_at": "2026-05-09T02:00:00+00:00", "timezone": "Asia/Shanghai"},
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
                return type("_Episode", (), {"personal_model_id": "you", "state_id": "state-1"})()

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
                        metadata={"tool_name": "tool.conversation.search", "tool_result": "家庭 recall test report"},
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
                        metadata={"event_type": "turn.internal", "user_query": "Write Iris's first message about family."},
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
                        metadata={"event_type": "turn.received", "user_query": "我们昨晚聊了家庭权力结构。"},
                    ),
                )

        result = PersonalModelUnderstandingSurface(repository=_Repo()).recall_personal_model(
            "session-life",
            query="家庭",
            time_range={"start_at": "2026-05-08T18:00:00+00:00", "end_at": "2026-05-09T06:00:00+00:00"},
        )

        contents = "\n".join(str(hit.get("content") or "") for hit in tuple(result.get("hits") or ()))
        self.assertIn("家庭权力结构", contents)
        self.assertNotIn("tool result", contents)
        self.assertNotIn("Write Iris", contents)

    def test_tool_update_adds_review_metadata_for_changeable_account_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)

            result = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.profile.positioning",
                text="小红书账号约20条笔记，399赞藏，10+粉丝。",
                reason="user shared account data",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )
            claim = result["claim"]
            fact = repository.list_personal_model_facts(
                personal_model_id=state.personal_model_id,
                status="active",
            )[0]

        self.assertEqual(claim["recall_policy"], "review")
        self.assertEqual(claim["retention_lifecycle"], "review")
        self.assertEqual(claim["review_after_days"], "14")
        self.assertEqual(fact.metadata["retention_lifecycle"], "review")
        self.assertIn("last_verified_at", fact.metadata)

    def test_topics_mode_lists_existing_topic_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，399赞藏，10+粉丝。",
                reason="user shared account data",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )

            result = surface.audit_personal_model(
                "session-life",
                action="topics",
                personal_model_id=state.personal_model_id,
            )

        topics = tuple(result.get("topics") or ())
        self.assertEqual(topics[0]["topic"], "xiaohongshu.account.metrics")
        self.assertEqual(topics[0]["recall_policy"], "review")

    def test_update_surfaces_related_active_claims_for_similar_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.profile.positioning",
                text="小红书账号旧概览，399赞藏，10+粉丝。",
                reason="user shared account data",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )

            result = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号新指标，420赞藏，18粉丝。",
                reason="user shared account metrics",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )

        related = tuple(result.get("related_active_claims") or ())
        self.assertTrue(related)
        self.assertEqual(related[0]["topic"], "xiaohongshu.profile.positioning")

    def test_correct_inherits_existing_recall_policy_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，420赞藏，18粉丝。",
                reason="user shared account data",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )

            result = surface.update_personal_model(
                "session-life",
                action="correct",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，430赞藏，21粉丝。",
                reason="user corrected account metrics",
                source="user_corrected",
                personal_model_id=state.personal_model_id,
            )
            fact = repository.list_personal_model_facts(
                personal_model_id=state.personal_model_id,
                status="active",
            )[0]

        self.assertEqual(result["claim"]["recall_policy"], "review")
        self.assertEqual(fact.metadata["recall_policy"], "review")
        self.assertEqual(fact.metadata["review_after_days"], "14")
        self.assertIn("last_verified_at", fact.metadata)

    def test_forget_no_match_returns_ref_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)

            result = surface.update_personal_model(
                "session-life",
                action="forget",
                lens="world",
                topic="unknown.topic.key",
                reason="cleanup",
                personal_model_id=state.personal_model_id,
            )

        self.assertIn("search first and retry with ref", result["no_match_hint"])

    def test_delete_soft_deletes_unprotected_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            created = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号指标重复草稿。",
                reason="seed duplicate",
                personal_model_id=state.personal_model_id,
            )["claim"]

            result = run_personal_model_update(
                ToolInvocation(
                    invocation_id="invoke:delete-claim",
                    tool_id="tool.personal_model.update",
                    session_id="session-life",
                    context=ToolRuntimeContext(cwd=Path(tmpdir), personal_model_id=state.personal_model_id),
                    arguments={
                        "action": "delete",
                        "lens": "world",
                        "topic": "xiaohongshu.account.metrics",
                        "ref": created["ref"],
                        "reason": "duplicate invalid claim",
                        "source": "learned",
                    },
                ),
                surface=surface,
            )
            deleted = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="deleted")
            active = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="active")

        self.assertIn("status: deleted", result["summary"])
        self.assertIn(f"retired: {created['ref']}", result["summary"])
        self.assertEqual(active, ())
        self.assertEqual(deleted[0].fact_id, created["ref"])
        self.assertEqual(deleted[0].metadata["understanding_status"], "deleted")

    def test_delete_protected_claim_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            created = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="identity",
                topic="identity.body.safety.boundary",
                text="称呼：zoey。",
                reason="core profile seed",
                personal_model_id=state.personal_model_id,
            )["claim"]

            result = run_personal_model_update(
                ToolInvocation(
                    invocation_id="invoke:delete-protected-claim",
                    tool_id="tool.personal_model.update",
                    session_id="session-life",
                    context=ToolRuntimeContext(cwd=Path(tmpdir), personal_model_id=state.personal_model_id),
                    arguments={
                        "action": "delete",
                        "lens": "identity",
                        "topic": "identity.body.safety.boundary",
                        "ref": created["ref"],
                        "reason": "cleanup attempt",
                    },
                ),
                surface=surface,
            )
            active = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="active")

        self.assertIn("status: protected", result["summary"])
        self.assertIn("protected core topic cannot be deleted", result["summary"])
        self.assertEqual(active[0].fact_id, created["ref"])

    def test_background_learning_cannot_change_preferred_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            now = datetime.now(timezone.utc)
            repository.upsert_personal_model_fact(
                Fact(
                    fact_id="fact:preferred-name",
                    personal_model_id=state.personal_model_id,
                    lens="identity",
                    text="Bit",
                    confidence=1.0,
                    committed_at=now,
                    source="user_explicit",
                    status="active",
                    metadata={
                        **protected_topic_metadata("identity.anchor.name.preferred"),
                        "topic": "identity.anchor.name.preferred",
                    },
                )
            )

            result = run_personal_model_update(
                ToolInvocation(
                    invocation_id="invoke:overwrite-protected-name",
                    tool_id="tool.personal_model.update",
                    session_id="session-life",
                    context=ToolRuntimeContext(cwd=Path(tmpdir), personal_model_id=state.personal_model_id),
                    arguments={
                        "action": "correct",
                        "lens": "identity",
                        "topic": "identity.anchor.name.preferred",
                        "text": "训灼",
                        "source": "learned",
                        "reason": "background inference",
                    },
                ),
                surface=surface,
            )
            active = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="active")

        self.assertIn("status: protected", result["summary"])
        self.assertEqual(tuple(fact.text for fact in active), ("Bit",))

    def test_chat_correction_can_change_preferred_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            now = datetime.now(timezone.utc)
            repository.upsert_personal_model_fact(
                Fact(
                    fact_id="fact:preferred-name",
                    personal_model_id=state.personal_model_id,
                    lens="identity",
                    text="Bit",
                    confidence=1.0,
                    committed_at=now,
                    source="user_explicit",
                    status="active",
                    metadata={
                        **protected_topic_metadata("identity.anchor.name.preferred"),
                        "topic": "identity.anchor.name.preferred",
                    },
                )
            )

            result = run_personal_model_update(
                ToolInvocation(
                    invocation_id="invoke:chat-correct-name",
                    tool_id="tool.personal_model.update",
                    session_id="session-life",
                    context=ToolRuntimeContext(cwd=Path(tmpdir), personal_model_id=state.personal_model_id),
                    arguments={
                        "action": "correct",
                        "lens": "identity",
                        "topic": "identity.anchor.name.preferred",
                        "text": "灼灼",
                        "reason": "user asked to change preferred name in chat",
                    },
                ),
                surface=surface,
            )
            active = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="active")

        self.assertNotIn("status: protected", result["summary"])
        self.assertEqual(tuple(fact.text for fact in active), ("灼灼",))

    def test_search_diagnostics_returns_related_claims_and_broad_tip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            for idx in range(9):
                surface.update_personal_model(
                    "session-life",
                    action="remember",
                    lens="world",
                    topic=f"xiaohongshu.account.sample_{idx}",
                    text=f"小红书账号指标样本 {idx}。",
                    reason="seed broad search",
                    source="user_said",
                    recall_policy="review",
                    personal_model_id=state.personal_model_id,
                )

            result = surface.search_personal_model(
                "session-life",
                query="小红书账号指标",
                include_diagnostics=True,
                personal_model_id=state.personal_model_id,
                limit=12,
            )
            plain_result = surface.search_personal_model(
                "session-life",
                query="小红书账号指标",
                personal_model_id=state.personal_model_id,
                limit=12,
            )

        self.assertIn("narrowing_suggestions", result["search_tip"])
        suggestions = tuple(result.get("narrowing_suggestions") or ())
        self.assertTrue(suggestions)
        self.assertTrue(any("topic or ref" in item["suggestion"] for item in suggestions))
        self.assertTrue(tuple(plain_result.get("narrowing_suggestions") or ()))
        self.assertTrue(tuple(result.get("related_active_claims") or ()))

    def test_search_status_and_ref_can_audit_retired_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            old = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，438赞藏，23粉丝。",
                reason="seed old account data",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )["claim"]
            surface.update_personal_model(
                "session-life",
                action="correct",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，438赞藏，24粉丝。",
                reason="user corrected account data",
                source="user_corrected",
                personal_model_id=state.personal_model_id,
            )

            retired = surface.search_personal_model(
                "session-life",
                ref=old["ref"],
                status="retired",
                personal_model_id=state.personal_model_id,
            )
            all_hits = surface.search_personal_model(
                "session-life",
                topic="xiaohongshu.account.metrics",
                status="all",
                personal_model_id=state.personal_model_id,
            )

        retired_claims = tuple(retired.get("claims") or ())
        self.assertEqual(retired_claims[0]["ref"], old["ref"])
        self.assertEqual(retired_claims[0]["status"], "retired")
        statuses = {claim["status"] for claim in tuple(all_hits.get("claims") or ())}
        self.assertIn("active", statuses)
        self.assertIn("retired", statuses)

    def test_question_answer_writes_dot_path_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            created = surface.manage_personal_model_questions(
                "session-life",
                action="create",
                personal_model_id=state.personal_model_id,
                lens="identity",
                sub_lens="feedback_preference",
                text="How should I give feedback?",
                reason="seed question",
            )
            question_id = created["question"]["question_id"]

            answered = surface.manage_personal_model_questions(
                "session-life",
                action="answer",
                personal_model_id=state.personal_model_id,
                question_id=question_id,
                answer="Give options, then recommend one.",
            )

        claim = answered["claim_update"]["claim"]
        self.assertEqual(claim["topic"], "identity.question.feedback_preference")

    def test_audit_surface_returns_topics_and_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            surface.update_personal_model(
                "session-life",
                action="remember",
                lens="identity",
                topic="assistant.review.style",
                text="做评审时先指出最大风险。",
                reason="seed review style",
                source="user_said",
                recall_policy="stable",
                personal_model_id=state.personal_model_id,
            )

            topics = surface.audit_personal_model("session-life", action="topics", personal_model_id=state.personal_model_id)
            health = surface.audit_personal_model("session-life", action="health", personal_model_id=state.personal_model_id)

        self.assertTrue(tuple(topics.get("topics") or ()))
        self.assertEqual(health["health_report"]["total_active_claims"], 1)

    def test_single_active_topic_remember_supersedes_existing_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            first = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，438赞藏，25粉丝。",
                reason="seed old metrics",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )["claim"]
            second = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，438赞藏，26粉丝。",
                reason="new metrics",
                source="user_said",
                personal_model_id=state.personal_model_id,
            )

            active = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="active")
            retired = surface.search_personal_model("session-life", ref=first["ref"], status="retired", personal_model_id=state.personal_model_id)

        self.assertEqual(len(active), 1)
        self.assertEqual(second["retired"], (first["ref"],))
        self.assertEqual(tuple(retired.get("claims") or ())[0]["status"], "retired")

    def test_skill_optimization_claim_payload_and_search_surface_expose_candidate_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)

            claim = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="world.skills.optimization.python_development.update_procedure_ab12cd34",
                text="将 tool.terminal.exec → tool.file.read 编码为稳定流程。",
                reason="reflect candidate draft",
                source="user_said",
                personal_model_id=state.personal_model_id,
                metadata={
                    "review_status": "new",
                    "confidence": "0.84",
                    "optimization_type": "update_procedure",
                    "signal_type": "recurring_sequence",
                    "occurrence_count": "5",
                    "suggested_action": "Update python-development to encode the repeated tool sequence tool.terminal.exec -> tool.file.read.",
                    "skill_id": "python-development",
                },
            )["claim"]
            fact = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="active")[0]
            search = run_personal_model_search(
                ToolInvocation(
                    invocation_id="invoke:search-skillopt-claim",
                    tool_id="tool.personal_model.search",
                    session_id="session-life",
                    context=ToolRuntimeContext(cwd=Path(tmpdir), personal_model_id=state.personal_model_id),
                    arguments={
                        "lens": "world",
                        "topic": "world.skills.optimization.python_development.update_procedure_ab12cd34",
                        "personal_model_id": state.personal_model_id,
                    },
                ),
                surface=surface,
            )

        self.assertEqual(claim["candidate_key"], "update_procedure_ab12cd34")
        self.assertEqual(claim["candidate_id"], "skillopt_update_procedure_ab12cd34")
        self.assertEqual(claim["target_scope"], "python_development")
        self.assertEqual(claim["index_id"], "python_development")
        self.assertEqual(claim["skill_id"], "python-development")
        self.assertEqual(claim["optimization_type"], "update_procedure")
        self.assertEqual(claim["signal_type"], "recurring_sequence")
        self.assertEqual(claim["occurrence_count"], "5")
        self.assertEqual(claim["review_status"], "pending")
        self.assertEqual(claim["confidence"], 0.84)
        self.assertEqual(fact.confidence, 0.84)
        self.assertIn("candidate_key=update_procedure_ab12cd34", search["summary"])
        self.assertIn("review_status=pending", search["summary"])
        self.assertIn("target_scope=python_development", search["summary"])
        self.assertIn("confidence=0.84", search["summary"])
        self.assertIn("suggested_action: Update python-development to encode the repeated tool sequence", search["summary"])

    def test_skill_optimization_topics_are_normalized_at_write_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)

            created = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="world.skills.optimization.new.tool_sequence_questions_skill_list",
                text="将 tool.personal_model.questions → tool.skill.list 编码为过程性行为模式。",
                reason="reflect candidate draft",
                source="user_said",
                personal_model_id=state.personal_model_id,
                metadata={"review_status": "new"},
            )["claim"]
            updated = surface.update_personal_model(
                "session-life",
                action="correct",
                lens="world",
                topic="world.skills.optimization.new.tool_sequence_questions_skill_list",
                ref=created["ref"],
                text="将 tool.personal_model.questions → tool.skill.list 编码为稳定的过程性行为模式。",
                reason="tighten candidate wording",
                source="user_said",
                personal_model_id=state.personal_model_id,
                metadata={},
            )["claim"]
            active = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="active")
            self.assertEqual(len(active), 1)
            fact = active[0]

        self.assertEqual(updated["ref"], fact.fact_id)
        self.assertEqual(fact.metadata["source_kind"], "learned")
        self.assertEqual(fact.metadata["recall_policy"], "review")
        self.assertEqual(fact.metadata["retention_lifecycle"], "draft")
        self.assertEqual(fact.metadata["projection_policy"], "skill_optimization_candidate")
        self.assertEqual(fact.metadata["review_status"], "pending")
        self.assertEqual(fact.metadata["candidate_key"], "tool_sequence_questions_skill_list")
        self.assertEqual(fact.metadata["candidate_id"], "skillopt_tool_sequence_questions_skill_list")

    def test_restore_reactivates_disputed_claim_by_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            claim = surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="animal.welfare.nepal_elephant",
                text="用户关注尼泊尔大象福利。",
                reason="seed animal welfare fact",
                source="user_said",
                personal_model_id=state.personal_model_id,
            )["claim"]
            surface.update_personal_model(
                "session-life",
                action="dispute",
                lens="world",
                topic="animal.welfare.nepal_elephant",
                ref=claim["ref"],
                reason="temporary disagreement",
                personal_model_id=state.personal_model_id,
            )

            restored = surface.update_personal_model(
                "session-life",
                action="restore",
                lens="world",
                topic="animal.welfare.nepal_elephant",
                ref=claim["ref"],
                reason="user confirmed the claim again",
                personal_model_id=state.personal_model_id,
            )
            active = repository.list_personal_model_facts(personal_model_id=state.personal_model_id, status="active")

        self.assertEqual(restored["status"], "active")
        self.assertEqual(restored["claim"]["ref"], claim["ref"])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].metadata.get("restored_by"), "tool.personal_model.update")

    def test_health_and_related_reasons_with_clean_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，438赞藏，23粉丝。",
                reason="old account data",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )
            surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.snapshot",
                text="小红书账号约21条笔记，438赞藏，24粉丝。",
                reason="new account data",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )

            topics = surface.audit_personal_model("session-life", action="topics", personal_model_id=state.personal_model_id)
            health = surface.audit_personal_model("session-life", action="health", personal_model_id=state.personal_model_id)
            related = surface.search_personal_model(
                "session-life",
                query="小红书账号",
                include_diagnostics=True,
                personal_model_id=state.personal_model_id,
            )

        topic_rows = tuple(topics.get("topics") or ())
        self.assertEqual(topic_rows[0]["topic"], "xiaohongshu.account.metrics")
        report = health["health_report"]
        self.assertIn("total_active_claims", report)
        related_rows = tuple(related.get("related_active_claims") or ())
        self.assertTrue(related_rows)
        self.assertIn("relation_reason", related_rows[0])

    def test_update_rejects_bad_topic_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)

            with self.assertRaisesRegex(ValueError, "dot.path"):
                surface.update_personal_model(
                    "session-life",
                    action="remember",
                    lens="world",
                    topic="xiaohongshu_account_metrics",
                    text="旧格式 topic 不应被接受。",
                    reason="invalid topic test",
                    source="user_said",
                    personal_model_id=state.personal_model_id,
                )

    def test_forget_dispute_without_ref_does_not_report_retired_when_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)
            surface.update_personal_model(
                "session-life",
                action="remember",
                lens="world",
                topic="xiaohongshu.account.metrics",
                text="小红书账号约20条笔记，438赞藏，23粉丝。",
                reason="seed old account data",
                source="user_said",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
            )

            result = surface.update_personal_model(
                "session-life",
                action="forget",
                lens="world",
                topic="xiaohongshu.account.metric",
                reason="cleanup duplicate",
                personal_model_id=state.personal_model_id,
            )

        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("retry with ref", result["no_match_hint"])
        self.assertTrue(tuple(result.get("related_active_claims") or ()))
        self.assertFalse(tuple(result.get("retired") or ()))

    def test_tool_update_keeps_rapport_preference_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-life", elephant_name="Life")
            surface = PersonalModelUnderstandingSurface(repository=repository)

            surface.update_personal_model(
                "session-life",
                action="remember",
                lens="identity",
                topic="assistant.answer.style",
                text="User prefers concise answers.",
                reason="user said it",
                source="user_said",
                personal_model_id=state.personal_model_id,
            )
            fact = repository.list_personal_model_facts(
                personal_model_id=state.personal_model_id,
                status="active",
            )[0]

        self.assertEqual(fact.metadata["retention_lifecycle"], "preference")
        self.assertNotIn("last_verified_at", fact.metadata)


if __name__ == "__main__":
    unittest.main()
