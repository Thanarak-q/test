import ipaddress
from collections.abc import Iterable

from fastapi import HTTPException, Request

HTTPS_REQUIRED_MESSAGE = (
    "HTTPS is required. Update your client to use https:// and revoke this "
    "key, as it was transmitted unencrypted."
)
UNTRUSTED_PROXY_MESSAGE = "Request must arrive through a trusted proxy."


def build_trusted_proxy_set(trusted_proxy_ips: Iterable[str]) -> frozenset[str]:
    """Normalise trusted proxy addresses once, at startup."""
    return frozenset(
        str(ipaddress.ip_address(address)) for address in trusted_proxy_ips
    )


def require_https(request: Request, trusted_proxies: frozenset[str]) -> str:
    """Reject anything that did not reach us over HTTPS, and return the peer.

    The peer address is verified first because X-Forwarded-Proto is only
    trustworthy when the proxy overwrites it with proxy_set_header — otherwise
    a caller could simply send the header themselves.

    Returns the verified peer so the next step does not repeat the check.
    """
    peer = request.client.host if request.client else None
    if peer not in trusted_proxies:
        raise HTTPException(status_code=400, detail=UNTRUSTED_PROXY_MESSAGE)

    protocol = request.headers.get("X-Forwarded-Proto", "").strip().lower()
    if protocol != "https":
        # No redirect: the request already carried the key over plaintext, so
        # redirecting would only hide the mistake. A hard failure is what
        # prompts the caller to fix the client and rotate the key.
        raise HTTPException(status_code=400, detail=HTTPS_REQUIRED_MESSAGE)

    return peer
