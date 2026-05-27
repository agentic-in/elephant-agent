"""Proxy environment variable parsing for Seatbelt network policy.

Extracts localhost ports and Unix socket paths from standard proxy
environment variables (HTTP_PROXY, HTTPS_PROXY, ALL_PROXY, etc.) to
generate precise Seatbelt network rules.

Reference: Codex ``codex-rs/sandboxing/src/seatbelt.rs`` —
``proxy_loopback_ports_from_env()``
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


# Standard proxy environment variable names (case-sensitive + lowercase)
PROXY_ENV_VARS: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

_SCHEME_DEFAULT_PORTS: dict[str, int] = {
    "http": 80,
    "https": 443,
    "socks5": 1080,
    "socks5h": 1080,
    "socks4": 1080,
    "socks4a": 1080,
}


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """Parsed proxy configuration relevant for Seatbelt policy."""

    # Localhost ports that should be allowed for outbound connections
    loopback_ports: tuple[int, ...] = ()

    # Unix socket paths used by proxies
    unix_sockets: tuple[str, ...] = ()

    # Whether any proxy configuration was detected at all
    has_proxy: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.loopback_ports and not self.unix_sockets


def _is_loopback(host: str) -> bool:
    """Check if a host string refers to loopback."""
    return host.lower() in _LOOPBACK_HOSTS


def extract_proxy_config(
    env: dict[str, str] | None = None,
    extra_unix_sockets: tuple[str, ...] = (),
) -> ProxyConfig:
    """Extract proxy configuration from environment variables.

    Parses HTTP_PROXY, HTTPS_PROXY, ALL_PROXY (and lowercase variants)
    to find:
    - Localhost ports for TCP proxy connections
    - Unix socket paths for local proxy connections

    Args:
        env: Environment dict to read from. Defaults to os.environ.
        extra_unix_sockets: Additional Unix socket paths to include.

    Returns:
        ProxyConfig with extracted loopback ports and socket paths.
    """
    if env is None:
        env = dict(os.environ)

    ports: set[int] = set()
    sockets: list[str] = list(extra_unix_sockets)
    has_proxy = False

    for var_name in PROXY_ENV_VARS:
        raw_value = env.get(var_name, "").strip()
        if not raw_value:
            continue

        has_proxy = True

        # Handle Unix socket URLs: socks5h://unix:///path/to/sock
        if "unix://" in raw_value or "unix:" in raw_value:
            socket_path = _extract_unix_socket_path(raw_value)
            if socket_path and socket_path not in sockets:
                sockets.append(socket_path)
            continue

        # Normalize URL for parsing
        url = raw_value if "://" in raw_value else f"http://{raw_value}"

        try:
            parsed = urlparse(url)
        except (ValueError, OSError):
            continue

        host = parsed.hostname or ""
        if not _is_loopback(host):
            continue

        scheme = (parsed.scheme or "http").lower()
        port = parsed.port or _SCHEME_DEFAULT_PORTS.get(scheme, 80)
        ports.add(port)

    return ProxyConfig(
        loopback_ports=tuple(sorted(ports)),
        unix_sockets=tuple(sockets),
        has_proxy=has_proxy,
    )


def _extract_unix_socket_path(url: str) -> str | None:
    """Extract Unix socket path from a proxy URL.

    Handles formats like:
    - socks5h://unix:///tmp/proxy.sock
    - http://unix:/tmp/proxy.sock:/
    - unix:///tmp/proxy.sock
    """
    # Format: scheme://unix:///path
    if "unix:///" in url:
        idx = url.index("unix:///") + len("unix://")
        path = url[idx:]
        # Strip trailing path after the socket (e.g., :/path)
        if ":/" in path and not path.startswith(":/"):
            path = path[: path.index(":/")]
        return path.rstrip("/") or None

    # Format: http://unix:/path:/
    if "unix:" in url:
        idx = url.index("unix:") + len("unix:")
        path = url[idx:]
        if path.startswith("//"):
            path = path[1:]  # normalize
        # Strip trailing :/ suffix
        if path.endswith(":/"):
            path = path[:-2]
        elif path.endswith(":"):
            path = path[:-1]
        return path.rstrip("/") or None

    return None
