# 웹 (Next.js standalone). docker-compose.yml의 `web` 서비스가 빌드한다
FROM node:20-slim AS build
WORKDIR /app
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
# 브라우저용 값은 빌드할 때 번들에 들어간다 (lib/api-base.ts)
ARG NEXT_PUBLIC_API_BASE_URL
# 정적 페이지(홈 등)의 noindex는 빌드 때 정해진다. 둘 중 하나라도 비우면 noindex (docs/40 §9)
ARG INDEXING_ENABLED
ARG SITE_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

USER node
EXPOSE 3000
CMD ["node", "server.js"]
