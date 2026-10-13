"""검색 일치율 측정 (docs/50 §7 사전 등록 기준, ADR-028). 여기는 순수 함수만 둔다.

표본을 뽑는 방법·검색어를 만드는 법·실패 유형은 측정 전에 docs/50 §7에 적은 그대로다.
결과를 본 뒤에는 바꾸지 않는다.
"""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

SEED = 20261013  # 첫 측정. 재측정은 20261014 (docs/50 §7)
REMEASURE_SEED = 20261014
SAMPLE_SIZE = 2000

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class RecordKey:
    license_type: str
    mgmt_no: str


def sample_rank(seed: int, key: RecordKey) -> str:
    """표본 순위: `sha256("{seed}:{license_type}:{mgmt_no}")`의 16진 문자열."""
    return hashlib.sha256(f"{seed}:{key.license_type}:{key.mgmt_no}".encode()).hexdigest()


def draw_sample(
    population: Iterable[RecordKey], seed: int = SEED, size: int = SAMPLE_SIZE
) -> list[RecordKey]:
    """순위가 작은 것부터 `size`건. 모집단의 순서와 무관하게 같은 결과가 나온다."""
    ranked = sorted({key: sample_rank(seed, key) for key in population}.items(), key=_rank_then_key)
    return [key for key, _ in ranked[:size]]


def _rank_then_key(item: tuple[RecordKey, str]) -> tuple[str, str, str]:
    key, rank = item
    return rank, key.license_type, key.mgmt_no


def keyword_of(road_addr: str) -> str:
    """도로명주소의 기본부: 첫 쉼표 또는 첫 여는 괄호 앞까지, 공백은 하나로."""
    base = re.split(r"[,(]", road_addr, maxsplit=1)[0]
    return _WHITESPACE.sub(" ", base).strip()
