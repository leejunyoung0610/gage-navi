"""W0 재현 테스트 (docs/50 §3, docs/10 §7.4, T-020).

서울 일반음식점 2026-10-08 스냅샷(UTF-8 변환 파일, 환경 변수 `W0_SEOUL_CSV`)으로
`method_version='w0'`를 계산해 `analysis/README.md` §4.2~§4.5의 숫자와 견준다.

기대값과 허용 오차는 이 파일보다 먼저 커밋한 `w0_expected.json`에만 있다. 건수는 정확히, 나머지는
리포트에 적힌 자릿수로 반올림한 문자열이 같아야 한다. 다르게 나오면 기대값·자릿수를 고치지 않고
원인을 먼저 보고한다.
"""

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.location.ingest.license_file import (
    JIBUN_ADDR,
    MGMT_NO,
    ROAD_ADDR,
    has_seoul_address,
    iter_rows,
)
from app.location.normalize.records import (
    AREA_COLUMN,
    CATEGORY_COLUMN,
    CLOSED_ON_COLUMN,
    OPENED_ON_COLUMN,
    STATUS_COLUMN,
    STATUS_MAP,
    parse_area,
    parse_date,
)
from app.location.stats.card import ModelCardPayload, compute_w0

ENV = "W0_SEOUL_CSV"
EXPECTED = json.loads((Path(__file__).parent / "w0_expected.json").read_text(encoding="utf-8"))


def load_records(path: Path) -> pd.DataFrame:
    """원문 행 → `compute_w0`가 받는 열. 정규화(`normalize.records`)와 같은 방식으로 읽는다.

    서울 밖 주소 행과 날짜가 역전된 행은 `license_record`에 없으므로 여기서도 뺀다.
    """
    rows = []
    for number, row in enumerate(iter_rows(path, "utf-8-sig")):
        if not has_seoul_address(row):
            continue
        opened, closed = parse_date(row[OPENED_ON_COLUMN]), parse_date(row[CLOSED_ON_COLUMN])
        if opened is not None and closed is not None and closed < opened:
            continue
        rows.append(
            {
                "id": number,
                "mgmt_no": row[MGMT_NO],
                "status": STATUS_MAP.get(row[STATUS_COLUMN].strip()),
                "opened_on": opened,
                "closed_on": closed,
                "area_m2": parse_area(row[AREA_COLUMN]),
                "biz_category": row[CATEGORY_COLUMN].strip() or None,
                "jibun_addr": row[JIBUN_ADDR].strip() or None,
                "road_addr": row[ROAD_ADDR].strip() or None,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def card() -> ModelCardPayload:
    path = os.environ.get(ENV)
    if not path:
        pytest.skip(
            f"환경 변수 {ENV}가 없습니다. 서울 일반음식점 2026-10-08 파일을 UTF-8로 바꾼 경로를 "
            "넣으면 실행합니다 (data/README.md, iconv -f CP949 -t UTF-8)."
        )
    if not Path(path).is_file():
        pytest.skip(f"{ENV}가 가리키는 파일이 없습니다: {path}")
    return compute_w0(load_records(Path(path))).card


def pct(events: int, n: int) -> str:
    return f"{100 * events / n:.1f}"


def test_cohort(card: ModelCardPayload) -> None:
    events = sum(bucket.events for bucket in card.base_rates)
    got = {"n": card.data.n, "event_rate_pct": pct(events, card.data.n)}
    assert got == EXPECTED["cohort"]


def test_base_rates(card: ModelCardPayload) -> None:
    got = [{"bucket": b.bucket, "n": b.n, "rate_pct": pct(b.events, b.n)} for b in card.base_rates]
    assert got == EXPECTED["base_rates"]


def test_logit(card: ModelCardPayload) -> None:
    logit = card.logit
    assert logit is not None
    got = {
        "or_per_prior": f"{logit.or_per_prior:.3f}",
        "ci": [f"{value:.3f}" for value in logit.ci],
        "p": f"{logit.p:.1e}",
    }
    assert got == EXPECTED["logit"]


def test_logit_with_other_floor(card: ModelCardPayload) -> None:
    assert card.logit is not None
    other = card.logit.with_other_floor_control
    assert other is not None
    got = {
        "or_per_prior": f"{other.or_per_prior:.3f}",
        "ci": [f"{value:.3f}" for value in other.ci],
        "or_other_floor": f"{other.or_other_floor:.3f}",
    }
    assert got == EXPECTED["logit_with_other_floor"]


def test_by_sigungu(card: ModelCardPayload) -> None:
    got: dict[str, dict[str, Any]] = {}
    for item in card.by_sigungu:
        assert item.or_ is not None and item.ci is not None, item.sigungu
        got[item.sigungu] = {
            "sigungu": item.sigungu,
            "n": item.n,
            "or": f"{item.or_:.3f}",
            "ci": [f"{value:.3f}" for value in item.ci],
        }
    want = {item["sigungu"]: item for item in EXPECTED["by_sigungu"]}
    assert got == want


def test_by_sigungu_summary(card: ModelCardPayload) -> None:
    fits = [item for item in card.by_sigungu if item.or_ is not None and item.ci is not None]
    got = {
        "or_above_1": sum(item.or_ > 1 for item in fits if item.or_ is not None),
        "ci_low_above_1": sum(item.ci[0] > 1 for item in fits if item.ci is not None),
        "ci_high_below_1": sum(item.ci[1] < 1 for item in fits if item.ci is not None),
    }
    assert got == EXPECTED["by_sigungu_summary"]


def test_out_of_time(card: ModelCardPayload) -> None:
    out = card.out_of_time
    assert out is not None
    got = {"auc_base": f"{out.auc_base:.4f}", "auc_with_prior": f"{out.auc_with_prior:.4f}"}
    assert got == EXPECTED["out_of_time"]


def test_expected_file_is_self_consistent() -> None:
    """기대값 파일 자체의 점검 (데이터 없이도 돈다): 버킷·시군구 n의 합 = 코호트 n."""
    n = EXPECTED["cohort"]["n"]
    assert sum(bucket["n"] for bucket in EXPECTED["base_rates"]) == n
    assert sum(item["n"] for item in EXPECTED["by_sigungu"]) == n
    assert len(EXPECTED["by_sigungu"]) == 25
    for bucket in EXPECTED["base_rates"]:
        assert Decimal(bucket["rate_pct"]).as_tuple().exponent == -1
