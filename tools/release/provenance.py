#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SUFFIXES = (".whl", ".tar.gz")
DEFAULT_PROVENANCE_NAME = "elephant-agent-provenance.json"
DEFAULT_SHA256_NAME = "SHA256SUMS"


def package_artifacts(dist_dir: Path) -> tuple[Path, ...]:
    artifacts = [
        path
        for path in sorted(dist_dir.iterdir())
        if path.is_file() and any(path.name.endswith(suffix) for suffix in PACKAGE_SUFFIXES)
    ]
    return tuple(artifacts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit_sha(root: Path = ROOT) -> str:
    from_env = os.environ.get("GITHUB_SHA", "").strip()
    if from_env:
        return from_env
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def build_source() -> dict[str, str]:
    workflow = os.environ.get("GITHUB_WORKFLOW", "").strip()
    if workflow:
        return {
            "kind": "github-actions",
            "workflow": workflow,
            "run_id": os.environ.get("GITHUB_RUN_ID", "").strip(),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "").strip(),
            "ref": os.environ.get("GITHUB_REF", "").strip(),
        }
    return {"kind": "local", "workflow": "", "run_id": "", "run_attempt": "", "ref": ""}


def project_version(root: Path = ROOT) -> str:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10 fallback kept for local tools.
        return "unknown"
    payload = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload.get("project", {}).get("version", "unknown"))


def build_provenance(
    *,
    dist_dir: Path,
    root: Path = ROOT,
    version: str = "",
    commit_sha: str = "",
) -> dict[str, object]:
    artifacts = package_artifacts(dist_dir)
    if not artifacts:
        raise SystemExit(f"no Python package artifacts found in {dist_dir}")
    return {
        "project": "elephant-agent",
        "version": version or project_version(root),
        "commit_sha": commit_sha or git_commit_sha(root),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "build_source": build_source(),
        "validation": {
            "package_build": "make package-build",
            "package_verify": "make package-verify",
            "twine_check": "uvx twine check dist/*.whl dist/*.tar.gz",
        },
        "artifacts": [
            {
                "name": artifact.name,
                "size_bytes": artifact.stat().st_size,
                "sha256": sha256_file(artifact),
            }
            for artifact in artifacts
        ],
    }


def write_sha256sums(path: Path, provenance: dict[str, object]) -> None:
    artifacts = provenance.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise SystemExit("provenance artifacts must be a list")
    lines = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        sha256 = str(artifact.get("sha256", "")).strip()
        name = str(artifact.get("name", "")).strip()
        if sha256 and name:
            lines.append(f"{sha256}  {name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Elephant Agent package provenance.")
    parser.add_argument("--dist-dir", default="dist")
    parser.add_argument("--output", default="")
    parser.add_argument("--sha256-output", default="")
    parser.add_argument("--version", default=os.environ.get("ELEPHANT_RELEASE_VERSION", ""))
    parser.add_argument("--commit-sha", default=os.environ.get("GITHUB_SHA", ""))
    args = parser.parse_args()

    dist_dir = Path(args.dist_dir)
    if not dist_dir.is_absolute():
        dist_dir = ROOT / dist_dir
    output = Path(args.output) if args.output else dist_dir / DEFAULT_PROVENANCE_NAME
    sha256_output = Path(args.sha256_output) if args.sha256_output else dist_dir / DEFAULT_SHA256_NAME
    if not output.is_absolute():
        output = ROOT / output
    if not sha256_output.is_absolute():
        sha256_output = ROOT / sha256_output

    provenance = build_provenance(
        dist_dir=dist_dir,
        version=args.version,
        commit_sha=args.commit_sha,
    )
    output.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_sha256sums(sha256_output, provenance)
    print(f"Wrote {output}")
    print(f"Wrote {sha256_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
