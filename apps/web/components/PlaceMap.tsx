"use client";

import { useEffect, useRef, useState } from "react";

import { loadKakaoMaps } from "@/lib/kakao-maps";

const LEVEL = 3;

/** 필지 위치 작은 지도 (docs/40 §4.3). SDK는 화면이 뜬 뒤에 불러온다(지연 로딩, §11 JS 예산 밖) */
export function PlaceMap({ lat, lng }: { lat: number; lng: number }) {
  const container = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadKakaoMaps().then(
      (maps) => {
        if (cancelled || !container.current) return;
        const center = new maps.LatLng(lat, lng);
        const map = new maps.Map(container.current, { center, level: LEVEL });
        new maps.Marker({ position: center, map });
      },
      () => {
        if (!cancelled) setFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [lat, lng]);

  if (failed) return <p className="text-muted text-sm">지도를 불러오지 못했어요.</p>;
  return (
    <div
      ref={container}
      role="img"
      aria-label="필지 위치 지도"
      className="border-line bg-surface h-40 w-full rounded-lg border"
    />
  );
}
