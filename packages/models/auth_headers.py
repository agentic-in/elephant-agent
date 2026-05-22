"""Auth-header strategies for provider transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

ANTHROPIC_OAUTH_BETA_HEADER = (
    "interleaved-thinking-2025-05-14,"
    "fine-grained-tool-streaming-2025-05-14,"
    "claude-code-20250219,"
    "oauth-2025-04-20"
)


@dataclass(frozen=True, slots=True)
class AuthHeaderContext:
    provider_id: str
    request_family: str
    api_key: str | None
    anthropic_version: str = "2023-06-01"
    metadata: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class AuthHeaderStrategy(Protocol):
    strategy_id: str

    def supports(self, context: AuthHeaderContext) -> bool:
        """Return whether this strategy can build headers for the context."""

    def build_headers(self, context: AuthHeaderContext) -> Mapping[str, str]:
        """Build auth headers for the context."""


class InMemoryAuthHeaderStrategyRegistry:
    def __init__(self, strategies: tuple[AuthHeaderStrategy, ...] = ()) -> None:
        self._strategies: dict[str, AuthHeaderStrategy] = {}
        for strategy in strategies:
            self.register(strategy)

    def register(self, strategy: AuthHeaderStrategy) -> None:
        self._strategies[strategy.strategy_id] = strategy

    def get(self, strategy_id: str) -> AuthHeaderStrategy | None:
        return self._strategies.get(strategy_id)

    def list(self) -> tuple[AuthHeaderStrategy, ...]:
        return tuple(self._strategies.values())

    def select(self, context: AuthHeaderContext) -> AuthHeaderStrategy:
        configured = str(context.metadata.get("auth_header_strategy") or "").strip()
        if configured:
            strategy = self.get(configured)
            if strategy is None:
                raise LookupError(f"no auth-header strategy registered for id: {configured}")
            return strategy
        for strategy in self._strategies.values():
            if strategy.supports(context):
                return strategy
        raise LookupError(
            "no auth-header strategy registered for "
            f"provider={context.provider_id} request_family={context.request_family}"
        )

    @classmethod
    def default(cls) -> "InMemoryAuthHeaderStrategyRegistry":
        return cls(
            (
                _CopilotBearerStrategy(),
                _AnthropicOauthBearerStrategy(),
                _AnthropicApiKeyStrategy(),
                _BearerAuthHeaderStrategy(),
            )
        )


def _is_anthropic_oauth_token(api_key: str) -> bool:
    return (
        (api_key.startswith("sk-ant-") and not api_key.startswith("sk-ant-api"))
        or api_key.startswith("eyJ")
    )


class _CopilotBearerStrategy:
    strategy_id = "copilot-bearer"

    def supports(self, context: AuthHeaderContext) -> bool:
        return bool(context.api_key) and context.provider_id.strip().lower() == "copilot"

    def build_headers(self, context: AuthHeaderContext) -> Mapping[str, str]:
        api_key = str(context.api_key or "").strip()
        if not api_key:
            return {}
        headers = {"Authorization": f"Bearer {api_key}"}
        if context.request_family.strip().lower() == "messages":
            headers["anthropic-version"] = context.anthropic_version
        return headers


class _AnthropicOauthBearerStrategy:
    strategy_id = "anthropic-oauth-bearer"

    def supports(self, context: AuthHeaderContext) -> bool:
        api_key = str(context.api_key or "").strip()
        provider_id = context.provider_id.strip().lower()
        return bool(api_key) and (
            provider_id == "claude-code"
            or (provider_id == "anthropic" and _is_anthropic_oauth_token(api_key))
        )

    def build_headers(self, context: AuthHeaderContext) -> Mapping[str, str]:
        api_key = str(context.api_key or "").strip()
        if not api_key:
            return {}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "anthropic-beta": ANTHROPIC_OAUTH_BETA_HEADER,
            "user-agent": "claude-cli/2.1.74 (external, cli)",
            "x-app": "cli",
        }
        if context.provider_id.strip().lower() == "anthropic":
            headers["anthropic-version"] = context.anthropic_version
        return headers


class _AnthropicApiKeyStrategy:
    strategy_id = "anthropic-x-api-key"

    def supports(self, context: AuthHeaderContext) -> bool:
        api_key = str(context.api_key or "").strip()
        provider_id = context.provider_id.strip().lower()
        request_family = context.request_family.strip().lower()
        return bool(api_key) and (
            request_family == "messages" or provider_id == "anthropic"
        )

    def build_headers(self, context: AuthHeaderContext) -> Mapping[str, str]:
        api_key = str(context.api_key or "").strip()
        if not api_key:
            return {}
        return {
            "anthropic-version": context.anthropic_version,
            "x-api-key": api_key,
        }


class _BearerAuthHeaderStrategy:
    strategy_id = "bearer"

    def supports(self, context: AuthHeaderContext) -> bool:
        return bool(str(context.api_key or "").strip())

    def build_headers(self, context: AuthHeaderContext) -> Mapping[str, str]:
        api_key = str(context.api_key or "").strip()
        if not api_key:
            return {}
        return {"Authorization": f"Bearer {api_key}"}


_DEFAULT_AUTH_HEADER_STRATEGY_REGISTRY: InMemoryAuthHeaderStrategyRegistry | None = None


def default_auth_header_strategy_registry() -> InMemoryAuthHeaderStrategyRegistry:
    global _DEFAULT_AUTH_HEADER_STRATEGY_REGISTRY
    if _DEFAULT_AUTH_HEADER_STRATEGY_REGISTRY is None:
        _DEFAULT_AUTH_HEADER_STRATEGY_REGISTRY = InMemoryAuthHeaderStrategyRegistry.default()
    return _DEFAULT_AUTH_HEADER_STRATEGY_REGISTRY


def build_provider_auth_headers(
    *,
    provider_id: str,
    request_family: str,
    api_key: str | None,
    anthropic_version: str = "2023-06-01",
    metadata: Mapping[str, str] | None = None,
    registry: InMemoryAuthHeaderStrategyRegistry | None = None,
) -> dict[str, str]:
    context = AuthHeaderContext(
        provider_id=provider_id,
        request_family=request_family,
        api_key=api_key,
        anthropic_version=anthropic_version,
        metadata=dict(metadata or {}),
    )
    resolved_registry = registry or default_auth_header_strategy_registry()
    if not api_key:
        return {}
    return dict(resolved_registry.select(context).build_headers(context))


__all__ = [
    "ANTHROPIC_OAUTH_BETA_HEADER",
    "AuthHeaderContext",
    "AuthHeaderStrategy",
    "InMemoryAuthHeaderStrategyRegistry",
    "build_provider_auth_headers",
    "default_auth_header_strategy_registry",
]
