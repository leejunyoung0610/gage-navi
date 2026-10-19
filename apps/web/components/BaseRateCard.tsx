import Link from "next/link";

import { formatCount, formatRate, formatRateRange, formatSnapshotLabel } from "@/lib/format";
import type { BaseRate } from "@/lib/place";

/** 층 규모 문구 (docs/40 §4.4-3, T-019b) */
export const SCALE_LABELS: Record<BaseRate["floor_scale"], string> = {
  single: "한 점포가 쓰던 층",
  small: "여러 점포가 함께 있던 층(2~9곳)",
  large: "점포가 많은 층(10곳 이상)",
};

/** 버킷 `0`~`3` → "0회"~"3회", `4+` → "4회 이상" (docs/40 §4.4-3) */
export function bucketLabel(bucket: string): string {
  if (bucket === "4+") return "4회 이상";
  if (/^[0-3]$/.test(bucket)) return `${bucket}회`;
  throw new RangeError(`버킷이 아니에요: ${bucket}`);
}

const TEXT = {
  title: "비슷한 자리의 3년 내 폐업률",
  notReady: "이 자리의 통계는 아직 준비 중이에요.",
  insufficient: "비슷한 이력의 자리가 충분하지 않아(200곳 미만) 통계를 보여드리지 않아요.",
  notConfirmed:
    "이 정도 규모의 층에서는 과거 폐업 횟수와 폐업률의 관계가 검증 기준을 통과하지 못했어요",
  reference: "참고 통계예요. 이 자리에 열 가게의 성패를 예측하지 않아요.",
  how: "어떻게 계산했나요?",
} as const;

/** 소수 문자열 비율 → 막대 위치(CSS 퍼센트). 화면 배치용이고 숫자 표시는 `lib/format`이 한다 */
function cssPercent(rate: string): string {
  return `${Math.min(100, Math.max(0, Number(rate) * 100))}%`;
}

function CiBar({
  label,
  rate,
  ci,
}: {
  label: string;
  rate: string;
  ci: readonly [string, string];
}) {
  const [lo, hi] = ci;
  return (
    <div>
      <p className="text-sm">
        {label} <span className="font-bold">{formatRate(rate)}</span>{" "}
        <span className="text-muted">({formatRateRange(ci)})</span>
      </p>
      <div className="bg-line relative mt-1 h-3 w-full rounded-full" aria-hidden="true">
        <div
          className="bg-brand/40 absolute top-0 h-3 rounded-full"
          style={{ left: cssPercent(lo), width: `calc(${cssPercent(hi)} - ${cssPercent(lo)})` }}
        />
        <div
          className="bg-brand-strong absolute top-0 h-3 w-1 -translate-x-1/2 rounded"
          style={{ left: cssPercent(rate) }}
        />
      </div>
    </div>
  );
}

function MethodologyLink() {
  return (
    <Link href="/methodology" className="min-h-touch inline-flex items-center underline">
      {TEXT.how}
    </Link>
  );
}

/** 기준율 카드 (docs/40 §4.4-3). 판단 문장에 상호를 넣지 않는다 */
export function BaseRateCard({ baseRate }: { baseRate: BaseRate | null }) {
  return (
    <section aria-label={TEXT.title} className="border-line rounded-xl border p-4">
      <h2 className="font-bold">{TEXT.title}</h2>
      <Body baseRate={baseRate} />
    </section>
  );
}

function Body({ baseRate }: { baseRate: BaseRate | null }) {
  if (baseRate === null) return <p className="mt-2">{TEXT.notReady}</p>;
  if (!baseRate.display || !baseRate.primary || !baseRate.baseline) {
    // 규모에서 판정이 깨졌으면 비율·신뢰구간 없이 그 사실만 (docs/40 §4.4-3)
    const message =
      baseRate.hidden_reason === "not_confirmed_for_floor_scale"
        ? TEXT.notConfirmed
        : TEXT.insufficient;
    return (
      <>
        <p className="mt-2">{message}</p>
        <MethodologyLink />
      </>
    );
  }
  const { primary, baseline } = baseRate;
  const bucket = bucketLabel(baseRate.bucket);
  // 기준선이 서울로 대체됐으면 범위를 밝힌다 (docs/30 §2 기준율 선택)
  const baselineScope = baseline.scope_code !== primary.scope_code ? " (서울 기준)" : "";
  return (
    <>
      <p className="mt-2 text-lg">
        이 층처럼 과거 폐업이 <strong>{bucket}</strong>인 자리에 새로 연 가게는 3년 안에{" "}
        <strong className="text-2xl">{formatRate(primary.rate)}</strong>가 문을 닫았어요.
      </p>
      {baseRate.bucket !== "0" && (
        <p className="mt-1">
          과거 폐업이 없던 자리는 {formatRate(baseline.rate)}였어요{baselineScope}.
        </p>
      )}
      <div className="mt-3 space-y-2">
        <CiBar label={`과거 폐업 ${bucket}`} rate={primary.rate} ci={primary.ci} />
        {baseRate.bucket !== "0" && (
          <CiBar label="과거 폐업 없음" rate={baseline.rate} ci={baseline.ci} />
        )}
      </div>
      <p className="text-muted mt-3 text-sm">
        {primary.scope_label} {SCALE_LABELS[baseRate.floor_scale]} {formatCount(primary.n)}곳 기준 ·
        95% 신뢰구간 {formatRateRange(primary.ci)} · {formatSnapshotLabel(baseRate.snapshot_label)}{" "}
        데이터
      </p>
      <p className="mt-3 text-sm">{TEXT.reference}</p>
      <MethodologyLink />
    </>
  );
}
