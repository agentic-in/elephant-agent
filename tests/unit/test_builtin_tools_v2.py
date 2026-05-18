from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from email.message import Message
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.cli.runtime import CliRuntime
from packages.cron import CronRuntime
from packages.tools import handlers_code_execution
from packages.tools.builtins import builtin_tool_definitions
from packages.tools.adapters import DeliveryMessageSurfaceAdapter, StructuredClarifySurface
from packages.tools import (
    BuiltinToolDependencies,
    CallableApprovalGateway,
    InMemoryToolExecutor,
    InMemoryToolRegistry,
    ToolDefinition,
    ToolRuntime,
    ToolSideEffectMetadata,
    build_tool_fallback_prompt,
    register_builtin_tools,
)
from packages.tools.local_roots import default_local_allowed_roots


class _FakeUrlopenResponse:
    def __init__(
        self,
        body: str,
        *,
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://example.com",
    ) -> None:
        self._body = body.encode("utf-8")
        self._url = url
        self.headers = Message()
        self.headers.add_header("Content-Type", content_type)

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._body
        return self._body[:size]

    def geturl(self) -> str:
        return self._url


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
    def write_diary_entry(self, **kwargs):  # type: ignore[no-untyped-def]
        return {"entry_date": kwargs["entry_date"]}

    def list_diary_entries(self, **kwargs):  # type: ignore[no-untyped-def]
        return {"entries": ({"entry_date": "2026-05-14", "content": "Today note"},), "count": 1}


