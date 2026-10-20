"use client";

import { useEffect } from "react";

import { startVisitMeasure } from "@/lib/measure";

/** 방문 측정 (docs/40 §10, ADR-027). 화면에 그리는 것은 없다 */
export function VisitMeasure() {
  useEffect(() => {
    void startVisitMeasure();
  }, []);
  return null;
}
