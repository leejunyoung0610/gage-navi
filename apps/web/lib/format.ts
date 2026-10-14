/**
 * 화면의 숫자·날짜·금액 형식 (docs/40 §6). 화면 문구는 이 모듈만 쓴다.
 *
 * - 금액은 원 단위 정수(ADR-021). 부동소수 계산을 하지 않는다
 * - 비율은 API가 주는 소수 문자열(`"0.4340"`)을 정수 연산으로 바꾼다. 소수 첫째 자리에서 반올림(0.5는 올림)
 * - 날짜는 `YYYY-MM-DD` 문자열을 그대로 읽는다(`Date`의 시간대 변환을 거치지 않는다)
 */

const UNITS = [
  { size: 1_0000_0000_0000, label: "조" },
  { size: 1_0000_0000, label: "억" },
  { size: 1_0000, label: "만" },
] as const;

const groupFormat = new Intl.NumberFormat("ko-KR");

/** `30000000` → `3,000만 원`, `120000000` → `1억 2,000만 원`, `5000` → `5,000원` */
export function formatWon(won: number): string {
  if (!Number.isSafeInteger(won)) {
    throw new RangeError(`원 단위 정수가 아니에요: ${won}`);
  }
  if (won === 0) return "0원";
  const sign = won < 0 ? "-" : "";
  let rest = Math.abs(won);
  const parts: string[] = [];
  for (const unit of UNITS) {
    const count = Math.floor(rest / unit.size);
    if (count > 0) parts.push(`${groupFormat.format(count)}${unit.label}`);
    rest %= unit.size;
  }
  if (rest > 0) return `${sign}${[...parts, `${groupFormat.format(rest)}원`].join(" ")}`;
  return `${sign}${parts.join(" ")} 원`;
}

const DECIMAL = /^(\d+)(?:\.(\d+))?$/;

/** 소수 문자열 비율을 퍼센트 소수 첫째 자리(정수, 단위 0.1%p)로 바꾼다 */
function toPermille(rate: string): bigint {
  const match = DECIMAL.exec(rate);
  if (!match) throw new RangeError(`비율 문자열이 아니에요: ${JSON.stringify(rate)}`);
  const [, whole = "0", fraction = ""] = match;
  const scale = 10n ** BigInt(fraction.length);
  const scaled = (BigInt(whole) * scale + BigInt(fraction || "0")) * 1000n;
  // 반올림(0.5는 올림): floor((2x + s) / 2s)
  return (2n * scaled + scale) / (2n * scale);
}

function permilleText(permille: bigint): string {
  return `${permille / 10n}.${permille % 10n}`;
}

/** `"0.4340"` → `43.4%` */
export function formatRate(rate: string): string {
  return `${permilleText(toPermille(rate))}%`;
}

/** `["0.3920", "0.4710"]` → `(95% 신뢰구간 39.2~47.1%)` */
export function formatRateCi([lo, hi]: readonly [string, string]): string {
  return `(95% 신뢰구간 ${permilleText(toPermille(lo))}~${permilleText(toPermille(hi))}%)`;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

function parseDate(value: string): { year: number; month: number; day: number } {
  const match = ISO_DATE.exec(value);
  if (match) {
    const [year, month, day] = match.slice(1).map(Number) as [number, number, number];
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    if (month >= 1 && month <= 12 && day >= 1 && day <= lastDay) return { year, month, day };
  }
  throw new RangeError(`YYYY-MM-DD 날짜가 아니에요: ${value}`);
}

/** `"2026-11-20"` → `2026년 11월 20일` */
export function formatDate(value: string): string {
  const { year, month, day } = parseDate(value);
  return `${year}년 ${month}월 ${day}일`;
}

function yearMonth(value: string): string {
  const { year, month } = parseDate(value);
  return `${year}.${String(month).padStart(2, "0")}`;
}

/** 타임라인 기간 `2011.03 – 2013.08` */
export function formatPeriod(start: string, end: string): string {
  return `${yearMonth(start)} – ${yearMonth(end)}`;
}

/** 기간 길이(개월 수) `29` → `2년 5개월` */
export function formatMonths(months: number): string {
  if (!Number.isSafeInteger(months) || months < 0) {
    throw new RangeError(`0 이상의 정수 개월 수가 아니에요: ${months}`);
  }
  const years = Math.floor(months / 12);
  const rest = months % 12;
  if (years === 0) return `${rest}개월`;
  if (rest === 0) return `${years}년`;
  return `${years}년 ${rest}개월`;
}
