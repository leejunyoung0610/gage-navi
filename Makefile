API := services/api
WEB := apps/web

.PHONY: setup check check-api check-web test dev dev-api dev-web e2e gen-api

setup: ## 의존성 설치 (uv, pnpm, Node 20+ 필요)
	cd $(API) && uv sync
	cd $(WEB) && pnpm install --frozen-lockfile
	mkdir -p storage
	@if git rev-parse --git-dir >/dev/null 2>&1; then \
		cd $(API) && uv run pre-commit install; \
	fi

check: check-api check-web ## 린트·타입·단위 테스트 (PR 전 필수)

check-api:
	cd $(API) && uv run ruff check .
	cd $(API) && uv run ruff format --check .
	cd $(API) && uv run mypy
	cd $(API) && uv run lint-imports
	cd $(API) && uv run pytest tests/unit tests/property tests/scenario tests/golden

check-web:
	cd $(WEB) && pnpm lint
	cd $(WEB) && pnpm typecheck
	cd $(WEB) && pnpm format:check
	cd $(WEB) && pnpm test

test: ## 전체 테스트 (통합 테스트 포함)
	cd $(API) && uv run pytest
	cd $(WEB) && pnpm test

dev: ## 로컬 실행 (API :8000, 웹 :3000). DB는 docker compose up -d db
	$(MAKE) -j2 dev-api dev-web

dev-api:
	cd $(API) && uv run $(if $(wildcard .env),--env-file ../../.env) uvicorn app.main:app --reload --port 8000

dev-web:
	cd $(WEB) && pnpm dev

e2e: ## Playwright
	cd $(WEB) && pnpm exec playwright install chromium
	cd $(WEB) && pnpm e2e

gen-api: ## OpenAPI → TS 타입
	cd $(WEB) && pnpm gen:api
