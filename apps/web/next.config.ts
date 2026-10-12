import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // 상위 폴더의 다른 lockfile을 작업 공간 루트로 잡지 않도록 고정
  outputFileTracingRoot: import.meta.dirname,
};

export default nextConfig;
