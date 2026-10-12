"""폐업 시점 분석 (2019~2023년 서울 식품 3종) — analysis/closure_timing.md 재현 스크립트

서비스 코드가 아니다. 이 스크립트가 analysis/closure_timing.md 전체를 만든다.

입력: 서울 식품 3종 인허가 CSV 원본(CP949) 세 개, 순서대로 일반음식점·휴게음식점·제과점영업
실행: python3 -I closure_timing.py 일반음식점.csv 휴게음식점.csv 제과점영업.csv > closure_timing.md
의존: pandas
급증일 표시는 docs/10 §5 규칙(관할별 하루 30건 이상이고 관할 중앙값의 10배 이상, 3종 합산)을
이 파일 안에서 다시 계산한다. 서비스 구현은 services/api/app/location/normalize/bulk_closure.py.
정책 일정(§5)은 출처 기사에서 확인한 값을 그대로 적은 것이다.
"""
import sys

import pandas as pd

START, END = '2019-01-01', '2023-12-31'
YEARS = range(2019, 2024)
MIN_COUNT, MEDIAN_MULTIPLE = 30, 10  # docs/10 §5
KINDS = ['일반', '휴게', '제과']
WEEKDAYS = '월화수목금토일'
GU = r'서울특별시\s+(\S+구)'

cols = ['개방자치단체코드', '영업상태명', '폐업일자', '지번주소', '도로명주소']
df = pd.concat(
    [pd.read_csv(f, dtype=str, keep_default_na=False, usecols=cols, encoding='cp949').assign(kind=k)
     for f, k in zip(sys.argv[1:4], KINDS)], ignore_index=True)
df = df[df['영업상태명'].str.strip().eq('폐업')]
df = df[df['지번주소'].str.startswith('서울특별시') | df['도로명주소'].str.startswith('서울특별시')]
df['closed_on'] = pd.to_datetime(df['폐업일자'].str.strip(), errors='coerce')
df['jurisdiction'] = df['개방자치단체코드'].str.strip()
df = df.dropna(subset=['closed_on'])

# ---- 급증일 표시 (전체 기간 폐업 기록으로 계산) ----
c = df.groupby(['jurisdiction', 'closed_on'])['kind'].transform('size')
per_day = df.drop_duplicates(['jurisdiction', 'closed_on']).assign(c=c)
median = per_day.groupby('jurisdiction')['c'].median()
df['surge'] = (c >= MIN_COUNT) & (c >= MEDIAN_MULTIPLE * df['jurisdiction'].map(median))
df['gu'] = df['지번주소'].str.extract(GU)[0].fillna(df['도로명주소'].str.extract(GU)[0])

p = df[(df.closed_on >= START) & (df.closed_on <= END)]
day = p.groupby('closed_on').agg(
    n=('kind', 'size'), general=('kind', lambda s: int((s == '일반').sum())), surge=('surge', 'sum'))
cell = p.groupby(['closed_on', 'gu']).size()
day['top_gu'] = cell.groupby('closed_on').idxmax().map(lambda key: key[1])
day['top_n'] = cell.groupby('closed_on').max()
kinds = p.kind.value_counts()

out = []
w = out.append
w('# 폐업 시점 분석 — 2019~2023년 서울 식품 3종 (T-000)\n')
w('서비스 코드가 아니라 **설계 근거**다. 폐업일자가 날짜별·월별로 어떻게 몰리는지 재어 둔 기록이다(측정일 2026-10-13). '
  '재현 스크립트: `analysis/closure_timing.py` — 이 파일 전체를 만든다. 관련 결정은 ADR-020(폐업 처리 급증일).\n')

w('## 1. 측정 조건\n')
w('- 파일: `data/raw/2026-10-08/식품_일반음식점_서울특별시.csv`, `data/raw/2026-10-12/식품_휴게음식점_서울특별시.csv`, '
  '`data/raw/2026-10-12/식품_제과점영업_서울특별시.csv` (`data/README.md`)')
w('- 대상: `영업상태명`이 `폐업`이고 `폐업일자`가 있으며 `지번주소` 또는 `도로명주소`가 `서울특별시`로 시작하는 기록 중 '
  f'폐업일자가 {START} ~ {END}인 것')
w(f"- **{len(p):,}건** (일반음식점 {kinds['일반']:,} / 휴게음식점 {kinds['휴게']:,} / 제과점영업 {kinds['제과']:,}). "
  f'폐업이 1건 이상 있었던 날 {len(day):,}일, 하루 건수 중앙값 {day.n.median():.0f}건')
w(f'- 급증일 표시: docs/10 §5 규칙(관할별 하루 {MIN_COUNT}건 이상이고 관할 중앙값의 {MEDIAN_MULTIPLE}배 이상, 식품 3종 합산)을 '
  f'전체 기간 폐업 기록에 적용한 값. 이 기간의 표시 기록 {int(p.surge.sum()):,}건')
w('- "가장 많은 구"는 주소의 구 이름으로 셌다. 급증일 표시는 `개방자치단체코드` 기준이라 조금 다를 수 있다')
w('- 폐업일자는 신고·처리된 날짜다. 실제로 영업을 그만둔 날과 같다는 보장은 없다\n')

w('## 2. 폐업이 많았던 날 상위 30일\n')
w('| 순위 | 날짜 | 요일 | 3종 합계 | 일반음식점 | 급증일 표시 기록 | 가장 많은 구 |\n|---|---|---|---|---|---|---|')
top = day.sort_values('n', ascending=False, kind='stable').head(30)
for rank, (d, r) in enumerate(top.iterrows(), 1):
    w(f'| {rank} | {d.date()} | {WEEKDAYS[d.weekday()]} | {r.n:,} | {r.general:,} | {int(r.surge):,} '
      f'| {r.top_gu} {r.top_n:,} |')
