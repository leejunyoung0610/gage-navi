import type { MetadataRoute } from "next";

import { indexingSiteUrl } from "@/lib/indexing";

// 실행 환경의 색인 설정을 읽는다 (docs/40 §9)
export const dynamic = "force-dynamic";

/**
 * 색인이 꺼져 있으면 전체 차단. 켜졌으면 페이지는 막지 않고(각 페이지의 noindex를 크롤러가 읽어야 한다)
 * API 경로만 막고 사이트맵 색인을 알린다 (docs/40 §9, T-035)
 */
export default function robots(): MetadataRoute.Robots {
  const siteUrl = indexingSiteUrl();
  if (siteUrl === null) return { rules: { userAgent: "*", disallow: "/" } };
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
