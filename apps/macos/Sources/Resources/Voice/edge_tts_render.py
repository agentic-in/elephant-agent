#!/usr/bin/env python3
"""Render one text file with Microsoft Edge online neural TTS."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


async def render() -> None:
    args = parse_args()
    try:
        import edge_tts
    except Exception as exc:  # pragma: no cover - exercised by app fallback.
        print(
            json.dumps(
                {
                    "error": "edge-tts is not installed in the macOS voice runtime.",
                    "detail": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)

    text = Path(args.text_file).read_text(encoding="utf-8").strip()
    if not text:
        print(json.dumps({"error": "No text was provided."}), file=sys.stderr)
        raise SystemExit(2)

    output = Path(args.output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    retries = max(1, args.retries)
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            if output.exists():
                output.unlink()
            communicate = edge_tts.Communicate(text=text, voice=args.voice, rate=args.rate)
            await communicate.save(str(output))
            if output.exists() and output.stat().st_size > 0:
                return
            last_error = "Edge TTS did not create audio."
        except Exception as exc:  # pragma: no cover - depends on online service state.
            last_error = str(exc)
            if output.exists() and output.stat().st_size == 0:
                output.unlink()
        if attempt < retries:
            await asyncio.sleep(0.65 * attempt)

    if output.exists() and output.stat().st_size == 0:
        output.unlink()
    print(
        json.dumps(
            {
                "error": "Edge online voice is unavailable.",
                "detail": last_error,
                "attempts": retries,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(render())
