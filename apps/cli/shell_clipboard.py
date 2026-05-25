from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import subprocess
import sys
import time
from typing import Iterable

LOGGER = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = frozenset(
    {
        ".avif",
        ".bmp",
        ".gif",
        ".heic",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".tif",
        ".tiff",
        ".webp",
    }
)


@dataclass(frozen=True, slots=True)
class ClipboardAttachment:
    kind: str
    display_label: str
    prompt_fragment: str


@dataclass(frozen=True, slots=True)
class ClipboardSubmission:
    command: str
    display_command: str
    event_payload: dict[str, str]


@dataclass(frozen=True, slots=True)
class _ClipboardProbe:
    kind: str
    text: str = ""
    paths: tuple[str, ...] = ()


def _detect_paste_intent(text: str) -> str:
    """Classify a pasted blob so the UI can hint its nature.

    Returns one of:
      - "path"    — looks like a single file path
      - "code"    — multi-line with code-ish density
      - "error"   — traceback or error output
      - "text"    — fall-through, plain text
    Cheap heuristics only; never misbehave on edge cases.
    """
    stripped = text.strip()
    if not stripped:
        return "text"
    # Single line starting with / or ~ or ./ => likely a path.
    if "\n" not in stripped:
        if len(stripped) <= 400 and (
            stripped.startswith(("/", "~/", "./", "../"))
            or (len(stripped) >= 3 and stripped[1:3] == ":\\")  # windows drive
        ):
            return "path"
        return "text"
    # Multi-line: look for error markers first, then code markers.
    lowered = stripped.lower()
    if "traceback (most recent call last)" in lowered:
        return "error"
    error_marker_count = sum(
        1 for line in stripped.splitlines()
        if line.strip().startswith(("File \"", "File '", "  at ", "Error:", "Exception", "Caused by:"))
    )
    if error_marker_count >= 2:
        return "error"
    lines = stripped.splitlines()
    if len(lines) >= 4:
        code_markers = 0
        for line in lines:
            stripped_line = line.strip()
            if not stripped_line:
                continue
            if stripped_line.startswith(("def ", "class ", "import ", "from ", "function ", "const ", "let ", "var ")):
                code_markers += 2
            elif stripped_line.endswith((":", "{", "}", ");", ";")):
                code_markers += 1
            elif stripped_line.startswith(("//", "#", "/*", "*")):
                code_markers += 1
        if code_markers >= max(3, len(lines) // 3):
            return "code"
    return "text"


def build_text_attachment(text: str) -> ClipboardAttachment | None:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return None
    char_count = len(normalized)
    line_count = normalized.count("\n") + 1
    intent = _detect_paste_intent(normalized)
    # Human-readable chip in the composer: chip label varies by intent
    # so the user can tell at a glance what they just pasted.
    if intent == "code":
        label = f"[pasted code · {line_count} lines · {char_count:,} chars]"
    elif intent == "error":
        label = f"[pasted error · {line_count} lines]"
    elif intent == "path":
        label = f"[pasted path · {normalized.strip()[-48:]}]"
    else:
        label = f"[Pasted Content {char_count} chars]"
    # Prompt fragment wraps with an intent hint so the model knows what
    # the user dropped in, which makes replies more useful without the
    # user having to say "this is a traceback / this is code".
    hint = {
        "code": "[Clipboard code]",
        "error": "[Clipboard error / traceback]",
        "path": "[Clipboard path]",
        "text": "[Clipboard text]",
    }[intent]
    return ClipboardAttachment(
        kind=intent if intent != "text" else "text",
        display_label=label,
        prompt_fragment=f"{hint}\n{normalized}",
    )


def build_path_attachment(path: str, *, kind_hint: str | None = None) -> ClipboardAttachment | None:
    raw_path = str(path or "").strip()
    if not raw_path:
        return None
    resolved = str(Path(raw_path).expanduser().resolve())
    kind = kind_hint or _path_kind(resolved)
    return ClipboardAttachment(
        kind=kind,
        display_label=f"[{Path(resolved).name}]",
        prompt_fragment=f"@{kind}:{resolved}",
    )


def import_system_clipboard(*, storage_dir: Path) -> tuple[ClipboardAttachment, ...]:
    probe = _system_clipboard_probe(storage_dir=storage_dir)
    if probe.kind == "text":
        attachment = build_text_attachment(probe.text)
        return (attachment,) if attachment is not None else ()
    if probe.kind in {"files", "image"}:
        attachments = [
            attachment
            for raw_path in probe.paths
            if (attachment := build_path_attachment(raw_path, kind_hint="image" if probe.kind == "image" else None)) is not None
        ]
        return tuple(attachments)
    return ()


def compile_submission(raw_text: str, attachments: Iterable[ClipboardAttachment]) -> ClipboardSubmission:
    normalized = str(raw_text or "").strip()
    items = tuple(attachment for attachment in attachments if isinstance(attachment, ClipboardAttachment))
    if normalized.startswith("/"):
        return ClipboardSubmission(command=normalized, display_command=normalized, event_payload={})
    compact_display_command = _display_command(normalized, items)
    display_command = _expanded_display_command(normalized, items) or compact_display_command
    prompt_parts: list[str] = [normalized] if normalized else []
    prompt_parts.extend(
        attachment.prompt_fragment.strip()
        for attachment in items
        if attachment.prompt_fragment.strip()
    )
    command = "\n\n".join(part for part in prompt_parts if part)
    visible = display_command or normalized or command
    event_payload = (
        {
            "message": visible,
            "content": visible,
            "summary": visible,
        }
        if items
        else {}
    )
    return ClipboardSubmission(
        command=command,
        display_command=display_command or command,
        event_payload=event_payload,
    )


def _display_command(text: str, attachments: tuple[ClipboardAttachment, ...]) -> str:
    labels = " ".join(attachment.display_label for attachment in attachments if attachment.display_label).strip()
    if not labels:
        return text
    if text and "\n" not in text:
        return f"{text} {labels}".strip()
    return "\n".join(part for part in (text, labels) if part).strip()


def _expanded_display_command(text: str, attachments: tuple[ClipboardAttachment, ...]) -> str:
    parts: list[str] = [text] if text else []
    for attachment in attachments:
        restored = _restore_attachment_display_text(attachment)
        if restored:
            parts.append(restored)
    return "\n\n".join(part for part in parts if part).strip()


def _restore_attachment_display_text(attachment: ClipboardAttachment) -> str:
    if attachment.kind in {"file", "image"}:
        return attachment.display_label.strip()
    fragment = str(attachment.prompt_fragment or "").strip()
    if not fragment:
        return ""
    if "\n" not in fragment:
        return fragment
    _header, body = fragment.split("\n", 1)
    return body.strip()


def _path_kind(path: str) -> str:
    return "image" if Path(path).suffix.lower() in _IMAGE_EXTENSIONS else "file"


def _system_clipboard_probe(*, storage_dir: Path) -> _ClipboardProbe:
    if sys.platform == "darwin":
        try:
            return _probe_macos_clipboard(storage_dir=storage_dir)
        except Exception:
            LOGGER.warning("failed to probe macOS clipboard", exc_info=True)
            pass
        text = _pbpaste_text()
        if text.strip():
            return _ClipboardProbe(kind="text", text=text)
        return _ClipboardProbe(kind="empty")
    return _ClipboardProbe(kind="empty")


def _probe_macos_clipboard(*, storage_dir: Path) -> _ClipboardProbe:
    storage_dir.mkdir(parents=True, exist_ok=True)
    image_path = storage_dir / f"clipboard-image-{time.time_ns()}.png"
    script = _macos_clipboard_script(str(image_path))
    completed = subprocess.run(
        ["osascript", "-l", "JavaScript"],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = _parse_probe_payload(completed)
    if not isinstance(payload, dict):
        raise RuntimeError("clipboard probe did not return json")
    kind = str(payload.get("kind") or "empty").strip().lower()
    if kind == "text":
        return _ClipboardProbe(kind="text", text=str(payload.get("text") or ""))
    if kind == "files":
        paths = tuple(
            str(path).strip()
            for path in payload.get("paths", ())
            if str(path or "").strip()
        )
        return _ClipboardProbe(kind="files", paths=paths)
    if kind == "image":
        path = str(payload.get("path") or "").strip()
        return _ClipboardProbe(kind="image", paths=(path,) if path else ())
    return _ClipboardProbe(kind="empty")


def _parse_probe_payload(completed: subprocess.CompletedProcess[str]) -> object:
    candidates = [
        line.strip()
        for stream in (completed.stdout, completed.stderr)
        for line in str(stream or "").splitlines()
        if line.strip()
    ]
    for candidate in reversed(candidates):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _pbpaste_text() -> str:
    completed = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False)
    return str(completed.stdout or "")


def _macos_clipboard_script(image_path: str) -> str:
    path_literal = json.dumps(image_path)
    return (
        'ObjC.import("AppKit");'
        'ObjC.import("Foundation");'
        'function emit(obj){var text=JSON.stringify(obj)+"\\n";'
        'var data=$(text).dataUsingEncoding($.NSUTF8StringEncoding);'
        '$.NSFileHandle.fileHandleWithStandardOutput.writeData(data);}'
        'var pb=$.NSPasteboard.generalPasteboard;'
        'var items=pb.pasteboardItems;'
        'var paths=[];'
        'if(items){for(var i=0;i<items.count;i++){' 
        'var item=items.objectAtIndex(i);'
        'var urlString=item.stringForType($("public.file-url"))||item.stringForType($("NSURLPboardType"));'
        'if(urlString){var nsurl=$.NSURL.URLWithString(urlString);'
        'if(nsurl&&nsurl.isFileURL){paths.push(ObjC.unwrap(nsurl.path));}}}}'
        'if(paths.length){emit({kind:"files",paths:paths});}'
        'else{var str=pb.stringForType($.NSPasteboardTypeString);'
        'if(str){emit({kind:"text",text:ObjC.unwrap(str)});}'
        'else{var data=pb.dataForType($("public.png"))||pb.dataForType($("Apple PNG pasteboard type"));'
        f'var imagePath={path_literal};'
        'if(data){var ok=data.writeToFileAtomically($(imagePath),true);'
        'emit(ok?{kind:"image",path:imagePath}:{kind:"empty"});}'
        'else{var image=$.NSImage.alloc.initWithPasteboard(pb);'
        'if(image&&image.isValid()){var tiff=image.TIFFRepresentation();'
        'var rep=tiff?$.NSBitmapImageRep.imageRepWithData(tiff):null;'
        'var png=rep?rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG,$({})):null;'
        'if(png){var wrote=png.writeToFileAtomically($(imagePath),true);'
        'emit(wrote?{kind:"image",path:imagePath}:{kind:"empty"});}'
        'else{emit({kind:"empty"});}}'
        'else{emit({kind:"empty"});}}}'
    )


__all__ = [
    "ClipboardAttachment",
    "ClipboardSubmission",
    "build_path_attachment",
    "build_text_attachment",
    "compile_submission",
    "import_system_clipboard",
]
