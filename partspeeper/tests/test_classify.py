"""Tests for [C classify]. Fixtures are REAL RawParts read off parts input.pdf."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classify import classify, derive_assembly, resolve_finish, build_description

LEGEND = {
    "MTL.1": "STAINLESS STEEL 5WL TEXTURE",
    "SS.1": "BRUSHED STAINLESS STEEL NO: 4 FINISHED",
}

# Real cells observed on pages 16, 18, 40, 85.
FIXTURES = [
    {"source_doc": "parts input.pdf", "source_page": 16, "sheet_id": "P1", "cell_index": 1,
     "part_type_raw": "COLUMN COVER", "part_mark": "C12A",
     "schedule": {"finish_code": "MTL.1", "x": '14"', "y": '108"', "qty": "02"},
     "finish_legend": LEGEND, "material_hint": "16 GA SS",
     "notes_raw": ['DRILL THRU .19" DIA. HOLE', "HARDWARE IN MATCHING FINISH"]},

    {"source_doc": "parts input.pdf", "source_page": 40, "sheet_id": "P25", "cell_index": 1,
     "part_type_raw": "COLUMN COVER", "part_mark": "C8A",
     "schedule": {"finish_code": "MTL.1", "x": '15"', "y": '108"', "qty": "02"},
     "finish_legend": LEGEND, "material_hint": "16 GA SS"},

    {"source_doc": "parts input.pdf", "source_page": 85, "sheet_id": "P70", "cell_index": 1,
     "part_type_raw": "COLUMN COVER", "part_mark": "C26C",
     "schedule": {"finish_code": "MTL.1", "x": '18"', "y": '108"', "qty": "02"},
     "finish_legend": LEGEND, "material_hint": "16 GA SS"},

    {"source_doc": "parts input.pdf", "source_page": 17, "sheet_id": "P2", "cell_index": 1,
     "part_type_raw": "RECESSED CAPITAL", "part_mark": "RC1",
     "schedule": {"finish_code": "SS.1", "x": '14"', "y": '8"', "qty": "02"},
     "finish_legend": LEGEND, "material_hint": "16 GA SS"},

    {"source_doc": "parts input.pdf", "source_page": 18, "sheet_id": "P3", "cell_index": 4,
     "part_type_raw": "CAP", "part_mark": "CP1",
     "schedule": {"finish_code": "SS.1", "x": '2"', "y": '8"', "qty": "4"},
     "finish_legend": LEGEND, "material_hint": "16 GA SS"},

    {"source_doc": "parts input.pdf", "source_page": 18, "sheet_id": "P3", "cell_index": 2,
     "part_type_raw": "STIFFENER", "part_mark": "STF2",
     "schedule": {"x": '13-5/8"', "y": '3/4"', "qty": "4"},
     "finish_legend": LEGEND, "material_hint": "16 GA SS"},

    {"source_doc": "parts input.pdf", "source_page": 18, "sheet_id": "P3", "cell_index": 3,
     "part_type_raw": "T-BAR", "part_mark": "TB1",
     "schedule": {"qty": "8"}, "dims_other": '1 1/2" x 1 1/2" x 5 3/4"',
     "finish_legend": LEGEND, "material_hint": "16 GA SS"},
]


def test_assembly_derivation():
    assert derive_assembly("C12A") == "C12"
    assert derive_assembly("C1.2C") == "C1.2"
    assert derive_assembly("RC1A") == "RC1"
    assert derive_assembly("RC29") == "RC29"     # no trailing segment letter
    assert derive_assembly("TB1") == "TB1"
    assert derive_assembly("STF2") == "STF2"


def test_finish_resolution():
    txt, ok = resolve_finish("MTL.1", LEGEND)
    assert ok and txt == "Stainless Steel 5WL Texture"
    txt, ok = resolve_finish("SS.1", LEGEND)
    assert ok and txt == "Brushed Stainless Steel #4 Finish"


def test_cover_description():
    rec = classify(FIXTURES[0])
    assert rec["assembly"] == "C12"
    assert rec["qty"] == 2
    assert rec["finish"] == "Stainless Steel 5WL Texture"
    assert "C12A" in rec["description"] and "14\" arc x 108\" Ht." in rec["description"]
    assert rec["description"].endswith("Stainless Steel 5WL Texture.")


def test_no_fabrication_flag():
    # ColumnCover with anchor/keyway role unresolved must be flagged, not guessed.
    rec = classify(FIXTURES[0])
    assert "SEGMENT_ROLE_UNKNOWN" in rec["flags"]


if __name__ == "__main__":
    print("=== [C classify] on real fixtures ===\n")
    for fx in FIXTURES:
        r = classify(fx)
        print(f"{r['part_mark']:<6} asm={r['assembly']:<5} qty={r['qty']}  cat={r['category']}")
        print(f"   DESC: {r['description']}")
        if r["flags"]:
            print(f"   FLAGS: {r['flags']}")
        print()
    # run assertions
    test_assembly_derivation()
    test_finish_resolution()
    test_cover_description()
    test_no_fabrication_flag()
    print("all asserts passed")
