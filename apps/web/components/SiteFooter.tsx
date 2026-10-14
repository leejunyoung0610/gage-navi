import Link from "next/link";

// docs/40 §3: 데이터 출처, 방법론 링크, 대행·수수료 없음, 정정 요청 안내
export function SiteFooter() {
  return (
    <footer className="border-line bg-surface text-muted mt-12 border-t">
      <div className="max-w-page mx-auto space-y-2 px-4 py-6 text-sm">
        <p>데이터 출처: 행정안전부 인허가 데이터, 각 지원사업 공고 기관</p>
        <p>
          <Link href="/methodology" className="min-h-touch inline-flex items-center underline">
            데이터와 계산 방법 보기
          </Link>
        </p>
        <p>가게내비는 신청을 대행하거나 수수료를 받지 않아요.</p>
        <p>자리 이력 정보가 잘못됐다면 그 화면의 &ldquo;정보가 잘못됐나요?&rdquo;로 알려 주세요.</p>
      </div>
    </footer>
  );
}
