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

/** `["0.3920", "0.4710"]` → `39.2~47.1%` */
export function formatRateRange([lo, hi]: readonly [string, string]): string {
  return `${permilleText(toPermille(lo))}~${permilleText(toPermille(hi))}%`;
}

/** `["0.3920", "0.4710"]` → `(95% 신뢰구간 39.2~47.1%)` */
export function formatRateCi(ci: readonly [string, string]): string {
  return `(95% 신뢰구간 ${formatRateRange(ci)})`;
}

/**
 * 모형 카드의 부동소수 비율(Kaplan–Meier 추정 등) `0.5237` → `52.4%`. 소수 4자리 문자열로 바꾼 뒤
 * `formatRate`와 같은 규칙으로 반올림한다
 */
export function formatFloatRate(rate: number): string {
  return formatRate(floatToDecimal(rate));
}

/** `[0.51, 0.53]` → `51.0~53.0%` */
export function formatFloatRateRange([lo, hi]: readonly [number, number]): string {
  return formatRateRange([floatToDecimal(lo), floatToDecimal(hi)]);
}

function floatToDecimal(rate: number): string {
  if (!Number.isFinite(rate) || rate < 0) throw new RangeError(`비율이 아니에요: ${rate}`);
  return rate.toFixed(4);
}

/** 오즈비·AUC 같은 통계량 `1.100948` → `1.101` (소수 셋째 자리) */
export function formatStat(value: number): string {
  if (!Number.isFinite(value)) throw new RangeError(`숫자가 아니에요: ${value}`);
  return value.toFixed(3);
}

/** 통계량 구간 `[1.084, 1.118]` → `1.084~1.118` */
export function formatStatRange([lo, hi]: readonly [number, number]): string {
  return `${formatStat(lo)}~${formatStat(hi)}`;
}

/** p값 `2.9e-34` → `0.001 미만`, `0.0213` → `0.021` */
export function formatPValue(p: number): string {
  if (!Number.isFinite(p) || p < 0 || p > 1) throw new RangeError(`p값이 아니에요: ${p}`);
  return p < 0.001 ? "0.001 미만" : p.toFixed(3);
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

/** 타임라인 연월 `"2011-03-02"` → `2011.03` */
export function formatYearMonth(value: string): string {
  const { year, month } = parseDate(value);
  return `${year}.${String(month).padStart(2, "0")}`;
}

/** 타임라인 기간 `2011.03 – 2013.08` */
export function formatPeriod(start: string, end: string): string {
  return `${formatYearMonth(start)} – ${formatYearMonth(end)}`;
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

/** 건수 `14532` → `14,532` */
export function formatCount(count: number): string {
  return groupFormat.format(count);
}

/** 스냅샷 표기 `"2026-11"` → `2026년 11월` */
export function formatSnapshotLabel(label: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(label);
  if (!match) throw new RangeError(`YYYY-MM 스냅샷이 아니에요: ${label}`);
  return `${match[1]}년 ${Number(match[2])}월`;
}

/** 층 값(URL 표기) `B1` → `지하 1층`, `1` → `1층`, `RF` → `옥탑` */
export function formatFloor(floor: string): string {
  if (floor === "RF") return "옥탑";
  const basement = /^B([1-9])$/.exec(floor);
  if (basement) return `지하 ${basement[1]}층`;
  if (/^[1-9]\d?$/.test(floor)) return `${floor}층`;
  throw new RangeError(`층 값이 아니에요: ${floor}`);
}

/** 두 날짜(`YYYY-MM-DD`) 사이의 달력 개월 수. 끝 날짜의 일이 시작 일보다 작으면 1개월 덜 센다 */
export function monthsBetween(start: string, end: string): number {
  const a = parseDate(start);
  const b = parseDate(end);
  const months = (b.year - a.year) * 12 + (b.month - a.month) - (b.day < a.day ? 1 : 0);
  return Math.max(0, months);
}

/** 일수 → 개월 수(내림). 1461일 = 48개월(윤년 포함 4년)로 정수 연산만 쓴다 */
export function daysToMonths(days: number): number {
  if (!Number.isSafeInteger(days) || days < 0) {
    throw new RangeError(`0 이상의 정수 일수가 아니에요: ${days}`);
  }
  return Math.floor((days * 48) / 1461);
}
