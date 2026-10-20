"use client";

import { useState } from "react";

import { sendHelpful, type HelpfulResult } from "@/lib/measure";

const TEXT = {
  question: "계약 판단에 도움이 됐나요?",
  yes: "예",
  no: "아니오",
  thanks: "알려 주셔서 고마워요.",
  measure_off: "통계에서 빠지기를 켜 두어서 응답을 보내지 않았어요.",
  // 봇으로 보이는 브라우저, 저장소를 쓸 수 없는 브라우저 (lib/measure.ts `canMeasure`)
  unavailable: "이 브라우저에서는 응답을 보낼 수 없어서 보내지 않았어요.",
} as const;

/**
 * 층 페이지 "계약 판단에 도움이 됐나요? 예/아니오" (docs/40 §4.4-6, T-104).
 * 클릭 수만 센다 — 이벤트에는 날짜만 담고 필지·층·주소는 담지 않는다. 버튼은 서버에서 그대로 그린다
 */
export function HelpfulPrompt() {
  const [result, setResult] = useState<HelpfulResult | null>(null);
  if (result !== null) {
    return (
      <p role="status" className="text-muted text-sm">
        {result === "sent" ? TEXT.thanks : TEXT[result]}
      </p>
    );
  }
  return (
    <section aria-labelledby="helpful-title" className="space-y-2">
      <h2 id="helpful-title" className="font-bold">
        {TEXT.question}
      </h2>
      <div className="flex gap-2">
        {(["yes", "no"] as const).map((answer) => (
          <button
            key={answer}
            type="button"
            className="border-line min-h-touch flex-1 rounded-lg border px-3"
            onClick={() => setResult(sendHelpful(answer))}
          >
            {answer === "yes" ? TEXT.yes : TEXT.no}
          </button>
        ))}
      </div>
    </section>
  );
}
