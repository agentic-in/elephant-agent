"""Configuration and diagnostic helpers for the telephony skill script."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .telephony_support import (
        _env_or_config,
        _env_path,
        _load_state,
        _normalize_phone,
        _save_state,
        _state_path,
        _upsert_env_file,
    )
except ImportError:
    from telephony_support import (
        _env_or_config,
        _env_path,
        _load_state,
        _normalize_phone,
        _save_state,
        _state_path,
        _upsert_env_file,
    )

BLAND_DEFAULT_VOICE = "mason"
BLAND_DEFAULT_MODEL = "enhanced"
BLAND_VOICES = {
    "mason": "Male, natural, friendly (recommended)",
    "josh": "Male, conversational",
    "ryan": "Male, professional",
    "matt": "Male, casual",
    "evelyn": "Female, natural, warm (recommended)",
    "tina": "Female, warm, friendly",
    "june": "Female, conversational",
}
VAPI_DEFAULT_VOICE_PROVIDER = "11labs"
VAPI_DEFAULT_VOICE_ID = "cjVigY5qzO86Huf0OWal"
VAPI_DEFAULT_MODEL = "gpt-4o"
DEFAULT_AI_PROVIDER = "bland"


def _remember_twilio_number(
    *,
    phone_number: str,
    phone_sid: str = "",
    save_env: bool = False,
    state_path: Path | None = None,
    env_path: Path | None = None,
) -> dict[str, Any]:
    state = _load_state(state_path)
    twilio_state = state.setdefault("twilio", {})
    twilio_state["default_phone_number"] = phone_number
    if phone_sid:
        twilio_state["default_phone_sid"] = phone_sid
    _save_state(state, state_path)

    saved_env_keys: list[str] = []
    if save_env:
        updates = {"TWILIO_PHONE_NUMBER": phone_number}
        if phone_sid:
            updates["TWILIO_PHONE_NUMBER_SID"] = phone_sid
        _upsert_env_file(updates, env_path)
        saved_env_keys = sorted(updates)

    return {
        "state_path": str(state_path or _state_path()),
        "saved_env_keys": saved_env_keys,
    }


def _remember_vapi_number(
    *,
    phone_number_id: str,
    save_env: bool = False,
    state_path: Path | None = None,
    env_path: Path | None = None,
) -> dict[str, Any]:
    state = _load_state(state_path)
    vapi_state = state.setdefault("vapi", {})
    vapi_state["phone_number_id"] = phone_number_id
    _save_state(state, state_path)

    saved_env_keys: list[str] = []
    if save_env:
        _upsert_env_file({"VAPI_PHONE_NUMBER_ID": phone_number_id}, env_path)
        saved_env_keys = ["VAPI_PHONE_NUMBER_ID"]

    return {
        "state_path": str(state_path or _state_path()),
        "saved_env_keys": saved_env_keys,
    }


def _vapi_api_key() -> str:
    return _env_or_config(
        "VAPI_API_KEY",
        ("telephony", "vapi", "api_key"),
        ("phone", "vapi", "api_key"),
    )


def _vapi_phone_number_id() -> str:
    state = _load_state()
    vapi_state = state.get("vapi", {}) if isinstance(state.get("vapi"), dict) else {}
    return _env_or_config(
        "VAPI_PHONE_NUMBER_ID",
        ("telephony", "vapi", "phone_number_id"),
        ("phone", "vapi", "phone_number_id"),
        default=str(vapi_state.get("phone_number_id", "")),
    )


def _bland_api_key() -> str:
    return _env_or_config(
        "BLAND_API_KEY",
        ("telephony", "bland", "api_key"),
        ("phone", "bland", "api_key"),
    )


def _ai_provider(default: str = DEFAULT_AI_PROVIDER) -> str:
    return (
        _env_or_config(
            "PHONE_PROVIDER",
            ("telephony", "provider"),
            ("phone", "provider"),
            default=default,
        )
        .lower()
        .strip()
    )


def _provider_decision_tree() -> list[dict[str, str]]:
    return [
        {
            "need": "I want the agent to own a real number for SMS, inbound polling, or future telephony identity.",
            "use": "Twilio",
            "why": "Twilio is the clearest path to provisioning numbers, sending SMS/MMS, polling inbound texts, and later webhook-based inbound telephony.",
        },
        {
            "need": "I only want the easiest outbound AI voice calls right now.",
            "use": "Bland.ai",
            "why": "Bland is the simplest outbound AI calling setup: one API key, no separate number import flow.",
        },
        {
            "need": "I want premium conversational voice quality for AI calls, ideally on my own number.",
            "use": "Twilio + Vapi",
            "why": "Buy/import the number with Twilio, then import it into Vapi for better voices and more flexible assistants.",
        },
        {
            "need": "I want to call with a prerecorded/custom voice message generated elsewhere.",
            "use": "Twilio direct call + public audio URL",
            "why": "Generate or host audio separately, then let Twilio play it with a simple outbound call.",
        },
    ]


def diagnose() -> dict[str, Any]:
    state = _load_state()
    twilio_state = state.get("twilio", {}) if isinstance(state.get("twilio"), dict) else {}
    vapi_state = state.get("vapi", {}) if isinstance(state.get("vapi"), dict) else {}
    provider = _ai_provider()

    twilio_sid = _env_or_config(
        "TWILIO_ACCOUNT_SID",
        ("telephony", "twilio", "account_sid"),
        ("phone", "twilio", "account_sid"),
    )
    twilio_token = _env_or_config(
        "TWILIO_AUTH_TOKEN",
        ("telephony", "twilio", "auth_token"),
        ("phone", "twilio", "auth_token"),
    )
    twilio_phone = _env_or_config(
        "TWILIO_PHONE_NUMBER",
        ("telephony", "twilio", "phone_number"),
        ("phone", "twilio", "phone_number"),
        default=str(twilio_state.get("default_phone_number", "")),
    )

    bland_key = _bland_api_key()
    vapi_key = _vapi_api_key()
    vapi_phone_id = _vapi_phone_number_id() or str(vapi_state.get("phone_number_id", ""))

    return {
        "success": True,
        "state_path": str(_state_path()),
        "env_path": str(_env_path()),
        "ai_call_provider": provider,
        "providers": {
            "twilio": {
                "account_sid_configured": bool(twilio_sid),
                "auth_token_configured": bool(twilio_token),
                "default_phone_number": twilio_phone,
                "default_phone_sid": twilio_state.get("default_phone_sid", ""),
                "last_inbound_message_sid": twilio_state.get("last_inbound_message_sid", ""),
                "last_inbound_message_date": twilio_state.get("last_inbound_message_date", ""),
            },
            "bland": {
                "configured": bool(bland_key),
                "default_voice": _env_or_config(
                    "BLAND_DEFAULT_VOICE",
                    ("telephony", "bland", "default_voice"),
                    ("phone", "bland", "default_voice"),
                    default=BLAND_DEFAULT_VOICE,
                ),
            },
            "vapi": {
                "configured": bool(vapi_key),
                "phone_number_id": vapi_phone_id,
                "voice_provider": _env_or_config(
                    "VAPI_VOICE_PROVIDER",
                    ("telephony", "vapi", "default_voice_provider"),
                    ("phone", "vapi", "default_voice_provider"),
                    default=VAPI_DEFAULT_VOICE_PROVIDER,
                ),
                "voice_id": _env_or_config(
                    "VAPI_VOICE_ID",
                    ("telephony", "vapi", "default_voice_id"),
                    ("phone", "vapi", "default_voice_id"),
                    default=VAPI_DEFAULT_VOICE_ID,
                ),
                "model": _env_or_config(
                    "VAPI_MODEL",
                    ("telephony", "vapi", "model"),
                    ("phone", "vapi", "model"),
                    default=VAPI_DEFAULT_MODEL,
                ),
            },
        },
        "decision_tree": _provider_decision_tree(),
        "notes": [
            "Twilio is the best path for owning a durable phone number, texting, and polling inbound SMS.",
            "Bland is the easiest path for outbound AI calls only.",
            "Vapi is best when you want better AI voice quality, usually backed by a Twilio-owned number.",
            "VoIP numbers are not guaranteed to work for every third-party 2FA flow.",
        ],
    }


def save_twilio(account_sid: str, auth_token: str, phone_number: str = "", phone_sid: str = "") -> dict[str, Any]:
    updates = {
        "TWILIO_ACCOUNT_SID": account_sid.strip(),
        "TWILIO_AUTH_TOKEN": auth_token.strip(),
    }
    if phone_number:
        updates["TWILIO_PHONE_NUMBER"] = _normalize_phone(phone_number)
    if phone_sid:
        updates["TWILIO_PHONE_NUMBER_SID"] = phone_sid.strip()
    env_file = _upsert_env_file(updates)
    result = {
        "success": True,
        "provider": "twilio",
        "saved_env_keys": sorted(updates),
        "env_path": str(env_file),
        "message": "Twilio credentials saved to ~/.elephant/.env.",
    }
    if phone_number:
        result.update(
            _remember_twilio_number(
                phone_number=updates["TWILIO_PHONE_NUMBER"],
                phone_sid=phone_sid.strip(),
                save_env=False,
            )
        )
    return result


def save_bland(api_key: str, voice: str = BLAND_DEFAULT_VOICE) -> dict[str, Any]:
    env_file = _upsert_env_file(
        {
            "BLAND_API_KEY": api_key.strip(),
            "BLAND_DEFAULT_VOICE": voice.strip() or BLAND_DEFAULT_VOICE,
            "PHONE_PROVIDER": "bland",
        }
    )
    return {
        "success": True,
        "provider": "bland",
        "saved_env_keys": ["BLAND_API_KEY", "BLAND_DEFAULT_VOICE", "PHONE_PROVIDER"],
        "env_path": str(env_file),
        "message": "Bland.ai configuration saved to ~/.elephant/.env.",
    }


def save_vapi(
    api_key: str,
    *,
    phone_number_id: str = "",
    voice_provider: str = VAPI_DEFAULT_VOICE_PROVIDER,
    voice_id: str = VAPI_DEFAULT_VOICE_ID,
    model: str = VAPI_DEFAULT_MODEL,
) -> dict[str, Any]:
    updates = {
        "VAPI_API_KEY": api_key.strip(),
        "VAPI_VOICE_PROVIDER": voice_provider.strip() or VAPI_DEFAULT_VOICE_PROVIDER,
        "VAPI_VOICE_ID": voice_id.strip() or VAPI_DEFAULT_VOICE_ID,
        "VAPI_MODEL": model.strip() or VAPI_DEFAULT_MODEL,
        "PHONE_PROVIDER": "vapi",
    }
    if phone_number_id:
        updates["VAPI_PHONE_NUMBER_ID"] = phone_number_id.strip()
    env_file = _upsert_env_file(updates)
    result = {
        "success": True,
        "provider": "vapi",
        "saved_env_keys": sorted(updates),
        "env_path": str(env_file),
        "message": "Vapi configuration saved to ~/.elephant/.env.",
    }
    if phone_number_id:
        result.update(_remember_vapi_number(phone_number_id=phone_number_id.strip(), save_env=False))
    return result
