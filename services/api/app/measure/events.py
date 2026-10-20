"""측정 이벤트 종류와 받는 날짜 범위 (docs/30 `POST /measure/events`). 순수 함수."""

from datetime import date, timedelta
from typing import Literal, get_args

Event = Literal["first_visit", "revisit_7d", "helpful_yes", "helpful_no"]
EVENTS: tuple[Event, ...] = get_args(Event)

# 브라우저·서버 시계와 자정 경계 오차로 하루 여유를 둔다 (docs/30)
SKEW_DAYS = 1
# 재방문은 첫 방문 다음 날부터 7일 안 (docs/70 §5)
REVISIT_WINDOW_DAYS = 7


def date_in_range(event: Event, day: date, today: date) -> bool:
    """`today`(서버의 한국 시간 오늘) 기준으로 받을 수 있는 날짜인가.

    `revisit_7d`의 `day`는 첫 방문 날짜다.
    """
    skew = timedelta(days=SKEW_DAYS)
    if event == "revisit_7d":
        earliest = today - timedelta(days=REVISIT_WINDOW_DAYS) - skew
        return earliest <= day <= today
    return today - skew <= day <= today + skew
