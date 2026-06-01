"""Sandbox violation tracking and persistence.

Records sandbox-denied operations for later review via
``elephant sandbox violations``. Each violation is a structured
event with timestamp, operation type, path, and reason.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Violation:
    """A single sandbox violation event."""

    timestamp: float
    operation: str       # "write", "read", "network"
    path: str            # target path or host
    reason: str          # human-readable reason
    command: str = ""    # the command that triggered it
    diagnostic: str = "" # raw diagnostic string from _detect_violations

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Violation":
        return cls(
            timestamp=float(data.get("timestamp", 0)),
            operation=str(data.get("operation", "")),
            path=str(data.get("path", "")),
            reason=str(data.get("reason", "")),
            command=str(data.get("command", "")),
            diagnostic=str(data.get("diagnostic", "")),
        )

    def format_short(self) -> str:
        """One-line summary for display."""
        ts = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        op = self.operation.upper()
        return f"[{ts}] {op} DENIED {self.path}\n     Reason: {self.reason}"


class ViolationStore:
    """Append-only violation log backed by a JSONL file.

    The store is scoped to a state directory (typically ~/.elephant).
    """

    def __init__(self, state_dir: Path) -> None:
        self._log_path = state_dir / "sandbox_violations.jsonl"

    @property
    def log_path(self) -> Path:
        return self._log_path

    def record(self, violation: Violation) -> None:
        """Append a violation to the log."""
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(violation.to_dict(), ensure_ascii=False) + "\n")

    def record_from_diagnostics(
        self,
        diagnostics: tuple[str, ...],
        *,
        command: str = "",
    ) -> list[Violation]:
        """Parse diagnostics strings and record violations.

        Returns the list of violations that were recorded.
        """
        violations: list[Violation] = []
        now = time.time()

        for diag in diagnostics:
            if not diag.startswith("sandbox:denied"):
                continue

            # Parse diagnostic format: "sandbox:denied:OP PATH (reason)"
            # or "sandbox:denied (generic message)"
            operation = "unknown"
            path = ""
            reason = diag

            if ":write " in diag:
                operation = "write"
                # Extract path between ":write " and " ("
                after_write = diag.split(":write ", 1)[1]
                if " (" in after_write:
                    path = after_write.split(" (")[0]
                    reason = after_write.split("(", 1)[1].rstrip(")")
                else:
                    path = after_write
            elif ":read " in diag:
                operation = "read"
                after_read = diag.split(":read ", 1)[1]
                if " (" in after_read:
                    path = after_read.split(" (")[0]
                    reason = after_read.split("(", 1)[1].rstrip(")")
                else:
                    path = after_read
            elif ":network" in diag:
                operation = "network"
                if "(" in diag:
                    reason = diag.split("(", 1)[1].rstrip(")")
                path = "outbound"

            v = Violation(
                timestamp=now,
                operation=operation,
                path=path,
                reason=reason,
                command=command,
                diagnostic=diag,
            )
            violations.append(v)
            self.record(v)

        return violations

    def recent(self, limit: int = 20) -> list[Violation]:
        """Read the most recent violations (tail of log)."""
        if not self._log_path.exists():
            return []

        violations: list[Violation] = []
        try:
            lines = self._log_path.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-limit:]:
                try:
                    data = json.loads(line)
                    violations.append(Violation.from_dict(data))
                except (json.JSONDecodeError, KeyError):
                    continue
        except OSError:
            pass
        return violations

    def clear(self) -> int:
        """Clear all violations. Returns count of cleared entries."""
        if not self._log_path.exists():
            return 0
        try:
            count = len(self._log_path.read_text().strip().splitlines())
            self._log_path.unlink()
            return count
        except OSError:
            return 0
