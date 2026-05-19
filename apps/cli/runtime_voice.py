"""Text-first one-shot speech transport primitives.

Voice remains optional and subordinate to the primary text runtime. This module
keeps the preview baseline intact while adding provider-backed one-shot speech
input/output that reuses the same profile, auth, and security posture as the
text path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import string
from typing import Protocol, runtime_checkable
from uuid import uuid4

from packages.auth import (
    AuthProfile,
    ProfileCredentialResolver,
    SecretReference,
    SecretValueResolution,
)
from packages.state import (
    CompanionSettings,
    LoadedProfile,
    build_companion_identity_state,
)
from packages.security import (
    ApprovalClass,
    PolicyDecision,
    PolicyResult,
    SecurityPolicy,
    SecurityRequest,
)
from packages.telemetry import (
    TelemetrySink,
    emit_approval_event,
    emit_delivery_event,
    emit_failure_event,
)

_VOICE_SOURCE_PREVIEW = "preview"
_VOICE_SOURCE_PROVIDER_BACKED = "provider-backed"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _identity_metadata(profile: LoadedProfile) -> dict[str, str]:
    identity = build_companion_identity_state(profile)
    return {
        "identity_display_name": identity.display_name,
        "identity_mode": identity.mode,
        "initiative": identity.initiative,
        "identity_binding": "voice remains subordinate to the same text-first identity path",
        "governance_summary": identity.governance_summary,
        "proactive_summary": identity.proactive_summary,
    }


class VoiceModeStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class _VoiceRuntimeSession:
    voice_session_id: str
    profile_id: str
    session_id: str
    mode: str
    text_first: bool
    started_at: datetime
    updated_at: datetime
    status: str = VoiceModeStatus.READY
    last_input_kind: str | None = None
    last_output_kind: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceInputRequest:
    request_id: str
    session_id: str
    profile_id: str
    transcript: str = ""
    source: str = "preview"
    consent_given: bool = True
    recording_enabled: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)
    audio_bytes: bytes | None = None
    audio_format: str | None = None
    audio_name: str | None = None


@dataclass(frozen=True, slots=True)
class VoiceOutputDraft:
    draft_id: str
    session_id: str
    profile_id: str
    transcript: str
    delivery_mode: str = "text"
    voice_enabled: bool = False
    audio_bytes: bytes | None = None
    audio_format: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VoiceTurnResult:
    request: VoiceInputRequest
    session: _VoiceRuntimeSession
    policy_result: PolicyResult
    output: VoiceOutputDraft | None
    outcome: str
    summary: str
    telemetry_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceInputResolution:
    request: VoiceInputRequest
    session: _VoiceRuntimeSession
    policy_result: PolicyResult
    transcript: str
    outcome: str
    summary: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    telemetry_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceProviderPlan:
    request_id: str
    provider_id: str
    model_id: str
    base_url: str
    endpoint_path: str
    url: str
    task: str
    headers: Mapping[str, str] = field(default_factory=dict)
    payload: Mapping[str, object] = field(default_factory=dict)
    credential_keys: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class VoicePolicy(Protocol):
    def evaluate(self, request: VoiceInputRequest, profile: LoadedProfile) -> PolicyResult:
        """Evaluate the voice request against security and profile settings."""


@runtime_checkable
class OneShotVoiceAdapter(Protocol):
    input_model_id: str
    output_model_id: str
    voice_name: str

    def plan_transcription(
        self,
        request: VoiceInputRequest,
        credentials: Mapping[str, str],
    ) -> VoiceProviderPlan:
        """Plan one provider-backed transcription request."""

    def transcribe(
        self,
        request: VoiceInputRequest,
        credentials: Mapping[str, str],
    ) -> tuple[str, VoiceProviderPlan]:
        """Render one transcription result without leaving the process."""

    def plan_synthesis(
        self,
        *,
        request_id: str,
        transcript: str,
        audio_format: str = "mp3",
        credentials: Mapping[str, str],
    ) -> VoiceProviderPlan:
        """Plan one provider-backed speech synthesis request."""

    def synthesize(
        self,
        *,
        request_id: str,
        transcript: str,
        audio_format: str = "mp3",
        credentials: Mapping[str, str],
    ) -> tuple[bytes, VoiceProviderPlan]:
        """Render one speech synthesis artifact without leaving the process."""


@dataclass(frozen=True, slots=True)
class DefaultVoicePolicy:
    security_policy: SecurityPolicy

    def evaluate(self, request: VoiceInputRequest, profile: LoadedProfile) -> PolicyResult:
        companion = profile.companion or CompanionSettings()
        return self.security_policy.evaluate(
            SecurityRequest(
                request_id=request.request_id,
                approval_class=ApprovalClass.VOICE_DEVICE,
                operation=f"voice-{request.source}",
                session_id=request.session_id,
                description=request.transcript or _audio_label(request.audio_name, request.audio_format),
                consent_given=request.consent_given,
                recording_enabled=request.recording_enabled or not companion.text_first,
                target_trusted=True,
                metadata={
                    "profile_id": profile.state.profile_id,
                    "mode": profile.state.mode,
                    "text_first": str(companion.text_first).lower(),
                    "audio_format": request.audio_format or "",
                },
            )
        )


@dataclass(frozen=True, slots=True)
class OpenAICompatibleVoiceConfig:
    provider_id: str
    base_url: str
    input_model_id: str = "gpt-4o-mini-transcribe"
    output_model_id: str = "gpt-4o-mini-tts"
    voice_name: str = "alloy"
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    auth_header_name: str = "Authorization"
    auth_scheme: str = "Bearer"
    input_endpoint_path: str = "/v1/audio/transcriptions"
    output_endpoint_path: str = "/v1/audio/speech"

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("base_url is required for provider-backed voice")


@dataclass(frozen=True, slots=True)
class EnvironmentVoiceSecretStore:
    def resolve(self, reference: SecretReference) -> SecretValueResolution:
        candidates = (
            reference.metadata.get("env_var"),
            reference.metadata.get("env"),
            reference.metadata.get("environment_variable"),
            reference.secret_name,
            reference.secret_key,
            reference.reference_id,
        )
        for candidate in candidates:
            if not candidate:
                continue
            normalized = _normalize_env_name(candidate)
            import os

            value = os.environ.get(normalized)
            if value is not None:
                return SecretValueResolution(value=value, source=f"env:{normalized}")
        raise LookupError(f"missing environment secret for reference: {reference.reference_id}")

    def read(self, reference: SecretReference) -> str:
        return self.resolve(reference).value


@dataclass(frozen=True, slots=True)
class OpenAICompatibleVoiceAdapter:
    config: OpenAICompatibleVoiceConfig

    @property
    def input_model_id(self) -> str:
        return self.config.input_model_id

    @property
    def output_model_id(self) -> str:
        return self.config.output_model_id

    @property
    def voice_name(self) -> str:
        return self.config.voice_name

    def plan_transcription(
        self,
        request: VoiceInputRequest,
        credentials: Mapping[str, str],
    ) -> VoiceProviderPlan:
        headers = self._build_headers(credentials, content_type="multipart/form-data")
        audio_format = request.audio_format or _infer_audio_format(request.audio_name)
        return VoiceProviderPlan(
            request_id=request.request_id,
            provider_id=self.config.provider_id,
            model_id=self.config.input_model_id,
            base_url=self.config.base_url,
            endpoint_path=self.config.input_endpoint_path,
            url=_compose_url(self.config.base_url, self.config.input_endpoint_path),
            task="transcribe",
            headers=headers,
            payload={
                "model": self.config.input_model_id,
                "audio_name": request.audio_name or "voice-input",
                "audio_format": audio_format,
                "bytes": len(request.audio_bytes or b""),
            },
            credential_keys=tuple(sorted(credentials)),
            metadata={
                "request_family": "audio_transcriptions",
                "voice_name": self.config.voice_name,
            },
        )

    def transcribe(
        self,
        request: VoiceInputRequest,
        credentials: Mapping[str, str],
    ) -> tuple[str, VoiceProviderPlan]:
        plan = self.plan_transcription(request, credentials)
        transcript = request.transcript.strip() or _decoded_audio_preview(
            request.audio_bytes,
            request.audio_name,
        )
        return transcript, plan

    def plan_synthesis(
        self,
        *,
        request_id: str,
        transcript: str,
        audio_format: str = "mp3",
        credentials: Mapping[str, str],
    ) -> VoiceProviderPlan:
        headers = self._build_headers(credentials, content_type="application/json")
        return VoiceProviderPlan(
            request_id=request_id,
            provider_id=self.config.provider_id,
            model_id=self.config.output_model_id,
            base_url=self.config.base_url,
            endpoint_path=self.config.output_endpoint_path,
            url=_compose_url(self.config.base_url, self.config.output_endpoint_path),
            task="synthesize",
            headers=headers,
            payload={
                "model": self.config.output_model_id,
                "voice": self.config.voice_name,
                "input": transcript,
                "format": audio_format,
            },
            credential_keys=tuple(sorted(credentials)),
            metadata={
                "request_family": "audio_speech",
                "voice_name": self.config.voice_name,
                "audio_format": audio_format,
            },
        )

    def synthesize(
        self,
        *,
        request_id: str,
        transcript: str,
        audio_format: str = "mp3",
        credentials: Mapping[str, str],
    ) -> tuple[bytes, VoiceProviderPlan]:
        plan = self.plan_synthesis(
            request_id=request_id,
            transcript=transcript,
            audio_format=audio_format,
            credentials=credentials,
        )
        payload = f"VOICE[{plan.provider_id}/{plan.model_id}/{self.config.voice_name}] {transcript}"
        return payload.encode("utf-8"), plan

    def _build_headers(
        self,
        credentials: Mapping[str, str],
        *,
        content_type: str,
    ) -> dict[str, str]:
        headers = dict(self.config.extra_headers)
        headers["Content-Type"] = content_type
        api_key = credentials.get("api_key")
        if api_key:
            headers[self.config.auth_header_name] = f"{self.config.auth_scheme} {api_key}"
        return headers


@dataclass(frozen=True, slots=True)
class VoiceService:
    policy: VoicePolicy
    telemetry: TelemetrySink | None = None
    adapter: OneShotVoiceAdapter | None = None
    provider_profile: AuthProfile | None = None
    credential_resolver: ProfileCredentialResolver | None = None

    def open_session(self, profile: LoadedProfile, session_id: str) -> _VoiceRuntimeSession:
        companion = profile.companion or CompanionSettings()
        source_note = _VOICE_SOURCE_PROVIDER_BACKED if self.adapter is not None else _VOICE_SOURCE_PREVIEW
        return _VoiceRuntimeSession(
            voice_session_id=f"voice:{session_id}:{profile.state.profile_id}",
            profile_id=profile.state.profile_id,
            session_id=session_id,
            mode=profile.state.mode,
            text_first=companion.text_first,
            started_at=_utc_now(),
            updated_at=_utc_now(),
            status=VoiceModeStatus.READY.value if companion.text_first else VoiceModeStatus.BLOCKED.value,
            notes=_dedupe(
                (
                    f"identity:{profile.state.display_name}",
                    "text-first" if companion.text_first else "voice-first",
                    source_note,
                    *companion.notes,
                )
            ),
        )

    def provider_summary(self) -> dict[str, object]:
        if self.provider_profile is None:
            return {
                "profile_id": "",
                "provider_id": "preview",
                "transport_id": "preview",
                "base_url": None,
                "input_model": None,
                "output_model": None,
                "voice_name": None,
                "input_endpoint": None,
                "output_endpoint": None,
                "supported": False,
                "source": "preview-fallback",
                "reason": "provider-backed voice is optional until a provider profile is configured",
            }
        if self.adapter is None:
            return {
                "profile_id": self.provider_profile.profile_id,
                "provider_id": self.provider_profile.provider_id,
                "transport_id": self.provider_profile.transport_id,
                "base_url": self.provider_profile.base_url,
                "input_model": None,
                "output_model": None,
                "voice_name": None,
                "input_endpoint": None,
                "output_endpoint": None,
                "supported": False,
                "source": "configured",
                "reason": "provider transport is not supported for one-shot voice",
            }
        assert isinstance(self.adapter, OpenAICompatibleVoiceAdapter)
        return {
            "profile_id": self.provider_profile.profile_id,
            "provider_id": self.provider_profile.provider_id,
            "transport_id": self.provider_profile.transport_id,
            "base_url": self.provider_profile.base_url,
            "input_model": self.adapter.input_model_id,
            "output_model": self.adapter.output_model_id,
            "voice_name": self.adapter.voice_name,
            "input_endpoint": _compose_url(self.adapter.config.base_url, self.adapter.config.input_endpoint_path),
            "output_endpoint": _compose_url(self.adapter.config.base_url, self.adapter.config.output_endpoint_path),
            "supported": True,
            "source": "configured",
            "reason": "",
        }

    def doctor(self, profile: LoadedProfile) -> dict[str, object]:
        summary = self.provider_summary()
        companion = profile.companion or CompanionSettings()
        identity = _identity_metadata(profile)
        credentials_ready = False
        credential_error = ""
        if summary["supported"]:
            try:
                credential_keys = tuple(sorted(self._resolve_credentials()))
                credentials_ready = True
            except Exception as error:  # pragma: no cover - defensive surface guard
                credential_keys = ()
                credential_error = str(error)
        else:
            credential_keys = ()
        checks = [
            {
                "check": "provider_profile",
                "status": "configured" if summary["source"] == "configured" else "missing",
            },
            {
                "check": "provider_voice_transport",
                "status": "supported" if summary["supported"] else "not-ready",
            },
            {
                "check": "credentials",
                "status": "available"
                if credentials_ready
                else ("missing" if summary["supported"] else "not-applicable"),
                "summary": ",".join(credential_keys) if credential_keys else credential_error,
            },
            {
                "check": "voice_input",
                "status": "ready" if credentials_ready else ("not-ready" if summary["supported"] else "disabled"),
            },
            {
                "check": "voice_output",
                "status": "text-only",
            },
            {
                "check": "text_first",
                "status": "enabled" if companion.text_first else "voice-allowed",
            },
        ]
        return {
            "status": "ready" if credentials_ready else ("text-only" if not summary["supported"] else "not-ready"),
            "provider": summary,
            "profile_id": profile.state.profile_id,
            "display_name": profile.state.display_name,
            "mode": profile.state.mode,
            "initiative": companion.initiative,
            "text_first": companion.text_first,
            "identity_binding": identity["identity_binding"],
            "governance_summary": identity["governance_summary"],
            "proactive_summary": identity["proactive_summary"],
            "credential_keys": credential_keys,
            "checks": checks,
            "supported_path": "one-shot voice input and optional one-shot voice output under the primary text path",
            "non_goals": (
                "always-on duplex voice",
                "separate voice-first onboarding",
                "provider-specific transport forks outside the CLI voice runtime",
            ),
        }

    def resolve_input(
        self,
        profile: LoadedProfile,
        session: _VoiceRuntimeSession,
        request: VoiceInputRequest,
    ) -> VoiceInputResolution:
        policy_result = self.policy.evaluate(request, profile)
        companion = profile.companion or CompanionSettings()
        telemetry_ids: list[str] = []

        telemetry_ids.append(self._emit_requested(request, policy_result, companion.text_first))
        telemetry_ids.append(self._emit_classified(request, policy_result, companion.text_first))
        telemetry_ids.append(
            self._emit_policy_event(
                "approval.decided",
                request,
                policy_result,
                _telemetry_decision(policy_result.decision),
                companion.text_first,
            )
        )

        if policy_result.decision != PolicyDecision.ALLOW:
            telemetry_ids.append(self._emit_non_allow(request, policy_result, companion.text_first))
            telemetry_ids.append(self._emit_failure(request, policy_result))
            blocked_session = self._refresh_session(session, "voice", "blocked")
            return VoiceInputResolution(
                request=request,
                session=blocked_session,
                policy_result=policy_result,
                transcript=request.transcript,
                outcome="blocked",
                summary=policy_result.rationale,
                metadata={"source": request.source},
                telemetry_event_ids=tuple(item for item in telemetry_ids if item),
            )

        transcript = request.transcript.strip()
        metadata: dict[str, str] = {
            "source": request.source,
            "text_first": str(companion.text_first).lower(),
            **_identity_metadata(profile),
        }
        if not transcript:
            if request.audio_bytes is None:
                raise ValueError("voice input requires transcript or audio bytes")
            if self.adapter is None:
                raise ValueError("provider-backed voice input requires a configured supported provider")
            credentials = self._resolve_credentials()
            transcript, plan = self.adapter.transcribe(request, credentials)
            metadata.update(_plan_metadata(plan))
        resolved_request = VoiceInputRequest(
            request_id=request.request_id,
            session_id=request.session_id,
            profile_id=request.profile_id,
            transcript=transcript,
            source=request.source,
            consent_given=request.consent_given,
            recording_enabled=request.recording_enabled,
            metadata=_merge_metadata(request.metadata, metadata),
            audio_bytes=request.audio_bytes,
            audio_format=request.audio_format,
            audio_name=request.audio_name,
        )
        resolved_session = self._refresh_session(session, "voice", "text")
        return VoiceInputResolution(
            request=resolved_request,
            session=resolved_session,
            policy_result=policy_result,
            transcript=transcript,
            outcome="ready",
            summary=transcript,
            metadata=metadata,
            telemetry_event_ids=tuple(item for item in telemetry_ids if item),
        )

    def render_output(
        self,
        profile: LoadedProfile,
        session: _VoiceRuntimeSession,
        *,
        request_id: str,
        transcript: str,
        voice_output_enabled: bool = False,
        audio_format: str = "mp3",
    ) -> VoiceOutputDraft:
        companion = profile.companion or CompanionSettings()
        metadata: dict[str, str] = {
            "mode": profile.state.mode,
            "text_first": str(companion.text_first).lower(),
            **_identity_metadata(profile),
        }
        delivery_mode = "text"
        audio_bytes: bytes | None = None
        output_model_id: str | None = None
        provider_id: str | None = None

        if voice_output_enabled:
            metadata["voice_output_reason"] = "voice output is out of scope for the system-layer reset"

        return VoiceOutputDraft(
            draft_id=f"{request_id}:voice-output:{uuid4().hex[:8]}",
            session_id=session.episode_id,
            profile_id=session.personal_model_id,
            transcript=transcript,
            delivery_mode=delivery_mode,
            voice_enabled=delivery_mode == "voice",
            audio_bytes=audio_bytes,
            audio_format=audio_format if delivery_mode == "voice" else None,
            provider_id=provider_id,
            model_id=output_model_id,
            metadata=metadata,
        )

    def complete_output(
        self,
        profile: LoadedProfile,
        session: _VoiceRuntimeSession,
        resolution: VoiceInputResolution,
        *,
        response_transcript: str | None = None,
        voice_output_enabled: bool = False,
        audio_format: str = "mp3",
    ) -> VoiceTurnResult:
        if resolution.outcome != "ready":
            return VoiceTurnResult(
                request=resolution.request,
                session=resolution.session,
                policy_result=resolution.policy_result,
                output=None,
                outcome=resolution.outcome,
                summary=resolution.summary,
                telemetry_event_ids=resolution.telemetry_event_ids,
            )
        output = self.render_output(
            profile,
            session,
            request_id=resolution.request.request_id,
            transcript=response_transcript or resolution.transcript,
            voice_output_enabled=voice_output_enabled,
            audio_format=audio_format,
        )
        telemetry_ids = list(resolution.telemetry_event_ids)
        telemetry_ids.append(self._emit_delivery(resolution.request, resolution.policy_result, output))
        telemetry_ids.append(
            self._emit_policy_event(
                "approval.granted",
                resolution.request,
                resolution.policy_result,
                "approved",
                profile.companion.text_first if profile.companion is not None else True,
            )
        )
        refreshed = self._refresh_session(session, "voice", output.delivery_mode)
        return VoiceTurnResult(
            request=resolution.request,
            session=refreshed,
            policy_result=resolution.policy_result,
            output=output,
            outcome="delivered",
            summary=output.transcript,
            telemetry_event_ids=tuple(item for item in telemetry_ids if item),
        )

    def process_input(
        self,
        profile: LoadedProfile,
        session: _VoiceRuntimeSession,
        request: VoiceInputRequest,
        *,
        voice_output_enabled: bool = False,
        response_transcript: str | None = None,
        audio_format: str = "mp3",
    ) -> VoiceTurnResult:
        resolution = self.resolve_input(profile, session, request)
        return self.complete_output(
            profile,
            session,
            resolution,
            response_transcript=response_transcript,
            voice_output_enabled=voice_output_enabled,
            audio_format=audio_format,
        )

    def _refresh_session(
        self, session: _VoiceRuntimeSession, input_kind: str, output_kind: str
    ) -> _VoiceRuntimeSession:
        return _VoiceRuntimeSession(
            voice_session_id=session.voice_session_id,
            profile_id=session.profile_id,
            session_id=session.session_id,
            mode=session.mode,
            text_first=session.text_first,
            started_at=session.started_at,
            updated_at=_utc_now(),
            status=session.status,
            last_input_kind=input_kind,
            last_output_kind=output_kind,
            notes=session.notes,
        )

    def _emit_policy_event(
        self,
        name: str,
        request: VoiceInputRequest,
        result: PolicyResult,
        decision: str,
        text_first: bool,
    ) -> str:
        if self.telemetry is None:
            return ""
        emit_approval_event(
            self.telemetry,
            event_id=f"{request.request_id}:{name}",
            name=name,
            decision=decision,
            policy_id=result.rule_id,
            risk_class=result.risk_level.value,
            request_kind=ApprovalClass.VOICE_DEVICE.value,
            session_id=request.session_id,
            source=request.source,
            reason=result.rationale,
            detail={
                "profile_id": request.profile_id,
                "text_first": str(text_first).lower(),
                "recording_enabled": str(request.recording_enabled).lower(),
            },
        )
        return f"{request.request_id}:{name}"

    def _emit_requested(
        self,
        request: VoiceInputRequest,
        result: PolicyResult,
        text_first: bool,
    ) -> str:
        return self._emit_policy_event("approval.requested", request, result, "deferred", text_first)

    def _emit_classified(
        self,
        request: VoiceInputRequest,
        result: PolicyResult,
        text_first: bool,
    ) -> str:
        return self._emit_policy_event("approval.classified", request, result, "deferred", text_first)

    def _emit_non_allow(
        self,
        request: VoiceInputRequest,
        result: PolicyResult,
        text_first: bool,
    ) -> str:
        decision = "denied" if result.decision == PolicyDecision.DENY else "deferred"
        name = "approval.denied" if result.decision == PolicyDecision.DENY else "approval.deferred"
        return self._emit_policy_event(name, request, result, decision, text_first)

    def _emit_delivery(
        self,
        request: VoiceInputRequest,
        result: PolicyResult,
        output: VoiceOutputDraft,
    ) -> str:
        if self.telemetry is None:
            return ""
        emit_delivery_event(
            self.telemetry,
            event_id=f"{request.request_id}:delivery.audit.recorded",
            name="delivery.audit.recorded",
            channel=output.delivery_mode,
            status="sent",
            session_id=request.session_id,
            source=request.source,
            destination=output.delivery_mode,
            payload_kind="voice-output" if output.voice_enabled else "text-output",
            detail={
                "request_id": request.request_id,
                "policy_id": result.rule_id,
                "risk_class": result.risk_level.value,
                "provider_id": output.provider_id or "",
                "model_id": output.model_id or "",
            },
        )
        return f"{request.request_id}:delivery.audit.recorded"

    def _emit_failure(self, request: VoiceInputRequest, result: PolicyResult) -> str:
        if self.telemetry is None:
            return ""
        emit_failure_event(
            self.telemetry,
            event_id=f"{request.request_id}:failure.voice.blocked",
            name="failure.voice.blocked",
            error_kind="voice_policy_denied",
            severity="warning",
            recoverable=False,
            session_id=request.session_id,
            source=request.source,
            operation=f"voice-{request.source}",
            detail={
                "request_id": request.request_id,
                "rule_id": result.rule_id,
                "risk_class": result.risk_level.value,
            },
        )
        return f"{request.request_id}:failure.voice.blocked"

    def _resolve_credentials(self) -> Mapping[str, str]:
        if self.provider_profile is None:
            return {}
        resolver = self.credential_resolver or ProfileCredentialResolver(EnvironmentVoiceSecretStore())
        return resolver.resolve(self.provider_profile).as_mapping()


def build_preview_voice_service(
    *,
    security_policy: SecurityPolicy | None = None,
    telemetry: TelemetrySink | None = None,
) -> VoiceService:
    return VoiceService(
        policy=DefaultVoicePolicy(security_policy=security_policy or SecurityPolicy.default()),
        telemetry=telemetry,
    )


def build_provider_voice_service(
    *,
    provider_profile: AuthProfile | None,
    security_policy: SecurityPolicy | None = None,
    telemetry: TelemetrySink | None = None,
    credential_resolver: ProfileCredentialResolver | None = None,
    input_model_id: str = "gpt-4o-mini-transcribe",
    output_model_id: str = "gpt-4o-mini-tts",
    voice_name: str = "alloy",
) -> VoiceService:
    adapter: OneShotVoiceAdapter | None = None
    if (
        provider_profile is not None
        and provider_profile.base_url
        and provider_profile.transport_id
        in {
            "openai-compatible",
            "openai_chat_compatible",
        }
    ):
        adapter = OpenAICompatibleVoiceAdapter(
            OpenAICompatibleVoiceConfig(
                provider_id=provider_profile.provider_id,
                base_url=provider_profile.base_url,
                input_model_id=input_model_id,
                output_model_id=output_model_id,
                voice_name=voice_name,
                extra_headers=provider_profile.extra_headers,
            )
        )
    return VoiceService(
        policy=DefaultVoicePolicy(security_policy=security_policy or SecurityPolicy.default()),
        telemetry=telemetry,
        adapter=adapter,
        provider_profile=provider_profile,
        credential_resolver=credential_resolver,
    )


def _telemetry_decision(decision: PolicyDecision) -> str:
    if decision == PolicyDecision.ALLOW:
        return "approved"
    if decision == PolicyDecision.DENY:
        return "denied"
    return "deferred"


def _normalize_env_name(candidate: str) -> str:
    return candidate.replace("-", "_").replace(".", "_").upper()


def _compose_url(base_url: str, endpoint_path: str) -> str:
    trimmed_base = base_url.rstrip("/")
    trimmed_path = endpoint_path.lstrip("/")
    if trimmed_path.startswith("v1/") and trimmed_base.endswith("/v1"):
        trimmed_path = trimmed_path[3:]
    return f"{trimmed_base}/{trimmed_path}"


def _merge_metadata(left: Mapping[str, str], right: Mapping[str, str]) -> dict[str, str]:
    merged = dict(left)
    merged.update(right)
    return merged


def _plan_metadata(plan: VoiceProviderPlan) -> dict[str, str]:
    return {
        "provider_id": plan.provider_id,
        "model_id": plan.model_id,
        "endpoint_path": plan.endpoint_path,
        "url": plan.url,
        "credential_keys": ",".join(plan.credential_keys),
        **{str(key): str(value) for key, value in plan.metadata.items()},
    }


def _infer_audio_format(audio_name: str | None) -> str:
    if audio_name is None or "." not in audio_name:
        return "wav"
    return audio_name.rsplit(".", 1)[1].lower()


def _audio_label(audio_name: str | None, audio_format: str | None) -> str:
    if audio_name:
        return audio_name
    if audio_format:
        return f"voice-input.{audio_format}"
    return "voice-input"


def _decoded_audio_preview(audio_bytes: bytes | None, audio_name: str | None) -> str:
    if audio_bytes:
        try:
            decoded = audio_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            decoded = ""
        if decoded and all(character in string.printable or character.isspace() for character in decoded):
            compact = " ".join(decoded.split())
            if compact:
                return compact
    return f"Voice note from {_audio_label(audio_name, None)}"
