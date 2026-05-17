"""Global Elephant Agent runtime configuration stored as a small YAML document."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
import json
from typing import Any

from packages.runtime_layout import infer_install_root_from_state_dir


GLOBAL_CONFIG_FILENAME = "config.yaml"
DEFAULT_EXTERNAL_SKILL_DIRS: tuple[str, ...] = ("~/.agents/skills",)
_MISSING = object()

def default_personal_model_question_config() -> dict[str, Any]:
    return {
        "proactive_ask": {
            "enabled": True,
            "idle_threshold_minutes": 180,
            "daily_max": 8,
            "quiet_hours": [23, 7],
        },
    }


def personal_model_question_config_from_global(config: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        return default_personal_model_question_config()
    questions = config.get("personal_model_questions")
    if not isinstance(questions, Mapping):
        questions = {}
    return _deep_merge(default_personal_model_question_config(), questions)


def global_config_path_for_state_dir(state_dir: str | Path) -> Path:
    install_root = infer_install_root_from_state_dir(Path(state_dir))
    return install_root / GLOBAL_CONFIG_FILENAME



def default_global_config(*, state_dir: str | Path) -> dict[str, Any]:
    resolved_state_dir = Path(state_dir)
    return {
        "runtime": {
            "state_dir": str(resolved_state_dir),
            "default_profile_id": "default",
        },
        "models": {
            "default_provider_source": "config",
            "provider": None,
        },
        "sessions": {
            "persist_system_prompts": True,
            "persist_assistant_responses": True,
            "max_history_rows": 200,
        },
        "skills": {
            "enable_profile_overrides": True,
            "external_dirs": list(DEFAULT_EXTERNAL_SKILL_DIRS),
        },
        "tools": {
            "require_approval_for_risky": True,
        },
        "gateway": {
            "enabled": False,
            "state_dir": str(resolved_state_dir),
        },
        "dashboard": {
            "host": "127.0.0.1",
            "port": 4174,
        },
        "personal_model": {
            "first_language": "en",
        },
        "personal_model_questions": default_personal_model_question_config(),
        "observability": {
            "enabled": True,
            "log_level": "INFO",
            "log_file": "",
            "otel_endpoint": "",
            "service_name": "elephant-agent",
        },
        "extensions": {},
    }


def global_config_schema() -> list[dict[str, Any]]:
    return [
        {"path": "runtime.state_dir", "type": "string", "label": "Elephant directory", "section": "Runtime"},
        {"path": "runtime.default_profile_id", "type": "string", "label": "Default profile", "section": "Runtime"},
        {"path": "models.default_provider_source", "type": "string", "label": "Provider source", "section": "Models"},
        {"path": "models.provider", "type": "object", "label": "Provider profile", "section": "Models"},
        {"path": "sessions.persist_system_prompts", "type": "boolean", "label": "Persist system prompts", "section": "Sessions"},
        {"path": "sessions.persist_assistant_responses", "type": "boolean", "label": "Persist assistant responses", "section": "Sessions"},
        {"path": "sessions.max_history_rows", "type": "number", "label": "Max history rows", "section": "Sessions"},
        {"path": "skills.enable_profile_overrides", "type": "boolean", "label": "Skill profile overrides", "section": "Skills"},
        {"path": "skills.external_dirs", "type": "string_list", "label": "External skill dirs", "section": "Skills"},
        {"path": "tools.require_approval_for_risky", "type": "boolean", "label": "Approval for risky tools", "section": "Tools"},
        {"path": "gateway.enabled", "type": "boolean", "label": "Gateway enabled", "section": "Gateway"},
        {"path": "gateway.state_dir", "type": "string", "label": "Gateway herd directory", "section": "Gateway"},
        {"path": "dashboard.host", "type": "string", "label": "Dashboard host", "section": "Dashboard"},
        {"path": "dashboard.port", "type": "number", "label": "Dashboard port", "section": "Dashboard"},
        {"path": "personal_model.first_language", "type": "string", "label": "First language", "section": "Personal Model"},
        {"path": "personal_model_questions.proactive_ask.enabled", "type": "boolean", "label": "Proactive asks enabled", "section": "Personal Model"},
        {"path": "personal_model_questions.proactive_ask.idle_threshold_minutes", "type": "number", "label": "Idle threshold (minutes)", "section": "Personal Model"},
        {"path": "personal_model_questions.proactive_ask.daily_max", "type": "number", "label": "Daily max questions", "section": "Personal Model"},
        {"path": "personal_model_questions.proactive_ask.quiet_hours", "type": "string_list", "label": "Quiet hours [start, end]", "section": "Personal Model"},
        {"path": "observability.enabled", "type": "boolean", "label": "Observability enabled", "section": "Observability"},
        {"path": "observability.log_level", "type": "string", "label": "Log level", "section": "Observability"},
        {"path": "observability.log_file", "type": "string", "label": "Log file path", "section": "Observability"},
        {"path": "observability.otel_endpoint", "type": "string", "label": "OTLP endpoint", "section": "Observability"},
        {"path": "observability.service_name", "type": "string", "label": "Service name", "section": "Observability"},
    ]


def load_global_config(
    path: str | Path,
    *,
    state_dir: str | Path,
) -> dict[str, Any]:
    defaults = default_global_config(state_dir=state_dir)
    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError:
        return defaults
    loaded = parse_global_config_text(raw)
    if not isinstance(loaded, Mapping):
        return defaults
    return _without_removed_reset_keys(_deep_merge(defaults, loaded))


def read_global_config_text(path: str | Path, *, fallback: Mapping[str, Any]) -> str:
    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError:
        return serialize_global_config(fallback)
    parsed = parse_global_config_text(raw)
    if not isinstance(parsed, Mapping):
        return serialize_global_config(fallback)
    return serialize_global_config(_without_removed_reset_keys(parsed))


def write_global_config(path: str | Path, config: Mapping[str, Any]) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(serialize_global_config(_without_removed_reset_keys(config)), encoding="utf-8")


def parse_global_config_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("config JSON must be an object")
        return parsed
    return _parse_simple_yaml(stripped)


def serialize_global_config(config: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _write_yaml_mapping(lines, config, indent=0)
    return "\n".join(lines).rstrip() + "\n"


def default_external_skill_dirs() -> tuple[str, ...]:
    return DEFAULT_EXTERNAL_SKILL_DIRS


def configured_external_skill_dirs(config: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(config, Mapping):
        return DEFAULT_EXTERNAL_SKILL_DIRS
    skills = config.get("skills")
    if not isinstance(skills, Mapping):
        return DEFAULT_EXTERNAL_SKILL_DIRS
    raw = skills.get("external_dirs", _MISSING)
    if raw is _MISSING:
        return DEFAULT_EXTERNAL_SKILL_DIRS
    if raw is None:
        return ()
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return ()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, list):
                raw = parsed
            else:
                return tuple(item.strip() for item in stripped.replace("\n", ",").split(",") if item.strip())
        else:
            return tuple(item.strip() for item in stripped.replace("\n", ",").split(",") if item.strip())
    if isinstance(raw, (list, tuple, set)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    text = str(raw).strip()
    return (text,) if text else ()


def _without_removed_reset_keys(config: Mapping[str, Any]) -> dict[str, Any]:
    """Legacy function for backward compatibility. No longer removes any fields."""
    return dict(config)


def load_provider_from_config(config: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract the provider profile payload from global config."""
    models = config.get("models")
    if not isinstance(models, Mapping):
        return None
    provider = models.get("provider")
    if not isinstance(provider, Mapping):
        return None
    return dict(provider)


