from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.cron import CronRuntime
from packages.tools.builtins import builtin_tool_definitions
from packages.tools.adapters import DeliveryMessageSurfaceAdapter, StructuredClarifySurface
from packages.tools import (
    BuiltinToolDependencies,
    ToolDefinition,
    ToolSideEffectMetadata,
    build_tool_fallback_prompt,
)
from tests.unit.builtin_tools_test_support import BuiltinToolsTestBase


class _DeliveryStub:
    def deliver(self, session_id: str, payload):  # type: ignore[no-untyped-def]
        return {
            "execution_id": f"delivery:{session_id}",
            "summary": f"delivered {payload.get('body', '')}",
            "outcome": "success",
            "side_effects": ("delivery",),
        }


class _SubAgentsStub:
    def __init__(self) -> None:
        self.single: dict[str, object] | None = None
        self.batch: dict[str, object] | None = None
        self.started: dict[str, object] | None = None
        self.inspected: dict[str, object] | None = None

    def run_sub_agent(
        self,
        *,
        session_id: str,
        task: str,
        name: str | None = None,
        skills: tuple[str, ...] = (),
    ):
        self.single = {"session_id": session_id, "task": task, "name": name, "skills": skills}
        if task == "fail":
            return {"summary": "sub-agent failed", "status": "failed"}
        return {"summary": "single sub-agent finished"}

    def run_sub_agents(
        self,
        *,
        session_id: str,
        tasks,
        max_concurrency: int = 3,
    ):
        self.batch = {"session_id": session_id, "tasks": tasks, "max_concurrency": max_concurrency}
        return {"summary": "sub-agent pool finished"}

    def start_sub_agents(
        self,
        *,
        session_id: str,
        tasks,
        max_concurrency: int = 3,
    ):
        self.started = {"session_id": session_id, "tasks": tasks, "max_concurrency": max_concurrency}
        return {
            "summary": "sub_agent_run_id: subrun-test\nstatus: running",
            "run_id": "subrun-test",
            "status": "running",
        }

    def inspect_sub_agent_run(
        self,
        *,
        session_id: str,
        run_id: str,
        wait_timeout_seconds: float | None = None,
    ):
        self.inspected = {
            "session_id": session_id,
            "run_id": run_id,
            "wait_timeout_seconds": wait_timeout_seconds,
        }
        return {
            "summary": f"sub_agent_run_id: {run_id}\nstatus: completed",
            "run_id": run_id,
            "status": "completed",
        }

    def list_sub_agent_runs(self, *, session_id: str):
        return {"summary": f"runs for {session_id}", "status": "completed"}


