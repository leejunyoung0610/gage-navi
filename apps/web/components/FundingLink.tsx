"use client";

import { useRouter } from "next/navigation";

import { profileStore } from "@/lib/profile-store";

/**
 * "이 자리로 정책자금 알아보기" (docs/40 §4.4-6). 프로필(이 기기에만)에 지역을 저장하고 `/funding`으로.
 * 시도 코드는 PNU 앞 2자리, 시군구 코드는 앞 5자리. 다른 프로필 값은 그대로 둔다
 */
export function FundingLink({ pnu }: { pnu: string }) {
  const router = useRouter();
  return (
    <button
      type="button"
      className="bg-brand min-h-touch w-full rounded-lg px-3 font-bold text-white"
      onClick={() => {
        const current = profileStore.load() ?? { schema_version: 1 as const };
        // 저장이 막혀도(사파리 개인 정보 보호 모드 등) 메모리에 남고 화면은 그대로 간다
        profileStore.save({
          ...current,
          region: { sido_code: pnu.slice(0, 2), sigungu_code: pnu.slice(0, 5) },
        });
        router.push("/funding");
      }}
    >
      이 자리로 정책자금 알아보기
    </button>
  );
}
