/**
 * e2e용 가상 API 서버 (T-033). 응답 형식은 docs/30 §2, 값은 모두 가상 예시다.
 * 화면 폭 검사를 위해 긴 주소·긴 상호(띄어쓰기 없는 영문)·긴 목록을 넣었다.
 */
import { createServer } from "node:http";

const PORT = Number(process.env.MOCK_API_PORT ?? 4010);

export const PNU = "1121510700100470001"; // 가상 예시
const META = { request_id: "01JE2EMOCK0000000000000000", data_as_of: "2026-11-01" };
const LONG_LABEL = "가상특별시 가상구 아주긴이름의가상동 1234-5678";
const LONG_NAME = "VirtualExampleRestaurantWithAVeryLongNameWithoutSpaces가상가게";

const record = (i, extra = {}) => ({
  record_id: i,
  name: i % 5 === 0 ? LONG_NAME : `가상가게 ${i}`,
  license_type: "general_restaurant",
  biz_category: i % 3 === 0 ? null : "분식",
  opened_on: `${2000 + (i % 25)}-03-02`,
  closed_on: i % 4 === 0 ? null : `${2001 + (i % 25)}-08-30`,
  status: i % 4 === 0 ? "open" : "closed",
  tenure_days: 500,
  ho_list: i % 2 === 0 ? ["101"] : ["102"],
  bulk_closure: i % 7 === 0,
  bulk_closure_detail: i % 7 === 0 ? { jurisdiction_label: "가상구", closure_count: 412 } : null,
  ...extra,
});

const floorless = Array.from({ length: 25 }, (_, i) => ({ ...record(i + 1), ho_list: [] }));
const history = Array.from({ length: 30 }, (_, i) => ({
  ...record(i + 100),
  stale_suspect: i === 3,
}));

const place = {
  pnu: PNU,
  jibun_label: LONG_LABEL,
  road_addr: "가상특별시 가상구 아주아주긴가상도로이름로 123번길 45",
  location: null,
  floors: [
    { floor: "B1", record_count: 3, open_now_count: 1 },
    { floor: "1", record_count: 30, open_now_count: 8 },
  ],
  records_without_floor: floorless.length,
  history_without_floor: floorless,
};

const baseRate = (floor) =>
  floor === "B1"
    ? {
        display: false,
        hidden_reason: "not_confirmed_for_floor_scale",
        floor_scale: "large",
        prior_closures_now: 2,
        bucket: "2",
        primary: null,
        baseline: null,
        secondary: null,
        snapshot_label: "2026-11",
        method_version: "2026.10.1",
      }
    : {
        display: true,
        hidden_reason: null,
        floor_scale: "small",
        prior_closures_now: 9,
        bucket: "4+",
        primary: {
          scope_code: "11215",
          scope_label: "가상구",
          rate: "0.4310",
          ci: ["0.3920", "0.4710"],
          n: 612,
        },
        baseline: {
          scope_code: "11",
          bucket: "0",
          rate: "0.2950",
          ci: ["0.2810", "0.3090"],
          n: 4012,
        },
        secondary: {
          scope_code: "11",
          scope_label: "서울",
          rate: "0.4340",
          ci: ["0.4260", "0.4420"],
          n: 14532,
        },
        snapshot_label: "2026-11",
        method_version: "2026.10.1",
      };

const floorData = (floor) => ({
  pnu: PNU,
  floor,
  jibun_label: LONG_LABEL,
  summary: {
    record_count: history.length,
    records_since_2005: 20,
    open_now_count: 8,
    median_closed_tenure_days: 812,
    has_concurrent: true,
    max_concurrent: 5,
  },
  history,
  ho_groups: [
    {
      ho: "101",
      record_ids: history.filter((r) => r.ho_list[0] === "101").map((r) => r.record_id),
    },
    {
      ho: "102",
      record_ids: history.filter((r) => r.ho_list[0] === "102").map((r) => r.record_id),
    },
  ],
  base_rate: baseRate(floor),
  notices: [
    "multiple_units_possible",
    "bulk_closure_present",
    "stale_suspect_present",
    "pre_2005_floor_missing",
  ],
  data_as_of: META.data_as_of,
});

function send(res, status, body) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(JSON.stringify(body));
}

createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://localhost:${PORT}`);
  const path = url.pathname;
  if (path === "/api/v1/health") {
    return send(res, 200, {
      status: "ok",
      db: "ok",
      location_snapshot: "2026-11",
      approved_rules: null,
    });
  }
  if (path === "/api/v1/address/search") {
    return send(res, 200, {
      data: {
        items: [
          {
            road_addr: place.road_addr,
            jibun_addr: LONG_LABEL,
            building_name: null,
            pnu: PNU,
            has_history: true,
            related_pnus: ["1121510700100040003"],
            related_with_history: [
              {
                pnu: "1121510700100040003",
                jibun_label: "가상특별시 가상구 아주긴이름의가상동 4-3",
              },
            ],
          },
        ],
        page: 1,
        total: 1,
      },
      meta: { request_id: META.request_id },
    });
  }
  const floorMatch = /^\/api\/v1\/places\/(\d{19})\/floors\/([^/]+)$/.exec(path);
  if (floorMatch && floorMatch[1] === PNU && ["B1", "1"].includes(floorMatch[2])) {
    return send(res, 200, { data: floorData(floorMatch[2]), meta: META });
  }
  if (path === `/api/v1/places/${PNU}`) return send(res, 200, { data: place, meta: META });
  return send(res, 404, {
    error: {
      code: "NO_HISTORY",
      message: "이 필지에는 식품 업소 인허가 기록이 없어요.",
      details: {},
    },
    meta: { request_id: META.request_id },
  });
}).listen(PORT, () => console.log(`mock api :${PORT}`));
