"""Gateway application bootstrap and real messaging adapter pair."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayAccountRef,
    GatewayAttachmentRef,
    GatewayConversationRef,
    GatewayOutboundMessage,
    GatewayPolicyHint,
    GatewaySenderRef,
)

CHAT_BOT_ADAPTER_ID = "messaging.chat-bot"
WEBHOOK_ADAPTER_ID = "messaging.webhook"
TELEGRAM_ADAPTER_ID = "messaging.telegram"
FEISHU_ADAPTER_ID = "messaging.feishu"
DISCORD_ADAPTER_ID = "messaging.discord"
DINGDING_ADAPTER_ID = "messaging.dingding"
WECOM_ADAPTER_ID = "messaging.wecom"
WEIXIN_ADAPTER_ID = "messaging.weixin"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _object_map(payload: Mapping[str, object] | None) -> dict[str, object]:
    if payload is None:
        return {}
    return {str(key): value for key, value in payload.items()}


def _string_payload(payload: Mapping[str, object] | None) -> dict[str, str]:
    if payload is None:
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def _account_ref(
    adapter_id: str,
    *,
    account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID,
    surface: str | None = None,
    tenant_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> GatewayAccountRef:
    return GatewayAccountRef(
        adapter_id=adapter_id,
        account_id=account_id,
        tenant_id=tenant_id,
        surface=surface,
        metadata=_object_map(metadata),
    )


def _conversation_ref(
    conversation_id: str,
    *,
    parent_conversation_id: str | None = None,
    thread_id: str | None = None,
    chat_type: str | None = None,
    title: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> GatewayConversationRef:
    return GatewayConversationRef(
        conversation_id=conversation_id,
        parent_conversation_id=parent_conversation_id,
        thread_id=thread_id,
        chat_type=chat_type,
        title=title,
        metadata=_object_map(metadata),
    )


def _sender_ref(
    external_user_id: str,
    *,
    display_name: str | None = None,
    username: str | None = None,
    is_bot: bool = False,
    is_self: bool = False,
    metadata: Mapping[str, object] | None = None,
) -> GatewaySenderRef:
    return GatewaySenderRef(
        external_user_id=external_user_id,
        display_name=display_name,
        username=username,
        is_bot=is_bot,
        is_self=is_self,
        metadata=_object_map(metadata),
    )


def _attachment_refs(
    attachment_ids: tuple[str, ...],
    *,
    kind: str = "file",
) -> tuple[GatewayAttachmentRef, ...]:
    deduped = tuple(dict.fromkeys(attachment_ids))
    return tuple(
        GatewayAttachmentRef(
            attachment_id=attachment_id,
            kind=kind,
            platform_fetch_ref=attachment_id,
        )
        for attachment_id in deduped
    )


def _policy_hint(
    *,
    target_trusted_default: bool,
    consent_default: bool,
    is_external_default: bool,
    audience_scope: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> GatewayPolicyHint:
    return GatewayPolicyHint(
        target_trusted_default=target_trusted_default,
        consent_default=consent_default,
        is_external_default=is_external_default,
        audience_scope=audience_scope,
        metadata=_object_map(metadata),
    )


def _normalized_chat_type(chat_type: str) -> str:
    if chat_type == "private":
        return "direct"
    if chat_type == "p2p":
        return "direct"
    if chat_type in {"group", "supergroup"}:
        return "group"
    if chat_type == "channel":
        return "channel"
    return chat_type


def _telegram_display_name(payload: Mapping[str, object]) -> str | None:
    first_name = str(payload.get("first_name") or "").strip()
    last_name = str(payload.get("last_name") or "").strip()
    username = str(payload.get("username") or "").strip()
    combined = " ".join(part for part in (first_name, last_name) if part)
    if combined:
        return combined
    if username:
        return f"@{username}"
    return None


def _telegram_attachment_ids(message: Mapping[str, object]) -> tuple[str, ...]:
    attachments: list[str] = []
    photos = message.get("photo")
    if isinstance(photos, list):
        for item in photos:
            if isinstance(item, Mapping) and item.get("file_id") is not None:
                attachments.append(str(item["file_id"]))
    for key in ("document", "audio", "video", "voice", "sticker"):
        value = message.get(key)
        if isinstance(value, Mapping) and value.get("file_id") is not None:
            attachments.append(str(value["file_id"]))
    return tuple(dict.fromkeys(attachments))


def _telegram_delivery_defaults(chat_type: str) -> tuple[bool, bool, bool]:
    if chat_type == "private":
        return True, True, False
    return False, False, True


def _telegram_conversation_id(chat_id: str, thread_id: object | None) -> str:
    if thread_id is None:
        return chat_id
    return f"{chat_id}:{thread_id}"


def _discord_display_name(
    author: Mapping[str, object],
    *,
    member: Mapping[str, object] | None = None,
) -> str | None:
    if member is not None and member.get("nick") is not None:
        nickname = str(member.get("nick") or "").strip()
        if nickname:
            return nickname
    for key in ("global_name", "display_name", "username"):
        value = str(author.get(key) or "").strip()
        if value:
            return value
    return None


def _discord_attachment_refs(
    attachments: object,
) -> tuple[GatewayAttachmentRef, ...]:
    if not isinstance(attachments, list):
        return ()
    resolved: list[GatewayAttachmentRef] = []
    for item in attachments:
        if not isinstance(item, Mapping):
            continue
        attachment_id = str(item.get("id") or "").strip()
        if not attachment_id:
            continue
        filename = str(item.get("filename") or "").strip()
        content_type = str(item.get("content_type") or "").strip()
        resolved.append(
            GatewayAttachmentRef(
                attachment_id=attachment_id,
                kind="file",
                platform_fetch_ref=str(item.get("url") or attachment_id),
                metadata={
                    "filename": filename,
                    "content_type": content_type,
                },
            )
        )
    return tuple(resolved)


def _discord_chat_type(payload: Mapping[str, object]) -> str:
    explicit = str(payload.get("chat_type") or "").strip().lower()
    if explicit in {"direct", "channel", "topic"}:
        return explicit
    channel_type = payload.get("channel_type")
    try:
        channel_type_value = int(channel_type) if channel_type is not None else None
    except (TypeError, ValueError):
        channel_type_value = None
    if channel_type_value == 1:
        return "direct"
    if channel_type_value in {10, 11, 12}:
        return "topic"
    if payload.get("thread_id") is not None or payload.get("parent_id") is not None:
        return "topic"
    if payload.get("guild_id") is not None:
        return "channel"
    return "direct"


def _discord_delivery_defaults(chat_type: str) -> tuple[bool, bool, bool]:
    if chat_type == "direct":
        return True, True, False
    return False, False, True


def _discord_body(payload: Mapping[str, object]) -> str:
    content = str(payload.get("content") or "").strip()
    if content:
        return content
    attachments = _discord_attachment_refs(payload.get("attachments"))
    if attachments:
        filenames = [
            str(ref.metadata.get("filename") or "").strip()
            for ref in attachments
            if str(ref.metadata.get("filename") or "").strip()
        ]
        if filenames:
            return f"[attachments] {' '.join(filenames)}"
        return "[attachments]"
    return "discord-message"


_COMMAND_PREFIX_RE = re.compile(
    r"^(?:[$>]\s*)?(?:"
    r"elephant|uv|python(?:3)?|pip|pytest|git|npm|pnpm|yarn|node|bash|sh|zsh|fish|"
    r"cd|ls|cat|echo|cp|mv|rm|mkdir|touch|chmod|chown|grep|rg|sed|awk|curl|wget|"
    r"tar|zip|unzip|docker(?:-compose)?|kubectl|helm|terraform|ansible|make|cmake|"
    r"go|cargo|java|javac|mvn|gradle|poetry|uvicorn|flask|sqlite3|psql|mysql|redis-cli|"
    r"systemctl|journalctl|(?:/[\w./-]+)|(?:\./[\w./-]+)|(?:/[a-z][\w-]*)(?:\s+.+)?"
    r")\b"
)
_LATEX_COMMAND_RE = re.compile(
    r"\\(?:frac|sum|int|sqrt|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|Delta|cdot|times|leq|geq)\b"
)
_CODE_PREFIXES = (
    "def ",
    "class ",
    "import ",
    "from ",
    "async def ",
    "return ",
    "if ",
    "elif ",
    "else:",
    "for ",
    "while ",
    "try:",
    "except ",
    "finally:",
    "with ",
    "const ",
    "let ",
    "var ",
    "function ",
    "interface ",
    "type ",
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "{",
    "[",
    "<",
    "</",
)
_CODE_SIGNAL_RE = re.compile(r"(\b[A-Za-z_][\w.]*\([^\n]*\)|\s:=\s|\s=\s|->|=>|::|\{.*\}|</?[A-Za-z][^>]*>|;\s*$)")


def _is_command_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("```", "- ", "* ", "+ ")):
        return False
    return _COMMAND_PREFIX_RE.match(stripped) is not None


def _is_formula_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _is_command_line(stripped):
        return False
    if stripped.startswith(("$$", "\\(", "\\[", "\\begin{")):
        return True
    if stripped.endswith(("$$", "\\)", "\\]", "\\end{")):
        return True
    if _LATEX_COMMAND_RE.search(stripped):
        return True
    if not re.fullmatch(r"[A-Za-z0-9_(){}\[\] +\-*/=^<>|.,\\]+", stripped):
        return False
    operator_count = len(re.findall(r"[+\-*/=^<>]", stripped))
    if operator_count < 1:
        return False
    alpha_count = sum(character.isalpha() for character in stripped)
    return alpha_count <= max(16, len(stripped) // 2)


def _looks_like_code_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _is_command_line(stripped) or _is_formula_line(stripped):
        return False
    if stripped.startswith(("- ", "* ", "+ ", "> ")):
        return False
    if stripped.startswith(_CODE_PREFIXES):
        return True
    return _CODE_SIGNAL_RE.search(stripped) is not None


def _detect_code_fence_language(lines: list[str]) -> str:
    first = next((line.strip() for line in lines if line.strip()), "")
    if not first:
        return ""
    if _is_command_line(first):
        return "bash"
    if _is_formula_line(first):
        return "tex"
    if first.startswith(("def ", "class ", "import ", "from ", "async def ")):
        return "python"
    if first.startswith(("const ", "let ", "var ", "function ", "interface ", "type ")):
        return "ts"
    if first.startswith(("SELECT ", "INSERT ", "UPDATE ", "DELETE ")):
        return "sql"
    if first.startswith(("{", "[")):
        return "json"
    if first.startswith(("<", "</")):
        return "html"
    return "text"


def _fenced_block(lines: list[str], *, language: str) -> list[str]:
    opening = f"```{language}" if language else "```"
    return [opening, *lines, "```"]


def _wrap_rich_text_block(lines: list[str]) -> list[str]:
    if not lines:
        return []
    meaningful_lines = [line for line in lines if line.strip()]
    if not meaningful_lines:
        return lines
    if all(_is_command_line(line) for line in meaningful_lines):
        return _fenced_block(lines, language="bash")
    if all(_is_formula_line(line) for line in meaningful_lines):
        return _fenced_block(lines, language="tex")
    code_like_lines = [line for line in meaningful_lines if _looks_like_code_line(line)]
    if code_like_lines and (len(meaningful_lines) == 1 or len(code_like_lines) >= max(1, len(meaningful_lines) - 1)):
        return _fenced_block(lines, language=_detect_code_fence_language(meaningful_lines))
    return lines


def _render_rich_text_plain_segment(lines: list[str]) -> list[str]:
    rendered: list[str] = []
    block: list[str] = []

    def flush_block() -> None:
        if not block:
            return
        rendered.extend(_wrap_rich_text_block(block))
        block.clear()

    for raw_line in lines:
        if not raw_line.strip():
            flush_block()
            if rendered and rendered[-1] != "":
                rendered.append("")
            continue
        block.append(raw_line)
    flush_block()
    return rendered


def _render_rich_text_body(body: str) -> str:
    normalized = body.replace("\r\n", "\n")
    if not normalized.strip():
        return normalized
    rendered: list[str] = []
    plain_segment: list[str] = []
    in_fence = False
    for raw_line in normalized.split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            if plain_segment:
                rendered.extend(_render_rich_text_plain_segment(plain_segment))
                plain_segment.clear()
            rendered.append(raw_line)
            in_fence = not in_fence
            continue
        if in_fence:
            rendered.append(raw_line)
            continue
        plain_segment.append(raw_line)
    if plain_segment:
        rendered.extend(_render_rich_text_plain_segment(plain_segment))
    return "\n".join(rendered)


def _discord_reply_request(outbound: GatewayOutboundMessage) -> Mapping[str, object]:
    rendered_body = _render_rich_text_body(outbound.body)
    body: dict[str, object] = {
        "content": rendered_body,
        "allowed_mentions": {"parse": [], "replied_user": False},
    }
    guild_id = str(outbound.metadata.get("guild_id") or "").strip()
    if outbound.reply_to_message_id is not None:
        body["message_reference"] = {
            "message_id": outbound.reply_to_message_id,
            "channel_id": outbound.conversation_id,
        }
        if guild_id:
            body["message_reference"]["guild_id"] = guild_id
    return {
        "method": "POST",
        "path": f"/channels/{outbound.conversation_id}/messages",
        "path_label": "/channels/{channel_id}/messages",
        "channel_id": outbound.conversation_id,
        "guild_id": guild_id,
        "body": body,
    }


def _feishu_sender_user_id(payload: Mapping[str, object]) -> str:
    sender_id = payload.get("sender_id")
    if isinstance(sender_id, Mapping):
        for key in ("open_id", "user_id", "union_id"):
            value = sender_id.get(key)
            if value is not None:
                return str(value)
    for key in ("open_id", "user_id", "union_id"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    raise ValueError("feishu sender payload requires sender_id.open_id, sender_id.user_id, or sender_id.union_id")


def _feishu_display_name(payload: Mapping[str, object]) -> str | None:
    for key in ("name", "display_name", "sender_name"):
        value = payload.get(key)
        if value is not None:
            normalized = str(value).strip()
            if normalized:
                return normalized
    return None


def _feishu_message_content(content: object) -> dict[str, object]:
    if isinstance(content, Mapping):
        return {str(key): value for key, value in content.items()}
    if content is None:
        return {}
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {"raw": content}
        if isinstance(parsed, Mapping):
            return {str(key): value for key, value in parsed.items()}
        return {"raw": content}
    return {"raw": str(content)}


def _feishu_attachment_refs(
    content: Mapping[str, object],
) -> tuple[GatewayAttachmentRef, ...]:
    deduped: dict[str, GatewayAttachmentRef] = {}
    for field_name, kind in (
        ("image_key", "image"),
        ("file_key", "file"),
        ("audio_key", "audio"),
        ("media_key", "media"),
    ):
        value = content.get(field_name)
        if value is None:
            continue
        attachment_id = str(value)
        deduped.setdefault(
            attachment_id,
            GatewayAttachmentRef(
                attachment_id=attachment_id,
                kind=kind,
                platform_fetch_ref=attachment_id,
            ),
        )
    return tuple(deduped.values())


def _feishu_post_rows_text(rows: object) -> str | None:
    if not isinstance(rows, list):
        return None
    rendered_rows: list[str] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        fragments: list[str] = []
        for item in row:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if text is not None:
                fragments.append(str(text))
        if fragments:
            rendered_rows.append("".join(fragments))
    if not rendered_rows:
        return None
    return "\n".join(rendered_rows)


def _feishu_message_body(
    message_type: str,
    content: Mapping[str, object],
) -> str:
    if message_type == "text":
        text = content.get("text")
        if text is not None:
            return str(text)
    if message_type == "post":
        for locale in ("zh_cn", "en_us"):
            locale_payload = content.get(locale)
            if isinstance(locale_payload, Mapping):
                title = str(locale_payload.get("title") or "").strip()
                rows_text = _feishu_post_rows_text(locale_payload.get("content"))
                if title and rows_text:
                    return f"{title}\n{rows_text}"
                if title:
                    return title
                if rows_text:
                    return rows_text
        title = str(content.get("title") or "").strip()
        rows_text = _feishu_post_rows_text(content.get("content"))
        if title and rows_text:
            return f"{title}\n{rows_text}"
        if title:
            return title
        if rows_text:
            return rows_text
    if "text" in content and content["text"] is not None:
        return str(content["text"])
    return f"feishu-{message_type}-message"


def _feishu_extract_title_and_body(body: str) -> tuple[str, str]:
    normalized = body.replace("\r\n", "\n")
    title = "Elephant Agent"
    lines = normalized.split("\n")
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        heading = re.fullmatch(r"#{1,6}\s+(.+)", stripped)
        if heading is not None:
            title = heading.group(1).strip() or title
            lines = [*lines[:index], *lines[index + 1 :]]
            break
        if len(stripped) <= 72 and not re.match(r"^([-*•]|\d+[.)]|`{3}|>)\s*", stripped):
            remaining = [line.strip() for line in lines[index + 1 :] if line.strip()]
            if remaining and re.match(r"^([-*•]|\d+[.)])\s+", remaining[0]):
                title = stripped.rstrip(":：").strip() or title
                lines = [*lines[:index], *lines[index + 1 :]]
            break
        break
    return title, "\n".join(lines).strip() or normalized.strip() or "(empty reply)"


def _feishu_json_v2_markdown_body(body: str) -> str:
    normalized = body.replace("\r\n", "\n")
    language_aliases = {
        "tex": "latex",
        "ts": "typescript",
        "text": "plain_text",
    }
    rendered_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```") and len(stripped) > 3:
            language = stripped[3:].strip().lower()
            mapped = language_aliases.get(language, language)
            rendered_lines.append(f"```{mapped}")
            continue
        rendered_lines.append(raw_line)
    return "\n".join(rendered_lines)


def _feishu_interactive_payload(body: str) -> dict[str, object]:
    title, markdown_body = _feishu_extract_title_and_body(body)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": _feishu_json_v2_markdown_body(markdown_body),
                    "text_align": "left",
                }
            ],
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": title,
            },
            "padding": "12px 12px 12px 12px",
        },
    }


def _feishu_reply_request(outbound: "GatewayOutboundMessage") -> dict[str, object]:
    if not outbound.reply_to_message_id:
        raise ValueError("feishu reply request requires reply_to_message_id")
    rendered_body = _render_rich_text_body(outbound.body)
    delivery_uuid = f"elephant-{hashlib.sha256(outbound.message_id.encode('utf-8')).hexdigest()[:32]}"
    return {
        "method": "POST",
        "path": f"/open-apis/im/v1/messages/{outbound.reply_to_message_id}/reply",
        "body": {
            "content": json.dumps(_feishu_interactive_payload(rendered_body), ensure_ascii=False),
            "msg_type": "interactive",
            "reply_in_thread": outbound.conversation.thread_id is not None,
            "uuid": delivery_uuid,
        },
    }


def _runtime_database_path(state_dir: Path | None) -> Path:
    if state_dir is None:
        return Path(tempfile.mkdtemp(prefix="elephant-gateway-state-")) / "elephant.sqlite3"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "elephant.sqlite3"


__all__ = [
    "CHAT_BOT_ADAPTER_ID",
    "WEBHOOK_ADAPTER_ID",
    "TELEGRAM_ADAPTER_ID",
    "FEISHU_ADAPTER_ID",
    "DISCORD_ADAPTER_ID",
    "DINGDING_ADAPTER_ID",
    "WECOM_ADAPTER_ID",
    "WEIXIN_ADAPTER_ID",
    "_utc_now",
    "_object_map",
    "_string_payload",
    "_account_ref",
    "_conversation_ref",
    "_sender_ref",
    "_attachment_refs",
    "_policy_hint",
    "_normalized_chat_type",
    "_telegram_display_name",
    "_telegram_attachment_ids",
    "_telegram_delivery_defaults",
    "_telegram_conversation_id",
    "_discord_display_name",
    "_discord_attachment_refs",
    "_discord_chat_type",
    "_discord_delivery_defaults",
    "_discord_body",
    "_COMMAND_PREFIX_RE",
    "_LATEX_COMMAND_RE",
    "_CODE_PREFIXES",
    "_CODE_SIGNAL_RE",
    "_is_command_line",
    "_is_formula_line",
    "_looks_like_code_line",
    "_detect_code_fence_language",
    "_fenced_block",
    "_wrap_rich_text_block",
    "_render_rich_text_plain_segment",
    "_render_rich_text_body",
    "_discord_reply_request",
    "_feishu_sender_user_id",
    "_feishu_display_name",
    "_feishu_message_content",
    "_feishu_attachment_refs",
    "_feishu_post_rows_text",
    "_feishu_message_body",
    "_feishu_extract_title_and_body",
    "_feishu_json_v2_markdown_body",
    "_feishu_interactive_payload",
    "_feishu_reply_request",
    "_runtime_database_path",
]
