"""Sub-agent surface methods for the CLI runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .runtime_cron_sub_agents import (
    inspect_sub_agent_run,
    list_sub_agent_runs,
    run_sub_agent_task,
    run_sub_agent_tasks,
    start_sub_agent_tasks,
)


class CliRuntimeSubAgentsMixin:
    def run_sub_agent(
        self,
        *,
        session_id: str,
        task: str,
        name: str | None = None,
        skills: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...] = (),
        system_prompt: str = "",
        learning_agent: bool = False,
        child_metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return run_sub_agent_task(
            self,
            session_id=session_id,
            task=task,
            name=name,
            skills=skills,
            allowed_tools=allowed_tools,
            system_prompt=system_prompt,
            learning_agent=learning_agent,
            child_metadata=child_metadata,
        )

    def run_sub_agents(
        self,
        *,
        session_id: str,
        tasks: tuple[Mapping[str, Any], ...],
        max_concurrency: int = 3,
    ) -> Mapping[str, Any]:
        return run_sub_agent_tasks(self, session_id=session_id, tasks=tasks, max_concurrency=max_concurrency)

    def start_sub_agents(
        self,
        *,
        session_id: str,
        tasks: tuple[Mapping[str, Any], ...],
        max_concurrency: int = 3,
    ) -> Mapping[str, Any]:
        return start_sub_agent_tasks(self, session_id=session_id, tasks=tasks, max_concurrency=max_concurrency)

    def inspect_sub_agent_run(
        self,
        *,
        session_id: str,
        run_id: str,
        wait_timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        return inspect_sub_agent_run(
            self,
            session_id=session_id,
            run_id=run_id,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def list_sub_agent_runs(self, *, session_id: str) -> Mapping[str, Any]:
        return list_sub_agent_runs(self, session_id=session_id)
