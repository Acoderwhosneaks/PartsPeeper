"""[B digest] — parts schedule extraction.

Consumes a 2D parts drawing (PDF) and emits RawPart[] per the shared contract
(part_contract.md). The heavy lifting is done by pdfplumber's ruling-line table
extraction: the Moz schedules are drawn with visible grid lines, so
`page.extract_tables()` reconstructs them column-accurate, sidestepping the
reading-order column scramble that plain text extraction produces.

Universality note (operator seq16 "various inputs"): a table qualifies as a
*part schedule* by STRUCTURE, not by a hardcoded Moz catalog — its header row
must carry a part-number-like column and a quantity-like column. Any drawing set
that renders its parts in a ruled schedule with those two concepts is digested
the same way.

Interface:
    digest_pdf(path) -> list[RawPart]   (RawPart = plain dict, see contract)

The word/table extraction helper `_extract_page` is a TEMPORARY stand-in for
ceres's [A extract]; when extract.py lands, swap _extract_page for A's output.
The RawPart[] output shape is the locked B->C contract and will not change.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import pdfplumber


# --- header detection (structural, not catalog-based) ---------------------

def _norm(cell: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (cell or "")).strip().upper().rstrip(":")


def _is_partno_header(c: str) -> bool:
    return c in ("PART NO", "PART NO.", "PART NUMBER", "PART", "MARK", "PART MARK")


def _is_qty_header(c: str) -> bool:
    return c in ("QTY", "QTY.", "QUANTITY", "QTY:")


def _classify_columns(header: list[str]) -> Optional[dict[str, int]]:
    """Map a schedule header row to column roles. Returns None if this isn't a
    part schedule (no part-no column, or no qty column)."""
    roles: dict[str, int] = {}
    for i, raw in enumerate(header):
        c = _norm(raw)
        if _is_partno_header(c) and "partno" not in roles:
            roles["partno"] = i
        elif _is_qty_header(c) and "qty" not in roles:
            roles["qty"] = i
        elif c.startswith("FINISH") and "finish" not in roles:
            roles["finish"] = i
        elif c.startswith("X") and "x" not in roles:      # "X" or "X (ARC LENGTH)"
            roles["x"] = i
        elif c == "Y" and "y" not in roles:
            roles["y"] = i
    if "partno" in roles and "qty" in roles:
        return roles
    return None


# --- page context: finish legend + material hint --------------------------

_FINISH_CODE_RE = re.compile(r"^(MTL\.\d|SS\.\d)$")


def _page_finish_legend(words: list[dict]) -> dict[str, str]:
    """Pull the per-page FINISH SCHEDULE legend, e.g. MTL.1 -> 'STAINLESS STEEL
    5WL TEXTURE', by reading the words to the RIGHT of each finish code on the
    same line. Position-based, so the description column doesn't scramble.
    Best-effort; [C] holds the canonical mapping."""
    legend: dict[str, str] = {}
    codes = [w for w in words if _FINISH_CODE_RE.match(w["text"].strip())]
    for c in codes:
        code = c["text"].strip()
        if code in legend:
            continue
        same_line = [w for w in words
                     if abs(w["top"] - c["top"]) < 4 and w["x0"] > c["x1"] - 1]
        same_line.sort(key=lambda w: w["x0"])
        desc_words = []
        for w in same_line:
            if _FINISH_CODE_RE.match(w["text"].strip()):
                break  # next code begins the next legend entry
            desc_words.append(w["text"])
        desc = re.sub(r"\s+", " ", " ".join(desc_words)).strip(" -:")
        if 3 < len(desc) < 80:
            legend[code] = desc
    return legend


def _material_hint(text: str) -> Optional[str]:
    m = re.search(r"MATERIAL:\s*([0-9]+\s*GA[A-Z .]*|\.\d+\"?\s*ALUM[A-Z .]*)", text, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip(" .")
    return None


def _sheet_id(text: str) -> Optional[str]:
    # sheet tag like P50 / D10 / P2 appears near "SHEET"; grab a short alnum tag
    m = re.search(r"\b([A-Z]\d{1,3})\b\s*\n?\s*\d+ OF \d+", text)
    return m.group(1) if m else None


# --- schedule title lookup (for verbatim part_type_raw) -------------------

_SCHED_TITLE_RE = re.compile(
    r"([A-Z][A-Z /\-]+?)\s+SCHEDULE\b", re.I)


def _title_for_table(page_words: list[dict], table_bbox: tuple) -> Optional[str]:
    """Find the '<TYPE> SCHEDULE' label sitting just above a table's bbox,
    yielding a verbatim part_type_raw like 'COLUMN COVER' or 'RECESSED CAPITAL'.

    Pages stack several schedules, so we isolate the ONE title line whose bottom
    is immediately above this table's top and which horizontally overlaps the
    table's x-range — not just any nearby word."""
    x0, top, x1, bottom = table_bbox
    # candidate words in a tight band above the table, overlapping its columns
    cand = [w for w in page_words
            if (top - 55) <= w["top"] and w["bottom"] <= top + 8
            and w["x1"] > x0 - 6 and w["x0"] < x1 + 6]
    if not cand:
        return None
    # group into lines by rounded top; keep the line closest above the table
    lines: dict[int, list[dict]] = {}
    for w in cand:
        lines.setdefault(round(w["top"] / 3) * 3, []).append(w)
    for key in sorted(lines, key=lambda k: -k):        # nearest above first
        line = sorted(lines[key], key=lambda w: w["x0"])
        txt = " ".join(w["text"] for w in line).upper()
        m = _SCHED_TITLE_RE.search(txt)
        if m:
            t = re.sub(r"^FINISH\s+", "", m.group(1).strip()).strip()
            if t and t != "FINISH":
                return t
    return None


