#!/usr/bin/env python3
"""Telephony helper for the Elephant Agent telephony skill.

Capabilities:
- Persist telephony provider credentials to ~/.elephant/.env
- Search for, buy, and remember Twilio phone numbers
- Make direct Twilio calls (TwiML <Say> or <Play>)
- Send SMS / MMS via Twilio
- Poll inbound SMS for an owned Twilio number using only this script + state
- Import a Twilio number into Vapi and persist the returned Vapi phone_number_id
- Make outbound AI voice calls via Bland.ai or Vapi

This file intentionally uses Python stdlib HTTP clients so the skill can run in a
minimal environment with no extra pip installs.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from dataclasses import dataclass
from html import escape as xml_escape
from pathlib import Path
from typing import Any

try:
    from .telephony_admin import (
        _ai_provider,
        _bland_api_key,
        _remember_twilio_number,
        _remember_vapi_number,
        _vapi_api_key,
        _vapi_phone_number_id,
        BLAND_DEFAULT_MODEL,
        BLAND_DEFAULT_VOICE,
        VAPI_DEFAULT_MODEL,
        VAPI_DEFAULT_VOICE_ID,
        VAPI_DEFAULT_VOICE_PROVIDER,
        diagnose,
        save_bland,
        save_twilio,
        save_vapi,
    )
    from .telephony_support import (
        _env_or_config,
        _json_request,
        _load_state,
        _mask_phone,
        _normalize_phone,
        _parse_twilio_date,
        _save_state,
        _state_path,
        TelephonyError,
    )
except ImportError:
    from telephony_admin import (
        _ai_provider,
        _bland_api_key,
        _remember_twilio_number,
        _remember_vapi_number,
        _vapi_api_key,
        _vapi_phone_number_id,
        BLAND_DEFAULT_MODEL,
        BLAND_DEFAULT_VOICE,
        VAPI_DEFAULT_MODEL,
        VAPI_DEFAULT_VOICE_ID,
        VAPI_DEFAULT_VOICE_PROVIDER,
        diagnose,
        save_bland,
        save_twilio,
        save_vapi,
    )
    from telephony_support import (
        _env_or_config,
        _json_request,
        _load_state,
        _mask_phone,
        _normalize_phone,
        _save_state,
        _state_path,
        TelephonyError,
    )

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01/Accounts"
VAPI_API_BASE = "https://api.vapi.ai"
BLAND_API_BASE = "https://api.bland.ai/v1"
TWILIO_DEFAULT_TTS_VOICE = "Polly.Joanna"


@dataclass
class OwnedTwilioNumber:
    sid: str
    phone_number: str
    friendly_name: str
    capabilities: dict[str, Any]


def _twilio_creds() -> tuple[str, str]:
    sid = _env_or_config(
        "TWILIO_ACCOUNT_SID",
        ("telephony", "twilio", "account_sid"),
        ("phone", "twilio", "account_sid"),
    )
    token = _env_or_config(
        "TWILIO_AUTH_TOKEN",
        ("telephony", "twilio", "auth_token"),
        ("phone", "twilio", "auth_token"),
    )
    if not sid or not token:
        raise TelephonyError(
            "Twilio credentials are not configured. Use 'save-twilio' or set "
            "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in ~/.elephant/.env."
        )
    return sid, token


def _twilio_basic_headers() -> dict[str, str]:
    sid, token = _twilio_creds()
    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {auth}"}


def _twilio_request(method: str, path: str, *, params=None, form=None) -> dict[str, Any]:
    sid, _token = _twilio_creds()
    return _json_request(
        method,
        f"{TWILIO_API_BASE}/{sid}/{path.lstrip('/')}",
        headers=_twilio_basic_headers(),
        params=params,
        form=form,
    )


def _twilio_owned_numbers(limit: int = 50) -> list[OwnedTwilioNumber]:
    payload = _twilio_request("GET", "IncomingPhoneNumbers.json", params={"PageSize": limit})
    items = payload.get("incoming_phone_numbers", []) or []
    results: list[OwnedTwilioNumber] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        results.append(
            OwnedTwilioNumber(
                sid=str(item.get("sid", "")),
                phone_number=str(item.get("phone_number", "")),
                friendly_name=str(item.get("friendly_name", "")),
                capabilities=caps,
            )
        )
    return results


def _resolve_twilio_number(identifier: str | None = None) -> OwnedTwilioNumber:
    if identifier:
        wanted = identifier.strip()
        normalized = None
        if wanted.startswith("+"):
            normalized = _normalize_phone(wanted)
        for item in _twilio_owned_numbers(limit=100):
            if item.sid == wanted or item.phone_number == normalized:
                return item
        raise TelephonyError(f"Could not find an owned Twilio number matching {identifier}")

    env_number = _env_or_config(
        "TWILIO_PHONE_NUMBER",
        ("telephony", "twilio", "phone_number"),
        ("phone", "twilio", "phone_number"),
    )
    env_sid = _env_or_config(
        "TWILIO_PHONE_NUMBER_SID",
        ("telephony", "twilio", "phone_number_sid"),
        ("phone", "twilio", "phone_number_sid"),
    )
    state = _load_state()
    twilio_state = state.get("twilio", {}) if isinstance(state.get("twilio"), dict) else {}
    preferred_number = env_number or str(twilio_state.get("default_phone_number", ""))
    preferred_sid = env_sid or str(twilio_state.get("default_phone_sid", ""))

    owned = _twilio_owned_numbers(limit=100)
    if preferred_sid:
        for item in owned:
            if item.sid == preferred_sid:
                return item
    if preferred_number:
        normalized = _normalize_phone(preferred_number)
        for item in owned:
            if item.phone_number == normalized:
                return item
    if len(owned) == 1:
        return owned[0]

    raise TelephonyError(
        "No default Twilio phone number is set. Use 'twilio-buy --save-env', "
        "'twilio-set-default', or set TWILIO_PHONE_NUMBER in ~/.elephant/.env."
    )


def _twilio_search_numbers(
    *,
    country: str = "US",
    area_code: str | None = None,
    contains: str | None = None,
    limit: int = 10,
    sms_enabled: bool = True,
    voice_enabled: bool = True,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "PageSize": max(1, min(limit, 20)),
        "SmsEnabled": str(bool(sms_enabled)).lower(),
        "VoiceEnabled": str(bool(voice_enabled)).lower(),
    }
    if area_code:
        params["AreaCode"] = str(area_code)
    if contains:
        params["Contains"] = str(contains)

    payload = _twilio_request(
        "GET",
        f"AvailablePhoneNumbers/{country.upper()}/Local.json",
        params=params,
    )
    items = payload.get("available_phone_numbers", []) or []
    return {
        "success": True,
        "country": country.upper(),
        "count": len(items),
        "numbers": [
            {
                "phone_number": item.get("phone_number"),
                "friendly_name": item.get("friendly_name"),
                "locality": item.get("locality"),
                "region": item.get("region"),
                "postal_code": item.get("postal_code"),
                "iso_country": item.get("iso_country"),
                "capabilities": {
                    "voice": item.get("voice_enabled"),
                    "sms": item.get("sms_enabled"),
                    "mms": item.get("mms_enabled"),
                },
            }
            for item in items
            if isinstance(item, dict)
        ],
    }


def _twilio_buy_number(
    phone_number: str,
    *,
    save_env: bool = False,
    state_path: Path | None = None,
    env_path: Path | None = None,
) -> dict[str, Any]:
    normalized = _normalize_phone(phone_number)
    payload = _twilio_request("POST", "IncomingPhoneNumbers.json", form={"PhoneNumber": normalized})
    purchased = {
        "success": True,
        "provider": "twilio",
        "phone_number": payload.get("phone_number", normalized),
        "phone_sid": payload.get("sid"),
        "friendly_name": payload.get("friendly_name"),
        "capabilities": payload.get("capabilities", {}),
        "message": "Twilio number purchased successfully.",
    }
    purchased.update(
        _remember_twilio_number(
            phone_number=str(purchased["phone_number"]),
            phone_sid=str(purchased.get("phone_sid") or ""),
            save_env=save_env,
            state_path=state_path,
            env_path=env_path,
        )
    )
    return purchased


def _twilio_list_owned() -> dict[str, Any]:
    owned = _twilio_owned_numbers(limit=100)
    return {
        "success": True,
        "provider": "twilio",
        "count": len(owned),
        "numbers": [
            {
                "phone_number": item.phone_number,
                "phone_sid": item.sid,
                "friendly_name": item.friendly_name,
                "capabilities": item.capabilities,
            }
            for item in owned
        ],
    }


def _twilio_set_default(identifier: str, *, save_env: bool = False) -> dict[str, Any]:
    owned = _resolve_twilio_number(identifier)
    result = {
        "success": True,
        "provider": "twilio",
        "phone_number": owned.phone_number,
        "phone_sid": owned.sid,
        "message": "Default Twilio number updated.",
    }
    result.update(
        _remember_twilio_number(
            phone_number=owned.phone_number,
            phone_sid=owned.sid,
            save_env=save_env,
        )
    )
    return result


def _twiml_say(message: str, voice: str) -> str:
    return f'<Response><Say voice="{xml_escape(voice)}">{xml_escape(message)}</Say></Response>'


def _twiml_play(audio_url: str) -> str:
    return f"<Response><Play>{xml_escape(audio_url)}</Play></Response>"


def _twilio_call(
    to_number: str,
    *,
    message: str | None = None,
    audio_url: str | None = None,
    voice: str = TWILIO_DEFAULT_TTS_VOICE,
    send_digits: str | None = None,
    from_identifier: str | None = None,
    record: bool = False,
) -> dict[str, Any]:
    destination = _normalize_phone(to_number)
    source = _resolve_twilio_number(from_identifier)
    if bool(message) == bool(audio_url):
        raise TelephonyError("Provide exactly one of 'message' or 'audio_url' for twilio-call")

    twiml = _twiml_play(audio_url) if audio_url else _twiml_say(message or "", voice)
    form: dict[str, Any] = {
        "To": destination,
        "From": source.phone_number,
        "Twiml": twiml,
    }
    if send_digits:
        form["SendDigits"] = send_digits
    if record:
        form["Record"] = "true"

    payload = _twilio_request("POST", "Calls.json", form=form)
    return {
        "success": True,
        "provider": "twilio",
        "call_sid": payload.get("sid"),
        "status": payload.get("status"),
        "from_phone_number": source.phone_number,
        "to_phone_number_masked": _mask_phone(destination),
        "mode": "play" if audio_url else "say",
        "recording_requested": record,
        "message": "Twilio call initiated.",
    }


def _twilio_call_status(call_sid: str) -> dict[str, Any]:
    payload = _twilio_request("GET", f"Calls/{call_sid}.json")
    return {
        "success": True,
        "provider": "twilio",
        "call_sid": payload.get("sid"),
        "status": payload.get("status"),
        "direction": payload.get("direction"),
        "duration": payload.get("duration"),
        "from_phone_number": payload.get("from"),
        "to_phone_number_masked": _mask_phone(str(payload.get("to") or "")),
        "start_time": payload.get("start_time"),
        "end_time": payload.get("end_time"),
        "answered_by": payload.get("answered_by"),
    }


def _twilio_send_sms(
    to_number: str,
    body: str,
    *,
    media_urls: list[str] | None = None,
    from_identifier: str | None = None,
) -> dict[str, Any]:
    destination = _normalize_phone(to_number)
    source = _resolve_twilio_number(from_identifier)
    if not body.strip():
        raise TelephonyError("SMS body cannot be empty")
    form: dict[str, Any] = {
        "To": destination,
        "From": source.phone_number,
        "Body": body,
    }
    if media_urls:
        form["MediaUrl"] = media_urls
    payload = _twilio_request("POST", "Messages.json", form=form)
    return {
        "success": True,
        "provider": "twilio",
        "message_sid": payload.get("sid"),
        "status": payload.get("status"),
        "from_phone_number": source.phone_number,
        "to_phone_number_masked": _mask_phone(destination),
        "media_count": len(media_urls or []),
        "message": "SMS/MMS queued via Twilio.",
    }


def _checkpoint_for_messages(messages: list[dict[str, Any]]) -> tuple[str, str]:
    if not messages:
        return "", ""
    newest = messages[0]
    return str(newest.get("sid") or ""), str(newest.get("date_sent") or newest.get("date_created") or "")


def _messages_after_checkpoint(messages: list[dict[str, Any]], last_sid: str) -> list[dict[str, Any]]:
    if not last_sid:
        return messages
    filtered: list[dict[str, Any]] = []
    for message in messages:
        if str(message.get("sid") or "") == last_sid:
            break
        filtered.append(message)
    return filtered


def _twilio_inbox(
    *,
    limit: int = 20,
    since_last: bool = False,
    mark_seen: bool = False,
    phone_identifier: str | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    owned = _resolve_twilio_number(phone_identifier)
    payload = _twilio_request(
        "GET",
        "Messages.json",
        params={"To": owned.phone_number, "PageSize": max(1, min(limit, 100))},
    )
    raw_messages = payload.get("messages", []) or []
    messages = [m for m in raw_messages if isinstance(m, dict)]

    state = _load_state(state_path)
    twilio_state = state.setdefault("twilio", {})
    last_sid = str(twilio_state.get("last_inbound_message_sid", ""))
    if since_last:
        messages = _messages_after_checkpoint(messages, last_sid)

    message_rows = [
        {
            "sid": msg.get("sid"),
            "direction": msg.get("direction"),
            "status": msg.get("status"),
            "from_phone_number": msg.get("from"),
            "to_phone_number": msg.get("to"),
            "date_sent": msg.get("date_sent"),
            "body": msg.get("body"),
            "num_media": msg.get("num_media"),
        }
        for msg in messages
    ]

    if mark_seen and message_rows:
        last_seen_sid, last_seen_date = _checkpoint_for_messages(message_rows)
        twilio_state["last_inbound_message_sid"] = last_seen_sid
        twilio_state["last_inbound_message_date"] = last_seen_date
        _save_state(state, state_path)

    return {
        "success": True,
        "provider": "twilio",
        "phone_number": owned.phone_number,
        "count": len(message_rows),
        "messages": message_rows,
        "since_last": since_last,
        "marked_seen": bool(mark_seen and message_rows),
        "state_path": str(state_path or _state_path()),
        "last_seen_message_sid": twilio_state.get("last_inbound_message_sid", ""),
    }


def _vapi_import_twilio_number(
    *,
    phone_identifier: str | None = None,
    save_env: bool = False,
    state_path: Path | None = None,
    env_path: Path | None = None,
) -> dict[str, Any]:
    api_key = _vapi_api_key()
    if not api_key:
        raise TelephonyError("Vapi is not configured. Use 'save-vapi' or set VAPI_API_KEY in ~/.elephant/.env first.")
    owned = _resolve_twilio_number(phone_identifier)
    sid, token = _twilio_creds()
    payload = _json_request(
        "POST",
        f"{VAPI_API_BASE}/phone-number",
        headers={"Authorization": f"Bearer {api_key}"},
        json_body={
            "provider": "twilio",
            "number": owned.phone_number,
            "twilioAccountSid": sid,
            "twilioAuthToken": token,
        },
    )
    phone_number_id = str(payload.get("id") or "")
    if not phone_number_id:
        raise TelephonyError(f"Vapi did not return a phone number id: {payload}")
    result = {
        "success": True,
        "provider": "vapi",
        "phone_number_id": phone_number_id,
        "phone_number": owned.phone_number,
        "message": "Twilio number imported into Vapi.",
    }
    result.update(
        _remember_vapi_number(
            phone_number_id=phone_number_id,
            save_env=save_env,
            state_path=state_path,
            env_path=env_path,
        )
    )
    return result


def _bland_call(
    phone_number: str,
    task: str,
    *,
    voice: str | None = None,
    first_sentence: str | None = None,
    max_duration: int = 3,
) -> dict[str, Any]:
    api_key = _bland_api_key()
    if not api_key:
        raise TelephonyError("Bland.ai is not configured. Use 'save-bland' or set BLAND_API_KEY in ~/.elephant/.env.")
    normalized = _normalize_phone(phone_number)
    if voice is None:
        voice = _env_or_config(
            "BLAND_DEFAULT_VOICE",
            ("telephony", "bland", "default_voice"),
            ("phone", "bland", "default_voice"),
            default=BLAND_DEFAULT_VOICE,
        )
    payload = _json_request(
        "POST",
        f"{BLAND_API_BASE}/calls",
        headers={"authorization": api_key},
        json_body={
            "phone_number": normalized,
            "task": task,
            "voice": voice,
            "model": BLAND_DEFAULT_MODEL,
            "max_duration": max_duration,
            "record": True,
            "wait_for_greeting": True,
            **({"first_sentence": first_sentence} if first_sentence else {}),
        },
    )
    call_id = str(payload.get("call_id") or "")
    if not call_id:
        raise TelephonyError(f"Bland.ai returned no call_id: {payload}")
    return {
        "success": True,
        "provider": "bland",
        "call_id": call_id,
        "voice": voice,
        "max_duration_minutes": max_duration,
        "to_phone_number_masked": _mask_phone(normalized),
        "message": "AI call queued with Bland.ai.",
    }


def _bland_status(call_id: str, analyze: str | None = None) -> dict[str, Any]:
    api_key = _bland_api_key()
    if not api_key:
        raise TelephonyError("Bland.ai is not configured.")
    payload = _json_request("GET", f"{BLAND_API_BASE}/calls/{call_id}", headers={"authorization": api_key})
    result = {
        "success": True,
        "provider": "bland",
        "call_id": call_id,
        "status": payload.get("status"),
        "answered_by": payload.get("answered_by"),
        "duration_minutes": payload.get("call_length"),
        "transcript": payload.get("concatenated_transcript", ""),
        "recording_url": payload.get("recording_url"),
    }
    if analyze and payload.get("status") == "completed":
        questions = [[q.strip(), "string"] for q in analyze.split(",") if q.strip()]
        if questions:
            analysis = _json_request(
                "POST",
                f"{BLAND_API_BASE}/calls/{call_id}/analyze",
                headers={"authorization": api_key},
                json_body={"questions": questions},
            )
            result["analysis"] = analysis
    return result


def _vapi_call(
    phone_number: str,
    task: str,
    *,
    voice_id: str | None = None,
    first_sentence: str | None = None,
    max_duration: int = 3,
) -> dict[str, Any]:
    api_key = _vapi_api_key()
    if not api_key:
        raise TelephonyError("Vapi is not configured. Use 'save-vapi' or set VAPI_API_KEY in ~/.elephant/.env.")
    phone_number_id = _vapi_phone_number_id()
    if not phone_number_id:
        raise TelephonyError(
            "No Vapi phone number id is configured. Import an owned Twilio number with "
            "'vapi-import-twilio --save-env' or set VAPI_PHONE_NUMBER_ID in ~/.elephant/.env."
        )
    normalized = _normalize_phone(phone_number)
    voice_provider = _env_or_config(
        "VAPI_VOICE_PROVIDER",
        ("telephony", "vapi", "default_voice_provider"),
        ("phone", "vapi", "default_voice_provider"),
        default=VAPI_DEFAULT_VOICE_PROVIDER,
    )
    if voice_id is None:
        voice_id = _env_or_config(
            "VAPI_VOICE_ID",
            ("telephony", "vapi", "default_voice_id"),
            ("phone", "vapi", "default_voice_id"),
            default=VAPI_DEFAULT_VOICE_ID,
        )
    model = _env_or_config(
        "VAPI_MODEL",
        ("telephony", "vapi", "model"),
        ("phone", "vapi", "model"),
        default=VAPI_DEFAULT_MODEL,
    )
    assistant = {
        "model": {
            "provider": "openai",
            "model": model,
            "messages": [{"role": "system", "content": task}],
        },
        "voice": {"provider": voice_provider, "voiceId": voice_id},
        "maxDurationSeconds": max_duration * 60,
    }
    if first_sentence:
        assistant["firstMessage"] = first_sentence
    payload = _json_request(
        "POST",
        f"{VAPI_API_BASE}/call",
        headers={"Authorization": f"Bearer {api_key}"},
        json_body={
            "phoneNumberId": phone_number_id,
            "customer": {"number": normalized},
            "assistant": assistant,
        },
    )
    call_id = str(payload.get("id") or "")
    if not call_id:
        raise TelephonyError(f"Vapi returned no call id: {payload}")
    return {
        "success": True,
        "provider": "vapi",
        "call_id": call_id,
        "voice_provider": voice_provider,
        "voice_id": voice_id,
        "max_duration_minutes": max_duration,
        "to_phone_number_masked": _mask_phone(normalized),
        "message": "AI call queued with Vapi.",
    }


def _vapi_status(call_id: str) -> dict[str, Any]:
    api_key = _vapi_api_key()
    if not api_key:
        raise TelephonyError("Vapi is not configured.")
    payload = _json_request(
        "GET",
        f"{VAPI_API_BASE}/call/{call_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return {
        "success": True,
        "provider": "vapi",
        "call_id": call_id,
        "status": payload.get("status"),
        "duration_seconds": payload.get("duration"),
        "ended_reason": payload.get("endedReason"),
        "transcript": payload.get("transcript", ""),
        "recording_url": payload.get("recordingUrl"),
        "summary": payload.get("summary"),
        "cost": payload.get("cost"),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Elephant Agent telephony helper")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("diagnose", help="Show saved telephony state and provider readiness")

    p = sub.add_parser("save-twilio", help="Save Twilio credentials to ~/.elephant/.env")
    p.add_argument("account_sid")
    p.add_argument("auth_token")
    p.add_argument("--phone-number", default="")
    p.add_argument("--phone-sid", default="")

    p = sub.add_parser("save-bland", help="Save Bland.ai settings to ~/.elephant/.env")
    p.add_argument("api_key")
    p.add_argument("--voice", default=BLAND_DEFAULT_VOICE)

    p = sub.add_parser("save-vapi", help="Save Vapi settings to ~/.elephant/.env")
    p.add_argument("api_key")
    p.add_argument("--phone-number-id", default="")
    p.add_argument("--voice-provider", default=VAPI_DEFAULT_VOICE_PROVIDER)
    p.add_argument("--voice-id", default=VAPI_DEFAULT_VOICE_ID)
    p.add_argument("--model", default=VAPI_DEFAULT_MODEL)

    p = sub.add_parser("twilio-search", help="Search Twilio numbers available for purchase")
    p.add_argument("--country", default="US")
    p.add_argument("--area-code", default="")
    p.add_argument("--contains", default="")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--sms-enabled", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--voice-enabled", action=argparse.BooleanOptionalAction, default=True)

    p = sub.add_parser("twilio-buy", help="Buy a Twilio phone number")
    p.add_argument("phone_number")
    p.add_argument("--save-env", action="store_true")

    sub.add_parser("twilio-owned", help="List Twilio numbers already owned by the account")

    p = sub.add_parser("twilio-set-default", help="Remember one owned Twilio number as the default")
    p.add_argument("identifier", help="Owned phone number in E.164 or Twilio phone SID")
    p.add_argument("--save-env", action="store_true")

    p = sub.add_parser("twilio-call", help="Place a direct Twilio call")
    p.add_argument("to_number")
    p.add_argument("--message", default="")
    p.add_argument("--audio-url", default="")
    p.add_argument("--voice", default=TWILIO_DEFAULT_TTS_VOICE)
    p.add_argument("--send-digits", default="")
    p.add_argument("--from-number", default="")
    p.add_argument("--record", action="store_true")

    p = sub.add_parser("twilio-call-status", help="Check a Twilio call status")
    p.add_argument("call_sid")

    p = sub.add_parser("twilio-send-sms", help="Send SMS or MMS via Twilio")
    p.add_argument("to_number")
    p.add_argument("body")
    p.add_argument("--media-url", action="append", default=[])
    p.add_argument("--from-number", default="")

    p = sub.add_parser(
        "twilio-inbox",
        help="Poll inbound SMS for the default or specified Twilio number",
    )
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--since-last", action="store_true")
    p.add_argument("--mark-seen", action="store_true")
    p.add_argument("--phone-number", default="")

    p = sub.add_parser("vapi-import-twilio", help="Import an owned Twilio number into Vapi")
    p.add_argument("--phone-number", default="")
    p.add_argument("--save-env", action="store_true")

    p = sub.add_parser("ai-call", help="Place an outbound AI voice call via Bland.ai or Vapi")
    p.add_argument("to_number")
    p.add_argument("task")
    p.add_argument("--provider", choices=["bland", "vapi"], default="")
    p.add_argument("--voice", default="")
    p.add_argument("--first-sentence", default="")
    p.add_argument("--max-duration", type=int, default=3)

    p = sub.add_parser("ai-status", help="Check an AI call status via Bland.ai or Vapi")
    p.add_argument("call_id")
    p.add_argument("--provider", choices=["bland", "vapi"], default="")
    p.add_argument("--analyze", default="")

    return parser


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    cmd = args.command
    if cmd == "diagnose":
        return diagnose()
    if cmd == "save-twilio":
        return save_twilio(
            args.account_sid,
            args.auth_token,
            phone_number=args.phone_number,
            phone_sid=args.phone_sid,
        )
    if cmd == "save-bland":
        return save_bland(args.api_key, voice=args.voice)
    if cmd == "save-vapi":
        return save_vapi(
            args.api_key,
            phone_number_id=args.phone_number_id,
            voice_provider=args.voice_provider,
            voice_id=args.voice_id,
            model=args.model,
        )
    if cmd == "twilio-search":
        return _twilio_search_numbers(
            country=args.country,
            area_code=args.area_code or None,
            contains=args.contains or None,
            limit=args.limit,
            sms_enabled=args.sms_enabled,
            voice_enabled=args.voice_enabled,
        )
    if cmd == "twilio-buy":
        return _twilio_buy_number(args.phone_number, save_env=args.save_env)
    if cmd == "twilio-owned":
        return _twilio_list_owned()
    if cmd == "twilio-set-default":
        return _twilio_set_default(args.identifier, save_env=args.save_env)
    if cmd == "twilio-call":
        return _twilio_call(
            args.to_number,
            message=args.message or None,
            audio_url=args.audio_url or None,
            voice=args.voice,
            send_digits=args.send_digits or None,
            from_identifier=args.from_number or None,
            record=args.record,
        )
    if cmd == "twilio-call-status":
        return _twilio_call_status(args.call_sid)
    if cmd == "twilio-send-sms":
        return _twilio_send_sms(
            args.to_number,
            args.body,
            media_urls=args.media_url or None,
            from_identifier=args.from_number or None,
        )
    if cmd == "twilio-inbox":
        return _twilio_inbox(
            limit=args.limit,
            since_last=args.since_last,
            mark_seen=args.mark_seen,
            phone_identifier=args.phone_number or None,
        )
    if cmd == "vapi-import-twilio":
        return _vapi_import_twilio_number(
            phone_identifier=args.phone_number or None,
            save_env=args.save_env,
        )
    if cmd == "ai-call":
        provider = (args.provider or _ai_provider()).lower().strip()
        if provider == "vapi":
            return _vapi_call(
                args.to_number,
                args.task,
                voice_id=args.voice or None,
                first_sentence=args.first_sentence or None,
                max_duration=args.max_duration,
            )
        if provider == "bland":
            return _bland_call(
                args.to_number,
                args.task,
                voice=args.voice or None,
                first_sentence=args.first_sentence or None,
                max_duration=args.max_duration,
            )
        raise TelephonyError(
            f"Unsupported AI call provider '{provider}'. Use --provider bland or --provider vapi, "
            "or set PHONE_PROVIDER in ~/.elephant/.env."
        )
    if cmd == "ai-status":
        provider = (args.provider or _ai_provider()).lower().strip()
        if provider == "vapi":
            return _vapi_status(args.call_id)
        if provider == "bland":
            return _bland_status(args.call_id, analyze=args.analyze or None)
        raise TelephonyError(
            f"Unsupported AI call provider '{provider}'. Use --provider bland or --provider vapi, "
            "or set PHONE_PROVIDER in ~/.elephant/.env."
        )
    raise TelephonyError(f"Unknown command: {cmd}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except TelephonyError as exc:
        print(
            json.dumps({"success": False, "error": str(exc)}, indent=2, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
