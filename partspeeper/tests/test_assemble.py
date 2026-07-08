"""Golden tests for [D assemble] + validation.

Runnable two ways:
    pytest partspeeper/tests/test_assemble.py
    python  partspeeper/tests/test_assemble.py       (no pytest needed)

Fixtures are synthetic PartRecords shaped exactly like ../part_contract.md, using
the Miami input example the team scouted (C30 column: segments C30A..C30D +
recessed capital/base RC30/RB30).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from partspeeper.assemble import build_rows, to_csv_string  # noqa: E402
from partspeeper import validate as V  # noqa: E402


def _rec(**kw):
    base = dict(
        source_doc="parts input.pdf", source_page=30, sheet_id="P1", cell_index=1,
        part_mark="", assembly="", category="ColumnCover", type_label="Column Cover",
        material="16 GA Stainless Steel", finish_code="MTL.1",
        finish="Stainless Steel 5WL Texture", dim_x="14\"", dim_y="108\"",
        dim_dia=None, dimensions="14\" arc x 108\" Ht.", qty=1, crate="",
        description="", notes="", flags=[],
    )
    base.update(kw)
    return base


def sample_records():
    return [
        _rec(part_mark="C30A", assembly="C30", cell_index=1, qty=2,
             description='C30A / 16 GA Stainless Steel / Round Column Cover Anchor Segment / 14" arc x 108" Ht. in Stainless Steel 5WL Texture.'),
        _rec(part_mark="C30B", assembly="C30", cell_index=2, qty=2, dim_x='16"',
             dimensions='16" arc x 108" Ht.',
             description='C30B / 16 GA Stainless Steel / Round Column Cover Segment / 16" arc x 108" Ht. in Stainless Steel 5WL Texture.'),
        _rec(part_mark="RC30", assembly="RC30", cell_index=3, qty=1, category="RecessedCapital",
             finish_code="SS.1", finish="Brushed Stainless Steel No:4", dim_x='6"', dim_y='14"',
             dimensions='6" x 14"',
             description='RC30 / Recessed Capital Segment / 6" x 14" / Brushed Stainless Steel No:4.'),
    ]


def test_rows_have_headers_and_sequential_partnum():
    rows = build_rows(sample_records())
    # C30 header, C30A, C30B, then RC30 header, RC30  => 5 rows
    assert [r.kind for r in rows] == ["header", "part", "part", "header", "part"]
    assert [r.part_num for r in rows] == ["001", "002", "003", "004", "005"]
    # header rows: qty blank, "<Assembly> Column"
    assert rows[0].qty == "" and rows[0].description == "C30 Column"
    assert rows[3].qty == "" and rows[3].description == "RC30 Column"
    # part rows carry qty
    assert rows[1].qty == 2 and rows[1].description.startswith("C30A")


def test_csv_shape():
    csv = to_csv_string(sample_records())
    lines = csv.strip().splitlines()
    assert lines[0] == "PartNum,Qty,Description"
    assert lines[1].startswith("001,,")          # header row: empty qty
    assert lines[2].startswith("002,2,")          # first part
    assert len(lines) == 1 + 5                     # header + 5 rows


def test_qty_rollup_identical_mark():
    recs = sample_records()
    # same mark C30A appears again on another page with identical spec -> qty sums
    dup = dict(recs[0]); dup["source_page"] = 31; dup["cell_index"] = 1
    rows = build_rows(recs + [dup])
    c30a = [r for r in rows if r.description.startswith("C30A")]
    assert len(c30a) == 1, "identical duplicate mark must collapse to one row"
    assert c30a[0].qty == 4, "qty should roll up 2+2"


def test_conflicting_mark_kept_and_flagged():
    recs = sample_records()
    bad = dict(recs[0]); bad["dim_x"] = '99"'
    bad["description"] = 'C30A / 16 GA Stainless Steel / DIFFERENT SPEC / 99" arc x 108" Ht.'
    rows = build_rows(recs + [bad])
    c30a = [r for r in rows if r.part_num and r.description.startswith("C30A")]
    assert len(c30a) == 2, "conflicting specs for same mark must NOT be merged away"
    assert all("CONFLICT" in r.flags for r in c30a)


def test_validate_clean_passes():
    rep = V.validate(sample_records(), expected_marks=["C30A", "C30B", "RC30"])
    assert rep["ok"], V.format_report(rep)
    assert rep["n_part_rows"] == 3
    assert rep["n_header_rows"] == 2


def test_validate_missing_mark_fails():
    rep = V.validate(sample_records(), expected_marks=["C30A", "C30B", "RC30", "RB30"])
    assert not rep["ok"]
    assert any(e["type"] == "MISSING" and e["part_mark"] == "RB30" for e in rep["errors"])


def test_validate_dropped_dim_token_fails():
    recs = sample_records()
    # Description silently drops the height dimension -> verbatim check must catch it
    recs[0]["description"] = 'C30A / 16 GA Stainless Steel / Round Column Cover Anchor Segment / 14" arc in Stainless Steel 5WL Texture.'
    rep = V.validate(recs)
    assert not rep["ok"]
    assert any(e["type"] == "DIM_TOKEN_DROPPED" and e["field"] == "dim_y" for e in rep["errors"])


def test_normalized_finish_is_warning_not_error():
    recs = sample_records()
    # [C] normalized the finish phrasing in the Description; raw finish field differs.
    recs[0]["finish"] = "Brushed Stainless Steel No:4"
    recs[0]["description"] = 'C30A / 16 GA Stainless Steel / Round Column Cover Anchor Segment / 14" arc x 108" Ht. in Brushed #4 Finish.'
    rep = V.validate(recs)
    assert rep["ok"], "finish phrasing difference must NOT block"
    assert any(w["type"] == "FINISH_PHRASING_DIFFERS" for w in rep["warnings"])


def test_c_flags_are_ingested():
    recs = sample_records()
    recs[1]["flags"] = ["SEGMENT_ROLE_UNKNOWN"]      # soft -> warning
    recs[2]["flags"] = ["MISSING_DIMS"]               # hard -> error
    rep = V.validate(recs)
    assert not rep["ok"]
    assert any(e["type"] == "FLAG_MISSING_DIMS" for e in rep["errors"])
    assert any(w["type"] == "FLAG_SEGMENT_ROLE_UNKNOWN" for w in rep["warnings"])


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
