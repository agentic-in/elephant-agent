#!/usr/bin/env python3
"""Transcribe one audio file with local FunASR Paraformer Chinese models."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--hotwords")
    parser.add_argument("--health-check", action="store_true")
    return parser.parse_args()


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def joined_text(result: Any) -> str:
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, dict):
                value = item.get("text") or item.get("sentence_info") or ""
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, list):
                    parts.extend(
                        sentence.get("text", "")
                        for sentence in value
                        if isinstance(sentence, dict)
                    )
        return "".join(parts).strip()
    if isinstance(result, dict):
        return str(result.get("text") or "").strip()
    return ""


def activate_distutils_compat() -> None:
    # Python 3.12 removed stdlib distutils. FunASR still imports it in some
    # model files, and target site-packages do not process setuptools .pth hooks.
    os.environ.setdefault("SETUPTOOLS_USE_DISTUTILS", "local")
    try:
        import setuptools._distutils as distutils_compat

        sys.modules.setdefault("distutils", distutils_compat)
        try:
            import setuptools._distutils.version as distutils_version

            sys.modules.setdefault("distutils.version", distutils_version)
        except Exception:
            pass
    except Exception:
        pass


def activate_ffmpeg_compat() -> None:
    if shutil.which("ffmpeg"):
        return
    candidate = bundled_ffmpeg()
    if candidate is None:
        return
    shim_root = Path(os.environ.get("ELEPHANT_VOICE_CACHE") or tempfile.gettempdir()) / "bin"
    shim_root.mkdir(parents=True, exist_ok=True)
    shim = shim_root / "ffmpeg"
    if not shim.exists():
        try:
            shim.symlink_to(candidate)
        except OSError:
            shutil.copy2(candidate, shim)
            shim.chmod(0o755)
    os.environ["PATH"] = f"{shim_root}{os.pathsep}{os.environ.get('PATH', '')}"


def bundled_ffmpeg() -> Path | None:
    explicit = os.environ.get("ELEPHANT_FFMPEG")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.extend(
            [
                parent / "Runtime" / "ms-playwright" / "ffmpeg-1011" / "ffmpeg-mac",
                parent / "ms-playwright" / "ffmpeg-1011" / "ffmpeg-mac",
            ]
        )
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return None


def model_kwargs() -> dict[str, Any]:
    return {
        "model": "paraformer-zh",
        "vad_model": "fsmn-vad",
        "punc_model": "ct-punc",
        "device": "cpu",
        "ncpu": max(1, min(os.cpu_count() or 2, 4)),
        "disable_update": True,
        "disable_pbar": True,
    }


def main() -> int:
    args = parse_args()
    output = Path(args.output_json)
    audio = Path(args.input)
    logging.basicConfig(level=logging.ERROR)
    activate_distutils_compat()
    activate_ffmpeg_compat()

    if not args.health_check and not audio.exists():
        write_output(output, {"text": "", "error": f"Audio file does not exist: {audio}"})
        return 2

    try:
        from funasr import AutoModel
    except Exception as exc:  # pragma: no cover - exercised by app fallback.
        write_output(
            output,
            {
                "text": "",
                "error": "FunASR is not installed in the macOS voice runtime.",
                "detail": str(exc),
            },
        )
        return 2

    try:
        model = AutoModel(**model_kwargs())
        if args.health_check:
            write_output(
                output,
                {
                    "ok": True,
                    "model": "paraformer-zh",
                    "vad_model": "fsmn-vad",
                    "punc_model": "ct-punc",
                },
            )
            return 0

        hotword_text = ""
        if args.hotwords:
            hotword_path = Path(args.hotwords)
            if hotword_path.exists():
                hotword_text = hotword_path.read_text(encoding="utf-8").strip()
        result = model.generate(
            input=str(audio),
            language=args.language,
            hotword=hotword_text,
            batch_size_s=300,
        )
        text = joined_text(result)
        write_output(output, {"text": text, "segments": result})
        return 0 if text else 3
    except Exception as exc:
        write_output(output, {"text": "", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
