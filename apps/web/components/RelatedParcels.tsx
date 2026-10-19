"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { findRelatedParcels } from "@/lib/place";

const TEXT = {
  title: "같은 건물의 다른 필지 기록",
  unknown: "같은 건물의 다른 필지 기록은 확인하지 못했어요.",
} as const;

/**
 * 같은 건물의 다른 필지 중 기록이 있는 곳 (docs/40 §4.3). 브라우저에서 주소 검색을 한 번 부른다 —
 * 외부 API 결과를 서버 렌더링(ISR) 캐시에 섞지 않는다. 빈 목록이면 아무것도 그리지 않는다
 */
export function RelatedParcels({ pnu, jibunLabel }: { pnu: string; jibunLabel: string }) {
  const related = useQuery({
    queryKey: ["related-parcels", pnu, jibunLabel],
    queryFn: ({ signal }) => findRelatedParcels(pnu, jibunLabel, signal),
    retry: false,
  });
  if (related.isPending) return null;
  // 호출 실패·같은 항목 없음·null은 "확인 못 함" — 빈 목록처럼 다루지 않는다 (ADR-003)
  if (related.isError || related.data === null) {
    return <p className="text-muted text-sm">{TEXT.unknown}</p>;
  }
  if (related.data.length === 0) return null;
  return (
    <section aria-label={TEXT.title}>
      <h2 className="font-bold">{TEXT.title}</h2>
      <ul className="mt-1">
        {related.data.map((parcel) => (
          <li key={parcel.pnu}>
            <Link
              href={`/place/${parcel.pnu}`}
              className="min-h-touch inline-flex items-center underline"
            >
              {parcel.jibun_label}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
