"""카카오 로컬 API 클라이언트 — 좌표 → 법정동코드·지번 (docs/30 §2 `address/reverse`, docs/03 D5).

이용 조건(`data/README.md` "카카오 지도·로컬 API 이용 조건"): 응답은 요청을 처리하는 동안
한 번만 쓰고 저장·캐시·로그하지 않는다(가공한 값 포함). 요청 URL에 좌표가 들어가므로
이 모듈의 예외 메시지에 URL·좌표·REST 키를 넣지 않는다.
"""

from dataclasses import dataclass
from typing import Any

import httpx2

KAKAO_REGION_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"
KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
TIMEOUT_SECONDS = 5.0
LEGAL_DONG_TYPE = "B"  # `region_type`: B 법정동, H 행정동
_NUMBER_MAX = 9999  # 본번·부번은 PNU에서 4자리씩이다


class KakaoUnavailableError(Exception):
    """네트워크·HTTP 오류, 키 문제, 읽을 수 없는 응답. 메시지에 좌표·키를 넣지 않는다."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"kakao unavailable ({reason})")
        self.reason = reason


@dataclass(frozen=True)
class KakaoLot:
    is_san: bool
    main: int
    sub: int


@dataclass(frozen=True)
class KakaoSpot:
    """좌표 한 점의 법정동코드·지번·주소 문자열. 모르는 값은 `None` (ADR-003)."""

    legal_dong_code: str | None
    lot: KakaoLot | None
    jibun_addr: str | None
    road_addr: str | None
    building_name: str | None

    @property
    def pnu(self) -> str | None:
        """법정동코드(10) + 산 여부(일반 '1', 산 '2') + 본번(4) + 부번(4) (docs/10 §2.1)."""
        if self.legal_dong_code is None or self.lot is None:
            return None
        lot = self.lot
        return f"{self.legal_dong_code}{'2' if lot.is_san else '1'}{lot.main:04d}{lot.sub:04d}"


def _documents(payload: Any) -> list[Any]:
    documents = payload.get("documents") if isinstance(payload, dict) else None
    if not isinstance(documents, list):
        raise KakaoUnavailableError("unexpected_format")
    return documents


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def parse_region(payload: Any) -> str | None:
    """`coord2regioncode` 응답 → 법정동코드 10자리. 법정동 문서가 없거나 코드가 이상하면 `None`."""
    for document in _documents(payload):
        if isinstance(document, dict) and document.get("region_type") == LEGAL_DONG_TYPE:
            code = document.get("code")
            if isinstance(code, str) and len(code) == 10 and code.isdigit():
                return code
            return None
    return None


def _number(value: Any, *, empty_is_zero: bool) -> int | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text == "" and empty_is_zero:
        return 0  # 공식 가이드: 부번이 "없을 경우 빈 문자열("") 반환"
    if not text.isdigit() or int(text) > _NUMBER_MAX:
        return None
    return int(text)


def _lot(address: dict[str, Any]) -> KakaoLot | None:
    mountain = address.get("mountain_yn")
    main = _number(address.get("main_address_no"), empty_is_zero=False)
    sub = _number(address.get("sub_address_no"), empty_is_zero=True)
    if mountain not in ("Y", "N") or main is None or sub is None:
        return None
    return KakaoLot(is_san=mountain == "Y", main=main, sub=sub)


def parse_address(payload: Any, legal_dong_code: str | None) -> KakaoSpot:
    """`coord2address` 응답 → `KakaoSpot`. 주소가 없는 지점은 모든 값이 `None`."""
    documents = _documents(payload)
    first = documents[0] if documents else None
    if not isinstance(first, dict):
        return KakaoSpot(legal_dong_code, None, None, None, None)
    address = first.get("address")
    road = first.get("road_address")
    address = address if isinstance(address, dict) else {}
    road = road if isinstance(road, dict) else {}
    return KakaoSpot(
        legal_dong_code=legal_dong_code,
        lot=_lot(address) if address else None,
        jibun_addr=_text(address.get("address_name")),
        road_addr=_text(road.get("address_name")),
        building_name=_text(road.get("building_name")),
    )


class KakaoClient:
    def __init__(
        self, rest_api_key: str, http: httpx2.AsyncClient, timeout: float = TIMEOUT_SECONDS
    ) -> None:
        self._rest_api_key = rest_api_key
        self._http = http
        self._timeout = timeout

    async def _get(self, url: str, lat: float, lng: float) -> Any:
        try:
            response = await self._http.get(
                url,
                params={"x": str(lng), "y": str(lat)},  # 카카오는 x = 경도, y = 위도
                headers={"Authorization": f"KakaoAK {self._rest_api_key}"},
                timeout=self._timeout,
            )
        except httpx2.HTTPError as exc:
            raise KakaoUnavailableError(type(exc).__name__) from None
        if response.status_code != 200:
            raise KakaoUnavailableError(f"http_{response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise KakaoUnavailableError("invalid_json") from None

    async def locate(self, lat: float, lng: float) -> KakaoSpot:
        """좌표 → 법정동코드(`coord2regioncode`)와 지번·주소(`coord2address`). 두 번 부른다."""
        code = parse_region(await self._get(KAKAO_REGION_URL, lat, lng))
        return parse_address(await self._get(KAKAO_ADDRESS_URL, lat, lng), code)
