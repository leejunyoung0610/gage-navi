import Link from "next/link";

/** 층 이력 알림 문구 (docs/40 §4.4-4, 발생 조건은 docs/10 §7.1). 모르는 값은 보여주지 않는다 */
export const NOTICE_TEXT: Record<string, string> = {
  // 겹침은 여러 점포일 수도 신고 지연일 수도 있다(analysis/README §4.1) — 함께 영업했다고 단정하지 않는다
  multiple_units_possible:
    "이 층에는 영업 기간이 한 달 넘게 겹치는 기록이 있어요. 점포가 여러 개였거나 앞 가게의 폐업 신고가 늦어졌을 수 있어요.",
  bulk_closure_present:
    "폐업 처리 몰린 날에 폐업된 기록이 있어요. 그 가게들이 실제로 문을 닫은 날은 더 이를 수 있어요.",
  stale_suspect_present:
    "같은 호수로 나중에 다른 가게가 영업 신고를 한 기록이 있어요. 앞 가게의 폐업 신고가 늦어졌을 수 있어요.",
  pre_2005_floor_missing:
    "2005년 이전 기록은 신고 주소에 층이 적혀 있지 않은 경우가 많아요. 층을 알 수 없는 기록은 필지 페이지에서 볼 수 있어요.",
};

export function PlaceNotices({ notices, pnu }: { notices: readonly string[]; pnu: string }) {
  const known = notices.filter((notice) => notice in NOTICE_TEXT);
  if (known.length === 0) return null;
  return (
    <section aria-label="알아 둘 점" className="bg-surface space-y-2 rounded-xl p-4">
      <h2 className="font-bold">알아 둘 점</h2>
      <ul className="list-disc space-y-1 pl-5">
        {known.map((notice) => (
          <li key={notice}>
            {NOTICE_TEXT[notice]}
            {notice === "pre_2005_floor_missing" && (
              <>
                {" "}
                <Link href={`/place/${pnu}`} className="underline">
                  필지 페이지 보기
                </Link>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
