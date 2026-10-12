"""좌표계 후보 비교표 (T-014, docs/03 D1).

    python -m jobs.crs_candidates --file PATH [--file PATH ...] [--out reports/crs_candidates.md]

인허가 파일의 `좌표정보(X)`, `좌표정보(Y)`를 후보 EPSG별로 WGS84로 바꿔, 사람이 지도에서
대조할 표를 만든다. 서로 다른 구에서 한 건씩 20건을 고정 seed로 고른다.
어느 후보가 맞는지는 이 스크립트가 정하지 않는다(🧑 지도 대조).
"""

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from pyproj import Transformer

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "reports" / "crs_candidates.md"

CANDIDATES = (2097, 5174, 5181, 5186)
# 5186은 변환 결과 범위 표에만 남긴다. 서울 주소 행 전체가 위도 36.5~36.8로 변환돼
# 지도 대조 전에 탈락했다(가산 북거 600,000m, 나머지 셋은 500,000m).
MAP_CANDIDATES = (2097, 5174, 5181)
SAMPLE_SIZE = 20
SEED = 14
OPEN_STATUS = "영업/정상"
SEOUL = "서울특별시"
# 카카오맵 링크는 `이름,위도,경도` 형식이라 이름에 구분자가 있으면 깨진다
_LINK_UNSAFE = set(",/?#%&")


@dataclass(frozen=True)
class Row:
    mgmt_no: str
    name: str
    gu: str
    road_addr: str
    is_open: bool
    x: float
    y: float


def read_rows(paths: list[Path]) -> tuple[list[Row], int, int]:
    """좌표가 있고 지번주소가 서울인 행, 전체 행 수, 좌표가 빈 행 수."""
    rows: list[Row] = []
    total = 0
    empty = 0
    for path in paths:
        with path.open(encoding="cp949", newline="") as f:
            for rec in csv.DictReader(f):
                total += 1
                x, y = rec["좌표정보(X)"].strip(), rec["좌표정보(Y)"].strip()
                if not x or not y:
                    empty += 1
                    continue
                parts = rec["지번주소"].split()
                if len(parts) < 2 or parts[0] != SEOUL:
                    continue
                is_open = rec["영업상태명"] == OPEN_STATUS
                rows.append(
                    Row(
                        mgmt_no=rec["관리번호"],
                        name=rec["사업장명"].strip(),
                        gu=parts[1],
                        road_addr=rec["도로명주소"].strip(),
                        is_open=is_open,
                        x=float(x),
                        y=float(y),
                    )
                )
    return rows, total, empty


def pick_sample(rows: list[Row]) -> list[Row]:
    """영업 중이고 도로명주소가 있는 기록에서 구마다 한 건, 고정 seed."""
    by_gu: dict[str, list[Row]] = {}
    for row in rows:
        if row.is_open and row.name and row.road_addr and not (_LINK_UNSAFE & set(row.name)):
            by_gu.setdefault(row.gu, []).append(row)
    rng = random.Random(SEED)
    gus = rng.sample(sorted(by_gu), SAMPLE_SIZE)
    return [rng.choice(sorted(by_gu[gu], key=lambda r: r.mgmt_no)) for gu in sorted(gus)]


def kakao_link(name: str, lat: float, lng: float) -> str:
    return f"https://map.kakao.com/link/map/{quote(name)},{lat:.6f},{lng:.6f}"


def render(rows: list[Row], sample: list[Row], total: int, empty: int, files: list[str]) -> str:
    transformers = {e: Transformer.from_crs(e, 4326, always_xy=True) for e in CANDIDATES}
    xs, ys = [r.x for r in rows], [r.y for r in rows]
    out = [
        "# 좌표계 후보 비교표 (T-014, docs/03 D1)",
        "",
        "`python -m jobs.crs_candidates`가 만든 파일이다. 손으로 고치지 않는다.",
        "",
        f"- 파일: {', '.join(files)}",
        f"- 전체 {total:,}행, 좌표 빈 행 {empty:,}, 좌표가 있고 지번주소가 서울인 행 {len(rows):,}",
        f"- 원천 X 범위 {min(xs):.1f} ~ {max(xs):.1f}, Y 범위 {min(ys):.1f} ~ {max(ys):.1f}",
        f"- 표본: 영업 중·도로명주소 있음, 구마다 한 건, seed {SEED}",
        "",
        "## 후보별 변환 결과 범위 (좌표가 있는 서울 주소 행 전체)",
        "",
        "| EPSG | 위도 최소 | 위도 최대 | 경도 최소 | 경도 최대 | pyproj 변환 |",
        "|---|---|---|---|---|---|",
    ]
    for epsg, t in transformers.items():
        lng, lat = t.transform(xs, ys)
        out.append(
            f"| {epsg} | {min(lat):.5f} | {max(lat):.5f} | {min(lng):.5f} | {max(lng):.5f} "
            f"| {t.description} |"
        )
    out += [
        "",
        "## 20건 대조표",
        "",
        "핀이 주소의 실제 건물에 찍히는 후보를 고른다. 좌표는 `위도, 경도`(WGS84).",
        "",
        "| # | 구 | 사업장명 | 도로명주소 | 원천 X, Y | "
        + " | ".join(f"EPSG:{e}" for e in MAP_CANDIDATES)
        + " |",
        "|---|---|---|---|---|" + "---|" * len(MAP_CANDIDATES),
    ]
    for i, r in enumerate(sample, 1):
        cells = []
        for epsg in MAP_CANDIDATES:
            lng, lat = transformers[epsg].transform(r.x, r.y)
            cells.append(f"[{lat:.6f}, {lng:.6f}]({kakao_link(r.name, lat, lng)})")
        out.append(
            f"| {i} | {r.gu} | {r.name} | {r.road_addr} | {r.x:.3f}, {r.y:.3f} | "
            + " | ".join(cells)
            + " |"
        )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobs.crs_candidates", description="좌표계 후보 비교표")
    parser.add_argument("--file", type=Path, action="append", required=True, help="인허가 CSV")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="리포트 경로")
    args = parser.parse_args(argv)

    rows, total, empty = read_rows(args.file)
    sample = pick_sample(rows)
    report = render(rows, sample, total, empty, [p.name for p in args.file])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    line = {"job": "crs_candidates", "rows": len(rows), "sample": len(sample), "out": str(args.out)}
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
