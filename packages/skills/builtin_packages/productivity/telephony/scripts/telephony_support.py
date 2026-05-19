"""Shared support helpers for the telephony skill script."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

STATE_VERSION = 1


class TelephonyError(RuntimeError):
    """Domain-specific failure surfaced to the skill/user."""


def _elephant_home() -> Path:
    return Path(os.environ.get("EGGON_HOME", "~/.elephant")).expanduser()


def _env_path() -> Path:
    return _elephant_home() / ".env"


def _config_path() -> Path:
    return _elephant_home() / "config.yaml"


def _state_path() -> Path:
    return _elephant_home() / "telephony_state.json"


def _load_root_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        import yaml  # optional dependency; Elephant Agent already ships PyYAML
    except Exception:
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _config_lookup(*paths: tuple[str, ...], default: str = "") -> str:
    root = _load_root_config()
    for path in paths:
        node: Any = root
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if node not in (None, "") and not isinstance(node, dict):
            return str(node)
    return default


def _load_dotenv_values(path: Path | None = None) -> dict[str, str]:
    env_file = path or _env_path()
    if not env_file.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = raw_line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        values[key] = value
    return values


def _env_or_config(env_key: str, *config_paths: tuple[str, ...], default: str = "") -> str:
    value = os.environ.get(env_key, "")
    if value:
        return value
    dotenv_value = _load_dotenv_values().get(env_key, "")
    if dotenv_value:
        return dotenv_value
    return _config_lookup(*config_paths, default=default)


def _load_state(path: Path | None = None) -> dict[str, Any]:
    state_file = path or _state_path()
    if not state_file.exists():
        return {"version": STATE_VERSION}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("version", STATE_VERSION)
            return data
    except Exception:
        pass
    return {"version": STATE_VERSION}


def _save_state(state: dict[str, Any], path: Path | None = None) -> Path:
    state_file = path or _state_path()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state_file


def _quote_env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+@-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _upsert_env_file(updates: dict[str, str], env_path: Path | None = None) -> Path:
    path = env_path or _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, _, _rest = line.partition("=")
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={_quote_env_value(str(updates[key]))}")
            seen.add(key)
        else:
            new_lines.append(line)

    if new_lines and new_lines[-1].strip():
        new_lines.append("")
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={_quote_env_value(str(value))}")

    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    return path


def _normalize_phone(number: str) -> str:
    if not number:
        raise TelephonyError("Phone number is required")
    trimmed = number.strip()
    if not trimmed.startswith("+"):
        raise TelephonyError(f"Phone number must be E.164 format (for example +15551234567), got: {number}")
    digits = "+" + re.sub(r"\D", "", trimmed)
    if len(digits) < 8:
        raise TelephonyError(f"Phone number looks too short: {number}")
    return digits


def _mask_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number or "")
    if len(digits) < 4:
        return "***"
    return f"***-***-{digits[-4:]}"


def _parse_twilio_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _json_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"

    request_headers = dict(headers or {})
    body: bytes | None = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    req = urllib.request.Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(body_text) if body_text else {}
        except Exception:
            parsed = {"raw": body_text}
        raise TelephonyError(f"HTTP {exc.code} from {url}: {parsed or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise TelephonyError(f"Connection error for {url}: {exc.reason}") from exc
