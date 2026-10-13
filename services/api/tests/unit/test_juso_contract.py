"""도로명주소 API 계약 테스트 — 실제 응답을 녹화한 픽스처 (T-021 수용 기준, docs/03 D4).

픽스처는 `python -m jobs.record_juso_fixtures`로 만든다. 여기서는 API를 호출하지 않는다.
"""

import json
import os
import re
from typing import Any

import pytest

from app.address.juso import JusoKeywordError, parse_response
from jobs.record_juso_fixtures import CASES, FIXTURE_DIR

HTTP_FIXTURE_ROOT = FIXTURE_DIR.parent
# docs/03 D4 "사용 필드"
USED_FIELDS = (
    "roadAddr", "jibunAddr", "admCd", "mtYn", "lnbrMnnm", "lnbrSlno", "bdMgtSn", "bdNm",
)  # fmt: skip
# 승인키는 `U01TX0FVVEg`(base64 "SMS_AUTH")가 든 문자열로 발급된다
KEY_PATTERNS = (re.compile(r"confmKey", re.I), re.compile(r"U01TX0FVVEg"))


def load(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / f"{name}.json"
    assert path.exists(), f"녹화 픽스처가 없습니다: {path.name} (jobs.record_juso_fixtures)"
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def rows(name: str) -> list[dict[str, Any]]:
    juso: list[dict[str, Any]] = load(name)["response"]["results"]["juso"]
    return juso


def test_every_case_is_recorded() -> None:
    recorded = {path.stem for path in FIXTURE_DIR.glob("*.json")}
    assert recorded == {name for name, _, _ in CASES}


def test_fixtures_contain_no_key() -> None:
    files = [path for path in HTTP_FIXTURE_ROOT.rglob("*") if path.is_file()]
    assert files, "녹화 픽스처가 없습니다"
    secret = os.environ.get("JUSO_CONFM_KEY", "")
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern in KEY_PATTERNS:
            assert not pattern.search(text), f"{path.name}: 승인키로 보이는 문자열"
        if secret:
            assert secret not in text, f"{path.name}: 승인키가 들어 있습니다"


def test_fixture_documents_hold_only_keyword_page_and_response() -> None:
    for name, keyword, page in CASES:
        document = load(name)
        assert set(document) == {"source", "recorded_on", "request", "response"}
        assert document["request"] == {"keyword": keyword, "currentPage": page, "countPerPage": 10}


@pytest.mark.parametrize(
    "name",
    [
        "guide_sample",
        "single_parcel",
        "mountain_lot",
        "many_results_p1",
        "many_results_p2",
        "single_parcel_add_info",
        "mountain_lot_add_info",
    ],
)
def test_used_fields_exist_and_make_pnu(name: str) -> None:
    juso = rows(name)
    assert juso
    for row in juso:
        for field in USED_FIELDS:
            assert field in row, f"{name}: 응답에 {field} 없음"
        assert re.fullmatch(r"\d{10}", row["admCd"])
        assert row["mtYn"] in ("0", "1")
    page = parse_response(load(name)["response"], page=1)
    assert len(page.items) == len(juso) <= 10
    for item in page.items:
        assert item.pnu is not None and re.fullmatch(r"\d{10}[12]\d{8}", item.pnu)


def test_guide_sample_pnu() -> None:
    # 공식 가이드 예시(성암로 301): admCd 1144012700, mtYn 0, lnbrMnnm 1595, lnbrSlno 0
    page = parse_response(load("guide_sample")["response"], page=1)
    assert "1144012700115950000" in {item.pnu for item in page.items}


def test_mountain_lot_has_san_digit() -> None:
    assert any(row["mtYn"] == "1" for row in rows("mountain_lot"))
    page = parse_response(load("mountain_lot")["response"], page=1)
    assert any(item.pnu is not None and item.pnu[10] == "2" for item in page.items)


def test_many_results_paging() -> None:
    first = parse_response(load("many_results_p1")["response"], page=1)
    second = parse_response(load("many_results_p2")["response"], page=2)
    assert first.total == second.total > 10
    assert len(first.items) == 10
    assert {i.road_addr for i in first.items}.isdisjoint({i.road_addr for i in second.items})


def test_no_result() -> None:
    page = parse_response(load("no_result")["response"], page=1)
    assert page.items == () and page.total == 0


def test_keyword_too_broad_is_keyword_error() -> None:
    with pytest.raises(JusoKeywordError):
        parse_response(load("keyword_too_broad")["response"], page=1)


def test_related_lots_format() -> None:
    # T-021b: 추가 항목(`addInfoYn=Y`)의 관련지번을 읽는다 (불일치 분류용, docs/50 §7)
    from app.address.search_match import parse_rel_jibun

    for name in ("single_parcel_add_info", "mountain_lot_add_info"):
        juso = rows(name)
        assert all("relJibun" in row for row in juso)
        for row in juso:
            lots = parse_rel_jibun(row["relJibun"])
            assert len(lots) == len([e for e in row["relJibun"].split(",") if e.strip()])
    campus = parse_rel_jibun(rows("single_parcel_add_info")[0]["relJibun"])
    assert ("자양동", False, 225, 79) in campus and ("화양동", False, 4, 1) in campus
    assert any(lot[1] for lot in parse_rel_jibun(rows("mountain_lot_add_info")[0]["relJibun"]))
