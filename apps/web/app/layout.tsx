import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

import { Providers } from "./providers";

import "./globals.css";

// INDEXING_ENABLED가 "true"가 아니면 모든 페이지 noindex (docs/40 §9)
const indexingEnabled = process.env.INDEXING_ENABLED === "true";

export const metadata: Metadata = {
  title: { default: "가게내비", template: "%s | 가게내비" },
  applicationName: "가게내비",
  robots: indexingEnabled ? undefined : { index: false, follow: false },
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
      </body>
    </html>
  );
}
