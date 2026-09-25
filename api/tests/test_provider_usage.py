"""Usage validation: implausible is not the same as wrong, and a truthful
high count is never replaced by a lower estimate."""

import math

from app.services.provider import _validate_embedding_usage, validate_usage


def test_chat_charges_a_well_formed_count_above_the_fallback():
    usage = {"prompt_tokens": 1_000, "completion_tokens": 5, "total_tokens": 1_005}

    assert validate_usage(usage, est_input=100, cap_tokens=10) == (
        1_000,
        5,
        1_005,
        False,
    )


def test_chat_charges_the_fallback_when_it_is_higher():
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    prompt = math.ceil(100 * 1.1)
    assert validate_usage(usage, est_input=100, cap_tokens=10) == (
        prompt,
        10,
        prompt + 10,
        False,
    )


def test_chat_malformed_usage_is_never_trusted_even_when_high():
    usage = {"prompt_tokens": 1_000, "completion_tokens": 5, "total_tokens": 7}

    assert (
        validate_usage(usage, est_input=100, cap_tokens=10)[2]
        == math.ceil(100 * 1.1) + 10
    )


def test_embeddings_charge_a_well_formed_count_above_the_fallback():
    usage = {"prompt_tokens": 1_000, "total_tokens": 1_000}

    assert _validate_embedding_usage(usage, est_input=100) == (1_000, 1_000)


def test_embeddings_charge_the_fallback_when_it_is_higher():
    usage = {"prompt_tokens": 10, "total_tokens": 10}

    assert (
        _validate_embedding_usage(usage, est_input=100) == (math.ceil(100 * 1.1),) * 2
    )
