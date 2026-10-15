// `pnpm gen:api` (T-031, docs/30 머리말): FastAPI OpenAPI → lib/api/types.ts.
// 스키마는 services/api의 `app.openapi_export`에서 받는다(서버 실행·DB 불필요, uv 필요).
// `--check`는 파일을 쓰지 않고, 새로 만든 결과가 지금 파일과 다르면 실패한다(CI web-check, docs/50 §8).
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import openapiTS, { COMMENT_HEADER, astToString } from "openapi-typescript";

const webDir = resolve(import.meta.dirname, "..");
const apiDir = resolve(webDir, "../../services/api");
const outFile = resolve(webDir, "lib/api/types.ts");
const shown = relative(webDir, outFile);

const schemaJson = execFileSync("uv", ["run", "python", "-m", "app.openapi_export"], {
  cwd: apiDir,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "inherit"],
  maxBuffer: 64 * 1024 * 1024,
});
const generated = COMMENT_HEADER + astToString(await openapiTS(JSON.parse(schemaJson)));

if (process.argv.includes("--check")) {
  const current = existsSync(outFile) ? readFileSync(outFile, "utf8") : null;
  if (current !== generated) {
    console.error(
      `${shown}가 API의 OpenAPI와 달라요. \`make gen-api\`로 다시 만들고 커밋하세요 (손으로 고치지 않아요).`,
    );
    process.exit(1);
  }
  console.log(`gen:api --check: ${shown}가 API와 같아요`);
} else {
  mkdirSync(dirname(outFile), { recursive: true });
  writeFileSync(outFile, generated);
  console.log(`gen:api → ${shown}`);
}
