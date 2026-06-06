# core/guards.py
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
)

_BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal", "metadata.internal"})


def validate_repo_url(url: str) -> None:
    """Raise ValueError if *url* fails SSRF safety checks.

    Blocks non-HTTPS schemes and any URL that resolves to private, loopback,
    link-local, carrier-NAT, or IPv6 unique-local address space.
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
        if any(ip in net for net in _PRIVATE_NETWORKS):
            raise ValueError(
                f"Repository URL resolves to a private or reserved IP address "
                f"({ip}), which is not permitted."
            )
