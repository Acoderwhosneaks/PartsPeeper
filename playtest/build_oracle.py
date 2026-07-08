"""Playtester independent ground-truth oracle  (phobos).

PURPOSE: an acceptance oracle for the parts pipeline that is derived
INDEPENDENTLY of the pipeline code (it does NOT import partspeeper.digest). If a
bug lives in the pipeline's extraction, this oracle must not share it — so it
uses a different code path (pdfplumber `extract_tables()` raw cell grids +
positional column parse) and a SECOND cross-check (a word-token scan for part
marks). When both methods agree on the mark set, the ground truth is trusted.

Scope of the oracle (Miami FIXTURE #1):
  - every ruled part-schedule row  -> one expected part
  - + exactly one fastener from callouts (qty BLANK, per Jeff's ruling)
  - BY-OTHERS / installation-detail text excluded

Output: playtest/oracle.json  (list of expected parts w/ verbatim specs)
        + printed family counts / total for the coverage gate.

This is test-oracle data, not pipeline code — squarely playtester territory.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

import pdfplumber

INPUT = sys.argv[1] if len(sys.argv) > 1 else "parts input.pdf"

# structural header cues (generic concepts, not Miami catalog)
PARTNO = re.compile(r"^\s*PART\s*(NO|NUMBER|MARK)?\.?\s*:?\s*$", re.I)
QTY = re.compile(r"^\s*(QTY|QUANTITY)\.?\s*:?\s*$", re.I)
FINISH = re.compile(r"^\s*FINISH\s*:?\s*$", re.I)
XCOL = re.compile(r"^\s*X\b", re.I)
YCOL = re.compile(r"^\s*Y\s*$", re.I)
MARK = re.compile(r"^[A-Z]{1,4}\d+[A-Z0-9.\-]*$")


def _norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def _col_index(header, pat):
    for i, c in enumerate(header):
        if pat.match(_norm(c)):
            return i
    return None


# ---- METHOD 1: raw ruled-grid parse -------------------------------------

def extract_via_grids(pdf):
    parts = []
    for pageno, page in enumerate(pdf.pages, 1):
        for grid in page.extract_tables():
            if not grid or not grid[0]:
                continue
            header = [_norm(c) for c in grid[0]]
            ci_mark = _col_index(header, PARTNO)
            ci_qty = _col_index(header, QTY)
            if ci_mark is None or ci_qty is None:
                continue  # not a part schedule
            ci_fin = _col_index(header, FINISH)
            ci_x = _col_index(header, XCOL)
            ci_y = _col_index(header, YCOL)
            last_fin = None
            body = grid[1:]
            i = 0
            while i < len(body):
                row = body[i]

                def cell(ci, r=row):
                    return _norm(r[ci]) if (ci is not None and ci < len(r)) else ""

                markcell = cell(ci_mark)
                fin = cell(ci_fin) or last_fin
                if cell(ci_fin):
                    last_fin = cell(ci_fin)

                toks = markcell.split()
                if len(toks) > 1 and all(MARK.match(t) for t in toks):
                    # MERGED-MARK cell: N marks stacked into one PART-NO cell while
                    # X/Y/QTY split across this row + the following empty-mark rows.
                    # Pair mark[k] with row[i+k]'s X/Y/QTY. (p69 C24A-D case.)
                    rows_for = [row]
                    j = i + 1
                    while j < len(body) and len(rows_for) < len(toks) and not MARK.match(cell(ci_mark, body[j])):
                        rows_for.append(body[j])
                        j += 1
                    for k, t in enumerate(toks):
                        r = rows_for[k] if k < len(rows_for) else row
                        parts.append({
                            "mark": t, "page": pageno,
                            "qty": cell(ci_qty, r), "x": cell(ci_x, r), "y": cell(ci_y, r),
                            "finish_code": fin or None,
                            "recovered_merged_cell": True,
                        })
                    i = j
                    continue
                if MARK.match(markcell):
                    parts.append({
                        "mark": markcell, "page": pageno,
                        "qty": cell(ci_qty), "x": cell(ci_x), "y": cell(ci_y),
                        "finish_code": fin or None,
                    })
                i += 1
    return parts


# ---- METHOD 2: independent word-token cross-check -----------------------

def marks_via_words(pdf):
    """Count distinct part-mark tokens that sit inside a schedule column of a
    ruled table — a totally separate signal from the grid parse."""
    found = set()
    for page in pdf.pages:
        table_bboxes = [t.bbox for t in page.find_tables()]
        for w in page.extract_words():
            t = w["text"].strip()
            if not MARK.match(t):
                continue
            cx = (w["x0"] + w["x1"]) / 2
            cy = (w["top"] + w["bottom"]) / 2
            for (x0, top, x1, bottom) in table_bboxes:
                if x0 - 2 <= cx <= x1 + 2 and top - 2 <= cy <= bottom + 2:
                    found.add(t)
                    break
    return found


def family(mark):
    return re.match(r"^[A-Z]+", mark).group()


def main():
    with pdfplumber.open(INPUT) as pdf:
        grid_parts = extract_via_grids(pdf)
        word_marks = marks_via_words(pdf)

    grid_marks = {p["mark"] for p in grid_parts}
    print(f"METHOD 1 (grids): {len(grid_parts)} rows, {len(grid_marks)} distinct marks")
    print(f"METHOD 2 (words): {len(word_marks)} distinct marks")
    only_grid = grid_marks - word_marks
    only_word = word_marks - grid_marks
    print(f"AGREEMENT: {len(grid_marks & word_marks)} shared | grid-only={sorted(only_grid)} | word-only={sorted(only_word)}")

    dupes = {m: c for m, c in Counter(p["mark"] for p in grid_parts).items() if c > 1}
    print(f"duplicate marks in grid parse: {dupes or 'none'}")

    fam = Counter(family(p["mark"]) for p in grid_parts)
    print(f"families: {dict(sorted(fam.items()))}")

    # fastener: exactly one, from callouts, qty BLANK (Jeff's ruling)
    fastener = {
        "mark": "SCREW-12x0.75", "page": None,
        "qty": "", "x": None, "y": None, "finish_code": None,
        "note": '#12 x 3/4" self-tapping anchor screw, 16 GA SS, matching finish; '
                "callout-only, no verifiable qty -> FASTENER_QTY_UNVERIFIED",
        "source": "callout",
    }

    oracle = {
        "input": INPUT,
        "schedule_parts": grid_parts,
        "fastener_parts": [fastener],
        "expected_total": len(grid_parts) + 1,
        "expected_schedule_total": len(grid_parts),
        "family_counts": dict(sorted(fam.items())),
        "methods_agree": not only_grid and not only_word,
    }
    with open("playtest/oracle.json", "w") as f:
        json.dump(oracle, f, indent=1)
    print(f"\nEXPECTED TOTAL = {oracle['expected_total']} "
          f"({len(grid_parts)} schedule + 1 fastener)")
    print(f"methods_agree = {oracle['methods_agree']}")
    print("wrote playtest/oracle.json")


if __name__ == "__main__":
    main()
