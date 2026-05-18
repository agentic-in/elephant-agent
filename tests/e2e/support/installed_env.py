from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import TracebackType
from typing import Self


ROOT = Path(__file__).resolve().parents[3]


class InstalledElephantEnvironment:
    """Fresh editable install of the public ``elephant`` command."""

    def __init__(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tempdir.name)
        self.venv_dir = self.root / "venv"
        self.home_dir = self.root / "elephant-home"
        self.state_dir = self.home_dir / "herd"

    def __enter__(self) -> Self:
        self.install_editable()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.cleanup()

    @property
    def python_bin(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"

    @property
    def elephant_bin(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "elephant.exe"
        return self.venv_dir / "bin" / "elephant"

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env["ELEPHANT_HOME"] = str(self.home_dir)
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLUMNS", "120")
        env.setdefault("LINES", "40")
        if extra:
            env.update(extra)
        return env

    def install_editable(self) -> None:
        subprocess.run(
            [sys.executable, "-m", "venv", str(self.venv_dir)],
            cwd=ROOT,
            check=True,
            text=True,
        )
        subprocess.run(
            [str(self.python_bin), "-m", "pip", "install", "-e", "."],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
            timeout=600,
        )

    def run(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        timeout: int = 120,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(self.elephant_bin), *args],
            cwd=self.root,
            env=env or self.env(),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            raise AssertionError(
                "command failed: "
                + " ".join([str(self.elephant_bin), *args])
                + f"\nexit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def stop_daemon(self, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return self.run(
            "daemon",
            "stop",
            "--state-dir",
            str(self.state_dir),
            "--timeout",
            "5",
            "--force",
            timeout=timeout,
            check=False,
        )

    def cleanup(self) -> None:
        try:
            self.stop_daemon(timeout=15)
        finally:
            self._tempdir.cleanup()

