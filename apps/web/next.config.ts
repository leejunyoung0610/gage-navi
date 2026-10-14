import withSerwistInit from "@serwist/next";
import type { NextConfig } from "next";

// 서비스 워커는 프로덕션 빌드에서만 만든다 (개발 중 캐시가 화면을 가리지 않게)
const withSerwist = withSerwistInit({
  swSrc: "app/sw.ts",
  swDest: "public/sw.js",
  disable: process.env.NODE_ENV !== "production",
});

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Docker 이미지에는 실행에 필요한 파일만 담는다 (apps/web/Dockerfile)
  output: "standalone",
  // 상위 폴더의 다른 lockfile을 작업 공간 루트로 잡지 않도록 고정
  outputFileTracingRoot: import.meta.dirname,
};

export default withSerwist(nextConfig);