class BuiltinToolsV2Test(unittest.TestCase):
    def _make_builtin_runtime(self, *, cwd: Path, dependencies: BuiltinToolDependencies | None = None) -> ToolRuntime:
        runtime = ToolRuntime(
            registry=InMemoryToolRegistry(),
            executor=InMemoryToolExecutor(),
            approval_gateway=CallableApprovalGateway(lambda *_: True),
        )
        register_builtin_tools(
            runtime,
            enabled_overrides={},
            dependencies=dependencies or BuiltinToolDependencies(cwd=cwd),
        )
        return runtime

    def _make_cli_runtime(self, *, external_skill_dir: Path | None = None) -> CliRuntime:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        state_dir = root / "state"
        profile_dir = root / "profile"
        profile_dir.mkdir()
        skill_dirs = [] if external_skill_dir is None else [str(external_skill_dir)]
        (root / "config.yaml").write_text(
            f"skills:\n  external_dirs: {json.dumps(skill_dirs)}\n",
            encoding="utf-8",
        )
        (root / "profile.json").write_text(
            """{"profile_id":"profile-companion","display_name":"Elephant Agent","mode":"companion"}""",
            encoding="utf-8",
        )
        runtime = CliRuntime.create(state_dir=state_dir)
        runtime.update_identity_state(
            profile_id="profile-companion",
            elephant_identity_text="Stay durable and grounded.",
        )
        return runtime

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

    def test_file_tools_can_write_patch_read_and_search_root_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(cwd=cwd)

            written = runtime.invoke(
                "tool.file.write",
                {
                    "path": "notes/plan.txt",
                    "content": "alpha\nbeta\n",
                },
                session_id="session-file",
            )
            patched = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "replace",
                    "path": "notes/plan.txt",
                    "old_string": "beta",
                    "new_string": "gamma",
                },
                session_id="session-file",
            )
            read = runtime.invoke(
                "tool.file.read",
                {"path": "notes/plan.txt"},
                session_id="session-file",
            )
            searched = runtime.invoke(
                "tool.file.search",
                {"query": "gamma", "path": "notes"},
                session_id="session-file",
            )

            self.assertEqual(written.outcome, "success")
            self.assertIn("notes/plan.txt", written.summary)
            self.assertEqual(patched.outcome, "success")
            self.assertIn("replacements: 1", patched.summary)
            self.assertIn("1|alpha", read.summary)
            self.assertIn("2|gamma", read.summary)
            self.assertIn("plan.txt:2:gamma", searched.summary)

    def test_file_tools_can_write_to_posix_tmp_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(cwd=cwd)
            target = Path("/tmp") / f"elephant-tool-test-{os.getpid()}-{id(self)}.txt"
            target.unlink(missing_ok=True)
            self.addCleanup(target.unlink, missing_ok=True)

            written = runtime.invoke(
                "tool.file.write",
                {
                    "path": str(target),
                    "content": "tmp ok\n",
                },
                session_id="session-posix-tmp-file",
            )
            read = runtime.invoke(
                "tool.file.read",
                {"path": str(target)},
                session_id="session-posix-tmp-file",
            )

            self.assertEqual(written.outcome, "success")
            self.assertIn("1|tmp ok", read.summary)

    def test_default_local_allowed_roots_include_posix_tmp(self) -> None:
        with mock.patch("packages.tools.local_roots.tempfile.gettempdir", return_value="/var/folders/example/T"):
            roots = default_local_allowed_roots()

        self.assertIn(Path("/tmp").resolve(), roots)
        self.assertIn(Path("/var/folders/example/T").resolve(), roots)

    def test_file_tools_can_access_configured_roots_outside_primary_root(self) -> None:
        with tempfile.TemporaryDirectory() as local_tmpdir, tempfile.TemporaryDirectory() as external_tmpdir:
            local_root = Path(local_tmpdir)
            external = Path(external_tmpdir)
            shared = external / "shared.txt"
            shared.write_text("outside root\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(
                cwd=local_root,
                dependencies=BuiltinToolDependencies(
                    cwd=local_root,
                    additional_allowed_roots=(external,),
                ),
            )

            read = runtime.invoke(
                "tool.file.read",
                {"path": str(shared)},
                session_id="session-external-file",
            )
            searched = runtime.invoke(
                "tool.file.search",
                {"query": "outside", "path": str(external)},
                session_id="session-external-file",
            )
            written = runtime.invoke(
                "tool.file.write",
                {
                    "path": str(external / "notes.txt"),
                    "content": "draft\n",
                },
                session_id="session-external-file",
            )
            patched = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "replace",
                    "path": str(external / "notes.txt"),
                    "old_string": "draft",
                    "new_string": "final",
                },
                session_id="session-external-file",
            )
            terminal = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": "pwd",
                    "cwd": str(external),
                },
                session_id="session-external-file",
            )

            self.assertIn("1|outside root", read.summary)
            self.assertIn("shared.txt:1:outside root", searched.summary)
            self.assertEqual(written.outcome, "success")
            self.assertEqual(patched.outcome, "success")
            self.assertEqual((external / "notes.txt").read_text(encoding="utf-8"), "final\n")
            self.assertIn(str(external), terminal.summary)

    def test_file_and_terminal_tools_default_to_session_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmpdir, tempfile.TemporaryDirectory() as fallback_tmpdir:
            root = Path(root_tmpdir)
            fallback = Path(fallback_tmpdir)
            roots = {
                "session-alpha": root / "alpha",
                "session-beta": root / "beta",
            }
            for resolved_root in roots.values():
                resolved_root.mkdir()
            runtime = self._make_builtin_runtime(
                cwd=fallback,
                dependencies=BuiltinToolDependencies(
                    cwd=fallback,
                    cwd_resolver=lambda session_id: roots[str(session_id)],
                ),
            )

            written = runtime.invoke(
                "tool.file.write",
                {
                    "path": "notes.txt",
                    "content": "alpha root\n",
                },
                session_id="session-alpha",
            )
            terminal = runtime.invoke(
                "tool.terminal.exec",
                {"command": "pwd"},
                session_id="session-beta",
            )

            self.assertEqual(written.outcome, "success")
            self.assertTrue((roots["session-alpha"] / "notes.txt").exists())
            self.assertFalse((fallback / "notes.txt").exists())
            self.assertIn(str(roots["session-beta"]), terminal.summary)

    def test_file_read_is_paginated_and_rejects_binary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            text_file = cwd / "large.txt"
            text_file.write_text("\n".join(f"line-{index}" for index in range(1, 602)), encoding="utf-8")
            binary_file = cwd / "image.png"
            binary_file.write_bytes(b"\x89PNG\r\n\x1a\n")
            runtime = self._make_builtin_runtime(cwd=cwd)

            read = runtime.invoke(
                "tool.file.read",
                {"path": "large.txt"},
                session_id="session-file-read-guard",
            )

            self.assertIn("lines: 1-500 of 601", read.summary)
            self.assertIn("truncated: true", read.summary)
            self.assertIn("hint: use offset=501", read.summary)
            with self.assertRaisesRegex(ValueError, "likely binary"):
                runtime.invoke(
                    "tool.file.read",
                    {"path": "image.png"},
                    session_id="session-file-read-binary",
                )

    def test_model_file_read_and_search_reject_sensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            sensitive_files = (
                cwd / ".env",
                cwd / ".env.local",
                cwd / ".ssh" / "config",
                cwd / ".aws" / "credentials",
                cwd / ".config" / "gh" / "hosts.yml",
                cwd / ".codex" / "auth.json",
                cwd / ".qwen" / "oauth_creds.json",
                cwd / ".elephant" / "herd" / "provider-secrets.key",
                cwd / "gateway-local-secrets.json",
                cwd / "elephant.auth-secrets.json",
                cwd / "auth.db",
                cwd / "secret.sqlite3",
            )
            for path in sensitive_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("needle-secret\n", encoding="utf-8")
            (cwd / "notes.txt").write_text("needle-public\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            for path in sensitive_files:
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError, "sensitive credential path"):
                        runtime.invoke(
                            "tool.file.read",
                            {"path": str(path)},
                            session_id="session-sensitive-model-read",
                            requester="model",
                        )
                    with self.assertRaisesRegex(ValueError, "sensitive credential path"):
                        runtime.invoke(
                            "tool.file.search",
                            {"query": "needle", "path": str(path)},
                            session_id="session-sensitive-model-search",
                            requester="model",
                        )

            searched = runtime.invoke(
                "tool.file.search",
                {"query": "needle", "path": str(cwd)},
                session_id="session-sensitive-model-search-root",
                requester="model",
            )

            self.assertIn("notes.txt:1:needle-public", searched.summary)
            self.assertNotIn("needle-secret", searched.summary)

    def test_file_write_blocks_sensitive_home_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            with self.assertRaisesRegex(ValueError, "sensitive credential directory"):
                runtime.invoke(
                    "tool.file.write",
                    {"path": str(Path.home() / ".ssh" / "config"), "content": "Host *\n"},
                    session_id="session-sensitive-write",
                )
            with self.assertRaisesRegex(ValueError, "VCS metadata"):
                runtime.invoke(
                    "tool.file.write",
                    {"path": ".git/config", "content": "[core]\n"},
                    session_id="session-vcs-write",
                )

    def test_file_patch_requires_unique_match_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "dupes.txt").write_text("same\nsame\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            with self.assertRaisesRegex(ValueError, "found 2 matches"):
                runtime.invoke(
                    "tool.file.patch",
                    {
                        "mode": "replace",
                        "path": "dupes.txt",
                        "old_string": "same",
                        "new_string": "changed",
                    },
                    session_id="session-patch-unique",
                )

    def test_file_patch_accepts_standard_unified_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "plan.txt").write_text("alpha\nbeta\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "patch",
                    "patch": "\n".join(
                        (
                            "--- a/plan.txt",
                            "+++ b/plan.txt",
                            "@@ -1,2 +1,2 @@",
                            " alpha",
                            "-beta",
                            "+gamma",
                            "--- /dev/null",
                            "+++ b/new.txt",
                            "@@ -0,0 +1,1 @@",
                            "+created",
                        )
                    ),
                },
                session_id="session-unified-patch",
            )

            self.assertIn("format: unified-diff", result.summary)
            self.assertEqual((cwd / "plan.txt").read_text(encoding="utf-8"), "alpha\ngamma\n")
            self.assertEqual((cwd / "new.txt").read_text(encoding="utf-8"), "created\n")

    def test_file_patch_accepts_unified_diff_with_miscounted_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "plan.txt").write_text("alpha\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "patch",
                    "patch": "\n".join(
                        (
                            "--- a/plan.txt",
                            "+++ b/plan.txt",
                            "@@ -1,1 +1,1 @@",
                            " alpha",
                            "+beta",
                        )
                    ),
                },
                session_id="session-unified-miscounted-patch",
            )

            self.assertIn("format: unified-diff", result.summary)
            self.assertEqual((cwd / "plan.txt").read_text(encoding="utf-8"), "alpha\nbeta\n")

    def test_file_patch_positions_empty_old_side_unified_hunks_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "plan.txt").write_text("alpha\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "patch",
                    "patch": "\n".join(
                        (
                            "--- a/plan.txt",
                            "+++ b/plan.txt",
                            "@@ -1,0 +2,1 @@",
                            "+beta",
                        )
                    ),
                },
                session_id="session-unified-empty-old-side-patch",
            )

            self.assertIn("format: unified-diff", result.summary)
            self.assertEqual((cwd / "plan.txt").read_text(encoding="utf-8"), "alpha\nbeta\n")

    def test_file_search_applies_global_limit_and_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            for index in range(4):
                (cwd / f"match-{index}.txt").write_text(f"needle {index}\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            first_page = runtime.invoke(
                "tool.file.search",
                {"query": "needle", "limit": 2},
                session_id="session-search-page",
            )
            second_page = runtime.invoke(
                "tool.file.search",
                {"query": "needle", "limit": 2, "offset": 2},
                session_id="session-search-page",
            )

            self.assertIn("shown: 2", first_page.summary)
            self.assertIn("truncated: true", first_page.summary)
            self.assertIn("offset: 2", second_page.summary)

    def test_file_search_accepts_pattern_alias_for_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "test_memory.py").write_text("class TestmemoryRecall:\n    pass\n", encoding="utf-8")
            (cwd / "notes.py").write_text("class TestmemoryRecallIgnored:\n    pass\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.file.search",
                {
                    "include": "**/test_*.py",
                    "pattern": "class.*Test.*memory|class.*Test.*search|class.*Test.*recall",
                    "path": str(cwd),
                },
                session_id="session-search-pattern-alias",
            )

            self.assertIn("TestmemoryRecall", result.summary)
            self.assertNotIn("TestmemoryRecallIgnored", result.summary)

    def test_file_search_allows_glob_only_file_listing_and_blocks_vcs_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "notes.md").write_text("hello\n", encoding="utf-8")
            (cwd / "notes.txt").write_text("hello\n", encoding="utf-8")
            (cwd / ".git").mkdir()
            runtime = self._make_builtin_runtime(cwd=cwd)

            listed = runtime.invoke(
                "tool.file.search",
                {"target": "files", "glob": "*.md"},
                session_id="session-search-files",
            )

            self.assertIn("notes.md", listed.summary)
            self.assertNotIn("notes.txt", listed.summary)
            all_files = runtime.invoke(
                "tool.file.search",
                {"target": "files"},
                session_id="session-search-all-files",
            )
            self.assertIn("notes.md", all_files.summary)
            self.assertIn("notes.txt", all_files.summary)
            with self.assertRaisesRegex(ValueError, "VCS metadata"):
                runtime.invoke(
                    "tool.file.search",
                    {"query": "anything", "path": ".git"},
                    session_id="session-search-vcs",
                )

    def test_terminal_exec_background_processes_can_be_waited_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            started = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": 'python3 -c "import time; print(\'bg-finished\'); time.sleep(0.1)"',
                    "background": True,
                },
                session_id="session-process",
            )
            process_id = started.summary.splitlines()[0].split(": ", 1)[1]

            listed = runtime.invoke(
                "tool.process.manage",
                {"action": "list"},
                session_id="session-process",
            )
            waited = runtime.invoke(
                "tool.process.manage",
                {
                    "action": "wait",
                    "process_id": process_id,
                    "timeout_seconds": 2,
                },
                session_id="session-process",
            )

            self.assertIn(process_id, listed.summary)
            self.assertIn("status: exited(0)", waited.summary)
            self.assertIn("bg-finished", waited.summary)

    def test_process_manage_poll_drains_running_process_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            started = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": f"{sys.executable} -u -c \"import time; print('ready', flush=True); time.sleep(2)\"",
                    "background": True,
                },
                session_id="session-process-poll",
            )
            process_id = started.summary.splitlines()[0].split(": ", 1)[1]
            self.addCleanup(
                lambda: runtime.invoke(
                    "tool.process.manage",
                    {"action": "kill", "process_id": process_id},
                    session_id="session-process-poll",
                )
            )

            polled = runtime.invoke(
                "tool.process.manage",
                {"action": "poll", "process_id": process_id},
                session_id="session-process-poll",
            )

            self.assertIn("status: running", polled.summary)
            self.assertIn("ready", polled.summary)

    def test_terminal_exec_merges_env_overrides_with_parent_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            result = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": (
                        "python3 -c \"import os; "
                        "print(os.environ.get('ELEPHANT_TEST_ENV')); "
                        "print(bool(os.environ.get('PATH')))\""
                    ),
                    "env": {"ELEPHANT_TEST_ENV": "present"},
                },
                session_id="session-terminal-env",
            )

            self.assertIn("present", result.summary)
            self.assertIn("True", result.summary)

    def test_code_execute_can_call_allowlisted_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "context.txt").write_text("hello from elephant\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.code.execute",
                {
                    "code": "\n".join(
                        (
                            "result = tool('tool.file.read', {'path': 'context.txt'})",
                            "print('read-via-rpc')",
                        )
                    )
                },
                session_id="session-code",
            )

            self.assertEqual(result.outcome, "success")
            self.assertIn("read-via-rpc", result.summary)
            self.assertIn("1|hello from elephant", result.summary)
            self.assertIn("tool_calls_made: 1", result.summary)

    def test_model_code_execute_preserves_requester_for_nested_file_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / ".env").write_text("needle-secret\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            with self.assertRaisesRegex(RuntimeError, "sensitive credential path"):
                runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": "result = tool('tool.file.read', {'path': '.env'})",
                    },
                    session_id="session-code-model-sensitive-read",
                    requester="model",
                )

    def test_code_execute_allows_safe_stdlib_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            result = runtime.invoke(
                "tool.code.execute",
                {
                    "code": "\n".join(
                        (
                            "import json",
                            "import re",
                            "from collections import Counter",
                            "counts = Counter(re.findall('a', 'banana'))",
                            "print(json.dumps({'a': counts['a']}, sort_keys=True))",
                        )
                    )
                },
                session_id="session-code-import-safe",
            )

            self.assertEqual(result.outcome, "success")
            self.assertIn('"a": 3', result.summary)

    def test_code_execute_documents_and_allows_copy_pow_and_safe_dunder_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            result = runtime.invoke(
                "tool.code.execute",
                {
                    "code": "\n".join(
                        (
                            "import copy",
                            "value = copy.copy({'n': pow(2, 5)})",
                            "try:",
                            "    raise ValueError('x')",
                            "except ValueError as error:",
                            "    print(type(error).__name__, value['n'])",
                        )
                    )
                },
                session_id="session-code-safe-more",
            )

            self.assertIn("ValueError 32", result.summary)

    def test_code_execute_schema_safe_imports_match_enforced_allowlist(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions({}, dependencies=BuiltinToolDependencies(cwd=Path("/tmp")))
        }
        description = definitions["tool.code.execute"].schema["properties"]["code"]["description"]

        for module in handlers_code_execution.SAFE_CODE_IMPORTS:
            self.assertIn(module, description)
        for blocked in ("os", "sys", "random", "subprocess", "open()"):
            self.assertIn(blocked, description)
        self.assertIn("blocked", description)

    def test_code_execute_runs_with_project_cwd_and_venv_python_by_default(self) -> None:
        from packages.tools import handlers_code_execution

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            staging = root / "staging"
            project = root / "project"
            venv = root / "venv"
            staging.mkdir()
            project.mkdir()
            python_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
            python_dir.mkdir(parents=True)
            python_path = python_dir / ("python.exe" if sys.platform == "win32" else "python")
            if sys.platform == "win32":
                python_path.write_text("", encoding="utf-8")
            else:
                python_path.symlink_to(sys.executable)

            self.assertEqual(
                handlers_code_execution._code_child_cwd(mode="project", project_cwd=project, staging_cwd=staging),
                project.resolve(),
            )
            self.assertEqual(
                handlers_code_execution._code_child_cwd(mode="strict", project_cwd=project, staging_cwd=staging),
                staging,
            )
            with mock.patch.dict(os.environ, {"VIRTUAL_ENV": str(venv), "CONDA_PREFIX": ""}, clear=False):
                if sys.platform == "win32":
                    self.assertIn(
                        handlers_code_execution._code_child_python(mode="project"),
                        {str(python_path), sys.executable},
                    )
                else:
                    self.assertEqual(handlers_code_execution._code_child_python(mode="project"), str(python_path))
            self.assertEqual(handlers_code_execution._code_child_python(mode="strict"), sys.executable)

    def test_code_execute_can_call_terminal_but_rejects_background_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            result = runtime.invoke(
                "tool.code.execute",
                {
                    "code": "result = tool('tool.terminal.exec', {'command': 'printf terminal-ok'})",
                },
                session_id="session-code-terminal",
            )

            self.assertEqual(result.outcome, "success")
            self.assertIn("terminal-ok", result.summary)
            self.assertIn("tool_calls_made: 1", result.summary)

            with self.assertRaisesRegex(RuntimeError, "does not allow tool.terminal.exec arguments: background"):
                runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": (
                            "result = tool('tool.terminal.exec', "
                            "{'command': 'printf blocked', 'background': True})"
                        ),
                    },
                    session_id="session-code-terminal-blocked",
                )

    def test_code_execute_caps_nested_tool_rpc_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "context.txt").write_text("hello from elephant\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            with self.assertRaisesRegex(RuntimeError, "exceeded 50 nested tool calls"):
                runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": "\n".join(
                            (
                                "for _ in range(51):",
                                "    tool('tool.file.read', {'path': 'context.txt'})",
                            )
                        )
                    },
                    session_id="session-code-cap",
                )

    def test_code_execute_can_write_files_and_extract_web_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(cwd=cwd)

            with mock.patch(
                "packages.tools.handlers_network.urlopen",
                return_value=_FakeUrlopenResponse(
                    "<html><head><title>Alpha Doc</title></head><body><p>First source excerpt.</p></body></html>",
                    url="https://example.com/alpha",
                ),
            ):
                result = runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": "\n".join(
                            (
                                "tool('tool.file.write', {'path': 'notes/out.txt', 'content': 'saved by code\\n', 'create_parents': True})",
                                "tool('tool.file.patch', {'mode': 'replace', 'path': 'notes/out.txt', 'old_string': 'saved', 'new_string': 'patched'})",
                                "result = tool('tool.web.extract', {'urls': ['https://example.com/alpha']})",
                            )
                        )
                    },
                    session_id="session-code-write",
                )

            self.assertEqual(result.outcome, "success")
            self.assertEqual((cwd / 'notes' / 'out.txt').read_text(encoding='utf-8'), "patched by code\n")
            self.assertIn("Alpha Doc", result.summary)

    def test_code_execute_rejects_unsafe_imports_and_non_allowlisted_tool_rpc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            with self.assertRaisesRegex(ValueError, "does not allow importing os"):
                runtime.invoke(
                    "tool.code.execute",
                    {"code": "import os\nresult = 1"},
                    session_id="session-code-import",
                )
            with self.assertRaisesRegex(RuntimeError, "tool RPC is not allowed"):
                runtime.invoke(
                    "tool.code.execute",
                    {"code": "result = tool('tool.personal_model.search', {})"},
                    session_id="session-code-rpc-deny",
                )

    def test_code_execute_enforces_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": "while True:\n    pass",
                        "timeout_seconds": 1,
                    },
                    session_id="session-code-timeout",
                )

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
