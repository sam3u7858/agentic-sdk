import ipaddress
import socket
from typing import Any, Dict, Optional
from urllib.parse import urlparse


_BLOCKED_HEADER_KEYS = {
    "host",
    "content-length",
    "connection",
    "cookie",
    "authorization",
    "proxy-authorization",
    "x-forwarded-for",
    "x-real-ip",
}


def validate_outbound_url(url: str) -> Optional[str]:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"}:
        return "Only http/https URLs are allowed."
    if not parsed.netloc:
        return "URL must include hostname."
    if parsed.username or parsed.password:
        return "URL credentials are not allowed."

    host = (parsed.hostname or "").strip()
    if not host:
        return "URL must include hostname."

    direct_ip_error = _reject_ip_literal(host)
    if direct_ip_error:
        return direct_ip_error

    dns_error = _reject_host_by_dns(host)
    if dns_error:
        return dns_error
    return None


def sanitize_request_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    if not isinstance(headers, dict):
        return sanitized
    for key, value in headers.items():
        key_str = str(key).strip()
        if not key_str:
            continue
        key_l = key_str.lower()
        if key_l in _BLOCKED_HEADER_KEYS:
            continue
        sanitized[key_str] = str(value)
    return sanitized


def is_textual_content_type(content_type: str) -> bool:
    ct = str(content_type or "").lower()
    if not ct:
        return True
    if ct.startswith("text/"):
        return True
    if "json" in ct:
        return True
    if "xml" in ct:
        return True
    if "javascript" in ct:
        return True
    if "x-www-form-urlencoded" in ct:
        return True
    return False


def is_json_content_type(content_type: str) -> bool:
    return "json" in str(content_type or "").lower()


def _reject_ip_literal(host: str) -> Optional[str]:
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        return None
    if _is_private_or_local_ip(ip_obj):
        return "Target host resolves to a private/local IP, request blocked."
    return None


def _reject_host_by_dns(host: str) -> Optional[str]:
    host_l = host.lower()
    if host_l in {"localhost", "localhost.localdomain"} or host_l.endswith(".local"):
        return "Localhost/local domain targets are blocked."

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return "DNS resolution failed for target host."

    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_raw = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_raw)
        except ValueError:
            continue
        if _is_private_or_local_ip(ip_obj):
            return "Target host resolves to a private/local IP, request blocked."
    return None


def _is_private_or_local_ip(ip_obj: Any) -> bool:
    return bool(
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )
