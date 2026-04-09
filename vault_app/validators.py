import socket
import ipaddress
from dataclasses import dataclass
from urllib.parse import quote, urlparse


@dataclass(frozen=True)
class SiteInfo:
    display: str
    normalized: str


def parse_site(site: str) -> SiteInfo | None:
    raw = site.strip()
    if not raw or any(char.isspace() for char in raw):
        return None

    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = parsed.hostname

    if not parsed.scheme or not host:
        return None

    try:
        normalized_host = ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        normalized_host = host.rstrip(".").lower()

    if not normalized_host:
        return None

    port = parsed.port
    if (parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443):
        port = None

    authority = f"{normalized_host}:{port}" if port else normalized_host
    normalized = f"{parsed.scheme.lower()}://{authority}"
    return SiteInfo(display=authority, normalized=normalized)


def normalize_site(site: str) -> str:
    info = parse_site(site)
    return info.normalized if info else ""


def is_valid_site(site: str) -> bool:
    return parse_site(site) is not None


def site_exists(site: str) -> bool:
    info = parse_site(site)
    if info is None:
        return False

    parsed = urlparse(info.normalized)
    host = parsed.hostname
    if not host:
        return False

    try:
        socket.gethostbyname(host)
        return True
    except socket.gaierror:
        return False


def coerce_legacy_site(site: str) -> SiteInfo:
    info = parse_site(site)
    if info:
        return info

    raw = site.strip() or "unknown"
    # Для старых некорректных значений сохраняем отображаемое имя как есть,
    # а служебный ключ делаем безопасным и предсказуемым.
    return SiteInfo(display=raw, normalized=f"legacy://{quote(raw, safe='')}")
