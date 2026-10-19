import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { CorrectionButton, CorrectionProvider } from "@/components/CorrectionSheet";
import { FloorTimeline } from "@/components/FloorTimeline";
import { PlaceMap } from "@/components/PlaceMap";
import { RelatedParcels } from "@/components/RelatedParcels";
import { formatCount, formatFloor } from "@/lib/format";
import { fetchPlace, fetchSnapshotMonth, type PlaceData } from "@/lib/place";

// ISR 1일 (docs/40 §2). 정정 요청 처리 때는 API가 /api/revalidate로 바로 재생성한다
export const revalidate = 86400;

type Params = Promise<{ pnu: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { pnu } = await params;
  const place = await fetchPlace(pnu);
  if (place.kind !== "ok") return { title: "필지 가게 이력" };
  return {
    title: `${place.data.jibun_label} 가게 이력`,
    description: `${place.data.jibun_label}에 신고된 식품 업소 인허가 기록이에요.`,
  };
}

/** "이 필지에는 2026년 {월} 기준 식품 업소 인허가 기록이 없어요" (docs/40 §4.3) */
async function NoHistory() {
  const month = await fetchSnapshotMonth();
  const basis = month ? `${month.slice(0, 4)}년 ${Number(month.slice(5, 7))}월 기준 ` : "";
  return (
    <main className="max-w-page mx-auto px-4 py-8">
      <h1 className="text-xl font-bold">필지 가게 이력</h1>
      <p className="mt-4">이 필지에는 {basis}식품 업소 인허가 기록이 없어요.</p>
      <Link href="/" className="min-h-touch mt-2 inline-flex items-center underline">
        다른 주소 찾기
      </Link>
    </main>
  );
}

export default async function PlacePage({ params }: { params: Params }) {
  const { pnu } = await params;
  const place = await fetchPlace(pnu);
  if (place.kind === "invalid") notFound();
  if (place.kind === "no_history") return <NoHistory />;
  const { data, dataAsOf } = place;

  // 층이 1개이고 층 미상 기록이 없으면 바로 층 페이지로 (docs/40 §4.3)
  const [only] = data.floors;
  if (data.floors.length === 1 && only && data.records_without_floor === 0) {
    redirect(`/place/${data.pnu}/${only.floor}`);
  }

  return (
    <CorrectionProvider pnu={data.pnu} floor={null}>
      <main className="max-w-page mx-auto space-y-6 px-4 py-8">
        <header>
          <h1 className="text-xl font-bold break-words">{data.jibun_label}</h1>
          {data.road_addr && <p className="text-muted break-words">{data.road_addr}</p>}
        </header>
        {data.location && <PlaceMap lat={data.location.lat} lng={data.location.lng} />}
        <FloorList data={data} />
        <RelatedParcels pnu={data.pnu} jibunLabel={data.jibun_label} />
        {data.records_without_floor > 0 && (
          <section aria-labelledby="floorless-title" className="space-y-2">
            <h2 id="floorless-title" className="font-bold">
              층을 알 수 없는 기록 {formatCount(data.records_without_floor)}건
            </h2>
            <p className="text-muted text-sm">
              신고 주소에 층이 적혀 있지 않아 어느 층의 가게인지 알 수 없는 기록이에요. 층별 이력과
              통계에는 포함되지 않았어요.
            </p>
            <FloorTimeline
              history={data.history_without_floor}
              dataAsOf={dataAsOf}
              label="층을 알 수 없는 기록"
            />
          </section>
        )}
        <CorrectionButton />
      </main>
    </CorrectionProvider>
  );
}

function FloorList({ data }: { data: PlaceData }) {
  if (data.floors.length === 0) return null;
  return (
    <section aria-labelledby="floors-title">
      <h2 id="floors-title" className="font-bold">
        층 고르기
      </h2>
      <ul className="divide-line mt-2 divide-y">
        {data.floors.map((floor) => (
          <li key={floor.floor}>
            <Link
              href={`/place/${data.pnu}/${floor.floor}`}
              className="min-h-touch flex items-center justify-between gap-2 py-2"
            >
              <span className="font-bold">{formatFloor(floor.floor)}</span>
              <span className="text-muted text-sm">
                기록 {formatCount(floor.record_count)}건 · 영업 중{" "}
                {formatCount(floor.open_now_count)}곳
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
