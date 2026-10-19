import { formatCount, formatStat, formatStatRange } from "@/lib/format";
import type { SigunguOut } from "@/lib/methodology";

/** 값 → 가로 위치(CSS 퍼센트). 화면 배치용이고 숫자 표시는 `lib/format`이 한다 */
function position(value: number, min: number, max: number): string {
  return `${((value - min) / (max - min)) * 100}%`;
}

/**
 * 시군구별 과거 폐업 1회당 오즈비 점그래프 (docs/40 §4.9). 점 = 오즈비, 선 = 95% 신뢰구간,
 * 세로선 = 1(관계 없음). 숫자를 글자로 함께 적어 색·위치만으로 전하지 않는다
 */
export function SigunguOrPlot({ items }: { items: readonly SigunguOut[] }) {
  const fitted = items.filter((item) => item.or !== null && item.ci !== null);
  const bounds = fitted.flatMap((item) => [item.ci![0], item.ci![1]]);
  const min = Math.min(1, ...bounds);
  const max = Math.max(1, ...bounds);
  const pad = (max - min) * 0.05 || 0.05;
  const [lo, hi] = [min - pad, max + pad];
  const sorted = [...items].sort((a, b) => (b.or ?? -Infinity) - (a.or ?? -Infinity));
  return (
    <div>
      <ul aria-label="시군구별 과거 폐업 1회당 오즈비" className="space-y-1">
        {sorted.map((item) => (
          <li
            key={item.sigungu}
            className="grid grid-cols-[4.5rem_1fr] items-center gap-2 text-sm sm:grid-cols-[5rem_1fr_9.5rem]"
          >
            <span>{item.sigungu}</span>
            {item.or !== null && item.ci !== null ? (
              <>
                <div className="relative h-5" aria-hidden="true">
                  <div
                    className="bg-muted absolute top-0 h-5 w-px"
                    style={{ left: position(1, lo, hi) }}
                  />
                  <div
                    className="bg-brand/60 absolute top-2 h-1 rounded"
                    style={{
                      left: position(item.ci[0], lo, hi),
                      width: `calc(${position(item.ci[1], lo, hi)} - ${position(item.ci[0], lo, hi)})`,
                    }}
                  />
                  <div
                    className="bg-brand-strong absolute top-1 h-3 w-3 -translate-x-1/2 rounded-full"
                    style={{ left: position(item.or, lo, hi) }}
                  />
                </div>
                <span className="text-muted col-span-2 sm:col-span-1">
                  {formatStat(item.or)} ({formatStatRange(item.ci)}, {formatCount(item.n)}건)
                </span>
              </>
            ) : (
              <span className="text-muted">계산하지 못했어요 ({formatCount(item.n)}건)</span>
            )}
          </li>
        ))}
      </ul>
      <p className="text-muted mt-2 text-sm">
        점은 오즈비, 선은 95% 신뢰구간, 세로선은 1(관계 없음)이에요.
      </p>
    </div>
  );
}
