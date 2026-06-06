# core/guards.py
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal", "metadata.internal"})


def _is_non_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *ip* must not be contacted as a remote Git host.

    Covers: loopback, private (RFC1918/ULA), link-local (v4 & v6),
    carrier-NAT (100.64/10), multicast, reserved, unspecified, and
    IPv4-mapped IPv6 addresses (e.g. ::ffff:10.0.0.1).
    """
    # Unwrap IPv4-mapped IPv6 so ::ffff:10.0.0.1 is treated as 10.0.0.1
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_repo_url(url: str) -> None:
    """Raise ValueError if *url* fails SSRF safety checks.

    Blocks non-HTTPS schemes and any URL that resolves to private, loopback,
    link-local, carrier-NAT, multicast, reserved, or unspecified address space,
    including IPv4-mapped IPv6 addresses (e.g. ::ffff:10.0.0.1).

    Note: this guard validates the address at call time. If the caller uses a
    separate DNS resolution (e.g. git clone), a sufficiently short-TTL DNS
    rebinding attack can still occur. For high-security deployments, run the
    server behind a network egress filter that enforces the same blocklist.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(
            f"Only https:// repository URLs are accepted; got '{parsed.scheme}://'."
        )
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("Repository URL has no hostname.")
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise ValueError(f"Hostname '{hostname}' is not permitted.")
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname '{hostname}': {exc}") from exc
    for _family, _type, _proto, _canon, sockaddr in addr_infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_non_public(ip):
            raise ValueError(
                f"Repository URL resolves to a private or reserved IP address "
                f"({ip}), which is not permitted."
            )
