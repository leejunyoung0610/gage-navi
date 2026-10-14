// docs/40 §3: 공개 게이트를 통과하지 않은 모듈 화면의 상단 고정 배너
export type BetaModule = "location" | "funding" | "closure";

// 게이트를 통과한 모듈. 통과하면 여기에 더한다 (docs/50 §7)
const RELEASED_MODULES: readonly BetaModule[] = [];

export function BetaBanner({ module }: { module: BetaModule }) {
  if (RELEASED_MODULES.includes(module)) return null;
  return (
    <div
      role="note"
      className="bg-beta-bg text-beta-ink sticky top-0 z-10 px-4 py-2 text-center text-sm font-medium"
    >
      베타예요. 결과를 그대로 믿지 말고 공고 원문을 확인하세요.
    </div>
  );
}
