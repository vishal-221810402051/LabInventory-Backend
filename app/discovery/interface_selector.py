from __future__ import annotations

import ipaddress
import socket


def validate_advertise_ip(value: str) -> str:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        msg = f"Invalid mDNS advertise IP address: {value}"
        raise ValueError(msg) from exc
    if ip.version != 4:
        msg = "mDNS advertise IP must be IPv4."
        raise ValueError(msg)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        msg = "mDNS advertise IP must be a non-loopback, non-APIPA unicast address."
        raise ValueError(msg)
    if not ip.is_private:
        msg = "mDNS advertise IP must be a private LAN address."
        raise ValueError(msg)
    return str(ip)


def select_advertise_ip(override: str | None = None) -> str:
    if override:
        return validate_advertise_ip(override)

    candidates = _hostname_candidates()
    candidates.extend(_udp_route_candidates())
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return validate_advertise_ip(candidate)
        except ValueError:
            continue

    msg = "No active non-loopback private IPv4 address could be selected for mDNS."
    raise RuntimeError(msg)


def _hostname_candidates() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except socket.gaierror:
        return []
    return [info[4][0] for info in infos]


def _udp_route_candidates() -> list[str]:
    candidates: list[str] = []
    for target in ("8.8.8.8", "1.1.1.1"):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.connect((target, 80))
                candidates.append(sock.getsockname()[0])
            except OSError:
                continue
    return candidates
