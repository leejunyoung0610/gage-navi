"""T-051S 문서 변환 스파이크: 공고 원문(HWP·PDF)을 텍스트로 바꿔 본문 누락·표 보존을 잰다.

결과 해석은 reports/conversion_spike.md, 형식별 go/no-go는 docs/02-adr.md ADR-024.

실행 (프로젝트 의존성에 넣지 않고 일회성으로 설치해 쓴다. 정식 추가는 T-051):

    uv run --no-project --python 3.12 --with pdfplumber --with pyhwp --with six \
        python analysis/conversion_spike.py --dir storage/announcements --dump /tmp/spike > metrics.json

PDF 대조용으로 poppler의 `pdftotext`가 PATH에 있어야 한다 (없으면 대조 지표는 null).

방법
- PDF: pdfplumber로 (a) 페이지별 줄 (b) 표 영역은 `extract_tables`의 셀을 `| 셀 | 셀 |` 행으로,
  표 밖은 줄로 뽑아 세로 위치 순으로 합친 텍스트. 누락 대조 기준은 pdftotext(다른 구현체).
  (b)는 줄 순서가 기준과 달라지므로 순서와 무관한 `char_coverage`(글자 빈도 대조)로 잰다.
  `cells_contiguous`: 글자·숫자 20자 이상인 표 셀 중 그 내용이 텍스트에 끊기지 않고 있는 비율
  (옆 칸 글자가 끼어들면 근거 인용 대조가 깨진다 — docs/20 §10.4).
- HWP: (a) `hwp5txt` (b) pyhwp XML 이벤트를 훑어 문단·표 셀 순서대로 텍스트화
  (c) pyhwp 없이 olefile로 본문 스트림의 레코드 트리를 직접 읽어 같은 형태로 텍스트화.
  누락 대조 기준은 `raw_hwp_paragraphs` — 문단 텍스트 레코드(HWPTAG_PARA_TEXT)만 순서대로 읽은 것.
  (b)와 (c)는 서로 다른 구현이므로 둘의 일치(`records.agrees_with_xml`)도 함께 본다.
- 대조 지표 `coverage`: 기준 텍스트의 문단(PDF는 줄)에서 글자·숫자만 남긴 것이 변환 결과
  (같은 처리)에 그대로 들어 있는 문단의 글자 수 비율. 1.0이면 기준의 글자·숫자가 전부 결과에
  같은 순서로 있다. 공백·문장부호·각주 기호(*)의 위치 차이는 누락으로 세지 않는다.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

WS = re.compile(r"\s+")


def squash(text: str) -> str:
    return WS.sub("", text)


def alnum(text: str) -> str:
    """글자·숫자만 (대조용). 공백·문장부호·표 구분 기호를 뺀다."""
    return "".join(ch for ch in text if ch.isalnum())


def coverage(reference_units: list[str], output_text: str) -> dict[str, Any]:
    """기준 단위(문단·줄) 중 결과에 그대로 있는 것의 글자 수 비율과 빠진 단위 표본."""
    haystack = alnum(output_text)
    total = found = 0
    missing: list[str] = []
    for unit in reference_units:
        needle = alnum(unit)
        if not needle:
            continue
        total += len(needle)
        if needle in haystack:
            found += len(needle)
        else:
            missing.append(unit.strip())
    return {
        "ref_chars": total,
        "covered_chars": found,
        "coverage": round(found / total, 4) if total else None,
        "missing_units": len(missing),
        "missing_samples": [m[:80] for m in missing[:5]],
    }


def char_coverage(reference_text: str, output_text: str) -> float | None:
    """순서와 무관한 대조: 기준의 글자·숫자 빈도 중 결과에도 있는 비율."""
    ref, out = Counter(alnum(reference_text)), Counter(alnum(output_text))
    total = sum(ref.values())
    return round(sum(min(n, out[ch]) for ch, n in ref.items()) / total, 4) if total else None


def contiguous_share(cells: list[str], text: str) -> dict[str, Any]:
    haystack = alnum(text)
    long_cells = [alnum(cell) for cell in cells if len(alnum(cell)) >= 20]
    hit = sum(1 for cell in long_cells if cell in haystack)
    return {
        "long_cells": len(long_cells),
        "contiguous": hit,
        "share": round(hit / len(long_cells), 4) if long_cells else None,
    }


# --------------------------------------------------------------------------- PDF


# 표 셀 글자 수가 표 영역 글자 수의 이 비율에 못 미치면 셀 추출이 내용을 잃은 것으로 본다
TABLE_KEEP_RATIO = 0.98


def convert_pdf(path: Path) -> dict[str, Any]:
    import pdfplumber

    lines: list[dict[str, Any]] = []
    merged: list[str] = []
    lossy_tables = 0
    kept_cells: list[str] = []
    tables: list[list[list[str | None]]] = []
    table_pages: set[int] = set()
    empty_pages: list[int] = []
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, start=1):
            page_lines = page.extract_text_lines()
            if not page_lines:
                empty_pages.append(page_no)
            for line_no, line in enumerate(page_lines, start=1):
                lines.append({"page": page_no, "line": line_no, "text": line["text"]})
            # (b) 표 영역은 셀 단위로, 표 밖은 줄 단위로 뽑아 세로 위치 순으로 합친다
            outside = page
            blocks: list[tuple[float, list[str]]] = []
            for found in page.find_tables():
                rows = found.extract()
                tables.append(rows)
                table_pages.add(page_no)
                x0, top, x1, bottom = found.bbox
                px0, ptop, px1, pbottom = page.bbox
                bbox = (max(x0, px0), max(top, ptop), min(x1, px1), min(bottom, pbottom))
                # 셀 추출이 표 영역의 글자를 잃으면(테두리 없는 칸 등) 그 표는 줄 텍스트로 둔다
                in_area = len(alnum(page.crop(bbox).extract_text() or ""))
                in_cells = len(alnum("".join(cell or "" for row in rows for cell in row)))
                if in_cells < TABLE_KEEP_RATIO * in_area:
                    lossy_tables += 1
                    continue
                kept_cells.extend(cell for row in rows for cell in row if cell)
                outside = outside.outside_bbox(bbox)
                blocks.append((top, pdf_table_rows(rows)))
            for line in outside.extract_text_lines():
                blocks.append((line["top"], [line["text"]]))
            for _, block in sorted(blocks, key=lambda item: item[0]):
                merged.extend(block)
    text = "\n".join(line["text"] for line in lines)
    cells = [cell for table in tables for row in table for cell in row]
    filled = [cell for cell in cells if cell and cell.strip()]
    return {
        "text": text,
        "merged_text": "\n".join(merged),
        "pages": pages,
        "lines": len(lines),
        "empty_pages": empty_pages,
        "tables": len(tables),
        "table_pages": len(table_pages),
        "lossy_tables": lossy_tables,
        "kept_cells": kept_cells,
        "cells": len(cells),
        "filled_cells": len(filled),
        "table_rows": tables,
    }


def pdftotext_lines(path: Path) -> list[str] | None:
    if shutil.which("pdftotext") is None:
        return None
    out = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, check=True
    ).stdout.decode("utf-8", errors="replace")
    return [line for line in out.replace("\f", "\n").splitlines() if line.strip()]


def pdf_table_rows(table: list[list[str | None]]) -> list[str]:
    return [
        "| " + " | ".join(WS.sub(" ", cell or "").strip() for cell in row) + " |" for row in table
    ]


def pdf_tables_as_text(tables: list[list[list[str | None]]]) -> str:
    out: list[str] = []
    for index, table in enumerate(tables, start=1):
        out.append(f"[표 {index}]")
        out.extend(pdf_table_rows(table))
    return "\n".join(out)


# --------------------------------------------------------------------------- HWP

HWPTAG_PARA_HEADER = 16 + 50
HWPTAG_PARA_TEXT = 16 + 51
HWPTAG_CTRL_HEADER = 16 + 55
HWPTAG_LIST_HEADER = 16 + 56
TABLE_CTRL_ID = b" lbt"  # 'tbl ' (리틀 엔디언으로 저장)
# 문단 텍스트 안의 제어 문자 (HWP 5.0 문서 형식): 아래 코드는 8 WCHAR를 차지한다
EXTENDED_CONTROLS = set(range(1, 10)) | {11, 12} | set(range(14, 24))


def hwp_records(path: Path) -> list[tuple[int, int, bytes]]:
    """본문 스트림의 레코드 `(tag, level, payload)`를 구역 순서대로 (pyhwp 없이 olefile만)."""
    import olefile

    ole = olefile.OleFileIO(str(path))
    try:
        flags = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)[0]
        if flags & 0x2:
            raise ValueError("암호가 걸린 문서")
        if flags & 0x4:
            raise ValueError("배포용 문서(ViewText 암호화)는 읽지 못한다")
        sections = sorted(
            (entry for entry in ole.listdir() if entry[0] == "BodyText"),
            key=lambda entry: int(re.sub(r"\D", "", entry[1]) or 0),
        )
        out: list[tuple[int, int, bytes]] = []
        for entry in sections:
            data = ole.openstream(entry).read()
            if flags & 0x1:
                data = zlib.decompress(data, -15)
            pos = 0
            while pos + 4 <= len(data):
                header = struct.unpack_from("<I", data, pos)[0]
                pos += 4
                tag, level, size = header & 0x3FF, (header >> 10) & 0x3FF, header >> 20
                if size == 0xFFF:
                    size = struct.unpack_from("<I", data, pos)[0]
                    pos += 4
                out.append((tag, level, data[pos : pos + size]))
                pos += size
        return out
    finally:
        ole.close()


def raw_hwp_paragraphs(path: Path) -> list[str]:
    """문단 텍스트 레코드만 순서대로 (대조 기준)."""
    return [
        _decode_para_text(payload)
        for tag, _, payload in hwp_records(path)
        if tag == HWPTAG_PARA_TEXT
    ]


class _Record:
    def __init__(self, tag: int, level: int, payload: bytes) -> None:
        self.tag, self.level, self.payload = tag, level, payload
        self.children: list[_Record] = []


class HwpRecordText:
    """레코드 트리 → 줄 목록 (pyhwp 없음). 출력 형태는 `HwpXmlText`와 같다."""

    def __init__(self) -> None:
        self.tables = 0
        self.cells = 0

    def convert(self, path: Path) -> list[str]:
        root = _Record(0, -1, b"")
        stack = [root]
        for tag, level, payload in hwp_records(path):
            while stack[-1].level >= level:
                stack.pop()
            node = _Record(tag, level, payload)
            stack[-1].children.append(node)
            stack.append(node)
        return self._blocks(root)

    def _blocks(self, node: _Record) -> list[str]:
        out: list[str] = []
        for child in node.children:
            if child.tag == HWPTAG_PARA_HEADER:
                out.extend(self._paragraph(child))
            else:
                out.extend(self._blocks(child))
        return out

    def _paragraph(self, para: _Record) -> list[str]:
        text = ""
        after: list[str] = []
        for child in para.children:
            if child.tag == HWPTAG_PARA_TEXT:
                text = WS.sub(" ", _decode_para_text(child.payload)).strip()
            elif child.tag == HWPTAG_CTRL_HEADER and child.payload[:4] == TABLE_CTRL_ID:
                after.extend(self._table(child))
            else:
                after.extend(self._blocks(child))
        return ([text] if text else []) + after

    def _table(self, ctrl: _Record) -> list[str]:
        self.tables += 1
        rows: dict[int, dict[int, list[str]]] = {}
        current: list[str] | None = None
        for child in ctrl.children:
            if child.tag == HWPTAG_LIST_HEADER:
                # 목록 머리(8바이트) 뒤에 셀 주소: col, row (각 UINT16)
                col, row = struct.unpack_from("<HH", child.payload, 8)
                current = rows.setdefault(row, {}).setdefault(col, [])
                self.cells += 1
            elif child.tag == HWPTAG_PARA_HEADER and current is not None:
                current.extend(self._paragraph(child))
        return [
            "| " + " | ".join(" / ".join(rows[row][col]) for col in sorted(rows[row])) + " |"
            for row in sorted(rows)
        ]


def _decode_para_text(payload: bytes) -> str:
    units = struct.unpack(f"<{len(payload) // 2}H", payload[: len(payload) // 2 * 2])
    out: list[str] = []
    i = 0
    while i < len(units):
        code = units[i]
        if code in EXTENDED_CONTROLS:
            i += 8
            out.append(" ")
        elif code < 32:
            i += 1
            out.append(" ")
        else:
            i += 1
            out.append(chr(code))
    # 서로게이트 쌍을 문자로 합친다
    return "".join(out).encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def hwp5txt(path: Path) -> str:
    from hwp5.hwp5txt import TextTransform
    from hwp5.xmlmodel import Hwp5File

    buffer = io.BytesIO()
    hwp5file = Hwp5File(str(path))
    try:
        TextTransform().transform_hwp5_to_text(hwp5file, buffer)
    finally:
        hwp5file.close()
    return buffer.getvalue().decode("utf-8")


def hwp_xml(path: Path) -> bytes:
    from hwp5.xmlmodel import Hwp5File

    buffer = io.BytesIO()
    hwp5file = Hwp5File(str(path))
    try:
        hwp5file.xmlevents(embedbin=False).dump(buffer)
    finally:
        hwp5file.close()
    return buffer.getvalue()


class HwpXmlText:
    """pyhwp XML → 줄 목록. 표는 `| 셀 | 셀 |` 행, 표 밖 문단은 한 줄."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.tables = 0
        self.nested_tables = 0
        self.cells = 0
        self.filled_cells = 0
        self.merged_cells = 0
        self.cell_texts: list[str] = []

    def convert(self, xml: bytes) -> list[str]:
        root = ET.fromstring(xml)
        for block in self._blocks(root, depth=0):
            self.lines.append(block)
        return self.lines

    def _blocks(self, elem: ET.Element, depth: int) -> list[str]:
        out: list[str] = []
        for child in elem:
            if child.tag == "Paragraph":
                out.extend(self._paragraph(child, depth))
            elif child.tag == "TableControl":
                out.extend(self._table(child, depth))
            else:
                out.extend(self._blocks(child, depth))
        return out

    def _paragraph(self, para: ET.Element, depth: int) -> list[str]:
        pieces: list[str] = []
        after: list[str] = []
        for seg in para:
            if seg.tag != "LineSeg":
                after.extend(self._blocks_of(seg, depth))
                continue
            for node in seg:
                if node.tag == "Text":
                    pieces.append(node.text or "")
                elif node.tag == "ControlChar":
                    if node.get("name") in (
                        "TAB",
                        "LINE_BREAK",
                        "NONBREAK_SPACE",
                        "FIXWIDTH_SPACE",
                    ):
                        pieces.append(" ")
                elif node.find(".//Paragraph") is None:
                    # 하이퍼링크 같은 줄 안 필드: 문단 안 제자리에 둔다
                    pieces.extend(inner.text or "" for inner in node.iter("Text"))
                else:
                    after.extend(self._blocks_of(node, depth))
        text = WS.sub(" ", "".join(pieces)).strip()
        return ([text] if text else []) + after

    def _blocks_of(self, node: ET.Element, depth: int) -> list[str]:
        if node.tag == "TableControl":
            return self._table(node, depth)
        return self._blocks(node, depth)

    def _table(self, table: ET.Element, depth: int) -> list[str]:
        self.tables += 1
        if depth > 0:
            self.nested_tables += 1
        rows: list[str] = []
        for row in table.iter("TableRow"):
            if not self._belongs(table, row):
                continue
            cells: list[str] = []
            for cell in row:
                if cell.tag != "TableCell":
                    continue
                # 셀 안 문단은 " / "로 잇고, 셀 안의 표는 행을 그대로 이어 붙인다
                text = " / ".join(self._blocks(cell, depth + 1))
                self.cells += 1
                if text:
                    self.filled_cells += 1
                    self.cell_texts.append(text)
                if int(cell.get("colspan", "1")) > 1 or int(cell.get("rowspan", "1")) > 1:
                    self.merged_cells += 1
                cells.append(text)
            rows.append("| " + " | ".join(cells) + " |")
        return rows

    @staticmethod
    def _belongs(table: ET.Element, row: ET.Element) -> bool:
        """`row`가 중첩 표가 아니라 이 표의 직속 행인지."""
        for body in table:
            if body.tag == "TableBody" and row in list(body):
                return True
        return False


