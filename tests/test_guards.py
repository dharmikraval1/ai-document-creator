# tests/test_guards.py
import socket
from unittest.mock import patch

import pytest

from core.guards import validate_repo_url


def _dns(ip: str):
    """Return a mock getaddrinfo result resolving to *ip*."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]


def test_valid_public_url_passes():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("140.82.121.4")):
        validate_repo_url("https://github.com/user/repo")


def test_http_scheme_rejected():
    with pytest.raises(ValueError, match="Only https://"):
        validate_repo_url("http://github.com/user/repo")


def test_git_scheme_rejected():
    with pytest.raises(ValueError, match="Only https://"):
        validate_repo_url("git://github.com/user/repo")


def test_file_scheme_rejected():
    with pytest.raises(ValueError, match="Only https://"):
        validate_repo_url("file:///etc/passwd")


def test_loopback_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("127.0.0.1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://evil.example.com/repo")


def test_aws_metadata_ip_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("169.254.169.254")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://sneaky.example.com/repo")


def test_private_rfc1918_class_a_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("10.0.0.1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://internal.corp/repo")


def test_private_rfc1918_class_c_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("192.168.1.1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://router.local/repo")


def test_google_metadata_hostname_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("169.254.169.254")):
        with pytest.raises(ValueError, match="not permitted"):
            validate_repo_url("https://metadata.google.internal/computeMetadata/v1/")


def test_dns_failure_rejected():
    with patch("core.guards.socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
        with pytest.raises(ValueError, match="Cannot resolve"):
            validate_repo_url("https://does-not-exist.invalid/repo")


def _dns6(ip: str):
    """Return a mock getaddrinfo result resolving to IPv6 address *ip*."""
    return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (ip, 0, 0, 0))]


def test_ipv6_mapped_private_ipv4_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns6("::ffff:10.0.0.1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://bypass.example.com/repo")


def test_ipv6_mapped_loopback_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns6("::ffff:127.0.0.1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://bypass.example.com/repo")


def test_ipv6_link_local_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns6("fe80::1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://bypass.example.com/repo")


def test_ipv6_ula_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns6("fd00::1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://bypass.example.com/repo")