def save_provider_to_config(
    config_path: str | Path,
    *,
    state_dir: str | Path,
    provider_payload: Mapping[str, Any],
) -> None:
    """Write the provider profile into the global config file."""
    config = load_global_config(config_path, state_dir=state_dir)
    models = config.get("models")
    if not isinstance(models, dict):
        models = {}
    models["provider"] = dict(provider_payload)
    models["default_provider_source"] = "config"
    config["models"] = models
    write_global_config(config_path, config)


def load_extensions_from_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the extensions section from global config."""
    extensions = config.get("extensions")
    if not isinstance(extensions, Mapping):
        return {}
    return dict(extensions)


def save_extensions_to_config(
    config_path: str | Path,
    *,
    state_dir: str | Path,
    extensions: Mapping[str, Any],
) -> None:
    """Write the extensions section into the global config file."""
    config = load_global_config(config_path, state_dir=state_dir)
    config["extensions"] = dict(extensions)
    write_global_config(config_path, config)


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = deepcopy(dict(base))
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        if ":" not in line_without_comment:
            raise ValueError(f"invalid YAML line: {raw_line}")
        key, raw_value = _split_key_value(line_without_comment.lstrip(" "))
        key = _parse_key(key)
        if not key:
            raise ValueError(f"invalid YAML key: {raw_line}")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"invalid YAML indentation: {raw_line}")
        parent = stack[-1][1]
        value_text = raw_value.strip()
        if value_text == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value_text)
    return root


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith(("{", "[")):
        return json.loads(value)
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _write_yaml_mapping(lines: list[str], mapping: Mapping[str, Any], *, indent: int) -> None:
    prefix = " " * indent
    for key, value in mapping.items():
        rendered_key = _format_key(key)
        if isinstance(value, Mapping):
            lines.append(f"{prefix}{rendered_key}:")
            _write_yaml_mapping(lines, value, indent=indent + 2)
        elif isinstance(value, list):
            lines.append(f"{prefix}{rendered_key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{prefix}{rendered_key}: {_format_scalar(value)}")


def _split_key_value(line: str) -> tuple[str, str]:
    in_single = False
    in_double = False
    escape = False
    for index, character in enumerate(line):
        if escape:
            escape = False
            continue
        if character == "\\" and in_double:
            escape = True
            continue
        if character == '"' and not in_single:
            in_double = not in_double
            continue
        if character == "'" and not in_double:
            in_single = not in_single
            continue
        if character == ":" and not in_single and not in_double:
            return line[:index], line[index + 1 :]
    raise ValueError(f"invalid YAML line: {line}")


def _parse_key(value: str) -> str:
    text = value.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return _parse_scalar(text)
    return text


def _format_key(value: Any) -> str:
    text = str(value)
    if not text or any(character in text for character in (":", "#", "{", "}", "[", "]", "\n", " ")):
        return json.dumps(text, ensure_ascii=False)
    return text


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text or any(character in text for character in (":", "#", "{", "}", "[", "]", "\n")):
        return json.dumps(text, ensure_ascii=False)
    return text