def convert_hwp(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    reference = raw_hwp_paragraphs(path)
    result["reference_paragraphs"] = len([p for p in reference if alnum(p)])

    started = time.perf_counter()
    try:
        plain = hwp5txt(path)
        result["hwp5txt"] = {
            "ok": True,
            "seconds": round(time.perf_counter() - started, 2),
            "chars": len(squash(plain)),
            "table_placeholders": len(re.findall(r"^<표>$", plain, flags=re.MULTILINE)),
            **coverage(reference, plain),
        }
    except Exception as exc:  # noqa: BLE001 — 스파이크: 실패 유형을 그대로 기록
        plain = ""
        result["hwp5txt"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    started = time.perf_counter()
    try:
        walker = HwpXmlText()
        lines = walker.convert(hwp_xml(path))
        text = "\n".join(lines)
        cell_cov = coverage(walker.cell_texts, plain) if plain else None
        result["xml"] = {
            "ok": True,
            "seconds": round(time.perf_counter() - started, 2),
            "chars": len(squash(text)),
            "lines": len(lines),
            "tables": walker.tables,
            "nested_tables": walker.nested_tables,
            "cells": walker.cells,
            "filled_cells": walker.filled_cells,
            "merged_cells": walker.merged_cells,
            **coverage(reference, text),
        }
        result["hwp5txt_cell_coverage"] = cell_cov and cell_cov["coverage"]
        result["text"] = text
    except Exception as exc:  # noqa: BLE001
        lines = []
        result["xml"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    started = time.perf_counter()
    try:
        reader = HwpRecordText()
        own_lines = reader.convert(path)
        own_text = "\n".join(own_lines)
        result["records"] = {
            "ok": True,
            "seconds": round(time.perf_counter() - started, 2),
            "chars": len(squash(own_text)),
            "lines": len(own_lines),
            "tables": reader.tables,
            "cells": reader.cells,
            **coverage(reference, own_text),
            "agrees_with_xml": {
                "same_line_count": len(own_lines) == len(lines),
                "identical_lines": sum(1 for a, b in zip(own_lines, lines, strict=False) if a == b),
                "same_alnum_lines": sum(
                    1 for a, b in zip(own_lines, lines, strict=False) if alnum(a) == alnum(b)
                ),
            },
        }
        result["records_text"] = own_text
    except Exception as exc:  # noqa: BLE001
        result["records"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    result["hwp5txt_text"] = plain
    return result


# --------------------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, required=True, help="공고 원문 디렉터리")
    parser.add_argument("--dump", type=Path, help="변환 텍스트를 저장할 디렉터리 (저장소 밖)")
    args = parser.parse_args()
    if args.dump:
        args.dump.mkdir(parents=True, exist_ok=True)

    report: list[dict[str, Any]] = []
    for path in sorted(args.dir.iterdir()):
        suffix = path.suffix.lower()
        if suffix not in (".pdf", ".hwp", ".hwpx"):
            continue
        entry: dict[str, Any] = {
            "file": path.name,
            "format": suffix[1:],
            "bytes": path.stat().st_size,
        }
        started = time.perf_counter()
        if suffix == ".pdf":
            converted = convert_pdf(path)
            entry["seconds"] = round(time.perf_counter() - started, 2)
            text = converted.pop("text")
            merged_text = converted.pop("merged_text")
            table_rows = converted.pop("table_rows")
            kept_cells = converted.pop("kept_cells")
            entry.update(converted)
            entry["chars"] = len(squash(text))
            reference = pdftotext_lines(path)
            entry["vs_pdftotext"] = coverage(reference, text) if reference is not None else None
            cell_texts = [cell for table in table_rows for row in table for cell in row if cell]
            entry["lines_text"] = {
                "char_coverage": reference and char_coverage("\n".join(reference), text),
                "cells_contiguous": contiguous_share(cell_texts, text),
            }
            entry["merged_text"] = {
                "chars": len(squash(merged_text)),
                "char_coverage": reference and char_coverage("\n".join(reference), merged_text),
                "cells_contiguous": contiguous_share(cell_texts, merged_text),
                "kept_cells_contiguous": contiguous_share(kept_cells, merged_text),
            }
            if args.dump:
                (args.dump / f"{path.stem}.merged.txt").write_text(merged_text, encoding="utf-8")
                (args.dump / f"{path.stem}.pdfplumber.txt").write_text(text, encoding="utf-8")
                (args.dump / f"{path.stem}.tables.txt").write_text(
                    pdf_tables_as_text(table_rows), encoding="utf-8"
                )
        elif suffix == ".hwp":
            converted = convert_hwp(path)
            text = converted.pop("text", "")
            plain = converted.pop("hwp5txt_text", "")
            own_text = converted.pop("records_text", "")
            entry.update(converted)
            if args.dump:
                (args.dump / f"{path.stem}.records.txt").write_text(own_text, encoding="utf-8")
                (args.dump / f"{path.stem}.xml.txt").write_text(text, encoding="utf-8")
                (args.dump / f"{path.stem}.hwp5txt.txt").write_text(plain, encoding="utf-8")
        else:
            entry["note"] = "HWPX 변환기는 이 스파이크에서 구현하지 않았다 (표본 없음)"
        report.append(entry)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
