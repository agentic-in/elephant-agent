"""Provider, security, and voice surfaces for the CLI runtime."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from apps.provider_runtime import capture_runtime_secret_env, provider_profile_from_payload
from packages.continuity import RelationshipPolicy, build_relationship_policy
from packages.auth import AuthProfile, SecretReference
from packages.embeddings import (
    ELEPHANT_EMBED_DEFAULT_DIMENSIONS,
    ELEPHANT_EMBED_MODEL_ID,
    ELEPHANT_EMBED_PROVIDER_ID,
    ELEPHANT_EMBED_PROVIDER_KIND,
    OPENAI_COMPATIBLE_EMBED_DEFAULT_SECRET_ENV_VAR,
    OPENAI_COMPATIBLE_EMBED_PROFILE_ID,
    OPENAI_COMPATIBLE_EMBED_PROVIDER_ID,
    OPENAI_COMPATIBLE_EMBED_SECRET_REFERENCE_ID,
    default_local_embedding_provider_config,
)
from packages.contracts.layers import Episode
from packages.contracts.runtime import ExecutionResult, PersonalModelRuntimeState
from packages.models.provider_catalog import provider_definition
from packages.models.provider_runtime import ProviderCatalogRecord, ProviderSetupGuide
from packages.security import SecurityPolicy, default_surface_policy_bundles
from packages.state import CompanionSettings, LoadedProfile, normalize_profile_mode
from packages.state.loader import companion_manifest_payload
from .runtime_voice import VoiceInputRequest, build_provider_voice_service

from .runtime_cognition import _CliContextCapability
from .runtime_extensions import _PreviewTelemetrySink
from .runtime_support import CliVoiceTurnResult, _PLACEHOLDER_MODELS_BY_PROVIDER, _iso, _utc_now

_EMBEDDING_API_KEY_ENV_VAR = OPENAI_COMPATIBLE_EMBED_DEFAULT_SECRET_ENV_VAR
_EMBEDDING_API_KEY_REFERENCE_ID = OPENAI_COMPATIBLE_EMBED_SECRET_REFERENCE_ID

class CliRuntimeProviderMixin:
    def provider_summary(self) -> Mapping[str, object]:
        return self.model_provider.describe()

    def provider_inventory(self):
        return self.model_provider.discover_provider_states()

    def discovered_provider(self, provider_id: str):
        return self.model_provider.discovered_provider_state(provider_id)

    def _resolved_provider_metadata_api_key(
        self,
        *,
        provider_id: str,
        base_url: str | None = None,
        explicit_api_key: str | None = None,
    ) -> str | None:
        if explicit_api_key is not None:
            resolved = str(explicit_api_key).strip()
            if resolved:
                return resolved
        active_profile = self.model_provider.active_profile()
        if active_profile is not None and active_profile.provider_id == provider_id:
            profile_base_url = str(active_profile.base_url or "").strip() or None
            requested_base_url = str(base_url or "").strip() or None
            if requested_base_url in {None, profile_base_url}:
                credentials = self.model_provider.resolve_credentials(active_profile)
                resolved = str(credentials.get("api_key", "")).strip()
                if resolved:
                    return resolved
        discovered = self.model_provider.resolve_discovered_credentials(provider_id)
        resolved = str(discovered.get("api_key", "")).strip()
        return resolved or None

    def active_provider_context_window(self, *, default: int = 4096) -> int:
        summary = dict(self.provider_summary())
        value = summary.get("context_window_tokens")
        try:
            parsed = int(value) if value is not None else 0
        except (TypeError, ValueError):
            parsed = 0
        return parsed if parsed > 0 else default

    def discover_provider_models(
        self,
        *,
        provider_id: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        return self.model_provider.discover_models(
            provider_id=provider_id,
            base_url=base_url,
            api_key=self._resolved_provider_metadata_api_key(
                provider_id=provider_id,
                base_url=base_url,
                explicit_api_key=api_key,
            ),
        )

    def detect_provider_context_window(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> int | None:
        return self.model_provider.detect_context_window(
            provider_id=provider_id,
            base_url=base_url,
            model_id=model_id,
            api_key=self._resolved_provider_metadata_api_key(
                provider_id=provider_id,
                base_url=base_url,
                explicit_api_key=api_key,
            ),
        )

    def set_model_stream_observer(self, observer) -> None:
        self.model_provider.set_stream_observer(observer)

    def provider_catalog(self) -> tuple[ProviderCatalogRecord, ...]:
        return self.model_provider.runtime_resolver.list_catalog()

    def provider_setup_guide(self, provider_id: str) -> ProviderSetupGuide:
        return self.model_provider.runtime_resolver.build_setup_guide(provider_id)

    def _embedding_provider_profile(self) -> AuthProfile | None:
        profile = self.repository.load_auth_profile(OPENAI_COMPATIBLE_EMBED_PROFILE_ID)
        if profile is None or profile.provider_id != OPENAI_COMPATIBLE_EMBED_PROVIDER_ID:
            return None
        return profile

    def _active_embedding_provider_profile(self) -> AuthProfile | None:
        profile = self._embedding_provider_profile()
        if profile is None:
            return None
        if str(profile.metadata.get("embedding_active") or "").strip().lower() != "true":
            return None
        return profile

    def _embedding_secret_reference(self, *, env_var: str | None = None) -> SecretReference:
        metadata = {"storage": "local-vault", "scope": "embedding-provider"}
        resolved_env_var = str(env_var or "").strip() or _EMBEDDING_API_KEY_ENV_VAR
        metadata["env_var"] = resolved_env_var
        return SecretReference(
            reference_id=_EMBEDDING_API_KEY_REFERENCE_ID,
            provider_id=OPENAI_COMPATIBLE_EMBED_PROVIDER_ID,
            secret_name="api_token",
            secret_key="api_key",
            metadata=metadata,
        )

    def _embedding_auth_profile(
        self,
        *,
        base_url: str,
        model_id: str,
        dimensions: int,
        reference: SecretReference,
        active: bool,
        configured_from: str,
    ) -> AuthProfile:
        existing = self._embedding_provider_profile()
        metadata = dict(existing.metadata) if existing is not None else {}
        metadata.update(
            {
                "embedding_active": "true" if active else "false",
                "dimensions": str(dimensions),
                "configured_from": configured_from,
            }
        )
        secret_env_var = str(reference.metadata.get("env_var") or "").strip()
        if secret_env_var:
            metadata["secret_env_var"] = secret_env_var
        return AuthProfile(
            profile_id=OPENAI_COMPATIBLE_EMBED_PROFILE_ID,
            provider_id=OPENAI_COMPATIBLE_EMBED_PROVIDER_ID,
            transport_id="openai-compatible",
            base_url=base_url,
            default_model=model_id,
            auth_method="api_key",
            provider_kind="embedding",
            secret_references=(reference,),
            metadata=metadata,
        )

    def _embedding_dimensions(self, profile: AuthProfile) -> int:
        try:
            return int(str(profile.metadata.get("dimensions") or "0").replace(",", ""))
        except (TypeError, ValueError):
            return 0

    def _stored_embedding_api_key(self, reference_id: str) -> str | None:
        stored = self.repository.load_auth_secret_value(reference_id)
        if stored is None:
            return None
        return self.model_provider.secret_cipher.decrypt(stored)

    def embedding_provider_summary(self) -> Mapping[str, object]:
        provider = dict(self.provider_summary())
        profile = self._active_embedding_provider_profile()
        if profile is not None:
            reference = next((item for item in profile.secret_references if item.secret_key == "api_key"), None)
            reference_id = reference.reference_id if reference is not None else ""
            has_secret = bool(reference_id) and self.repository.has_auth_secret_value(reference_id)
            return {
                "source": "configured",
                "profile_id": profile.profile_id,
                "config_id": profile.profile_id,
                "provider_id": profile.provider_id,
                "provider_kind": profile.provider_kind,
                "model_id": profile.default_model or "",
                "dimensions": self._embedding_dimensions(profile),
                "base_url": profile.base_url or "",
                "status": "active",
                "secret_status": "stored" if has_secret else "missing",
                "secret_reference_id": reference_id,
                "embedding_bootstrap_status": "external",
                "embedding_bootstrap_summary": "OpenAI-compatible embeddings do not use the local bootstrap worker.",
            }
        local_default = default_local_embedding_provider_config()
        return {
            "source": "local-default",
            "profile_id": "",
            "config_id": "local-default",
            "provider_id": local_default.get("provider_id") or ELEPHANT_EMBED_PROVIDER_ID,
            "provider_kind": local_default.get("provider_kind") or ELEPHANT_EMBED_PROVIDER_KIND,
            "model_id": local_default.get("model_id") or ELEPHANT_EMBED_MODEL_ID,
            "dimensions": local_default.get("dimensions") or ELEPHANT_EMBED_DEFAULT_DIMENSIONS,
            "base_url": "",
            "status": "active",
            "secret_status": "not-required",
            "secret_reference_id": "",
            "embedding_bootstrap_status": provider.get("embedding_bootstrap_status") or "unknown",
            "embedding_bootstrap_summary": provider.get("embedding_bootstrap_summary") or "",
        }

    def set_local_embedding_provider(self, *, source: str = "huggingface"):
        profile = self._embedding_provider_profile()
        if profile is not None and str(profile.metadata.get("embedding_active") or "").strip().lower() == "true":
            self.repository.upsert_auth_profile(
                replace(
                    profile,
                    metadata={
                        **dict(profile.metadata),
                        "embedding_active": "false",
                        "configured_from": "cli",
                    },
                )
            )
        self.model_provider.ensure_embedding_bootstrap_state(source=source)
        return self.embedding_provider_summary()

    def set_openai_compatible_embedding_provider(
        self,
        *,
        base_url: str,
        model_id: str,
        dimensions: int,
        api_key: str | None = None,
        secret_env_var: str | None = None,
    ):
        resolved_base_url = str(base_url).strip()
        resolved_model_id = str(model_id).strip()
        if not resolved_base_url:
            raise ValueError("embedding base_url must not be empty")
        if not resolved_model_id:
            raise ValueError("embedding model must not be empty")
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        reference = self._embedding_secret_reference(env_var=secret_env_var)
        persisted_api_key = (
            str(api_key or "").strip()
            or self._stored_embedding_api_key(reference.reference_id)
            or self._stored_api_key_for_active_provider("openai-compatible")
        )
        if not persisted_api_key:
            raise ValueError(
                "OpenAI-compatible embeddings require an API key; rerun with --api-key or configure an active OpenAI-compatible provider first."
            )
        profile = self._embedding_auth_profile(
            base_url=resolved_base_url,
            model_id=resolved_model_id,
            dimensions=dimensions,
            reference=reference,
            active=True,
            configured_from="cli",
        )
        self.repository.upsert_auth_profile(profile)
        self.model_provider.store_secret_value(reference, persisted_api_key)
        return {
            "source": "configured",
            "profile_id": profile.profile_id,
            "config_id": profile.profile_id,
            "provider_id": profile.provider_id,
            "provider_kind": profile.provider_kind,
            "model_id": profile.default_model or "",
            "dimensions": dimensions,
            "base_url": profile.base_url or "",
            "status": "active",
            "secret_status": "stored",
            "secret_reference_id": reference.reference_id,
            "embedding_bootstrap_status": "external",
            "embedding_bootstrap_summary": "OpenAI-compatible embeddings do not use the local bootstrap worker.",
        }

    def provider_reasoning_efforts(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> tuple[str, ...]:
        return self.model_provider.reasoning_efforts(
            provider_id=provider_id,
            model_id=model_id,
            base_url=base_url,
            api_key=self._resolved_provider_metadata_api_key(
                provider_id=provider_id,
                base_url=base_url,
                explicit_api_key=api_key,
            ),
        )

    def provider_test(self, *, prompt: str = "Summarize the current provider configuration.") -> ExecutionResult:
        active_profile = self.model_provider.active_profile()
        context_capability = _CliContextCapability(
            profile_loader=self.profile_loader,
            repository=self.repository,
            prompt_mode="minimal",
            snapshot_path=self.snapshot_path,
            total_tokens=self.active_provider_context_window(),
            skill_prompt_context=self.skill_prompt_context,
            install_root=self.paths.home_dir,
            workspaces_dir=self.paths.workspaces_dir,
        )
        if active_profile is None:
            profile = PersonalModelRuntimeState(
                profile_id="provider-test",
                display_name="Elephant Agent",
                mode="companion",
            )
            session = Episode(
                episode_id=f"episode:provider-test:{uuid4().hex[:8]}",
                state_id="state:provider-test:default",
                personal_model_id=profile.profile_id,
                entry_surface="cli",
                elephant_id="provider-test",
                status="open",
                started_at=_utc_now(),
                updated_at=_utc_now(),
            )
            context = context_capability.assemble(session, (), ())
            return self.model_provider.generate(profile=profile, session=session, context=context, prompt=prompt)

        loaded_profile = self.current_profile()
        profile = loaded_profile.state
        session = Episode(
            episode_id=f"episode:provider-test:{uuid4().hex[:8]}",
            state_id="state:provider-test:default",
            personal_model_id=profile.profile_id,
            entry_surface="cli",
            elephant_id="provider-test",
            status="open",
            started_at=_utc_now(),
            updated_at=_utc_now(),
        )
        context = context_capability.assemble(session, (), ())
        return self.model_provider.generate(profile=profile, session=session, context=context, prompt=prompt)

    def provider_doctor(self, *, deep: bool = True) -> dict[str, Any]:
        """Report provider health.

        `deep=True` (default) runs the full diagnostic: live model-catalog
        discovery + an LLM round-trip probe. That's appropriate for the
        provider-configuration wizard and explicit deep status checks.

        `deep=False` skips both remote calls. The wake flow only needs
        "is the configured profile + credential path in place?" to
        decide whether to proceed — it never consumes the live model
        catalog or the probe summary, so blocking on them for 10+ s
        before every `elephant wake` was pure regression. Callers that
        need those signals pass `deep=True` explicitly.
        """
        summary = dict(self.provider_summary())
        guide: dict[str, Any] | None = None
        if summary["provider_id"] not in {"preview", ""}:
            guide = self.provider_setup_guide(str(summary["provider_id"])).as_mapping()
        secret_ready = summary.get("secret_status") in {"stored", "not-required"}
        checks = [
            {
                "check": "provider_profile",
                "status": "configured" if summary["source"] == "configured" else "missing",
            },
            {
                "check": "credentials",
                "status": (
                    "available"
                    if summary["source"] == "configured" and secret_ready
                    else ("missing" if summary["source"] == "configured" else "preview")
                ),
                "summary": str(summary.get("secret_source", "encrypted-local-store")),
            },
            {
                "check": "embedding_bootstrap",
                "status": str(summary.get("embedding_bootstrap_status") or "unknown"),
                "summary": str(summary.get("embedding_bootstrap_summary") or ""),
            },
        ]
        configured_model = str(summary.get("model_id") or summary.get("default_model") or "").strip()
        live_models = ()
        if deep and summary["source"] == "configured" and secret_ready:
            try:
                discovered_models = tuple(
                    self.discover_provider_models(
                        provider_id=str(summary["provider_id"]),
                        base_url=str(summary.get("base_url") or "").strip() or None,
                    )
                )
            except Exception as error:  # pragma: no cover - defensive surface guard
                checks.append({"check": "model_catalog", "status": "not-ready", "summary": str(error)})
            else:
                live_models = tuple(model for model in discovered_models if model.source != "catalog-hint")
                if live_models:
                    checks.append(
                        {
                            "check": "model_catalog",
                            "status": "ok",
                            "summary": f"{len(live_models)} live model(s) discovered",
                        }
                    )
                elif discovered_models:
                    checks.append(
                        {
                            "check": "model_catalog",
                            "status": "hinted",
                            "summary": "Fell back to curated model hints because the live model catalog was unavailable.",
                        }
                    )
        probe = None
        probe_error: str | None = None
        if deep and summary["source"] == "configured" and secret_ready:
            if self._is_placeholder_model_id(str(summary["provider_id"]), configured_model):
                probe_error = (
                    "configured model is still a placeholder; read the provider model catalog "
                    "or enter the exact model id before running runtime checks"
                )
            elif live_models and configured_model and configured_model not in {model.model_id for model in live_models}:
                probe_error = (
                    f"configured model '{configured_model}' was not returned by the provider model catalog"
                )
            else:
                try:
                    probe = self.provider_test(prompt="Doctor check")
                except Exception as error:  # pragma: no cover - defensive surface guard
                    probe_error = str(error)
        if probe is not None:
            checks.append({"check": "runtime", "status": "ok", "summary": probe.summary})
        elif probe_error is not None:
            checks.append({"check": "runtime", "status": "not-ready", "summary": probe_error})
        return {
            "status": "ready"
            if summary["source"] == "configured" and secret_ready and probe_error is None
            else ("not-ready" if summary["source"] == "configured" else "preview"),
            "provider": summary,
            "setup_guide": guide,
            "checks": checks,
            "probe_summary": probe.summary if probe is not None else (probe_error or ""),
        }

    def _is_placeholder_model_id(self, provider_id: str, model_id: str) -> bool:
        normalized_provider = provider_id.strip().lower()
        normalized_model = model_id.strip()
        if not normalized_model:
            return True
        return normalized_model in _PLACEHOLDER_MODELS_BY_PROVIDER.get(normalized_provider, set())

    def security_doctor(self) -> dict[str, Any]:
        policy = SecurityPolicy.default()
        profile = self.model_provider.active_profile()
        embedding_profile = self._active_embedding_provider_profile()
        provider = dict(self.provider_summary())
        secret_refs = ()
        if profile is not None:
            secret_refs = tuple(profile.secret_references)
        if embedding_profile is not None:
            secret_refs = tuple(secret_refs) + tuple(embedding_profile.secret_references)
        stored_reference_ids = tuple(
            reference.reference_id
            for reference in secret_refs
            if self.repository.has_auth_secret_value(reference.reference_id)
        )
        missing_reference_ids = tuple(
            reference.reference_id
            for reference in secret_refs
            if reference.reference_id not in stored_reference_ids
        )
        checks: list[dict[str, object]] = [
            {
                "check": "policy_rules",
                "status": "ok",
                "summary": ", ".join(bundle.surface_id for bundle in default_surface_policy_bundles()),
            },
            {
                "check": "secret_boundary",
                "status": (
                    "ok"
                    if not missing_reference_ids
                    else "warning"
                ),
                "summary": (
                    "preview fallback carries no runtime provider secrets"
                    if provider["source"] != "configured" and embedding_profile is None
                    else (
                        "provider and embedding secrets are stored in the encrypted local vault"
                        if not missing_reference_ids
                        else (
                            "missing stored provider secrets for "
                            + ", ".join(missing_reference_ids)
                        )
                    )
                ),
            },
            {
                "check": "support_bundle",
                "status": "ok",
                "summary": "support bundle exports provider ids, models, and secret reference ids only",
            },
        ]
        return {
            "status": (
                "ready"
                if not missing_reference_ids
                else "not-ready"
            ),
            "provider": provider,
            "checks": checks,
            "surface_bundles": tuple(
                bundle.to_record(policy) for bundle in default_surface_policy_bundles()
            ),
            "support_bundle": self.security_support_bundle(),
        }

    def security_support_bundle(self) -> dict[str, Any]:
        profile = self.model_provider.active_profile()
        embedding_profile = self._active_embedding_provider_profile()
        provider = dict(self.provider_summary())
        secret_reference_ids = ()
        stored_reference_ids = ()
        if profile is not None:
            secret_reference_ids = tuple(reference.reference_id for reference in profile.secret_references)
            stored_reference_ids = tuple(
                reference.reference_id
                for reference in profile.secret_references
                if self.repository.has_auth_secret_value(reference.reference_id)
            )
        embedding_secret_reference_ids = ()
        embedding_stored_reference_ids = ()
        embedding_summary = dict(self.embedding_provider_summary())
        if embedding_profile is not None:
            embedding_secret_reference_ids = tuple(
                reference.reference_id for reference in embedding_profile.secret_references
            )
            embedding_stored_reference_ids = tuple(
                reference.reference_id
                for reference in embedding_profile.secret_references
                if self.repository.has_auth_secret_value(reference.reference_id)
            )
        return {
            "provider": {
                "provider_id": provider["provider_id"],
                "profile_id": provider["profile_id"],
                "transport_id": provider["transport_id"],
                "base_url": provider["base_url"],
                "model_id": provider.get("model_id") or provider.get("default_model"),
                "embedding_bootstrap_status": provider.get("embedding_bootstrap_status"),
                "embedding_bootstrap_summary": provider.get("embedding_bootstrap_summary"),
                "embedding_bootstrap_updated_at": provider.get("embedding_bootstrap_updated_at"),
                "embedding_model_root": provider.get("embedding_model_root"),
                "context_window_tokens": provider.get("context_window_tokens"),
                "context_window_mode": provider.get("context_window_mode"),
                "source": provider["source"],
                "secret_reference_ids": secret_reference_ids,
                "stored_secret_reference_ids": stored_reference_ids,
                "secret_store": "encrypted-local-store",
            },
            "embedding_provider": {
                "provider_id": embedding_summary.get("provider_id"),
                "profile_id": embedding_summary.get("profile_id"),
                "base_url": embedding_summary.get("base_url"),
                "model_id": embedding_summary.get("model_id"),
                "dimensions": embedding_summary.get("dimensions"),
                "source": embedding_summary.get("source"),
                "secret_reference_ids": embedding_secret_reference_ids,
                "stored_secret_reference_ids": embedding_stored_reference_ids,
                "secret_store": "encrypted-local-store",
            },
            "surface_bundles": tuple(bundle.surface_id for bundle in default_surface_policy_bundles()),
            "generated_at": _iso(_utc_now()),
            "notes": (
                "secret values are never exported here",
                "set or rotate runtime credentials outside the support bundle",
            ),
        }

    def voice_summary(
        self,
        *,
        input_model_id: str = "gpt-4o-mini-transcribe",
        output_model_id: str = "gpt-4o-mini-tts",
        voice_name: str = "alloy",
    ) -> Mapping[str, object]:
        return self._build_voice_service(
            input_model_id=input_model_id,
            output_model_id=output_model_id,
            voice_name=voice_name,
        ).provider_summary()

    def voice_doctor(
        self,
        *,
        profile_id: str | None = None,
        input_model_id: str = "gpt-4o-mini-transcribe",
        output_model_id: str = "gpt-4o-mini-tts",
        voice_name: str = "alloy",
    ) -> dict[str, Any]:
        resolved_profile_id = profile_id or self.current_profile().state.profile_id
        loaded = self._load_profile(resolved_profile_id)
        return self._build_voice_service(
            input_model_id=input_model_id,
            output_model_id=output_model_id,
            voice_name=voice_name,
        ).doctor(loaded)

    def run_voice_turn(
        self,
        *,
        session_id: str,
        audio_bytes: bytes,
        audio_name: str,
        audio_format: str | None = None,
        state_query: str | None = None,
        voice_output_enabled: bool = False,
        input_model_id: str = "gpt-4o-mini-transcribe",
        output_model_id: str = "gpt-4o-mini-tts",
        voice_name: str = "alloy",
        output_audio_format: str = "mp3",
    ) -> CliVoiceTurnResult:
        session = self.repository.load_episode_state(session_id)
        if session is None:
            raise KeyError(session_id)
        loaded_profile = self._load_profile(session.personal_model_id)
        voice_service = self._build_voice_service(
            telemetry=_PreviewTelemetrySink(self.snapshot_path),
            input_model_id=input_model_id,
            output_model_id=output_model_id,
            voice_name=voice_name,
        )
        voice_session = voice_service.open_session(loaded_profile, session_id)
        resolution = voice_service.resolve_input(
            loaded_profile,
            voice_session,
            VoiceInputRequest(
                request_id=f"voice-turn:{uuid4().hex[:8]}",
                session_id=session_id,
                profile_id=loaded_profile.state.profile_id,
                source="provider-backed",
                consent_given=True,
                recording_enabled=False,
                audio_bytes=audio_bytes,
                audio_format=audio_format,
                audio_name=audio_name,
            ),
        )
        if resolution.outcome != "ready":
            return CliVoiceTurnResult(
                input_resolution=resolution,
                kernel_outcome=None,
                voice_turn=voice_service.complete_output(
                    loaded_profile,
                    voice_session,
                    resolution,
                    voice_output_enabled=voice_output_enabled,
                    audio_format=output_audio_format,
                ),
            )
        outcome = self.explain_next_step(
            session_id=session_id,
            prompt=resolution.transcript,
            state_query=state_query,
        )
        voice_turn = voice_service.complete_output(
            loaded_profile,
            voice_session,
            resolution,
            response_transcript=outcome.execution.summary,
            voice_output_enabled=voice_output_enabled,
            audio_format=output_audio_format,
        )
        return CliVoiceTurnResult(
            input_resolution=resolution,
            kernel_outcome=outcome,
            voice_turn=voice_turn,
        )

    def _stored_api_key_for_active_provider(self, provider_id: str) -> str | None:
        active_profile = self.model_provider.active_profile()
        if active_profile is None or active_profile.provider_id != provider_id:
            return None
        reference = next(
            (item for item in active_profile.secret_references if item.secret_key == "api_key"),
            None,
        )
        if reference is None or not self.repository.has_auth_secret_value(reference.reference_id):
            return None
        credentials = self.model_provider.resolve_credentials(active_profile)
        resolved = str(credentials.get("api_key", "")).strip()
        return resolved or None

    def _store_api_key_for_profile(self, provider_profile, api_key: str | None) -> None:
        if api_key is None:
            return
        api_reference = next(
            (reference for reference in provider_profile.secret_references if reference.secret_key == "api_key"),
            None,
        )
        if api_reference is not None:
            self.model_provider.store_secret_value(api_reference, api_key)

    def set_default_provider(
        self,
        *,
        provider_id: str,
        profile_id: str | None = None,
        display_name: str | None = None,
        mode: str | None = None,
        base_url: str | None = None,
        model_id: str | None = None,
        auth_method: str | None = None,
        provider_kind: str | None = None,
        api_key: str | None = None,
        secret_env_var: str | None = None,
        context_window_tokens: int | None = None,
        context_window_mode: str | None = None,
        reasoning_effort: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> LoadedProfile:
        del profile_id, display_name, mode  # identity flows from the DB, not here
        loaded = self.profile_loader.load()
        resolved_model = str(model_id or "").strip() or None
        provider_payload = self._build_provider_payload(
            profile_id=f"provider-{provider_id}",
            provider_id=provider_id,
            base_url=base_url,
            default_model=resolved_model,
            auth_method=auth_method,
            provider_kind=provider_kind,
            secret_env_var=secret_env_var,
            context_window_tokens=context_window_tokens,
            context_window_mode=context_window_mode,
            reasoning_effort=reasoning_effort,
            extra_headers=extra_headers,
        )
        # Write provider to config.yaml
        from packages.runtime_config import save_provider_to_config, global_config_path_for_state_dir
        config_path = global_config_path_for_state_dir(self.paths.state_dir)
        save_provider_to_config(
            config_path,
            state_dir=self.paths.state_dir,
            provider_payload=provider_payload,
        )
        active_profile = provider_profile_from_payload(provider_payload)
        capture_runtime_secret_env(self.paths.state_dir, active_profile)
        self.repository.upsert_auth_profile(active_profile)
        persisted_api_key = str(api_key or "").strip() or self._stored_api_key_for_active_provider(provider_id)
        self._store_api_key_for_profile(active_profile, persisted_api_key)
        self.model_provider.set_active_profile(
            provider_profile_id=active_profile.profile_id,
            provider_id=active_profile.provider_id,
        )
        return self._load_profile(loaded.state.profile_id)

    def relationship_projection_policy(self, loaded_profile: LoadedProfile) -> RelationshipPolicy:
        companion = loaded_profile.companion or CompanionSettings()
        return build_relationship_policy(
            loaded_profile.state.mode,
            text_first=companion.text_first,
            preserve_relationship_timeline=companion.preserve_relationship_timeline,
            preserve_preferences=companion.preserve_preferences,
            preserve_corrections=companion.preserve_corrections,
            preserve_emotional_context=companion.preserve_emotional_context,
        )

    def _build_provider_payload(
        self,
        *,
        profile_id: str,
        provider_id: str,
        base_url: str | None,
        default_model: str | None,
        auth_method: str | None,
        provider_kind: str | None,
        secret_env_var: str | None,
        context_window_tokens: int | None,
        context_window_mode: str | None,
        reasoning_effort: str | None,
        extra_headers: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        definition = provider_definition(provider_id)
        metadata: dict[str, str] = {}
        if context_window_mode is not None:
            metadata["context_window_mode"] = context_window_mode
        if context_window_tokens is not None:
            metadata["context_window_tokens"] = str(context_window_tokens)
        if reasoning_effort is not None:
            metadata["reasoning_effort"] = reasoning_effort
        payload: dict[str, Any] = {
            "profile_id": profile_id,
            "provider_id": provider_id,
            "secret_references": [],
            "metadata": metadata,
        }
        if provider_id == "openai-compatible":
            if base_url is None or default_model is None:
                raise ValueError("openai-compatible provider defaults require base_url and default_model")
            payload["base_url"] = base_url
            payload["default_model"] = default_model
        elif base_url is not None:
            payload["base_url"] = base_url
        if default_model is not None and provider_id != "openai-compatible":
            payload["default_model"] = default_model
        if auth_method is not None or definition is not None:
            payload["auth_method"] = auth_method or definition.auth_method
        if provider_kind is not None or definition is not None:
            payload["provider_kind"] = provider_kind or definition.provider_kind
        merged_extra_headers = {
            **(dict(definition.extra_headers) if definition is not None else {}),
            **dict(extra_headers or {}),
        }
        if merged_extra_headers:
            payload["extra_headers"] = merged_extra_headers
        if self.provider_setup_guide(provider_id).required_secret_keys:
            secret_metadata = {"storage": "local-vault"}
            resolved_secret_env_var = secret_env_var.strip() if secret_env_var is not None else ""
            if resolved_secret_env_var:
                secret_metadata["env_var"] = resolved_secret_env_var
            elif definition is not None and definition.env_var_names:
                secret_metadata["env_var"] = definition.env_var_names[0]
            payload["secret_references"] = [
                {
                    "reference_id": f"secret-{profile_id}-api-key",
                    "provider_id": provider_id,
                    "secret_name": "api_token",
                    "secret_key": "api_key",
                    "metadata": secret_metadata,
                }
            ]
        return payload

    def _build_voice_service(
        self,
        *,
        telemetry: Any = None,
        input_model_id: str = "gpt-4o-mini-transcribe",
        output_model_id: str = "gpt-4o-mini-tts",
        voice_name: str = "alloy",
    ):
        return build_provider_voice_service(
            provider_profile=self.model_provider.active_profile(),
            telemetry=telemetry,
            input_model_id=input_model_id,
            output_model_id=output_model_id,
            voice_name=voice_name,
        )
