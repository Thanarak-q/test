"""Token estimates, for rate limiting and quota reservation only.

No tokenizer: an estimate from UTF-8 byte length. English runs about four
bytes per token; Thai is three bytes per character and tokenizes at roughly
one token per character or less, so bytes/4 stays on the high side for both.
Quota is settled with the provider's own count after the call.
"""

import math
from collections.abc import Iterable, Mapping

from app.constants.llm import TOKENS_PER_MESSAGE

_BYTES_PER_TOKEN = 4
_REPLY_PRIMER_TOKENS = 3


def estimate_text_tokens(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / _BYTES_PER_TOKEN)


def estimate_tokens(messages: Iterable[Mapping[str, str]]) -> int:
    """Estimated prompt tokens for a list of {role, content} messages."""
    return _REPLY_PRIMER_TOKENS + sum(
        TOKENS_PER_MESSAGE
        + estimate_text_tokens(message["role"])
        + estimate_text_tokens(message["content"])
        for message in messages
    )
