from unittest.mock import patch

from app.services import api_keys
from app.services.validate_api_key import _parse_token


def test_ulid_timestamp_matches_the_spec_example():
    # ulid/spec: 1469918176385 ms encodes to the time part "01ARYZ6S41".
    with patch.object(api_keys.time, "time_ns", return_value=1469918176385 * 10**6):
        assert api_keys._new_ulid()[:10] == "01ARYZ6S41"


def test_generated_keys_parse_as_valid_tokens():
    key_id = api_keys._new_ulid()
    token = f"{api_keys.key_prefix(key_id)}_{'A1b2C3d4' * 4}"

    assert _parse_token(token) == (key_id, "A1b2C3d4" * 4)
