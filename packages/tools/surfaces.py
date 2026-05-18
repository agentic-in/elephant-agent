"""Protocols and in-memory support types for built-in tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import select
from pathlib import Path
import subprocess
from typing import Any, Callable, Protocol
from uuid import uuid4

from packages.contracts.runtime import ExecutionResult
from packages.cron import CronRuntime
from packages.skills import SkillDefinition, SkillHubEntry, SkillManifestLoadRecord
from .local_roots import default_local_allowed_roots
from .runtime import ToolInvocation

class PersonalModelUnderstandingSurface(Protocol):
    def search_personal_model(
        self,
        session_id: str,
        *,
        query: str = "",
        lens: str = "",
        topic: str = "",
        query_variants: object = (),
        include_diagnostics: bool = False,
        limit: int = 12,
        status: str = "active",
        ref: str = "",
        personal_model_id: str = "",
        mode: str = "auto",
    ) -> Mapping[str, Any]:
        """Search Personal Model claims and optional governance diagnostics."""

    def search_conversation(
        self,
        session_id: str,
        *,
        query: str = "",
        time_range: object = None,
        mode: str = "recall",
        bucket: str = "auto",
        preview: str = "anchors",
        view: str = "conversation",
        limit: int = 8,
        personal_model_id: str = "",
        include_current_episode: bool = True,
    ) -> Mapping[str, Any]:
        """Discover or recall prior user/assistant conversation history separate from Personal Model claims."""

    def inspect_personal_model(
        self,
        session_id: str,
        *,
        ref: str = "",
        topic: str = "",
        query: str = "",
        personal_model_id: str = "",
        limit: int = 5,
    ) -> Mapping[str, Any]:
        """Inspect one PM claim/topic/history source and its related history/provenance."""

    def audit_personal_model(
        self,
        session_id: str,
        *,
        action: str = "health",
        lens: str = "",
        personal_model_id: str = "",
        limit: int = 30,
    ) -> Mapping[str, Any]:
        """Audit Personal Model topic tree, conflicts, stale claims, and health."""

    def update_personal_model(
        self,
        session_id: str,
        *,
        action: str,
        lens: str,
        topic: str,
        text: str = "",
        ref: str = "",
        reason: str = "",
        source: str = "user_said",
        recall_policy: str = "",
        personal_model_id: str = "",
        metadata: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        """Remember, correct, forget, or dispute one four-lens Personal Model claim."""

    def manage_personal_model_questions(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        """Manage proactive questions bound to a Personal Model lens/topic."""



class BrowserVisionAnalyzer(Protocol):
    def analyze_browser_screenshot(
        self,
        *,
        session_id: str,
        invocation_id: str,
        question: str,
        screenshot_path: Path,
        page_url: str = "",
        page_title: str = "",
        page_snapshot: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | str:
        """Analyze a browser screenshot with an optional multimodal provider."""


class BrowserToolBackend(Protocol):
    def backend_label(self) -> str:
        """Human-readable backend identifier."""

    def invoke(
        self,
        action: str,
        invocation: ToolInvocation,
        *,
        vision_analyzer: BrowserVisionAnalyzer | None = None,
    ) -> Mapping[str, Any] | ExecutionResult:
        """Run one browser action."""


class MessageDeliverySurface(Protocol):
    def send_message(
        self,
        *,
        session_id: str,
        body: str,
        target: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any] | ExecutionResult:
        """Deliver an outbound message to a configured target."""


class ClarifySurface(Protocol):
    def request_clarification(
        self,
        *,
        session_id: str,
        question: str,
        mode: str,
        choices: tuple[str, ...] = (),
    ) -> Mapping[str, Any] | ExecutionResult:
        """Request user clarification through a surface-aware prompt."""


class LearningResultSurface(Protocol):
    def write_learning_result(
        self,
        *,
        session_id: str,
        job_id: str,
        status: str,
        summary: str,
        mode: str = "",
        pm_facts: Mapping[str, Any] | None = None,
        skill_affinities: Mapping[str, Any] | None = None,
        questions: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        followups: tuple[str, ...] = (),
        diagnostics: Mapping[str, Any] | None = None,
        personal_model_id: str = "",
        state_id: str = "",
    ) -> Mapping[str, Any]:
        """Persist the explicit final result of one background learning job."""


class DiarySurface(Protocol):
    def write_diary_entry(
        self,
        *,
        personal_model_id: str,
        entry_date: str,
        content: str,
        source_episode_ids: tuple[str, ...] = (),
        metadata: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        """Persist a diary entry for a given date."""

    def list_diary_entries(
        self,
        *,
        personal_model_id: str,
        limit: int = 30,
        before_date: str | None = None,
    ) -> Mapping[str, Any]:
        """Return recent diary entries."""


class SubAgentsSurface(Protocol):
    def run_sub_agent(
        self,
        *,
        session_id: str,
        task: str,
        name: str | None = None,
        skills: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...] = (),
        system_prompt: str = "",
    ) -> Mapping[str, Any] | ExecutionResult:
        """Run one bounded sub-agent task and return its final result."""

    def run_sub_agents(
        self,
        *,
        session_id: str,
        tasks: tuple[Mapping[str, Any], ...],
        max_concurrency: int = 3,
    ) -> Mapping[str, Any] | ExecutionResult:
        """Run a bounded pool of sub-agent tasks and return final results."""

    def start_sub_agents(
        self,
        *,
        session_id: str,
        tasks: tuple[Mapping[str, Any], ...],
        max_concurrency: int = 3,
    ) -> Mapping[str, Any] | ExecutionResult:
        """Start a bounded pool of sub-agent tasks and return a run handle immediately."""

    def inspect_sub_agent_run(
        self,
        *,
        session_id: str,
        run_id: str,
        wait_timeout_seconds: float | None = None,
    ) -> Mapping[str, Any] | ExecutionResult:
        """Inspect or wait for a previously started sub-agent run."""

    def list_sub_agent_runs(self, *, session_id: str) -> Mapping[str, Any] | ExecutionResult:
        """List sub-agent runs attached to the session."""


class SkillManagementSurface(Protocol):
    def list_skill_hub(self, *, limit: int | None = None) -> tuple[SkillHubEntry, ...]:
        """List local skill shelf entries visible on this surface."""

    def inspect_skill(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        """Inspect one installed or local-hub skill package."""

    def inspect_skill_source(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        """Inspect one operator-selected local or remote skill package source."""

    def set_skill_enabled(
        self,
        skill_id: str,
        enabled: bool,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillDefinition:
        """Enable or disable one installed skill."""

    def install_skill_source(
        self,
        reference: str | Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        requester: str | None = None,
    ) -> SkillManifestLoadRecord:
        """Install one skill package from a reference or path."""

    def create_authored_skill(
        self,
        *,
        skill_id: str,
        display_name: str,
        summary: str,
        instruction_text: str,
        category: str | None = None,
        install: bool = True,
        overwrite: bool = False,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        """Create one authored skill package."""

    def update_authored_skill(
        self,
        skill_id: str,
        *,
        display_name: str | None = None,
        summary: str | None = None,
        instruction_text: str | None = None,
        category: str | None = None,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        """Update one authored skill package."""

    def delete_skill_source(
        self,
        skill_id: str,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> tuple[str, str]:
        """Delete one installed or authored skill package."""


@dataclass(frozen=True, slots=True)
class TodoItem:
    item_id: str
    title: str
    status: str = "open"
    notes: str = ""
    work_item_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TodoStore(Protocol):
    def list_items(self, session_id: str) -> tuple[TodoItem, ...]:
        """List session-scoped todo items."""

    def inspect_item(self, session_id: str, item_id: str) -> TodoItem:
        """Inspect one todo item."""

    def upsert_item(
        self,
        session_id: str,
        *,
        item_id: str | None = None,
        title: str,
        status: str = "open",
        notes: str = "",
        work_item_id: str | None = None,
    ) -> TodoItem:
        """Create or update a todo item."""

    def remove_item(self, session_id: str, item_id: str) -> TodoItem:
        """Remove one todo item."""

    def clear(self, session_id: str) -> int:
        """Clear all todo items for a session."""


@dataclass
class InMemorySessionTodoStore:
    _items: dict[str, dict[str, TodoItem]] = field(default_factory=dict)

    def list_items(self, session_id: str) -> tuple[TodoItem, ...]:
        return tuple(self._items.get(session_id, {}).values())

    def inspect_item(self, session_id: str, item_id: str) -> TodoItem:
        item = self._items.get(session_id, {}).get(item_id)
        if item is None:
            raise KeyError(item_id)
        return item

    def upsert_item(
        self,
        session_id: str,
        *,
        item_id: str | None = None,
        title: str,
        status: str = "open",
        notes: str = "",
        work_item_id: str | None = None,
    ) -> TodoItem:
        now = datetime.now(timezone.utc)
        resolved_id = item_id or f"todo:{uuid4().hex[:10]}"
        current = self._items.get(session_id, {}).get(resolved_id)
        created_at = current.created_at if current is not None else now
        item = TodoItem(
            item_id=resolved_id,
            title=title,
            status=status,
            notes=notes,
            work_item_id=work_item_id,
            created_at=created_at,
            updated_at=now,
        )
        self._items.setdefault(session_id, {})[resolved_id] = item
        return item

    def remove_item(self, session_id: str, item_id: str) -> TodoItem:
        items = self._items.get(session_id, {})
        item = items.pop(item_id, None)
        if item is None:
            raise KeyError(item_id)
        return item

    def clear(self, session_id: str) -> int:
        removed = len(self._items.get(session_id, {}))
        self._items.pop(session_id, None)
        return removed


@dataclass
class ManagedProcess:
    process_id: str
    command: str
    cwd: Path
    process: subprocess.Popen[str]
    started_at: datetime
    stdout: str = ""
    stderr: str = ""
    finished_at: datetime | None = None

    @property
    def returncode(self) -> int | None:
        return self.process.poll()

    @property
    def running(self) -> bool:
        return self.returncode is None


@dataclass
class InMemoryProcessManager:
    _processes: dict[str, ManagedProcess] = field(default_factory=dict)

    def start(self, *, command: str, cwd: Path, env: Mapping[str, str] | None = None) -> ManagedProcess:
        process_id = f"proc:{uuid4().hex[:10]}"
        popen = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env={**os.environ, **dict(env or {})} if env else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for stream in (popen.stdout, popen.stderr):
            if stream is not None:
                os.set_blocking(stream.fileno(), False)
        managed = ManagedProcess(
            process_id=process_id,
            command=command,
            cwd=cwd,
            process=popen,
            started_at=datetime.now(timezone.utc),
        )
        self._processes[process_id] = managed
        return managed

    def list(self) -> tuple[ManagedProcess, ...]:
        return tuple(self._processes.values())

    def get(self, process_id: str) -> ManagedProcess:
        process = self._processes.get(process_id)
        if process is None:
            raise KeyError(process_id)
        return process

    def capture_if_finished(self, process_id: str) -> ManagedProcess:
        managed = self.get(process_id)
        self._drain_process_output(managed)
        if managed.running or managed.finished_at is not None:
            return managed
        self._drain_process_output(managed)
        managed.finished_at = datetime.now(timezone.utc)
        return managed

    def wait(self, process_id: str, *, timeout_seconds: int = 20) -> ManagedProcess:
        managed = self.get(process_id)
        if managed.finished_at is not None:
            return managed
        deadline = datetime.now(timezone.utc).timestamp() + max(1, timeout_seconds)
        while managed.running and datetime.now(timezone.utc).timestamp() < deadline:
            self._drain_process_output(managed)
            try:
                managed.process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
        self._drain_process_output(managed)
        if not managed.running:
            managed.finished_at = datetime.now(timezone.utc)
        return managed

    def write(self, process_id: str, data: str) -> ManagedProcess:
        managed = self.get(process_id)
        if not managed.running or managed.process.stdin is None:
            raise RuntimeError(f"process is not writable: {process_id}")
        managed.process.stdin.write(data)
        managed.process.stdin.flush()
        self._drain_process_output(managed)
        return managed

    def kill(self, process_id: str) -> ManagedProcess:
        managed = self.get(process_id)
        if managed.running:
            managed.process.kill()
            managed.process.wait(timeout=1)
        return self.capture_if_finished(process_id)

    def _drain_process_output(self, managed: ManagedProcess) -> None:
        managed.stdout += _drain_text_stream(managed.process.stdout)
        managed.stderr += _drain_text_stream(managed.process.stderr)


def _drain_text_stream(stream: Any) -> str:
    if stream is None:
        return ""
    chunks: list[str] = []
    while True:
        try:
            ready, _, _ = select.select([stream], [], [], 0)
        except (OSError, ValueError):
            break
        if not ready:
            break
        try:
            chunk = stream.read()
        except (BlockingIOError, OSError, ValueError):
            break
        if not chunk:
            break
        chunks.append(str(chunk))
    return "".join(chunks)


@dataclass(frozen=True, slots=True)
class BuiltinToolDependencies:
    cwd: Path
    cwd_resolver: Callable[[str | None], Path] | None = None
    cron_runtime: CronRuntime | None = None
    personal_model_understanding: PersonalModelUnderstandingSurface | None = None
    skill_management: SkillManagementSurface | None = None
    browser_backend: BrowserToolBackend | None = None
    browser_vision_analyzer: BrowserVisionAnalyzer | None = None
    message_delivery: MessageDeliverySurface | None = None
    clarify_surface: ClarifySurface | None = None
    learning_result_surface: LearningResultSurface | None = None
    diary_surface: DiarySurface | None = None
    sub_agents_surface: SubAgentsSurface | None = None
    process_manager: InMemoryProcessManager = field(default_factory=InMemoryProcessManager)
    todo_store: InMemorySessionTodoStore = field(default_factory=InMemorySessionTodoStore)
    additional_allowed_roots: tuple[Path, ...] = field(default_factory=default_local_allowed_roots)
    web_user_agent: str = "Elephant Agent/2.0 (+https://github.com/agentic-in/elephant)"
    code_tool_allowlist: tuple[str, ...] = (
        "tool.file.read",
        "tool.file.write",
        "tool.file.patch",
        "tool.file.search",
        "tool.web.search",
        "tool.web.read",
        "tool.web.extract",
        "tool.terminal.exec",
    )

    def resolve_cwd(self, session_id: str | None) -> Path:
        if self.cwd_resolver is None:
            return self.cwd
        return self.cwd_resolver(session_id)
