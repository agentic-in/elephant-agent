"""Unified host ↔ sandbox path mapping.

Provides a single, authoritative mapping between host filesystem paths
(e.g. ``/Users/alice/.elephant/workspaces/mother-elephant/foo.py``) and
their corresponding sandbox-internal paths (e.g. ``/home/user/mother-elephant/foo.py``).

All sandbox components (executor, backends) share a single ``SandboxPathMapper``
instance to ensure consistent path translation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class SandboxPathMapper:
    """Unified host ↔ sandbox path mapping.

    Uses ``workspaces_dir`` prefix matching to automatically strip the host
    workspaces prefix and produce clean sandbox paths like
    ``/home/user/{elephant_id}/file.py``.

    No need to pass ``elephant_id`` explicitly — it is derived from the
    relative path under ``workspaces_dir``.
    """

    workspaces_dir: Path | None = None
    """Host workspaces root, e.g. ``~/.elephant/workspaces``."""

    startup_cwd: Path | None = None
    """Host directory where the session launched (fallback mapping)."""

    sandbox_home: str = "/home/user"
    """Sandbox home directory (all mapped paths land here)."""

    def to_remote(self, local_path: str) -> str:
        """Map a host path to the corresponding sandbox path.

        Rules (applied in order):
          1. Already a remote path (``/home/...`` or ``/tmp/...``) → unchanged
          2. Relative path → resolved under ``sandbox_home``
          3. Under ``workspaces_dir`` → strip prefix, yielding ``{elephant_id}/...``
          4. Under ``startup_cwd`` → map to ``sandbox_home/project/...``
          5. Fallback → ``sandbox_home/{basename}``
        """
        if not local_path:
            return self.sandbox_home

        # Rule 1: already remote
        if local_path.startswith("/home/") or local_path.startswith("/tmp/"):
            return local_path

        path = Path(local_path)

        # Rule 2: relative path
        if not path.is_absolute():
            return str(PurePosixPath(self.sandbox_home) / local_path)

        # Rule 3: under workspaces_dir → strip prefix
        if self.workspaces_dir is not None:
            try:
                relative = path.resolve().relative_to(self.workspaces_dir.resolve())
                return str(PurePosixPath(self.sandbox_home) / str(relative))
            except ValueError:
                pass

        # Rule 4: under startup_cwd → map to project/
        if self.startup_cwd is not None:
            try:
                relative = path.resolve().relative_to(self.startup_cwd.resolve())
                parts_str = str(relative)
                if parts_str and parts_str != ".":
                    return str(PurePosixPath(self.sandbox_home) / "project" / parts_str)
                return f"{self.sandbox_home}/project"
            except ValueError:
                pass

        # Rule 5: fallback — use basename
        name = path.name
        if name:
            return f"{self.sandbox_home}/{name}"
        return self.sandbox_home

    def remote_cwd(self, local_cwd: str | Path | None = None) -> str:
        """Determine the sandbox working directory for a given host cwd.

        If *local_cwd* is ``None``, returns ``sandbox_home``.
        """
        if local_cwd is not None:
            return self.to_remote(str(local_cwd))
        return self.sandbox_home