# --- part-mark validity (drop boilerplate rows) ---------------------------

_MARK_RE = re.compile(r"^[A-Z]{1,4}\d+[A-Z0-9.\-]*$")


def _looks_like_mark(s: str) -> bool:
    s = (s or "").strip()
    return bool(_MARK_RE.match(s.upper())) and any(ch.isdigit() for ch in s)


# --- temporary [A] stand-in ----------------------------------------------

def _extract_page(page) -> dict[str, Any]:
    """TEMP stand-in for ceres's [A extract]. Returns the raw material B needs
    from one page: ruled tables, words (for title lookup), and full text."""
    return {
        "tables": page.find_tables(),
        "words": page.extract_words(use_text_flow=False, keep_blank_chars=False),
        "text": page.extract_text() or "",
    }


# --- main digest ----------------------------------------------------------

def digest_pdf(path: str) -> list[dict]:
    raw_parts: list[dict] = []
    with pdfplumber.open(path) as pdf:
        for pageno, page in enumerate(pdf.pages, start=1):
            ctx = _extract_page(page)
            text = ctx["text"]
            words = ctx["words"]
            legend = _page_finish_legend(words)
            material = _material_hint(text)
            sheet = _sheet_id(text)

            for tbl in ctx["tables"]:
                rows = tbl.extract()
                if not rows or not rows[0]:
                    continue
                roles = _classify_columns(rows[0])
                if not roles:
                    continue
                title = _title_for_table(words, tbl.bbox)
                last_finish = None
                for r in rows[1:]:
                    def cell(role):
                        i = roles.get(role)
                        return (r[i].strip() if (i is not None and i < len(r) and r[i]) else "")
                    mark = cell("partno")
                    if not _looks_like_mark(mark):
                        continue  # boilerplate / spanned row
                    finish = cell("finish") or last_finish
                    if cell("finish"):
                        last_finish = cell("finish")  # forward-fill merged FINISH
                    raw_parts.append({
                        "source_doc": path.replace("\\", "/").split("/")[-1],
                        "source_page": pageno,
                        "sheet_id": sheet,
                        "cell_index": None,
                        "part_type_raw": title,          # verbatim schedule type, may be None
                        "part_mark": mark,
                        "schedule": {
                            "finish_code": finish or None,
                            "x": cell("x") or None,
                            "y": cell("y") or None,
                            "qty": cell("qty") or None,
                        },
                        "finish_legend": legend,
                        "material_hint": material,
                        "notes_raw": [],
                        "raw_tokens": [],
                    })
    return raw_parts


if __name__ == "__main__":
    import json
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "parts input.pdf"
    parts = digest_pdf(src)
    print(f"# digested {len(parts)} raw parts from {src}")
    print(json.dumps(parts, indent=2))
