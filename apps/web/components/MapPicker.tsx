"use client";

import { useEffect, useRef, useState } from "react";

import { loadKakaoMaps, type KakaoMarker } from "@/lib/kakao-maps";

// 지도 첫 화면의 중심(서울시청 부근)과 확대 수준. 화면 위치일 뿐 판단에 쓰지 않는다
const INITIAL_CENTER = { lat: 37.5666, lng: 126.9784 };
const INITIAL_LEVEL = 3;

type Status = "loading" | "ready" | "error";

/**
 * 지도에서 한 점을 찍으면 `onPick(lat, lng)` (docs/40 §4.2 "지도에서 고르기").
 * 위치 권한이 필요 없다. 찍은 좌표는 넘기기만 하고 저장하지 않는다.
 */
export function MapPicker({ onPick }: { onPick: (lat: number, lng: number) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const pick = useRef(onPick);
  const [status, setStatus] = useState<Status>("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    pick.current = onPick;
  }, [onPick]);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    loadKakaoMaps().then(
      (maps) => {
        if (cancelled || !container.current) return;
        const center = new maps.LatLng(INITIAL_CENTER.lat, INITIAL_CENTER.lng);
        const map = new maps.Map(container.current, { center, level: INITIAL_LEVEL });
        let marker: KakaoMarker | null = null;
        maps.event.addListener(map, "click", ({ latLng }) => {
          if (marker) marker.setPosition(latLng);
          else marker = new maps.Marker({ position: latLng, map });
          pick.current(latLng.getLat(), latLng.getLng());
        });
        setStatus("ready");
      },
      () => {
        if (!cancelled) setStatus("error");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  return (
    <div className="mt-3">
      <p className="text-muted text-sm">찾을 건물 위를 눌러 주세요.</p>
      <div
        ref={container}
        role="application"
        aria-label="지도"
        className="border-line mt-2 h-72 w-full rounded-lg border bg-surface"
      />
      {status === "loading" && (
        <p role="status" className="text-muted mt-2 text-sm">
          지도를 불러오고 있어요.
        </p>
      )}
      {status === "error" && (
        <div role="alert" className="mt-2 text-sm">
          <p>지도를 불러오지 못했어요.</p>
          <button
            type="button"
            className="mt-1 min-h-touch underline"
            onClick={() => setAttempt((n) => n + 1)}
          >
            다시 시도
          </button>
        </div>
      )}
    </div>
  );
}
