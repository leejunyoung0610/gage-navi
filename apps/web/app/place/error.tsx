"use client";

/**
 * 필지·층 페이지를 만들지 못했을 때 (docs/40 §7, ADR-031). 서버 렌더링 공유 한도 초과(429)와
 * API 장애(503 등)가 모두 여기로 온다. 운영 빌드에서는 오류 내용이 브라우저에 오지 않아 둘을 가르지 않는다.
 * 이 화면은 캐시되지 않는다(Next.js가 `no-store`로 응답한다 — ADR-031 결과)
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { startTransition } from "react";

export default function PlaceError({ reset }: { error: Error; reset: () => void }) {
  const router = useRouter();
  const retry = () =>
    startTransition(() => {
      router.refresh();
      reset();
    });
  return (
    <main className="max-w-page mx-auto px-4 py-8">
      <h1 className="text-xl font-bold">지금은 이 페이지를 열 수 없어요</h1>
      <p className="mt-4">
        요청이 한꺼번에 몰렸거나 일시적인 문제가 생겼어요. 1분쯤 뒤에 다시 열어 주세요.
      </p>
      <p className="text-muted mt-2 text-sm">이미 본 적 있는 페이지는 계속 열 수 있어요.</p>
      <div className="mt-4 flex flex-wrap gap-4">
        <button
          type="button"
          onClick={retry}
          className="min-h-touch inline-flex items-center underline"
        >
          다시 시도
        </button>
        <Link href="/" className="min-h-touch inline-flex items-center underline">
          홈으로
        </Link>
      </div>
    </main>
  );
}
