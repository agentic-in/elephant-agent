"""Sandbox scope and lifecycle management.

Phase 3: Provides scope-aware session management and lifecycle operations
(list, prune, inspect) for sandbox sessions across backends.
"""

from __future__ import annotations

import dataclasses
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SandboxConfig, SandboxScope
from .types import EnvironmentBackend, SessionHandle


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Read-only snapshot of an active sandbox session."""

    session_id: str
    backend_id: str
    scope: SandboxScope
    sandbox_root: Path
    cwd: Path
    created_at: datetime
    agent_id: str | None = None


@dataclass
class SandboxScopeManager:
    """Manages sandbox session lifecycle with scope awareness.

    Scopes:
    - ``session``: Session-scoped — lives and dies with one conversation session
    - ``agent``: Agent-scoped — shared across sessions of the same agent
    - ``shared``: Shared across all agents on the same host

    The scope determines the session ID namespace and cleanup policy:
    - session-scoped sessions are cleaned up when the session ends
    - agent-scoped sessions survive across sessions but are cleaned up
      when the agent shuts down
    - shared sessions persist until explicitly pruned
    """

    _config: SandboxConfig
    _backend: EnvironmentBackend
    _sessions: dict[str, SessionHandle] = field(default_factory=dict)
    _session_meta: dict[str, SessionInfo] = field(default_factory=dict)

    def resolve_session_id(
        self,
        base_session_id: str,
        *,
        agent_id: str | None = None,
    ) -> str:
        """Resolve a session ID based on the configured scope.

        For ``session`` scope, returns the base ID unchanged.
        For ``agent`` scope, prefixes with the agent ID.
        For ``shared`` scope, uses a fixed well-known prefix.
        """
        scope = self._config.scope
        if scope == "session":
            return base_session_id
        elif scope == "agent":
            effective_agent = agent_id or "default"
            return f"agent:{effective_agent}:{base_session_id}"
        elif scope == "shared":
            return f"shared:{base_session_id}"
        return base_session_id

    def create_session(
        self,
        *,
        session_id: str,
        cwd: Path,
        env: dict[str, str],
        agent_id: str | None = None,
    ) -> SessionHandle:
        """Create a new sandbox session with scope-aware ID resolution."""
        effective_id = self.resolve_session_id(session_id, agent_id=agent_id)

        if effective_id in self._sessions:
            return self._sessions[effective_id]

        handle = self._backend.create_session(
            session_id=effective_id, cwd=cwd, env=env,
        )

        self._sessions[effective_id] = handle
        self._session_meta[effective_id] = SessionInfo(
            session_id=effective_id,
            backend_id=handle.backend_id,
            scope=self._config.scope,
            sandbox_root=handle.sandbox_root,
            cwd=handle.cwd,
            created_at=datetime.now(timezone.utc),
            agent_id=agent_id,
        )

        return handle

    def get_session(self, session_id: str) -> SessionHandle | None:
        effective_id = self.resolve_session_id(session_id)
        return self._sessions.get(effective_id)

    def cleanup_session(self, session_id: str) -> bool:
        """Clean up a specific session. Returns True if found and cleaned."""
        effective_id = self.resolve_session_id(session_id)
        handle = self._sessions.pop(effective_id, None)
        self._session_meta.pop(effective_id, None)
        if handle is not None:
            self._backend.cleanup_session(handle)
            return True
        return False

    def cleanup_session_scope(self, *, agent_id: str | None = None) -> int:
        """Clean up all sessions matching the current scope.

        For ``session`` scope: cleans up sessions for the given agent.
        For ``agent`` scope: cleans up sessions for the given agent.
        For ``shared`` scope: cleans up all shared sessions.

        Returns the number of sessions cleaned up.
        """
        cleaned = 0
        to_remove: list[str] = []

        for sid, meta in self._session_meta.items():
            scope = self._config.scope
            if scope == "session" and (agent_id is None or meta.agent_id == agent_id):
                to_remove.append(sid)
            elif scope == "agent" and meta.agent_id == agent_id:
                to_remove.append(sid)
            elif scope == "shared":
                to_remove.append(sid)

        for sid in to_remove:
            handle = self._sessions.pop(sid, None)
            self._session_meta.pop(sid, None)
            if handle is not None:
                self._backend.cleanup_session(handle)
                cleaned += 1

        return cleaned

    # ------------------------------------------------------------------
    # Lifecycle operations (CLI-facing)
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[SessionInfo]:
        """List all active sessions managed by this scope manager."""
        return list(self._session_meta.values())

    def inspect_session(self, session_id: str) -> SessionInfo | None:
        """Get metadata for a specific session."""
        effective_id = self.resolve_session_id(session_id)
        return self._session_meta.get(effective_id)

    def prune_stale_sessions(self, max_age_seconds: int = 3600) -> int:
        """Remove sessions older than *max_age_seconds*.

        Returns the number of pruned sessions.
        """
        now = datetime.now(timezone.utc).timestamp()
        pruned = 0
        to_remove: list[str] = []

        for sid, meta in self._session_meta.items():
            age = now - meta.created_at.timestamp()
            if age > max_age_seconds:
                to_remove.append(sid)

        for sid in to_remove:
            handle = self._sessions.pop(sid, None)
            self._session_meta.pop(sid, None)
            if handle is not None:
                self._backend.cleanup_session(handle)
                pruned += 1

        return pruned

    def cleanup_all(self) -> int:
        """Clean up all sessions. Returns count of cleaned sessions."""
        count = 0
        for handle in self._sessions.values():
            try:
                self._backend.cleanup_session(handle)
                count += 1
            except Exception:
                pass
        self._sessions.clear()
        self._session_meta.clear()
        return count
