import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BaseRateCard } from "@/components/BaseRateCard";
import { CorrectionButton, CorrectionProvider } from "@/components/CorrectionSheet";
import { FloorTimeline } from "@/components/FloorTimeline";
import { PlaceNotices } from "@/components/PlaceNotices";
import { daysToMonths, formatCount, formatFloor, formatMonths } from "@/lib/format";
import { isIndexableFloor, pageRobots } from "@/lib/indexing";
import { fetchFloor, type FloorData } from "@/lib/place";

// ISR 1일 (docs/40 §2)
export const revalidate = 86400;

type Params = Promise<{ pnu: string; floor: string }>;

function floorLabel(floor: string): string | null {
  try {
    return formatFloor(floor);
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { pnu, floor } = await params;
  const result = await fetchFloor(pnu, floor);
  if (result.kind !== "ok") return { title: "층 가게 이력" };
  const where = `${result.data.jibun_label} ${floorLabel(result.data.floor) ?? ""}`.trim();
  // 설명에 평가적 표현을 쓰지 않는다 (docs/40 §4.4-7)
  return {
    title: `${where} 가게 이력`,
    description: `${where}에 신고된 식품 업소 인허가 기록과 참고 통계예요.`,
    // 기록(숨김 제외) 2건 이상인 층만 색인 허용 (docs/40 §9)
    robots: pageRobots(isIndexableFloor(result.data.summary.record_count)),
  };
}

export default async function FloorPage({ params }: { params: Params }) {
  const { pnu, floor } = await params;
  const result = await fetchFloor(pnu, floor);
  if (result.kind === "invalid") notFound();
  if (result.kind === "no_history") {
    return (
      <main className="max-w-page mx-auto px-4 py-8">
        <h1 className="text-xl font-bold">층 가게 이력</h1>
        <p className="mt-4">이 층에는 식품 업소 인허가 기록이 없어요.</p>
        <Link
          href={`/place/${pnu}`}
          className="min-h-touch mt-2 inline-flex items-center underline"
        >
          필지의 다른 층 보기
        </Link>
      </main>
    );
  }
  const { data, dataAsOf } = result;
  return (
    <CorrectionProvider pnu={data.pnu} floor={data.floor}>
      <main className="max-w-page mx-auto space-y-6 px-4 py-8">
        <header>
          <h1 className="text-xl font-bold break-words">
            {data.jibun_label} {floorLabel(data.floor)}
          </h1>
          <Link
            href={`/place/${data.pnu}`}
            className="text-muted min-h-touch inline-flex items-center text-sm underline"
          >
            필지의 다른 층 보기
          </Link>
        </header>
        <SummaryChips data={data} />
        <BaseRateCard baseRate={data.base_rate} />
        <PlaceNotices notices={data.notices} pnu={data.pnu} />
        <section aria-labelledby="timeline-title" className="space-y-2">
          <h2 id="timeline-title" className="font-bold">
            이 층을 거쳐간 가게
          </h2>
          <FloorTimeline
            history={data.history}
            hoGroups={data.ho_groups}
            dataAsOf={dataAsOf}
            label="층 이력"
          />
        </section>
        <div className="space-y-2">
          <CorrectionButton />
        </div>
      </main>
    </CorrectionProvider>
  );
}

/** 요약 칩 (docs/40 §4.4-2) */
function SummaryChips({ data }: { data: FloorData }) {
  const { summary } = data;
  const median =
    summary.median_closed_tenure_days === null
      ? "폐업 업소 영업기간 중앙값 알 수 없음"
      : `폐업 업소 영업기간 중앙값 ${formatMonths(daysToMonths(summary.median_closed_tenure_days))}`;
  const chips = [
    `거쳐간 업소 ${formatCount(summary.records_since_2005)}곳(2005년 이후)`,
    median,
    `지금 영업 중 ${formatCount(summary.open_now_count)}곳`,
  ];
  return (
    <ul aria-label="요약" className="flex flex-wrap gap-2">
      {chips.map((chip) => (
        <li key={chip} className="bg-surface rounded-full px-3 py-1 text-sm">
          {chip}
        </li>
      ))}
    </ul>
  );
}
