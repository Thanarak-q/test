"""Shared helpers for trusting the reverse proxy in front of the API."""

import ipaddress
from collections.abc import Iterable

from fastapi import HTTPException, Request

UNTRUSTED_REQUEST_MESSAGE = "Request must arrive through a trusted proxy."
HTTPS_REQUIRED_MESSAGE = "HTTPS is required. Update your client to use https://"


def build_trusted_proxy_set(trusted_proxy_ips: Iterable[str]) -> frozenset[str]:
    """Normalise trusted proxy addresses once, at startup.

    Doing this per request would add work to the path that exists to reject
    floods as cheaply as possible.
    """
    return frozenset(
        str(ipaddress.ip_address(address)) for address in trusted_proxy_ips
    )


def require_https(request: Request, trusted_proxies: frozenset[str]) -> str:
    """Reject anything that did not reach us over HTTPS, and return the peer.

    The peer address is verified first because X-Forwarded-Proto is only
    trustworthy when the proxy overwrites it with proxy_set_header. Without
    that check a caller could simply send the header themselves.

    Returns the verified peer so later steps can prove they ran after this one
    instead of repeating the check.
    """
    peer = request.client.host if request.client else None
    if peer not in trusted_proxies:
        raise _untrusted_request()

    protocol = request.headers.get("X-Forwarded-Proto", "").strip().lower()
    if protocol != "https":
        # No redirect: the request already carried the key over plaintext, so
        # redirecting would only hide the mistake. A hard failure is what
        # prompts the caller to fix the client and rotate the key.
        raise HTTPException(status_code=400, detail=HTTPS_REQUIRED_MESSAGE)

    return peer


def get_client_ip(request: Request, verified_peer: str) -> str:
    """Resolve the caller's IP from a request already verified by require_https.

    Taking the verified peer as an argument means this cannot be called on a
    request that skipped the proxy check — there is no way to obtain the
    argument otherwise.

    X-Real-IP is set by nginx with proxy_set_header, which overwrites whatever
    the client sent. X-Forwarded-For is appended to instead, so its leftmost
    values are attacker-controlled and its rightmost value is the real client
    only when exactly one proxy sits in front of us. Requiring X-Real-IP keeps
    the trusted path unambiguous.
    """
    client_ip = request.headers.get("X-Real-IP")
    if client_ip is None:
        raise _untrusted_request()

    try:
        return str(ipaddress.ip_address(client_ip.strip()))
    except ValueError as exc:
        raise _untrusted_request() from exc


def _untrusted_request() -> HTTPException:
    """One message for every proxy or client-IP failure.

    Distinct messages would tell a caller which stage of the pipeline they
    reached, which helps nobody except someone probing it.
    """
    return HTTPException(status_code=400, detail=UNTRUSTED_REQUEST_MESSAGE)
