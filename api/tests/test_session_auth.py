import pytest
from starlette.requests import Request

from app.config import Settings
from app.envelope import AppError
from app.services.session_auth import (
    Principal,
    check_session_config,
    ensure_admin,
    resolve_principal,
)


def config(**overrides) -> Settings:
    return Settings(
        database_url="mysql://unused", redis_url="redis://unused", **overrides
    )


def request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


@pytest.mark.parametrize("env", ["test", "staging", "production"])
def test_startup_refuses_dev_override_outside_dev(env):
    with pytest.raises(RuntimeError):
        check_session_config(config(env=env, dev_session_user_id=1))


def test_startup_allows_dev_override_in_dev():
    check_session_config(config(env="dev", dev_session_user_id=1))


def test_env_defaults_to_production(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)

    assert Settings(_env_file=None, database_url="x", redis_url="x").env == (
        "production"
    )


async def test_dev_override_resolves_in_dev():
    principal = await resolve_principal(
        request(), config(env="dev", dev_session_user_id=3, dev_session_role="admin")
    )

    assert principal == Principal(user_id=3, role="admin")


@pytest.mark.parametrize("env", ["test", "staging", "production"])
async def test_dev_override_is_ignored_outside_dev(env):
    # Even if startup were bypassed, the override does nothing here.
    with pytest.raises(AppError) as exc_info:
        await resolve_principal(request(), config(env=env, dev_session_user_id=3))

    assert exc_info.value.status_code == 401


async def test_no_session_is_401_with_no_fallback_user():
    with pytest.raises(AppError) as exc_info:
        await resolve_principal(request(), config(env="dev"))

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "identity_unauthenticated"


def test_ensure_admin_rejects_a_user():
    with pytest.raises(AppError) as exc_info:
        ensure_admin(Principal(user_id=1, role="user"))

    assert exc_info.value.status_code == 403


def test_ensure_admin_accepts_an_admin():
    ensure_admin(Principal(user_id=1, role="admin"))