spread = top[top.surge == 0]
w(f'\n- 30일 중 급증일 표시 기록이 0건인 날 {len(spread)}일. 이 날들은 가장 많은 구도 '
  f'{spread.top_n.min()}~{spread.top_n.max()}건이다(한 구에 몰리지 않고 여러 구에 퍼져 있다)\n')

w('## 3. 연말\n')
w('| 연도 | 12월 28일 | 12월 29일 | 12월 30일 | 12월 31일 | 그해 하루 평균 |\n|---|---|---|---|---|---|')
for y in YEARS:
    cells = []
    for dd in (28, 29, 30, 31):
        d = pd.Timestamp(y, 12, dd)
        cells.append(f'{int(day.n.get(d, 0)):,} ({WEEKDAYS[d.weekday()]})')
    g = day[day.index.year == y]
    w(f'| {y} | ' + ' | '.join(cells) + f' | {g.n.sum() / len(g):.1f} |')
year_end = p[(p.closed_on.dt.month == 12) & (p.closed_on.dt.day >= 30)]
month_end = p[p.closed_on.dt.is_month_end]
calendar = pd.date_range(START, END)
w('\n- 하루 평균은 그해 합계 ÷ 폐업이 1건 이상 있었던 날 수')
w(f'- 12월 30~31일 기록 {len(year_end):,}건 중 급증일 표시 {int(year_end.surge.sum())}건')
w(f'- 월의 마지막 날에 폐업한 기록은 전체의 {100 * len(month_end) / len(p):.2f}% (달력에서 월의 마지막 날은 '
  f'{len(calendar):,}일 중 {int(calendar.is_month_end.sum())}일, {100 * calendar.is_month_end.mean():.2f}%)\n')

m = p.assign(y=p.closed_on.dt.year, m=p.closed_on.dt.month).groupby(['m', 'y']).agg(
    n=('kind', 'size'), surge=('surge', 'sum'))
m['ex'] = m.n - m.surge
total = m.groupby('y')[['n', 'ex']].sum()
share = pd.Series({(mm, y): 100 * m.ex[(mm, y)] / total.ex[y] for mm in range(1, 13) for y in YEARS})


def table(values, fmt):
    w('| 월 | ' + ' | '.join(str(y) for y in YEARS) + ' |\n|---|' + '---|' * len(YEARS))
    for mm in range(1, 13):
        w(f'| {mm} | ' + ' | '.join(fmt(values[(mm, y)]) for y in YEARS) + ' |')


def other_years(mm, year):
    values = [share[(mm, y)] for y in YEARS if y != year]
    return f'{min(values):.1f}~{max(values):.1f}%'


w('## 4. 월별 건수\n')
w('### 4.1 3종 합계\n')
table(m.n, lambda v: f'{v:,}')
w('| **합계** | ' + ' | '.join(f'**{total.n[y]:,}**' for y in YEARS) + ' |\n')
w('### 4.2 급증일 표시 기록 제외\n')
table(m.ex, lambda v: f'{v:,}')
w('| **합계** | ' + ' | '.join(f'**{total.ex[y]:,}**' for y in YEARS) + ' |\n')
w('### 4.3 월별 비중 (급증일 표시 기록을 뺀 월별 건수 ÷ 그해 합계, %)\n')
table(share, lambda v: f'{v:.1f}')

december = [share[(12, y)] for y in YEARS]
w('\n## 5. 정책 일정과의 대조\n')
w('소상공인 지원금 세 제도의 지급 시작 달에 폐업 비중(§4.3)이 다른 해 같은 달과 달랐는지 본다. 일정은 아래 출처 기사에 적힌 내용이다.\n')
w('| 제도 | 일정 (출처) | 본 달 | 그 달의 비중 | 다른 해 같은 달 |\n|---|---|---|---|---|')
w('| 버팀목자금 플러스 | 2021-03-29 1차 신속지급 시작. 2021년 2월 말까지 개업한 사업체 대상 [1] | 2021년 4월 '
  f'| **{share[(4, 2021)]:.1f}%** | {other_years(4, 2021)} |')
w('| 손실보전금 | 2022-05-30 ~ 07-29 신청. 2021-12-15 이전 개업, 2021-12-31 기준 영업 [2] | 2022년 6월 '
  f'| **{share[(6, 2022)]:.1f}%** | {other_years(6, 2022)} |')
w(f'| 희망회복자금 | 2021-08-17 지급 시작 [3] | 2021년 8월 | **{share[(8, 2021)]:.1f}%** | {other_years(8, 2021)} |')
w(f'\n- 12월의 비중은 매년 {min(december):.1f}~{max(december):.1f}%로, 정책 일정과 상관없이 해마다 높다(§3 연말)')
w('\n**결론**: 세 제도 중 둘에서 지급 시작 달의 폐업 비중이 다른 해보다 높았다. 인과는 확인하지 않았다.\n')
w('### 출처\n')
w('1. 이투데이, "\'버팀목자금 플러스\', 19일부터 51만 개 사업체에 추가 지급", 2021-04-18. '
  'https://www.etoday.co.kr/news/view/2016606')
w('2. 이투데이, "\'최대 1000만원\' 손실보전금 지급 30일부터..."348만 개사에 신속지급"", 2022-05-30. '
  'https://www.etoday.co.kr/news/view/2138795')
w('3. 이투데이, "희망회복자금, 오늘부터 지급 시작...17ㆍ18일은 홀짝제", 2021-08-17. '
  'https://www.etoday.co.kr/news/view/2054099')
w('\n일정은 위 기사 본문에서 확인했다(2026-10-13 열람). 정부 공고 원문과 대조하지는 않았다.')
sys.stdout.write('\n'.join(out) + '\n')
