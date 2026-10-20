import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { VisitMeasure } from "@/components/VisitMeasure";
import { pageRobots } from "@/lib/indexing";

import { Providers } from "./providers";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "가게내비", template: "%s | 가게내비" },
  applicationName: "가게내비",
  // 기본은 noindex. 색인 허용 범위(홈·방법론·기록 2건 이상 층)는 각 페이지가 덮어쓴다 (docs/40 §9)
  robots: pageRobots(false),
  icons: { apple: "/icons/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "가게내비", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f766e",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body className="text-ink flex min-h-dvh flex-col bg-white font-sans antialiased">
        <SiteHeader />
        <div className="flex-1">
          <Providers>{children}</Providers>
        </div>
        <SiteFooter />
        <VisitMeasure />
      </body>
    </html>
  );
}
