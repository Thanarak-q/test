"""model_validate and manage_model against real MySQL and Redis."""

import pytest
from sqlalchemy import select

from app.envelope import AppError
from app.models import LlmModelAuditLog
from app.services.model_catalogue import (
    MODEL_CACHE_KEY,
    ValidatedModel,
    manage_model,
    model_validate,
)
from app.services.session_auth import Principal

ADMIN = Principal(user_id=900, role="admin")


class CountingFactory:
    """Wraps the session factory and counts sessions opened."""

    def __init__(self, inner):
        self.inner = inner
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return self.inner()


async def test_validates_an_enabled_model_and_caches_it(db, redis):
    model = await model_validate(redis, db, "  gpt-4o \n", kind="chat")

    assert (model.name, model.context_window, model.max_output_tokens) == (
        "gpt-4o",
        128_000,
        16_384,
    )
    assert await redis.hexists(MODEL_CACHE_KEY, "gpt-4o")
    assert 0 < await redis.ttl(MODEL_CACHE_KEY) <= 300


async def test_a_cache_hit_does_not_touch_the_database(db, redis):
    await model_validate(redis, db, "gpt-4o", kind="chat")
    counting = CountingFactory(db)

    model = await model_validate(redis, counting, "gpt-4o", kind="chat")

    assert model.name == "gpt-4o"
    assert counting.opened == 0


@pytest.mark.parametrize("name", ["GPT-4o", "gpt-4", "gpt-4o-mini", "4o", "gpt", ""])
async def test_only_an_exact_name_matches(db, redis, name):
    with pytest.raises(AppError) as exc_info:
        await model_validate(redis, db, name, kind="chat")

    assert exc_info.value.status_code == (400 if not name else 403)


@pytest.mark.parametrize("value", [None, 5, ["gpt-4o"], "   "])
async def test_a_missing_model_is_400_with_no_default(db, redis, value):
    with pytest.raises(AppError) as exc_info:
        await model_validate(redis, db, value, kind="chat")

    assert (exc_info.value.status_code, exc_info.value.code) == (
        400,
        "llm_model_required",
    )


async def test_redis_down_falls_back_to_the_database(db, unreachable_redis):
    model = await model_validate(unreachable_redis, db, "gpt-4.1", kind="chat")

    assert model.name == "gpt-4.1"


def test_a_validated_model_cannot_be_forged():
    with pytest.raises(TypeError):
        ValidatedModel(model_id=1, name="x", context_window=1, max_output_tokens=1)


async def test_disabling_a_model_audits_and_clears_the_cache(db, redis):
    model = await model_validate(redis, db, "gpt-4o", kind="chat")

    async with db() as session:
        await manage_model(
            session,
            redis,
            principal=ADMIN,
            model_id=model.model_id,
            status="disabled",
            source_ip="203.0.113.1",
            request_id="req-9",
        )

    assert not await redis.exists(MODEL_CACHE_KEY)
    with pytest.raises(AppError) as exc_info:
        await model_validate(redis, db, "gpt-4o", kind="chat")
    assert exc_info.value.status_code == 403
    async with db() as session:
        audit = (await session.execute(select(LlmModelAuditLog))).scalar_one()
    assert (audit.action, audit.actor_id, audit.actor_type, audit.target_id) == (
        "model.disabled",
        ADMIN.user_id,
        "admin",
        model.model_id,
    )


async def test_manage_model_checks_the_role_itself(db, redis):
    async with db() as session:
        with pytest.raises(AppError) as exc_info:
            await manage_model(
                session,
                redis,
                principal=Principal(user_id=1, role="user"),
                model_id=1,
                status="disabled",
                source_ip=None,
                request_id=None,
            )

    assert exc_info.value.status_code == 403


async def test_unknown_model_is_404(db, redis):
    async with db() as session:
        with pytest.raises(AppError) as exc_info:
            await manage_model(
                session,
                redis,
                principal=ADMIN,
                model_id=999,
                status="disabled",
                source_ip=None,
                request_id=None,
            )

    assert exc_info.value.status_code == 404


async def test_failed_cache_invalidation_is_500(db, unreachable_redis):
    async with db() as session:
        with pytest.raises(AppError) as exc_info:
            await manage_model(
                session,
                unreachable_redis,
                principal=ADMIN,
                model_id=1,
                status="disabled",
                source_ip=None,
                request_id=None,
            )

    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "llm_model_change_pending"
