"""수요 검증 측정값 (docs/70 §5 정의). 순수 함수 — 판정은 하지 않고 측정값과 일별 분포만 낸다.

- 순방문 = 기간(1~`days`일차) 첫 방문 이벤트 수
- 재방문율 = 분자 / 분모. 분모는 첫 방문 날짜가 1~(`days`−7)일차인 첫 방문 수(7일 뒤까지 관찰할 수
  있는 사람만), 분자는 첫 방문 날짜가 같은 구간인 "7일 안 재방문" 수
- 예/아니오 = 기간의 클릭 수
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.measure.events import EVENTS, REVISIT_WINDOW_DAYS

RATE_PLACES = Decimal("0.0001")  # docs/30 비율 문자열 소수 4자리


@dataclass(frozen=True)
class DailyRow:
    day: date
    first_visit: int
    revisit_7d: int  # 이 날이 첫 방문 날짜인 재방문
    helpful_yes: int
    helpful_no: int


@dataclass(frozen=True)
class Ratio:
    numerator: int
    denominator: int
    rate: str | None  # 분모가 0이면 None


@dataclass(frozen=True)
class DemandReport:
    start: date
    end: date
    days: int
    unique_visitors: int
    revisit: Ratio
    revisit_cohort_end: date  # 재방문율 분모에 드는 마지막 첫 방문 날짜
    helpful_yes: int
    helpful_no: int
    helpful_yes_share: Ratio
    daily: list[DailyRow]


def ratio(numerator: int, denominator: int) -> Ratio:
    if denominator == 0:
        return Ratio(numerator, denominator, None)
    value = (Decimal(numerator) / Decimal(denominator)).quantize(RATE_PLACES, ROUND_HALF_UP)
    return Ratio(numerator, denominator, str(value))


def period_end(start: date, days: int) -> date:
    return start + timedelta(days=days - 1)


Counts = dict[tuple[date, str], int]


def daily_rows(counts: Counts, start: date, end: date) -> list[DailyRow]:
    """`start`~`end`(포함) 날짜마다 한 줄. 이벤트가 없던 날은 0으로 채운다."""
    days = (end - start).days + 1
    return [
        DailyRow(day, *(counts.get((day, event), 0) for event in EVENTS))
        for day in (start + timedelta(days=i) for i in range(days))
    ]


def demand_report(counts: Counts, start: date, days: int) -> DemandReport:
    """`counts`는 `(날짜, 이벤트) → 합계`(기간 밖 날짜는 무시한다). `start`는 1일차."""
    if days <= REVISIT_WINDOW_DAYS:
        raise ValueError(f"기간은 {REVISIT_WINDOW_DAYS}일보다 길어야 해요")
    end = period_end(start, days)
    cohort_end = period_end(start, days - REVISIT_WINDOW_DAYS)
    daily = daily_rows(counts, start, end)
    cohort = [row for row in daily if row.day <= cohort_end]
    yes = sum(row.helpful_yes for row in daily)
    no = sum(row.helpful_no for row in daily)
    return DemandReport(
        start=start,
        end=end,
        days=days,
        unique_visitors=sum(row.first_visit for row in daily),
        revisit=ratio(sum(r.revisit_7d for r in cohort), sum(r.first_visit for r in cohort)),
        revisit_cohort_end=cohort_end,
        helpful_yes=yes,
        helpful_no=no,
        helpful_yes_share=ratio(yes, yes + no),
        daily=daily,
    )
