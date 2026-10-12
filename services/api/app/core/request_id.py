"""요청 ID (ULID: 시각 48비트 + 난수 80비트, Crockford base32 26자)."""

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_request_id() -> str:
    value = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    return "".join(_ALPHABET[(value >> shift) & 31] for shift in range(125, -1, -5))
