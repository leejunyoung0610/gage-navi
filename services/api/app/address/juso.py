"""도로명주소 검색 API 클라이언트 (docs/03 D4, docs/10 §2.2).

승인키와 검색어는 POST 본문으로만 보낸다. 요청 URL은 고정이라 URL이 찍히는 곳
(HTTP 클라이언트 로그, 예외 메시지)에 승인키·검색어가 남지 않는다.
이 모듈의 예외 메시지에도 승인키·검색어를 넣지 않는다.
"""

import re
from dataclasses import dataclass
from typing import Any

import httpx2

JUSO_SEARCH_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
COUNT_PER_PAGE = 10  # 검색 화면 첫 페이지 후보 수 (docs/40 §4.2)
TIMEOUT_SECONDS = 5.0
CONNECTION_REASON = "connection_"  # `JusoUnavailableError.reason` 접두어: 연결 실패·시간 초과

# 검색어 문제로 돌아오는 오류코드 (공식 가이드 「검색API 활용 가이드」 2.2 에러코드)
KEYWORD_ERROR_CODES = frozenset(
    {"E0005", "E0006", "E0008", "E0009", "E0010", "E0011", "E0012", "E0013", "E0015"}
)

# 공식 가이드 4.1 "API 호출 전에 검색어(keyword) 정제": 아래 예약어와 특수문자가 든 검색어는
# 차단될 수 있다. 예약어는 낱말 단위로만 지운다(건물명 안의 글자는 건드리지 않는다).
_SQL_WORDS = (
    "or", "select", "insert", "delete", "update", "create", "drop", "exec", "union", "fetch",
    "declare", "truncate",
)  # fmt: skip
_SQL_WORD = re.compile(r"(?<![A-Za-z])(?:" + "|".join(_SQL_WORDS) + r")(?![A-Za-z])", re.I)
_BLOCKED_CHARS = re.compile(r"[%=<>\[\]'\"+;]")
_WHITESPACE = re.compile(r"\s+")
_NUMBER_MAX = 9999  # 본번·부번은 PNU에서 4자리씩이다
_REL_LOT = re.compile(r"^(?P<san>산)?(?P<main>\d+)(?:-(?P<sub>\d+))?$")


class JusoError(Exception):
    """도로명주소 API 호출 실패. 메시지에 승인키·검색어를 넣지 않는다."""


class JusoKeywordError(JusoError):
    """검색어를 API가 받지 않았다 (너무 짧음, 시도명만 입력 등)."""

    def __init__(self, code: str) -> None:
        super().__init__(f"juso keyword rejected ({code})")
        self.code = code


