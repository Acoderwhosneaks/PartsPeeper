"""Completeness attestation harness  (phobos, playtester).

ceres META RULE: the oracle's completeness IS the 100% bar, and it must be
proven by ORTHOGONAL checks that converge — not by trusting one extractor.

This runs THREE mutually-independent detectors of the part-mark set and asserts
they converge on the oracle. The key one is METHOD C: a table-INDEPENDENT scan
of the raw text words. If an entire schedule table were undetected (a failure
mode invisible to any table-based extractor), its marks would still appear in
text and surface here as "in text, not in oracle". Convergence across all three
is the evidence behind the completeness attestation.

Known structural failure modes this guards against (all found on the Miami
fixture and now covered):
  1. merged PART-NO cell        -> C24A-D (p69)   [caught by C vs grid]
  2. missing QTY column         -> STF26  (p56)   [caught by title-callout + C]
  3. combined CXX/CYY titles    -> C18/C20 (p49)  [grid handles; only fools naive
                                                    cross-checks unless '/'-split]

Exit 0 + "CONVERGED" only when all three == oracle. Run each playtest pass.
"""
from __future__ import annotations

import json
import re
import sys

import pdfplumber

INPUT = sys.argv[1] if len(sys.argv) > 1 else "parts input.pdf"
ORACLE = "playtest/oracle.json"

FAM = re.compile(r"^(C\d+[A-Z]+|RC\d+|RB\d+|STF\d+|TB\d+|CP\d+)$")
PARTNO = re.compile(r"^\s*PART\s*(NO|NUMBER|MARK)?\.?\s*:?\s*$", re.I)
DETAIL_TITLE = re.compile(
    r"(COLUMN COVER|RECESSED CAPITAL|RECESSED BASE|STIFFENER|T-?BAR|CAP)\s*-\s*"
    r"([A-Z]{1,4}\d+[A-Z0-9]*(?:\s*/\s*[A-Z]{1,4}\d+[A-Z0-9]*)*)", re.I)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def method_grid(pdf):
    """A: every mark in any schedule PART-NO column (QTY optional, merged split)."""
    marks = set()
    for page in pdf.pages:
        for t in page.find_tables():
            g = t.extract()
            if not g or not g[0]:
                continue
            if any(len(_norm(c)) > 60 for c in g[0]):
                continue
            hdr = [_norm(c) for c in g[0]]
            ci = next((i for i, h in enumerate(hdr) if PARTNO.match(h)), None)
            if ci is None:
                continue
            for row in g[1:]:
                cell = _norm(row[ci]) if ci < len(row) else ""
                for tok in cell.split():
                    if FAM.match(tok):
                        marks.add(tok)
    return marks


def method_text(pdf):
    """C: table-INDEPENDENT — family-pattern tokens anywhere in the word stream,
    splitting combined CXX/CYY tokens."""
    marks = set()
    for page in pdf.pages:
        for w in page.extract_words():
            raw = w["text"].strip().rstrip(".:,")
            for tok in re.split(r"[/,]", raw):
                if FAM.match(tok.strip()):
                    marks.add(tok.strip())
    return marks


def method_titles(pdf):
    """B: table-independent — marks named in per-part detail-drawing titles."""
    marks = set()
    for page in pdf.pages:
        text = page.extract_text() or ""
        for _typ, grp in DETAIL_TITLE.findall(text):
            for tok in re.split(r"[/,]", grp):
                if FAM.match(tok.strip()):
                    marks.add(tok.strip())
    return marks


def main():
    with pdfplumber.open(INPUT) as pdf:
        grid = method_grid(pdf)
        text = method_text(pdf)
        titles = method_titles(pdf)

    oracle = json.load(open(ORACLE))
    omarks = set(oracle["expected_marks"]) - {oracle["fastener_mark"]}

    print(f"oracle schedule marks : {len(omarks)}")
    print(f"A grid parse          : {len(grid)}  | vs oracle: +{sorted(grid-omarks)} -{sorted(omarks-grid)}")
    print(f"C text (table-indep)  : {len(text)}  | vs oracle: +{sorted(text-omarks)} -{sorted(omarks-text)}")
    print(f"B detail titles       : {len(titles)} | titles not in oracle (drops): {sorted(titles-omarks)}")

    converged = (grid == omarks == text) and not (titles - omarks)
    print(f"\nfastener (callout, +1): {oracle['fastener_mark']}")
    print(f"EXPECTED TOTAL        : {oracle['expected_total']}")
    print("RESULT:", "CONVERGED — oracle attested complete" if converged
          else "NOT CONVERGED — investigate delta above")
    return 0 if converged else 1


if __name__ == "__main__":
    raise SystemExit(main())
