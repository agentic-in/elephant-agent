"""Discord gateway bootstrap, service description, and delivery wiring."""

from __future__ import annotations

from .discord_support import *  # noqa: F401,F403
from .discord_service import DiscordGatewayService


def register_discord_gateway_service(
    registry: GatewayPluginRegistry,
) -> GatewayPluginRegistry:
    registry.register_service(
        "discord",
        factory=lambda app, **kwargs: DiscordGatewayService(app=app, **kwargs),
        enabled_by_default=True,
    )
    return registry


def build_discord_gateway_service(
    *,
    profile_id: str = "you",
    provider_profile: Mapping[str, Any] | None = None,
    state_dir: str | None = None,
    environ: Mapping[str, str] | None = None,
    plugin_registry: GatewayPluginRegistry | None = None,
) -> DiscordGatewayService:
    app, _, _ = build_gateway_app(
        profile_id=profile_id,
        provider_profile=provider_profile,
        state_dir=state_dir,
        plugin_registry=plugin_registry,
    )
    return DiscordGatewayService(
        app=app,
        environ=dict(environ or os.environ),
        runtime_state_dir=Path(state_dir) if state_dir is not None else None,
    )
