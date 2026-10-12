import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";

// INDEXING_ENABLED가 "true"가 아니면 모든 페이지 noindex (docs/40 §9)
const indexingEnabled = process.env.INDEXING_ENABLED === "true";

export const metadata: Metadata = {
  title: "가게내비",
  robots: indexingEnabled ? undefined : { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-dvh bg-white text-neutral-900 antialiased">{children}</body>
    </html>
  );
}