class _ConversationSearchStub:
    def search_personal_model(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return {"personal_model_id": "you", "claims": ()}

    def search_conversation(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return {
            "personal_model_id": "you",
            "scope": "history",
            "mode": kwargs.get("mode", "discover"),
            "view": kwargs.get("view", "conversation"),
            "query": kwargs.get("query", "release"),
            "bucket": "hour",
            "total": 1,
            "ranges": (
                {
                    "range_id": "range-1",
                    "start_at": "2026-05-12T08:00:00+08:00",
                    "end_at": "2026-05-12T09:00:00+08:00",
                    "score": 1,
                    "count": 2,
                    "by_kind": {"turn:user": 1},
                    "time_range": {
                        "start_at": "2026-05-12T08:00:00+08:00",
                        "end_at": "2026-05-12T09:00:00+08:00",
                        "timezone": "Asia/Shanghai",
                    },
                    "anchors": (),
                },
            ),
        }


class _DiaryStub:
    def __init__(self) -> None:
        self.last_write_kwargs = None

    def write_diary_entry(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_write_kwargs = kwargs
        return {"entry_date": kwargs["entry_date"]}

    def list_diary_entries(self, **kwargs):  # type: ignore[no-untyped-def]
        return {"entries": ({"entry_date": "2026-05-14", "content": "Today note"},), "count": 1}


class BuiltinToolsV2Test(BuiltinToolsTestBase):


    def test_runtime_filters_model_visible_available_tools(self) -> None:
        runtime = self._make_builtin_runtime(
            cwd=Path("/tmp"),
            dependencies=BuiltinToolDependencies(
                cwd=Path("/tmp"),
                cron_runtime=object(),
                personal_model_understanding=object(),
                skill_management=object(),
            ),
        )
        runtime.register_tool(
            ToolDefinition(
                tool_id="tool.operator.audit",
                display_name="Operator Audit",
                version="1.0.0",
                family="operator",
                audience="operator",
                backend="in-memory",
                description="Operator-only helper.",
                side_effects=ToolSideEffectMetadata(categories=("operator",)),
            ),
            handler=lambda invocation: {"summary": invocation.tool_id},
        )

        model_visible = {tool.tool_id for tool in runtime.list_tools(audience="model", enabled_only=True, available_only=True)}
        operator_visible = {tool.tool_id for tool in runtime.list_tools(audience="operator", enabled_only=True)}

        self.assertIn("tool.file.read", model_visible)
        self.assertIn("tool.personal_model.search", model_visible)
        self.assertIn("tool.personal_model.update", model_visible)
        self.assertIn("tool.personal_model.questions", model_visible)
        self.assertNotIn("tool.memory.recall", model_visible)
        self.assertNotIn("tool.memory.note", model_visible)
        self.assertIn("tool.skill.list", model_visible)
        self.assertIn("tool.skill.view", model_visible)
        self.assertIn("tool.skill.draft", model_visible)
        self.assertNotIn("tool.profile.manage", model_visible)
        self.assertNotIn("tool.memory.upload", model_visible)
        self.assertNotIn("tool.procedure.inspect", model_visible)
        self.assertNotIn("tool.procedure.manage", model_visible)
        self.assertNotIn("tool.skill.manage", model_visible)
        self.assertNotIn("tool.browser.navigate", model_visible)
        self.assertNotIn("tool.message.send", model_visible)
        self.assertNotIn("tool.operator.audit", model_visible)
        self.assertNotIn("tool.diary.write", model_visible)
        self.assertNotIn("tool.diary.list", model_visible)
        self.assertNotIn("tool.learning.result.write", model_visible)
        self.assertIn("tool.operator.audit", operator_visible)
        self.assertIn("tool.skill.manage", operator_visible)

    def test_personal_model_questions_tool_can_manage_open_questions(self) -> None:
        runtime = self._make_cli_runtime()
        session = runtime.start()

        listed = runtime.tool_runtime.invoke(
            "tool.personal_model.questions",
            {"action": "list", "status": "open", "limit": 3},
            session_id=session.session_id,
            requester="model",
        )
        self.assertIn("questions:", listed.summary)
        created = runtime.tool_runtime.invoke(
            "tool.personal_model.questions",
            {
                "action": "create",
                "lens": "identity",
                "topic": "test.preference",
                "text": "What should I learn next?",
                "reason": "unit test",
                "priority": 0.7,
            },
            session_id=session.session_id,
            requester="model",
        )
        self.assertIn("test.preference", created.summary)
        created_alias = runtime.tool_runtime.invoke(
            "tool.personal_model.questions",
            {
                "action": "create",
                "lens": "identity",
                "topic": "test.alias",
                "question": "Which wording should I use?",
                "reason": "unit test",
            },
            session_id=session.session_id,
            requester="model",
        )
        self.assertIn("Which wording should I use?", created_alias.summary)
        question_id = next(
            q.question_id
            for q in runtime.repository.list_open_questions(
                personal_model_id=session.personal_model_id,
                status="open",
                sub_lens="test.preference",
            )
        )
        asked = runtime.tool_runtime.invoke(
            "tool.personal_model.questions",
            {"action": "ask", "question_id": question_id, "surface": "unit-test"},
            session_id=session.session_id,
            requester="model",
        )
        self.assertIn("asked", asked.summary)
        stored = runtime.repository.list_open_questions(
            personal_model_id=session.personal_model_id,
            status="asked",
            sub_lens="test.preference",
        )
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].last_asked_surface, "unit-test")

    def test_skill_tools_can_list_view_and_manage_authored_skills(self) -> None:
        runtime = self._make_cli_runtime()
        session = runtime.start()

        listed = runtime.tool_runtime.invoke(
            "tool.skill.list",
            {"limit": 8},
            session_id=session.session_id,
            requester="model",
        )
        viewed = runtime.tool_runtime.invoke(
            "tool.skill.view",
            {"skill_id": "apple-notes"},
            session_id=session.session_id,
            requester="model",
        )
        with self.assertRaisesRegex(PermissionError, "tool is not visible to model: tool.skill.manage"):
            runtime.tool_runtime.invoke(
                "tool.skill.manage",
                {
                    "action": "create",
                    "skill_id": "elephant-brief",
                    "display_name": "Elephant Agent Brief",
                    "summary": "Keep the Elephant Agent thread aligned.",
                    "instruction_text": "Always summarize Elephant Agent context before acting.",
                    "category": "research",
                },
                session_id=session.session_id,
                requester="model",
            )
        created = runtime.tool_runtime.invoke(
            "tool.skill.manage",
            {
                "action": "create",
                "skill_id": "elephant-brief",
                "display_name": "Elephant Agent Brief",
                "summary": "Keep the Elephant Agent thread aligned.",
                "instruction_text": "Always summarize Elephant Agent context before acting.",
                "category": "research",
            },
            session_id=session.session_id,
            requester="operator",
        )
        updated = runtime.tool_runtime.invoke(
            "tool.skill.manage",
            {
                "action": "update",
                "skill_id": "elephant-brief",
                "summary": "Keep the Elephant Agent thread tightly aligned.",
                "instruction_text": "Always summarize Elephant Agent context before acting, then write the next step.",
            },
            session_id=session.session_id,
            requester="operator",
        )
        viewed_authored = runtime.tool_runtime.invoke(
            "tool.skill.view",
            {"skill_id": "elephant-brief"},
            session_id=session.session_id,
            requester="model",
        )
        deleted = runtime.tool_runtime.invoke(
            "tool.skill.manage",
            {"action": "delete", "skill_id": "elephant-brief"},
            session_id=session.session_id,
            requester="operator",
        )

        self.assertEqual(listed.outcome, "success")
        self.assertIn("apple-notes", listed.summary)
        self.assertEqual(viewed.outcome, "success")
        self.assertIn("skill_id: apple-notes", viewed.summary)
        self.assertIn("Apple Notes", viewed.summary)
        self.assertEqual(created.outcome, "success")
        self.assertIn("elephant-brief", created.summary)
        self.assertEqual(updated.outcome, "success")
        self.assertIn("elephant-brief", updated.summary)
        self.assertIn("Keep the Elephant Agent thread tightly aligned.", viewed_authored.summary)
        self.assertEqual(deleted.outcome, "success")
        self.assertIn("skill_id: elephant-brief", deleted.summary)
        self.assertFalse(any(entry.skill_id == "elephant-brief" for entry in runtime.list_skill_hub(limit=None)))

    def test_skill_draft_tool_is_learning_agent_only_and_writes_pending_disabled_skill(self) -> None:
        runtime = self._make_cli_runtime()
        session = runtime.start()

        with self.assertRaisesRegex(PermissionError, "background learning agents"):
            runtime.tool_runtime.invoke(
                "tool.skill.draft",
                {
                    "action": "create",
                    "skill_id": "paper-summary-flow",
                    "display_name": "Paper Summary Flow",
                    "summary": "Use when the user repeatedly asks to turn papers into concise publication notes.",
                    "workflow_steps": ["Read the paper source.", "Write the reusable summary artifact."],
                },
                session_id=session.session_id,
                requester="model",
            )

        learning_session = replace(
            session,
            episode_id="learning-child",
            entry_surface="cli:sub_agent",
            metadata={"episode_kind": "sub_agent", "learning_agent": "true"},
        )
        runtime.repository.upsert_episode(learning_session)
        drafted = runtime.tool_runtime.invoke(
            "tool.skill.draft",
            {
                "action": "create",
                "skill_id": "paper-summary-flow",
                "display_name": "Paper Summary Flow",
                "summary": "Use when the user repeatedly asks to turn papers into concise publication notes.",
                "workflow_steps": ["1. Read the paper source.", "2. Write the reusable summary artifact."],
                "inputs": ["paper URL or PDF"],
                "outputs": ["summary notes"],
                "validation": ["The output names the source and has concrete next steps."],
                "source_episode_ids": ["episode-1", "episode-2"],
                "confidence": "0.72",
            },
            session_id=learning_session.session_id,
            requester="model",
        )

        self.assertEqual(drafted.outcome, "success")
        self.assertIn("review_status: pending", drafted.summary)
        entry = runtime.inspect_skill_hub_entry("paper-summary-flow")
        self.assertFalse(bool(entry.metadata["default_enabled"]))
        self.assertEqual(entry.metadata["review_status"], "pending")
        self.assertEqual(entry.metadata["source_kind"], "elephant-authored-draft")
        skill = runtime.inspect_skill("paper-summary-flow")
        self.assertIn("1. Read the paper source.", skill.instruction_text)
        self.assertNotIn("1. 1. Read the paper source.", skill.instruction_text)

    def test_model_skill_list_and_view_include_external_shelves(self) -> None:
        external_tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(external_tmpdir.cleanup)
        external_root = Path(external_tmpdir.name) / ".agents" / "skills"
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
        runtime = self._make_cli_runtime(external_skill_dir=external_root)
        session = runtime.start()

        listed = runtime.tool_runtime.invoke(
            "tool.skill.list",
            {"limit": 8},
            session_id=session.session_id,
            requester="model",
        )
        viewed = runtime.tool_runtime.invoke(
            "tool.skill.view",
            {"skill_id": "personal-journal"},
            session_id=session.session_id,
            requester="model",
        )

        self.assertIn("personal-journal | Personal Journal | source=agents", listed.summary)
        self.assertIn("reference=agents:personal-journal", listed.summary)
        self.assertIn("skill_id: personal-journal", viewed.summary)
        self.assertIn("Use this skill when the user asks to review personal journal notes.", viewed.summary)

    def test_model_visible_action_tools_expose_constrained_action_enums(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions({}, dependencies=BuiltinToolDependencies(cwd=Path("/tmp")))
        }

        process_action = definitions["tool.process.manage"].schema["properties"]["action"]["enum"]
        cron_action = definitions["tool.cron.manage"].schema["properties"]["action"]["enum"]
        todo_action = definitions["tool.todo.manage"].schema["properties"]["action"]["enum"]
        todo_properties = definitions["tool.todo.manage"].schema["properties"]

        self.assertEqual(tuple(process_action), ("list", "ls", "poll", "inspect", "wait", "write", "kill"))
        self.assertEqual(
            tuple(cron_action),
            ("list", "ls", "create", "inspect", "pause", "resume", "remove", "delete"),
        )
        self.assertEqual(tuple(todo_properties["status"]["enum"]), ("open", "done"))
        self.assertIn("create", tuple(todo_action))
        self.assertNotIn("noop", tuple(process_action))
        self.assertNotIn("noop", tuple(cron_action))
        self.assertNotIn("noop", tuple(todo_action))

    def test_builtin_model_schema_carries_cron_description_and_action_guidance(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions({}, dependencies=BuiltinToolDependencies(cwd=Path("/tmp")))
        }

        schema = definitions["tool.cron.manage"].model_function_schema()
        function = schema["function"]
        parameters = function["parameters"]
        action = parameters["properties"]["action"]

        self.assertEqual(
            function["description"],
            "Create, inspect, pause, resume, remove/delete, and list built-in scheduled jobs.",
        )
        self.assertIn("delete", tuple(action["enum"]))
        self.assertIn("inspect|pause|resume|remove|delete", action["description"])
        self.assertNotIn("job_kind", parameters["properties"])
        self.assertIn("5-field cron", parameters["properties"]["schedule"]["description"])
        self.assertEqual(parameters["properties"]["prompt"]["description"], "Prompt payload for the scheduled prompt job when action=create.")
        self.assertEqual(parameters["properties"]["profile_id"]["description"], "Optional profile scope filter for listing or creating jobs.")
        self.assertEqual(parameters["properties"]["elephant_id"]["description"], "Optional elephant scope filter for listing or creating jobs.")
        self.assertNotIn("message", parameters["properties"])
        self.assertNotIn("query", parameters["properties"])

    def test_personal_model_tool_schemas_replace_legacy_memory_tools(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions({}, dependencies=BuiltinToolDependencies(cwd=Path("/tmp")))
        }

        search = definitions["tool.personal_model.search"].model_function_schema()["function"]
        conversation = definitions["tool.conversation.search"].model_function_schema()["function"]
        update = definitions["tool.personal_model.update"].model_function_schema()["function"]
        questions = definitions["tool.personal_model.questions"].model_function_schema()["function"]
        code = definitions["tool.code.execute"].model_function_schema()["function"]
        sub_agents = definitions["tool.sub_agents"].model_function_schema()["function"]
        todo = definitions["tool.todo.manage"].model_function_schema()["function"]
        clarify = definitions["tool.clarify"].model_function_schema()["function"]
        process = definitions["tool.process.manage"].model_function_schema()["function"]
        web_search = definitions["tool.web.search"].model_function_schema()["function"]
        web_read = definitions["tool.web.read"].model_function_schema()["function"]
        search_properties = search["parameters"]["properties"]
        update_properties = update["parameters"]["properties"]
        question_properties = questions["parameters"]["properties"]
        code_properties = code["parameters"]["properties"]
        sub_agent_properties = sub_agents["parameters"]["properties"]
        todo_properties = todo["parameters"]["properties"]
        clarify_properties = clarify["parameters"]["properties"]
        process_properties = process["parameters"]["properties"]
        web_search_properties = web_search["parameters"]["properties"]
        web_read_properties = web_read["parameters"]["properties"]

        conversation_properties = conversation["parameters"]["properties"]
        self.assertIn("Natural-language", search_properties["query"]["description"])
        self.assertIn("mode", search_properties)
        self.assertEqual(search_properties["mode"]["enum"], ["auto", "inventory"])
        system_design = (ROOT / "docs" / "system-design" / "system-layer-model.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Public search modes", system_design)
        self.assertIn("`auto` combines", system_design)
        self.assertIn("`inventory` returns", system_design)
        self.assertNotIn("`exact` disables", system_design)
        self.assertNotIn("`semantic` favors", system_design)
        self.assertNotIn("`verify` uses", system_design)
        self.assertIn("mode", conversation_properties)
        self.assertEqual(conversation_properties["mode"]["enum"], ["discover", "recall"])
        self.assertIn("expr", conversation_properties)
        self.assertIn("start_at", conversation_properties)
        self.assertIn("end_at", conversation_properties)
        self.assertIn("timezone", conversation_properties)
        self.assertNotIn("time_range", conversation_properties)
        self.assertIn("bucket", conversation_properties)
        self.assertNotIn("include_current_episode", conversation_properties)
        self.assertNotIn("tool.conversation.recall", definitions)
        self.assertNotIn("tool.conversation.timeline", definitions)
        self.assertNotIn("tool.personal_model.verify", definitions)
        self.assertNotIn("tool.personal_model.audit", definitions)
        self.assertNotIn("tool.personal_model.inspect", definitions)
        self.assertEqual(search_properties["status"]["enum"], ["active", "retired", "disputed", "all"])
        self.assertIn("ref", search_properties)
        self.assertIn("remember", update_properties["action"]["description"].lower() + " " + update["description"].lower())
        self.assertIn("restore", update_properties["action"]["enum"])
        self.assertIn("delete", update_properties["action"]["enum"])
        self.assertIn("identity={anchor", update_properties["topic"]["description"])
        self.assertIn("Required for delete/restore", update_properties["ref"]["description"])
        self.assertIn("recall_policy", update_properties)
        self.assertEqual(update_properties["recall_policy"]["enum"], ["stable", "current", "temporary", "review"])
        self.assertIn("text", question_properties)
        self.assertNotIn("question", question_properties)
        self.assertIn("copy", code_properties["code"]["description"])
        self.assertIn("pow", code_properties["code"]["description"])
        self.assertNotIn("importing os", code_properties["code"]["description"])
        self.assertIn("os", code_properties["code"]["description"])
        self.assertIn("blocked", code_properties["code"]["description"])
        self.assertIn("backend", sub_agent_properties)
        self.assertIn("baby_id", sub_agent_properties)
        self.assertIn("role", sub_agent_properties)
        self.assertIn("Mutually exclusive", sub_agent_properties["tasks"]["description"])
        self.assertIn("execution board", todo["description"])
        self.assertIn("in-session execution steps", todo["description"])
        self.assertIn("Use open or done", todo_properties["status"]["description"])
        self.assertIn("One concise question", clarify_properties["question"]["description"])
        self.assertIn("mode=choice", clarify_properties["choices"]["description"])
        self.assertIn("buffered stdout/stderr", process_properties["action"]["description"])
        self.assertIn("background tool.terminal.exec", process_properties["process_id"]["description"])
        self.assertIn("public-web information", web_search_properties["query"]["description"])
        self.assertIn("query_variants", web_search_properties)
        self.assertIn("search results to summarize", web_search_properties["limit"]["description"])
        self.assertIn("Public http(s) URL", web_read_properties["url"]["description"])
        self.assertNotIn("tool.memory.recall", definitions)
        self.assertNotIn("tool.memory.note", definitions)
        self.assertNotIn("tool.profile.manage", definitions)
        self.assertNotIn("tool.memory.upload", definitions)
        self.assertNotIn("tool.procedure.inspect", definitions)
        self.assertNotIn("tool.procedure.manage", definitions)

    def test_tool_fallback_prompt_routes_durable_personal_facts_to_personal_model_update(self) -> None:
        definitions = tuple(
            definition
            for definition in builtin_tool_definitions({}, dependencies=BuiltinToolDependencies(cwd=Path("/tmp")))
            if definition.tool_id in {"tool.personal_model.update", "tool.todo.manage"}
        )

        prompt = build_tool_fallback_prompt(definitions)

        self.assertIn("tool.personal_model.update", prompt)
        self.assertIn("explicitly asks you to remember", prompt)
        self.assertIn("do not say it was remembered unless the update tool succeeded", prompt)
        self.assertIn("tool.todo.manage", prompt)
        self.assertNotIn("tool.memory.note", prompt)
        self.assertNotIn("tool.profile.manage", prompt)
        self.assertNotIn("tool.memory.upload", prompt)

    def test_builtin_model_schemas_include_parameter_descriptions(self) -> None:
        definitions = builtin_tool_definitions({}, dependencies=BuiltinToolDependencies(cwd=Path("/tmp")))

        missing: list[str] = []
        missing_items: list[str] = []
        for definition in definitions:
            self._collect_schema_guidance_gaps(
                definition.tool_id,
                definition.schema,
                path=(),
                missing=missing,
                missing_items=missing_items,
            )

        self.assertEqual(missing, [])
        self.assertEqual(missing_items, [])

    def test_cron_tool_accepts_delete_alias_for_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            cron_runtime = CronRuntime(Path(tempdir) / "cron" / "jobs.json")
            job = cron_runtime.create_job(
                name="One-off reminder",
                schedule_text="2099-01-01T00:00:00+00:00",
                payload={"prompt": "say hello"},
            )
            runtime = self._make_builtin_runtime(
                cwd=Path(tempdir),
                dependencies=BuiltinToolDependencies(cwd=Path(tempdir), cron_runtime=cron_runtime),
            )

            result = runtime.invoke(
                "tool.cron.manage",
                {"action": "delete", "job_id": job.job_id},
                session_id="session-cron-delete",
            )

            self.assertEqual(result.outcome, "success")
            self.assertIn("status: removed", result.summary)
            self.assertEqual(cron_runtime.list_jobs(), ())

    def _collect_schema_guidance_gaps(
        self,
        tool_id: str,
        schema: Mapping[str, object],
        *,
        path: tuple[str, ...],
        missing: list[str],
        missing_items: list[str],
    ) -> None:
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            return
        for name, payload in properties.items():
            current_path = (*path, str(name))
            label = f"{tool_id}.{'.'.join(current_path).replace('.[]', '[]')}"
            if not isinstance(payload, Mapping):
                missing.append(label)
                continue
            if not str(payload.get("description") or "").strip():
                missing.append(label)
            if payload.get("type") == "array" and "items" not in payload:
                missing_items.append(label)
            items = payload.get("items")
            if isinstance(items, Mapping):
                self._collect_schema_guidance_gaps(
                    tool_id,
                    items,
                    path=(*current_path, "[]"),
                    missing=missing,
                    missing_items=missing_items,
                )
            for index, branch in enumerate(payload.get("oneOf") or ()):
                if isinstance(branch, Mapping) and branch.get("type") == "array" and "items" not in branch:
                    missing_items.append(f"{label}.oneOf[{index}]")

    def test_sub_agents_accepts_skills_object_flags(self) -> None:
        stub = _SubAgentsStub()
        runtime = self._make_builtin_runtime(
            cwd=Path("/tmp"),
            dependencies=BuiltinToolDependencies(cwd=Path("/tmp"), sub_agents_surface=stub),
        )

        single = runtime.invoke(
            "tool.sub_agents",
            {
                "task": "inspect core architecture",
                "skills": {"codebase-inspection": True, "disabled-skill": False},
            },
            session_id="session-sub-agent",
        )
        batch = runtime.invoke(
            "tool.sub_agents",
            {
                "tasks": [
                    {
                        "name": "core",
                        "task": "inspect core architecture",
                        "skills": {"codebase-inspection": True, "disabled-skill": False},
                    }
                ],
                "max_concurrency": 1,
            },
            session_id="session-sub-agent",
        )

        self.assertEqual(single.summary, "single sub-agent finished")
        self.assertEqual(stub.single["skills"], ("codebase-inspection",))
        self.assertEqual(batch.summary, "sub-agent pool finished")
        tasks = stub.batch["tasks"]
        self.assertEqual(tasks[0]["skills"], ("codebase-inspection",))

    def test_sub_agents_local_cli_single_task_routes_through_task_batch(self) -> None:
        stub = _SubAgentsStub()
        runtime = self._make_builtin_runtime(
            cwd=Path("/tmp"),
            dependencies=BuiltinToolDependencies(cwd=Path("/tmp"), sub_agents_surface=stub),
        )

        result = runtime.invoke(
            "tool.sub_agents",
            {
                "task": "run focused validation",
                "name": "Codex Baby",
                "backend": "local_cli",
                "baby_id": "codex-baby",
                "role": "coding implementer",
            },
            session_id="session-sub-agent",
        )

        self.assertEqual(result.summary, "sub-agent pool finished")
        self.assertIsNone(stub.single)
        self.assertEqual(stub.batch["max_concurrency"], 1)
        self.assertEqual(stub.batch["tasks"][0]["backend"], "local_cli")
        self.assertEqual(stub.batch["tasks"][0]["baby_id"], "codex-baby")
        self.assertEqual(stub.batch["tasks"][0]["role"], "coding implementer")

    def test_sub_agents_failed_result_sets_error_outcome(self) -> None:
        runtime = self._make_builtin_runtime(
            cwd=Path("/tmp"),
            dependencies=BuiltinToolDependencies(cwd=Path("/tmp"), sub_agents_surface=_SubAgentsStub()),
        )

        result = runtime.invoke("tool.sub_agents", {"task": "fail"}, session_id="session-sub-agent")

        self.assertEqual(result.outcome, "error")
        self.assertEqual(result.summary, "sub-agent failed")

    def test_sub_agents_start_status_and_join_actions_route_to_surface(self) -> None:
        stub = _SubAgentsStub()
        runtime = self._make_builtin_runtime(
            cwd=Path("/tmp"),
            dependencies=BuiltinToolDependencies(cwd=Path("/tmp"), sub_agents_surface=stub),
        )

        started = runtime.invoke(
            "tool.sub_agents",
            {"action": "start", "task": "inspect core architecture", "name": "core"},
            session_id="session-sub-agent",
        )
        status = runtime.invoke(
            "tool.sub_agents",
            {"action": "status", "run_id": "subrun-test"},
            session_id="session-sub-agent",
        )
        joined = runtime.invoke(
            "tool.sub_agents",
            {"action": "join", "run_id": "subrun-test", "timeout_seconds": 5},
            session_id="session-sub-agent",
        )

        self.assertIn("subrun-test", started.summary)
        self.assertEqual(stub.started["max_concurrency"], 1)
        self.assertEqual(status.summary, "sub_agent_run_id: subrun-test\nstatus: completed")
        self.assertEqual(joined.summary, "sub_agent_run_id: subrun-test\nstatus: completed")
        self.assertEqual(stub.inspected["wait_timeout_seconds"], 5.0)






























    def test_personal_model_update_remember_runs_without_error(self) -> None:
        runtime = self._make_cli_runtime()
        session = runtime.start()

        result = runtime.tool_runtime.invoke(
            "tool.personal_model.update",
            {
                "action": "remember",
                "lens": "identity",
                "topic": "identity.style.review",
                "text": "The user prefers direct, evidence-backed review.",
                "reason": "user explicitly stated this preference",
            },
            session_id=session.session_id,
        )
        self.assertIn("action: remember", result.summary)
        self.assertIn("status: active", result.summary)

    def test_personal_model_search_runs_without_error(self) -> None:
        runtime = self._make_cli_runtime()
        session = runtime.start()
        runtime.tool_runtime.invoke(
            "tool.personal_model.update",
            {
                "action": "remember",
                "lens": "journey",
                "topic": "journey.milestones.release_work_next",
                "text": "The next step is to publish the release artifacts.",
                "reason": "user explicitly stated the next step",
            },
            session_id=session.session_id,
        )

        queried = runtime.tool_runtime.invoke(
            "tool.personal_model.search",
            {"query": "publish", "limit": 3},
            session_id=session.session_id,
        )
        self.assertIn("claims:", queried.summary)
        self.assertIn("publish the release artifacts", queried.summary)

    def test_conversation_search_discover_returns_copyable_recall_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(
                    cwd=cwd,
                    personal_model_understanding=_ConversationSearchStub(),
                ),
            )

            result = runtime.invoke(
                "tool.conversation.search",
                {"mode": "discover", "query": "release", "expr": "yesterday"},
                session_id="session-conversation",
            )

            self.assertIn("recall_args: mode=recall", result.summary)
            self.assertIn("start_at=2026-05-12T08:00:00+08:00", result.summary)
            self.assertIn("timezone=Asia/Shanghai", result.summary)

    def test_diary_write_validates_date_and_warns_for_future_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(cwd=cwd, diary_surface=_DiaryStub()),
            )

            with self.assertRaisesRegex(ValueError, "valid YYYY-MM-DD"):
                runtime.invoke(
                    "tool.diary.write",
                    {"entry_date": "2099-99-99", "content": "Bad date"},
                    session_id="session-diary",
                )
            future = runtime.invoke(
                "tool.diary.write",
                {"entry_date": "2099-01-01", "content": "Future note"},
                session_id="session-diary",
            )

            self.assertIn("warning: entry_date is in the future", future.summary)

    def test_diary_write_passes_metadata_to_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            diary = _DiaryStub()
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(cwd=cwd, diary_surface=diary),
            )

            runtime.invoke(
                "tool.diary.write",
                {
                    "entry_date": "2026-05-23",
                    "content": "Letter",
                    "metadata": {"kind": "onboarding_letter", "empty": ""},
                },
                session_id="session-diary",
            )

            self.assertEqual(diary.last_write_kwargs["metadata"], {"kind": "onboarding_letter"})

    def test_diary_list_returns_structured_payload_not_tool_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(cwd=cwd, diary_surface=_DiaryStub()),
            )

            result = runtime.invoke("tool.diary.list", {"limit": 5}, session_id="session-diary")

            self.assertIn('"entries"', result.summary)
            self.assertIn('"count": 1', result.summary)
            self.assertNotIn("List recent diary entries", result.summary)

    def test_todo_manage_normalizes_unknown_status_to_open(self) -> None:
        runtime = self._make_cli_runtime()
        session = runtime.start()

        created = runtime.tool_runtime.invoke(
            "tool.todo.manage",
            {
                "action": "create",
                "title": "Draft the tool support rollout",
                "status": "eventually",
            },
            session_id=session.session_id,
        )
        item_id = created.summary.removeprefix("created: ").split(" |", 1)[0]
        item = runtime.todo_store.inspect_item(session.session_id, item_id)
        self.assertEqual(item.status, "open")
        self.assertIsNone(item.work_item_id)

    def test_message_send_uses_delivery_surface_when_available(self) -> None:
        runtime = self._make_builtin_runtime(
            cwd=Path("/tmp"),
            dependencies=BuiltinToolDependencies(
                cwd=Path("/tmp"),
                message_delivery=DeliveryMessageSurfaceAdapter(
                    _DeliveryStub(),
                    surface_label="test",
                    default_target="loopback",
                ),
            ),
        )

        result = runtime.invoke(
            "tool.message.send",
            {"body": "hello delivery"},
            session_id="session-message",
        )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.side_effects, ("delivery",))
        self.assertIn("delivered hello delivery", result.summary)

    def test_clarify_uses_structured_surface_when_available(self) -> None:
        runtime = self._make_builtin_runtime(
            cwd=Path("/tmp"),
            dependencies=BuiltinToolDependencies(
                cwd=Path("/tmp"),
                clarify_surface=StructuredClarifySurface(
                    surface_label="test-shell",
                    extra_metadata={"mode": "unit"},
                ),
            ),
        )

        result = runtime.invoke(
            "tool.clarify",
            {"question": "Which target should I use?", "choices": ["alpha", "beta"]},
            session_id="session-clarify",
        )

        self.assertEqual(result.outcome, "needs_input")
        self.assertIn("question: Which target should I use?", result.summary)
        self.assertIn("surface: test-shell", result.summary)
        self.assertIn("- alpha", result.summary)


if __name__ == "__main__":
    unittest.main()
