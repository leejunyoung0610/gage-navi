import type { Metadata } from "next";
import { connection } from "next/server";

import { Methodology } from "@/components/Methodology";
import { fetchModelCard } from "@/lib/methodology";

export const metadata: Metadata = {
  title: "데이터와 계산 방법",
  description: "가게내비가 쓰는 데이터, 정의, 통계 결과와 한계예요.",
};

/**
 * 방법론 `/methodology` (docs/40 §4.9, T-034). 빌드 때 API를 부르지 않도록 요청 때 렌더하고,
 * API 응답만 1일 캐시한다(`fetchModelCard`, docs/40 §2)
 */
export default async function MethodologyPage() {
  await connection();
  const data = await fetchModelCard();
  return (
    <main className="max-w-page mx-auto space-y-6 px-4 py-8">
      <header className="space-y-2">
        <h1 className="text-xl font-bold">데이터와 계산 방법</h1>
        <p className="text-muted">
          가게내비가 어떤 데이터로 무엇을 어떻게 셌는지, 그리고 무엇을 알 수 없는지 적었어요.
        </p>
      </header>
      <Methodology data={data} />
    </main>
  );
}
