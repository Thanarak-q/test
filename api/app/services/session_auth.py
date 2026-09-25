"""Who is calling the dashboard endpoints: the main application's session.

Key management and usage are called from the browser with the main app's
session, never with an API key. user_id comes from here or from a verified
key record — nowhere else, and there is no fallback user in any environment.
"""

from dataclasses import dataclass
from typing import Literal

from fastapi import Request

from app.config import Settings, settings
from app.envelope import AppError

Role = Literal["user", "admin"]


@dataclass(frozen=True)
class Principal:
    user_id: int
    role: Role


def check_session_config(config: Settings = settings) -> None:
    """Refuse to boot with the dev override set outside ENV=dev."""
    if config.dev_session_user_id is not None and config.env != "dev":
        raise RuntimeError(
            "DEV_SESSION_USER_ID is set but ENV is "
            f"{config.env!r}; the dev session override only exists in dev."
        )


async def resolve_principal(request: Request, config: Settings = settings) -> Principal:
    # Checked here as well as at startup, so the override stays off even if
    # settings are changed after boot.
    if config.env == "dev" and config.dev_session_user_id is not None:
        return Principal(
            user_id=config.dev_session_user_id, role=config.dev_session_role
        )

    principal = await _verify_main_app_session(request)
    if principal is None:
        raise AppError("identity_unauthenticated", "Sign in to continue.", 401)
    return principal


def ensure_admin(principal: Principal) -> None:
    """Call inside every admin service function, not only at the route.

    A route-level check alone is one forgotten dependency away from an open
    admin endpoint; the service is the last place that can refuse.
    """
    if principal.role != "admin":
        raise AppError("identity_forbidden", "You do not have access to this.", 403)


async def _verify_main_app_session(request: Request) -> Principal | None:
    # TODO(session): verify the main application's session here — cookie
    # name, JWT or server-side, and whether it can be verified locally are
    # still open (CLAUDE_CODE_BRIEF.md, open question 1). Until then every
    # request outside the dev override is unauthenticated: fail closed.
    return None
