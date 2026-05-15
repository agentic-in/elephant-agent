from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

WAKE_DISPLAY_SECONDS = 0.0


@dataclass(frozen=True, slots=True)
class BootFrameContext:
    display_name: str
    growth_stage_title: str
    provider_model: str


def render_boot_frame(
    *,
    context: BootFrameContext,
    rich_available: bool,
    table_cls: Any,
    group_cls: Any,
    text_cls: Any,
    panel_cls: Any,
    align_cls: Any,
    brand_accent: str,
    brand_accent_strong: str,
    brand_light: str,
    brand_muted: str,
    brand_dark: str,
    center_brand_block: Callable[[Any], Any],
    brand_mark: Any,
):
    """Static boot frame retained for callers that still render one explicitly."""
    if not rich_available or table_cls is None or group_cls is None:
        return text_cls(f"Elephant Agent · {context.display_name}")

    identity = text_cls(justify="center", no_wrap=True)
    identity.append(f"{context.display_name}", style=f"bold {brand_light}")
    identity.append(f" · {context.growth_stage_title}", style=brand_accent_strong)
    if context.provider_model and context.provider_model != "<unset>":
        identity.append(f" · {context.provider_model}", style=brand_muted)

    tagline = text_cls(justify="center", no_wrap=True)
    tagline.append("Picking up your thread", style=brand_light)

    boot = table_cls.grid(expand=True)
    boot.add_column(no_wrap=True)
    boot.add_row(center_brand_block(brand_mark))
    boot.add_row(center_brand_block(identity))
    boot.add_row(center_brand_block(tagline))

    panel = panel_cls(
        boot,
        title=f"[bold {brand_accent}]Elephant Agent[/bold {brand_accent}]",
        border_style=brand_dark,
        padding=(1, 3),
        width=72,
    )
    if align_cls is None:
        return panel
    return align_cls(panel, align="center")
