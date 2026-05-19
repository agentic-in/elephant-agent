"""DingDing gateway bootstrap module."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
from typing import Any

from .dingding_support import *  # noqa: F401,F403
from .dingding_service import DingdingGatewayService
from .plugins import GatewayPluginRegistry
from .runtime import build_gateway_app


def register_dingding_gateway_service(
    registry: GatewayPluginRegistry,
) -> GatewayPluginRegistry:
    registry.register_service(
        "dingding",
        factory=lambda app, **kwargs: DingdingGatewayService(app=app, **kwargs),
        enabled_by_default=True,
    )
    return registry


def build_dingding_gateway_service(
    *,
    profile_id: str = "you",
    provider_profile: Mapping[str, Any] | None = None,
    state_dir: str | None = None,
    environ: Mapping[str, str] | None = None,
    plugin_registry: GatewayPluginRegistry | None = None,
) -> DingdingGatewayService:
    app, _, _ = build_gateway_app(
        profile_id=profile_id,
        provider_profile=provider_profile,
        state_dir=state_dir,
        plugin_registry=plugin_registry,
    )
    return DingdingGatewayService(
        app=app,
        environ=dict(environ or os.environ),
        runtime_state_dir=Path(state_dir) if state_dir is not None else None,
    )
