"""지번주소 → PNU 19자리 (docs/10 §2.1).

PNU = 법정동코드(10) + 산 여부(일반 '1', 산 '2') + 본번(4) + 부번(4).
여기는 순수 함수만 둔다. `legal_dong` 행은 호출하는 쪽이 읽어 `LegalDongIndex`로 넘긴다.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

FAIL_REGEX_MISMATCH = "regex_mismatch"
FAIL_DONG_NOT_FOUND = "dong_not_found"
FAIL_AMBIGUOUS = "ambiguous"

SIDO = "서울특별시"

_WHITESPACE = re.compile(r"\s+")
_JIBUN = re.compile(
    r"^서울특별시\s+(?P<sigungu>\S+구)\s+(?P<dong>\S+)\s+"
    r"(?P<san>산\s*)?(?P<main>\d+)(?:-(?P<sub>\d+))?(?P<tail>.*)$"
)
_NUMBER_MAX = 9999  # 본번·부번은 PNU에서 4자리씩이다


@dataclass(frozen=True)
class JibunParts:
    sigungu: str
    dong: str
    is_san: bool
    main: int
    sub: int  # 부번이 없거나 0이면 0
    tail: str  # 번지 뒤 나머지. 층·호 파싱에 쓴다

    @property
    def full_name(self) -> str:
        return f"{SIDO} {self.sigungu} {self.dong}"


@dataclass(frozen=True)
class CodeLookup:
    code: str | None
    failure: str | None
    abolished_only: bool = False  # 현행 코드가 없어 폐지 코드를 썼다


@dataclass(frozen=True)
class PnuResult:
    pnu: str | None
    failure: str | None
    abolished_only: bool = False


class LegalDongIndex:
    """`full_name` → 법정동코드 조회 표. 같은 이름에 코드가 여럿일 때의 규칙은 docs/10 §2.1."""

    def __init__(self, current: dict[str, list[str]], abolished: dict[str, list[str]]) -> None:
        self._current = current
        self._abolished = abolished

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[str, str, bool]]) -> "LegalDongIndex":
        """`rows`: `(code, full_name, abolished)`."""
        current: dict[str, list[str]] = {}
        abolished: dict[str, list[str]] = {}
        for code, full_name, is_abolished in rows:
            (abolished if is_abolished else current).setdefault(full_name, []).append(code)
        return cls(current, abolished)

    def lookup(self, full_name: str) -> CodeLookup:
        current = self._current.get(full_name, [])
        if len(current) == 1:
            return CodeLookup(current[0], None)
        if len(current) > 1:
            return CodeLookup(None, FAIL_AMBIGUOUS)
        abolished = self._abolished.get(full_name, [])
        if len(abolished) == 1:
            return CodeLookup(abolished[0], None, abolished_only=True)
        if len(abolished) > 1:
            return CodeLookup(None, FAIL_AMBIGUOUS)
        return CodeLookup(None, FAIL_DONG_NOT_FOUND)


def parse_jibun(addr: str | None) -> JibunParts | None:
    """지번주소를 나눈다. 정규식에 맞지 않거나 본번·부번이 4자리를 넘으면 `None`."""
    if addr is None:
        return None
    match = _JIBUN.match(_WHITESPACE.sub(" ", addr).strip())
    if match is None:
        return None
    main = int(match["main"])
    sub = int(match["sub"]) if match["sub"] is not None else 0
    if main > _NUMBER_MAX or sub > _NUMBER_MAX:
        return None
    return JibunParts(
        sigungu=match["sigungu"],
        dong=match["dong"],
        is_san=match["san"] is not None,
        main=main,
        sub=sub,
        tail=match["tail"].strip(),
    )


def _format_pnu(code: str, parts: JibunParts) -> str:
    return f"{code}{'2' if parts.is_san else '1'}{parts.main:04d}{parts.sub:04d}"


def to_pnu(parts: JibunParts, index: LegalDongIndex) -> str | None:
    found = index.lookup(parts.full_name)
    return None if found.code is None else _format_pnu(found.code, parts)


def build_pnu(addr: str | None, index: LegalDongIndex) -> PnuResult:
    """주소 하나의 PNU와 실패 사유. 실패율 집계(docs/10 §2.1)에 쓴다."""
    parts = parse_jibun(addr)
    if parts is None:
        return PnuResult(None, FAIL_REGEX_MISMATCH)
    found = index.lookup(parts.full_name)
    if found.code is None:
        return PnuResult(None, found.failure)
    return PnuResult(_format_pnu(found.code, parts), None, found.abolished_only)
