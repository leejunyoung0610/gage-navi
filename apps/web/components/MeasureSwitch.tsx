"use client";

import { useEffect, useState } from "react";

import { browserStorage, isMeasureOff, setMeasureOff } from "@/lib/measure";

type State = "loading" | "unavailable" | "on" | "off";

const TEXT = {
  label: "통계에서 빠지기 (방문 측정 끄기)",
  on: "켜져 있어요. 이 브라우저는 방문 측정과 “도움이 됐나요” 응답을 보내지 않아요.",
  off: "꺼져 있어요. 이 브라우저는 날짜만 담은 익명 이벤트를 보내요.",
  unavailable:
    "이 브라우저는 저장 공간을 쓸 수 없어 스위치를 저장하지 못해요. 이 경우에는 원래 아무 이벤트도 보내지 않아요.",
  failed: "저장하지 못했어요. 브라우저 설정에서 사이트 데이터 저장이 막혀 있는지 확인해 주세요.",
} as const;

/** `/privacy`의 측정 끄기 스위치 (docs/40 §2, docs/60 §5). 내 기기 제외도 같은 표시다 */
export function MeasureSwitch() {
  const [state, setState] = useState<State>("loading");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const storage = browserStorage();
    setState(storage === null ? "unavailable" : isMeasureOff(storage) ? "on" : "off");
  }, []);

  function toggle() {
    const storage = browserStorage();
    if (storage === null) {
      setState("unavailable");
      return;
    }
    const next = state !== "on";
    const ok = setMeasureOff(storage, next);
    setFailed(!ok);
    if (ok) setState(next ? "on" : "off");
  }

  if (state === "unavailable") return <p className="text-sm">{TEXT.unavailable}</p>;
  return (
    <div className="space-y-2">
      <button
        type="button"
        role="switch"
        aria-checked={state === "on"}
        disabled={state === "loading"}
        onClick={toggle}
        className="border-line min-h-touch flex w-full items-center justify-between gap-3 rounded-lg border px-3 text-left"
      >
        <span>{TEXT.label}</span>
        <span aria-hidden="true" className="font-bold">
          {state === "on" ? "켜짐" : "꺼짐"}
        </span>
      </button>
      {state !== "loading" && (
        <p role="status" className="text-muted text-sm">
          {state === "on" ? TEXT.on : TEXT.off}
        </p>
      )}
      {failed && <p className="text-sm">{TEXT.failed}</p>}
    </div>
  );
}
