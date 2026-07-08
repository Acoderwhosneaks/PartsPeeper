"""[D assemble] — PartRecord[] -> ordered CSV rows -> parts.csv

Consumes the PartRecord contract from ../part_contract.md and emits the LOCKED
3-column output (operator spec image #19):

    PartNum, Qty, Description

Row model (mirrors goal.pdf):
  * Assembly-header row : PartNum, Qty="", Description="<Assembly> Column"
  * Part row            : PartNum, Qty=<int>, Description=<goal-style spec string>

Ordering: document order (source_page, cell_index) grouped under each assembly
header; assemblies appear in the order their first part is seen.

Dedup / qty-rollup: one row per distinct part_mark within an assembly. If a mark
recurs with an IDENTICAL spec, its qtys are summed (rollup) and no duplicate row
is emitted. If a mark recurs with a CONFLICTING spec, every occurrence is kept and
flagged CONFLICT so nothing is silently merged away — 100%-accuracy bar (op #19).
"""
from __future__ import annotations

import csv
import io
from typing import Iterable, Any

# ---- field access -----------------------------------------------------------
# PartRecord is a plain dict per the contract. Accept objects with attributes too.


def _f(rec: Any, name: str, default=None):
    if isinstance(rec, dict):
        return rec.get(name, default)
    return getattr(rec, name, default)


def _sort_key(rec: Any):
    page = _f(rec, "source_page", 0) or 0
    cell = _f(rec, "cell_index")
    # cell_index may be None (schedule row with no drawn cell) -> sort last within page
    cell = 10 ** 9 if cell is None else cell
    return (page, cell)


def _spec_signature(rec: Any):
    """Everything that must match for two same-mark records to be the SAME part."""
    return (
        (_f(rec, "description") or "").strip(),
        (_f(rec, "dimensions") or "").strip(),
        (_f(rec, "finish") or "").strip(),
        (_f(rec, "material") or "").strip(),
    )


def _as_qty(v) -> int:
    if v in (None, "", "-"):
        return 0
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        # keep whatever digits we can find, else 0
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        return int(digits) if digits else 0


# ---- core -------------------------------------------------------------------


class Row:
    __slots__ = ("part_num", "qty", "description", "kind", "assembly", "flags")

    def __init__(self, part_num, qty, description, kind, assembly, flags=None):
        self.part_num = part_num
        self.qty = qty  # "" for header rows, int for part rows
        self.description = description
        self.kind = kind  # "header" | "part"
        self.assembly = assembly
        self.flags = list(flags or [])

    def as_csv(self):
        return [self.part_num, "" if self.qty == "" else str(self.qty), self.description]


def _assembly_label(assembly: str) -> str:
    """Assembly-header Description, goal style: '<Assembly> Column'."""
    a = (assembly or "").strip()
    if not a:
        return "Column"
    if a.lower().endswith("column"):
        return a
    return f"{a} Column"


def _merge_marks(records: list) -> tuple[list, list]:
    """Collapse records sharing a part_mark. Returns (merged_records, conflicts).

    merged_records: one entry per (mark, spec-signature); qty summed across
    identical-spec occurrences, carrying the earliest doc-position for ordering.
    conflicts: list of dicts describing marks that appeared with >1 distinct spec.
    """
    by_mark: dict[str, dict] = {}
    order: list = []
    for rec in records:
        mark = (_f(rec, "part_mark") or "").strip()
        sig = _spec_signature(rec)
        key = mark
        slot = by_mark.get(key)
        if slot is None:
            slot = {"mark": mark, "variants": {}}
            by_mark[key] = slot
            order.append(key)
        var = slot["variants"].get(sig)
        if var is None:
            # copy the record; qty becomes accumulator
            base = dict(rec) if isinstance(rec, dict) else {
                k: _f(rec, k) for k in (
                    "source_doc", "source_page", "sheet_id", "cell_index",
                    "part_mark", "assembly", "category", "type_label", "material",
                    "finish_code", "finish", "dim_x", "dim_y", "dim_dia",
                    "dimensions", "qty", "crate", "description", "notes", "flags",
                )
            }
            base["qty"] = _as_qty(_f(rec, "qty"))
            base.setdefault("flags", list(_f(rec, "flags") or []))
            slot["variants"][sig] = base
        else:
            var["qty"] = _as_qty(var.get("qty")) + _as_qty(_f(rec, "qty"))

    merged: list = []
    conflicts: list = []
    for key in order:
        slot = by_mark[key]
        variants = list(slot["variants"].values())
        if len(variants) > 1:
            conflicts.append({
                "part_mark": slot["mark"],
                "n_variants": len(variants),
                "descriptions": [v.get("description") for v in variants],
            })
            for v in variants:
                v.setdefault("flags", [])
                if "CONFLICT" not in v["flags"]:
                    v["flags"].append("CONFLICT")
        merged.extend(variants)
    return merged, conflicts


def build_rows(records: Iterable[Any]) -> list:
    """PartRecord[] -> ordered list[Row] with assembly headers and sequential PartNum."""
    records = list(records)
    merged, _conflicts = _merge_marks(records)

    # order by document position
    merged.sort(key=_sort_key)

    # group under assembly, assemblies in first-seen order
    assembly_order: list = []
    grouped: dict[str, list] = {}
    for rec in merged:
        asm = (_f(rec, "assembly") or "").strip() or "(ungrouped)"
        if asm not in grouped:
            grouped[asm] = []
            assembly_order.append(asm)
        grouped[asm].append(rec)

    rows: list = []
    n = 0
    for asm in assembly_order:
        n += 1
        rows.append(Row(f"{n:03d}", "", _assembly_label(asm), "header", asm))
        for rec in grouped[asm]:
            n += 1
            desc = (_f(rec, "description") or "").strip()
            rows.append(Row(
                f"{n:03d}",
                _as_qty(_f(rec, "qty")),
                desc,
                "part",
                asm,
                flags=_f(rec, "flags"),
            ))
    return rows


def to_csv_string(records: Iterable[Any], *, include_header=True) -> str:
    rows = build_rows(records)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if include_header:
        w.writerow(["PartNum", "Qty", "Description"])
    for r in rows:
        w.writerow(r.as_csv())
    return buf.getvalue()


def write_csv(records: Iterable[Any], path: str, *, include_header=True) -> list:
    rows = build_rows(records)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        if include_header:
            w.writerow(["PartNum", "Qty", "Description"])
        for r in rows:
            w.writerow(r.as_csv())
    return rows
