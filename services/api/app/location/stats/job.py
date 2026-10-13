"""기준율·모형 카드 계산: `license_record` → `base_rate`·`model_card` (docs/10 §7.2·§7.3).

결론 유지 판정이 깨지면 두 테이블을 바꾸지 않는다. 같은 입력이면 같은 결과가 된다.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.location.history.build import METHOD_VERSION
from app.location.history.job import default_as_of
from app.location.stats import w0
from app.location.stats.card import Computation, compute, compute_w0, quantize

METHOD_VERSIONS = (METHOD_VERSION, w0.METHOD_VERSION)

_COLUMNS = (
    "id",
    "license_type",
    "pnu",
    "floor",
    "status",
    "opened_on",
    "closed_on",
    "bulk_closure",
    "stale_suspect",
    "stale_area_match",
    "no_fixed_place",
    "biz_category",
    "area_m2",
    "sigungu_code",
)
_W0_COLUMNS = (
    "id",
    "status",
    "opened_on",
    "closed_on",
    "area_m2",
    "biz_category",
    "jibun_addr",
    "road_addr",
)
# 시군구 이름: 폐지되지 않은 법정동의 이름이 뒤에 와서 우선한다
_SIGUNGU = """
SELECT DISTINCT left(code, 5), sigungu, abolished FROM legal_dong
WHERE sigungu IS NOT NULL ORDER BY abolished DESC
"""
_DELETE_RATES = """
DELETE FROM base_rate
WHERE snapshot_label = :snapshot_label AND method_version = :method_version
  AND license_group = :license_group
"""
_INSERT_RATE = """
INSERT INTO base_rate (snapshot_label, method_version, scope_code, license_group, prior_bucket,
                       n, events, rate, ci_low, ci_high, cohort_from, cohort_to)
VALUES (:snapshot_label, :method_version, :scope_code, :license_group, :prior_bucket,
        :n, :events, :rate, :ci_low, :ci_high, :cohort_from, :cohort_to)
"""
_UPSERT_CARD = """
INSERT INTO model_card (snapshot_label, method_version, payload)
VALUES (:snapshot_label, :method_version, CAST(:payload AS JSONB))
ON CONFLICT (snapshot_label, method_version)
DO UPDATE SET payload = EXCLUDED.payload, created_at = now()
"""


@dataclass(frozen=True)
class BaseRateResult:
    as_of: date
    computation: Computation
    saved: bool  # 판정이 깨지면 저장하지 않는다

    @property
    def holds(self) -> bool:
        robustness = self.computation.card.robustness
        return robustness is None or robustness.holds


async def _frame(conn: AsyncConnection, columns: tuple[str, ...], where: str = "") -> pd.DataFrame:
    rows = (
        await conn.execute(text(f"SELECT {', '.join(columns)} FROM license_record {where}"))
    ).all()
    return pd.DataFrame(rows, columns=list(columns))


async def _save(conn: AsyncConnection, computation: Computation) -> None:
    key = {
        "snapshot_label": computation.card.data.snapshot_label,
        "method_version": computation.method_version,
    }
    await conn.execute(text(_DELETE_RATES), {**key, "license_group": computation.license_group})
    rows = [
        {
            **key,
            "license_group": computation.license_group,
            "scope_code": item.scope_code,
            "prior_bucket": item.rate.bucket,
            "n": item.rate.n,
            "events": item.rate.events,
            "rate": quantize(item.rate.rate),
            "ci_low": quantize(item.rate.ci_low),
            "ci_high": quantize(item.rate.ci_high),
            "cohort_from": computation.cohort_from,
            "cohort_to": computation.cohort_to,
        }
        for item in computation.rates
    ]
    if rows:
        await conn.execute(text(_INSERT_RATE), rows)
    payload = computation.card.model_dump_json(by_alias=True)
    await conn.execute(text(_UPSERT_CARD), {**key, "payload": payload})


async def compute_base_rates(
    engine: AsyncEngine, method_version: str = METHOD_VERSION, as_of: date | None = None
) -> BaseRateResult:
    """기준율과 모형 카드를 계산하고, 판정이 유지되면 저장한다.

    `as_of`를 주지 않으면 스냅샷의 데이터 기준일을 쓴다. `w0`는 기준일이 고정이다(docs/10 §7.4).
    """
    if method_version not in METHOD_VERSIONS:
        raise ValueError(f"method_version은 {METHOD_VERSIONS} 중 하나여야 합니다: {method_version}")
    async with engine.begin() as conn:
        if method_version == w0.METHOD_VERSION:
            as_of = w0.AS_OF
            general = await _frame(conn, _W0_COLUMNS, "WHERE license_type = 'general_restaurant'")
            computation = compute_w0(general)
        else:
            if as_of is None:
                as_of = await default_as_of(conn)
            records = await _frame(conn, _COLUMNS)
            labels = {str(code): str(name) for code, name, _ in await conn.execute(text(_SIGUNGU))}
            computation = compute(records, as_of, labels)
        robustness = computation.card.robustness
        saved = robustness is None or robustness.holds
        if saved:
            await _save(conn, computation)
    return BaseRateResult(as_of=as_of, computation=computation, saved=saved)
