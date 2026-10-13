"""기준율 잡: 저장, 재실행, 판정이 깨지면 저장하지 않음, 층 규모별 저장 (T-019, T-019b).

기록은 모두 가상 예시다.
"""

import json
from datetime import date
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import get_engine
from app.location.stats.job import BaseRateResult, compute_base_rates
from jobs import compute_base_rates as cli
from tests.integration.test_build_history import execute, fetch_all, with_engine
from tests.unit.test_stats_model import crowded, synthetic

AS_OF = date(2026, 10, 7)
INSERT = """
INSERT INTO license_record
  (license_type, mgmt_no, jurisdiction_code, name, biz_category, status, status_raw, opened_on,
   closed_on, area_m2, pnu, sigungu_code, floor, parse_version)
VALUES (:license_type, :mgmt_no, '3040000', '가상업소', :biz_category, :status, :status,
        :opened_on, :closed_on, :area_m2, :pnu, :sigungu_code, :floor, '2026.10.1')
"""


def load(url: str, records: pd.DataFrame) -> None:
    rows = [
        {**row, "mgmt_no": f"M{row['id']}"}
        for row in records.astype(object).where(records.notna(), None).to_dict("records")
    ]

    async def work(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            for table in ("base_rate", "model_card", "license_record", "legal_dong"):
                await conn.execute(text(f"DELETE FROM {table}"))
            await conn.execute(
                text(
                    "INSERT INTO legal_dong (code, sido, sigungu, full_name) VALUES "
                    "('1121510700', '서울특별시', '광진구', '서울특별시 광진구 화양동'), "
                    "('1144010100', '서울특별시', '마포구', '서울특별시 마포구 아현동')"
                )
            )
            await conn.execute(text(INSERT), rows)

    with_engine(url, work)


def run(url: str, method_version: str = "2026.10.1") -> BaseRateResult:
    result: BaseRateResult = with_engine(
        url, lambda engine: compute_base_rates(engine, method_version, AS_OF)
    )
    return result


def counts(url: str) -> tuple[Any, ...]:
    return fetch_all(
        url, "SELECT (SELECT count(*) FROM base_rate), (SELECT count(*) FROM model_card)"
    )[0]


def test_saves_base_rates_and_model_card(migrated_db_url: str) -> None:
    load(migrated_db_url, synthetic(seed=1, effect=0.10, floors=600))
    result = run(migrated_db_url)
    assert result.holds and result.saved

    rows = fetch_all(
        migrated_db_url,
        "SELECT scope_code, prior_bucket, n, events, rate, ci_low, ci_high, cohort_from, cohort_to,"
        " snapshot_label, method_version, license_group FROM base_rate"
        " WHERE floor_scale = 'all' ORDER BY scope_code, prior_bucket",
    )
    assert {row[0] for row in rows} == {"11", "11215", "11440"}
    seoul = [row for row in rows if row[0] == "11"]
    assert [row[1] for row in seoul] == ["0", "1", "2", "3", "4+"]
    for row in rows:
        assert row[5] <= row[4] <= row[6]
        assert row[7:] == (date(2005, 1, 1), date(2023, 10, 8), "2026-10", "2026.10.1", "food3")
    # 시군구 합 = 서울
    assert sum(row[2] for row in rows if row[0] != "11") == sum(row[2] for row in seoul)

    ((payload, label),) = fetch_all(
        migrated_db_url, "SELECT payload, snapshot_label FROM model_card"
    )
    payload = payload if isinstance(payload, dict) else json.loads(payload)
    assert label == "2026-10"
    assert payload["robustness"] == {"holds": True, "failures": []}
    assert [b["n"] for b in payload["base_rates"]] == [row[2] for row in seoul]
    assert {item["sigungu"] for item in payload["by_sigungu"]} == {"광진구", "마포구"}

    # 다시 실행해도 같은 결과 (행이 늘지 않는다)
    before = counts(migrated_db_url)
    run(migrated_db_url)
    assert counts(migrated_db_url) == before


def test_saves_base_rates_only_for_floor_scales_that_hold(
    migrated_db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    # 단독 층에는 효과가 있고, 소형 복수 층에는 효과가 없다. 대형 층은 없다
    records = pd.concat(
        [synthetic(seed=1, effect=0.10, floors=1500), crowded(seed=5, effect=0.0, floors=300)],
        ignore_index=True,
    )
    load(migrated_db_url, records.assign(id=range(1, len(records) + 1)))
    result = run(migrated_db_url)
    assert result.holds and result.saved
    scales = result.computation.card.by_floor_scale
    assert scales is not None
    assert (scales.single.holds, scales.small.holds, scales.large.holds) == (True, False, False)

    saved = fetch_all(
        migrated_db_url,
        "SELECT floor_scale, count(*), count(DISTINCT scope_code) FROM base_rate"
        " GROUP BY floor_scale ORDER BY 1",
    )
    assert [row[0] for row in saved] == ["all", "single"]  # 깨진 규모의 행은 없다
    ((payload,),) = fetch_all(migrated_db_url, "SELECT payload FROM model_card")
    payload = payload if isinstance(payload, dict) else json.loads(payload)
    assert payload["by_floor_scale"]["small"]["holds"] is False
    assert payload["by_floor_scale"]["small"]["buckets"]  # 깨진 규모의 값도 카드에는 있다
    single = fetch_all(
        migrated_db_url,
        "SELECT prior_bucket, n FROM base_rate WHERE floor_scale = 'single' AND scope_code = '11'"
        " ORDER BY prior_bucket",
    )
    assert single == [
        (bucket["bucket"], bucket["n"]) for bucket in payload["by_floor_scale"]["single"]["buckets"]
    ]

    # 다시 실행해도 같은 결과
    rates = (
        "SELECT scope_code, floor_scale, prior_bucket, n, events, rate, ci_low, ci_high"
        " FROM base_rate ORDER BY 1, 2, 3"
    )
    before = fetch_all(migrated_db_url, rates)
    run(migrated_db_url)
    assert fetch_all(migrated_db_url, rates) == before

    # CLI: 규모가 깨져도 종료 코드는 0, 무엇이 깨졌는지 출력한다
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    get_engine.cache_clear()
    out = tmp_path / "base_rates.md"
    try:
        code = cli.main(["--as-of", AS_OF.isoformat(), "--out", str(out)])
    finally:
        get_engine.cache_clear()
    assert code == 0
    assert "층 규모 판정이 깨졌습니다: 소형 복수(2~9), (b)" in capsys.readouterr().err
    assert "깨진 규모가 있다" in out.read_text(encoding="utf-8")


def test_does_not_save_when_conclusion_breaks(
    migrated_db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    load(migrated_db_url, synthetic(seed=3, effect=0.0, floors=600))
    result = run(migrated_db_url)
    assert not result.holds and not result.saved
    assert counts(migrated_db_url) == (0, 0)

    # CLI: 리포트는 쓰고 종료 코드 2
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    get_engine.cache_clear()
    out = tmp_path / "base_rates.md"
    try:
        code = cli.main(["--as-of", AS_OF.isoformat(), "--out", str(out)])
    finally:
        get_engine.cache_clear()
    assert code == cli.EXIT_NOT_ROBUST
    assert "쓰지 않았다" in out.read_text(encoding="utf-8")
    assert "결론 유지 판정이 깨졌습니다" in capsys.readouterr().err
    assert counts(migrated_db_url) == (0, 0)


def test_w0_mode_saves_under_its_own_version(migrated_db_url: str) -> None:
    load(migrated_db_url, synthetic(seed=1, effect=0.10, floors=50))
    execute(
        migrated_db_url,
        "UPDATE license_record"
        " SET jibun_addr = '서울특별시 광진구 화양동 ' || id % 40 + 1 || ' 1층'",
    )
    result = run(migrated_db_url, "w0")
    assert result.saved and result.as_of == date(2026, 10, 8)
    assert fetch_all(
        migrated_db_url,
        "SELECT DISTINCT method_version, license_group, scope_code, cohort_to FROM base_rate",
    ) == [("w0", "general_restaurant", "11", date(2023, 10, 8))]