class JusoUnavailableError(JusoError):
    """네트워크·HTTP 오류, 승인키 문제, 읽을 수 없는 응답."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"juso unavailable ({reason})")
        self.reason = reason


@dataclass(frozen=True)
class RelatedLot:
    """관련지번 한 개. 법정동은 이름만 있다(코드는 `legal_dong`에서 찾는다)."""

    dong_name: str  # '서울특별시 광진구 화양동' (`legal_dong.full_name`과 같은 꼴)
    is_san: bool
    main: int
    sub: int


@dataclass(frozen=True)
class JusoItem:
    road_addr: str
    jibun_addr: str
    building_name: str | None
    pnu: str | None  # 응답 필드로 PNU를 만들 수 없으면 None (기본값으로 채우지 않는다)
    related_lots: tuple[RelatedLot, ...] = ()  # 같은 건물의 관련지번 (`relJibun`, docs/30 §2)


@dataclass(frozen=True)
class JusoPage:
    items: tuple[JusoItem, ...]
    page: int
    total: int


def clean_keyword(keyword: str) -> str:
    """차단 대상 특수문자와 SQL 예약어를 지우고 공백을 하나로 줄인다."""
    cleaned = _BLOCKED_CHARS.sub(" ", keyword)
    cleaned = _SQL_WORD.sub(" ", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


def _digits(value: Any) -> str | None:
    text = str(value).strip() if isinstance(value, str | int) else ""
    return text if text.isdigit() else None


def pnu_from_juso(adm_cd: Any, mt_yn: Any, lnbr_mnnm: Any, lnbr_slno: Any) -> str | None:
    """`admCd` + 산 여부(`mtYn` '0' → '1', '1' → '2') + 본번 4자리 + 부번 4자리 (docs/10 §2.2)."""
    code = _digits(adm_cd)
    main = _digits(lnbr_mnnm)
    sub = _digits(lnbr_slno)
    if code is None or len(code) != 10 or main is None or sub is None:
        return None
    if mt_yn not in ("0", "1") or int(main) > _NUMBER_MAX or int(sub) > _NUMBER_MAX:
        return None
    return f"{code}{'2' if mt_yn == '1' else '1'}{int(main):04d}{int(sub):04d}"


def parse_related_lots(rel_jibun: Any, sido: Any) -> tuple[RelatedLot, ...]:
    """관련지번 `서울특별시 광진구 자양동 225-79,화양동 4-1,4-3` → 지번 목록 (docs/30 §2).

    법정동 이름은 바뀔 때만 적혀 있어 앞 이름을 이어 쓴다. 이름 낱말이 시도(`sido`)로 시작하면
    통째로 바꾸고, 아니면 앞 이름의 끝 낱말을 그만큼 바꾼다(`화양동` → `… 광진구 화양동`).
    읽을 수 없는 항목은 건너뛴다. 형식이 달라도 예외를 내지 않는다(추가 항목은 바뀔 수 있다).
    """
    if not isinstance(rel_jibun, str):
        return ()
    lots: list[RelatedLot] = []
    prefix: list[str] | None = None
    for entry in rel_jibun.split(","):
        words = entry.split()
        if not words:
            continue
        names, lot = words[:-1], _REL_LOT.match(words[-1])
        if names:
            if prefix is None or names[0] == sido:
                prefix = names
            elif len(names) < len(prefix):
                prefix = prefix[: len(prefix) - len(names)] + names
            else:
                prefix = None
        if lot is None or prefix is None:
            continue
        main, sub = int(lot["main"]), int(lot["sub"] or 0)
        if main > _NUMBER_MAX or sub > _NUMBER_MAX:
            continue
        lots.append(RelatedLot(" ".join(prefix), lot["san"] is not None, main, sub))
    return tuple(lots)


def parse_response(payload: Any, page: int) -> JusoPage:
    """JSON 응답(`results.common`, `results.juso`) → `JusoPage`."""
    try:
        results = payload["results"]
        common = results["common"]
        code = str(common["errorCode"])
    except (KeyError, TypeError):
        raise JusoUnavailableError("unexpected_format") from None
    if code in KEYWORD_ERROR_CODES:
        raise JusoKeywordError(code)
    if code != "0":
        raise JusoUnavailableError(f"error_code_{code}")
    rows = results.get("juso") or []
    try:
        total = int(common["totalCount"])
        items = tuple(
            JusoItem(
                road_addr=str(row["roadAddr"]),
                jibun_addr=str(row["jibunAddr"]),
                building_name=str(row.get("bdNm") or "") or None,
                pnu=pnu_from_juso(
                    row.get("admCd"), row.get("mtYn"), row.get("lnbrMnnm"), row.get("lnbrSlno")
                ),
                related_lots=parse_related_lots(row.get("relJibun"), row.get("siNm")),
            )
            for row in rows
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise JusoUnavailableError("unexpected_format") from None
    return JusoPage(items=items, page=page, total=total)


class JusoClient:
    def __init__(
        self, confm_key: str, http: httpx2.AsyncClient, timeout: float = TIMEOUT_SECONDS
    ) -> None:
        self._confm_key = confm_key
        self._http = http
        self._timeout = timeout

    async def fetch(self, keyword: str, page: int, *, add_info: bool = False) -> Any:
        """응답 JSON을 그대로 돌려준다 (녹화 잡과 `search`가 함께 쓴다).

        `add_info`: 관련지번(`relJibun`) 등 추가 항목을 같은 호출로 함께 받는다(`addInfoYn=Y`).
        주소 검색 프록시(`search`, `related_pnus`)와 검색 일치율 측정의 불일치 사유 분류가 쓴다.
        """
        form = {
            "confmKey": self._confm_key,
            "currentPage": str(page),
            "countPerPage": str(COUNT_PER_PAGE),
            "keyword": keyword,
            "resultType": "json",
        }
        if add_info:
            form["addInfoYn"] = "Y"
        try:
            response = await self._http.post(JUSO_SEARCH_URL, data=form, timeout=self._timeout)
        except httpx2.TransportError as exc:  # 연결 실패·시간 초과 등
            raise JusoUnavailableError(f"{CONNECTION_REASON}{type(exc).__name__}") from None
        except httpx2.HTTPError as exc:
            raise JusoUnavailableError(type(exc).__name__) from None
        if response.status_code != 200:
            raise JusoUnavailableError(f"http_{response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise JusoUnavailableError("invalid_json") from None

    async def search(self, keyword: str, page: int) -> JusoPage:
        return parse_response(await self.fetch(keyword, page, add_info=True), page)
