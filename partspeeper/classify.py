"""
[C classify] stage of the universal 2D parts input program.

Owner: mars.
Input : RawPart dict (produced by [B digest]) -- see part_contract.md.
Output: PartRecord dict (consumed by [D assemble]).

Contract is dict-in / dict-out (no shared dataclass import) so the four pipeline
stages never collide on a common module. Field names match part_contract.md.

Design rules (operator #13/#14/#16/#19):
  - Only parts + specs. Output feeds a 3-column CSV: PartNum, Qty, Description.
  - Description packs EVERY spec, goal.pdf phrasing, INPUT values verbatim.
  - 100% accuracy => never fabricate a spec. If a value is missing/ambiguous we
    leave it out of the Description and raise a flag instead of guessing.
  - Universal core; Moz-specific text lives in small, swappable maps below.
"""

import re

# --------------------------------------------------------------------------
# Normalization maps  (Moz "profile" -- swap/extend per source, keep core generic)
# --------------------------------------------------------------------------

# Finish legend text (as it appears in the input FINISH SCHEDULE block) -> goal-style phrasing.
FINISH_TEXT_NORMALIZE = {
    "STAINLESS STEEL 5WL TEXTURE": "Stainless Steel 5WL Texture",
    "BRUSHED STAINLESS STEEL NO:4 FINISHED": "Brushed Stainless Steel #4 Finish",
    "BRUSHED STAINLESS STEEL NO: 4 FINISHED": "Brushed Stainless Steel #4 Finish",
}

MATERIAL_NORMALIZE = {
    "16 GA SS": '16 GA Stainless Steel',
    "16 GA STAINLESS STEEL": '16 GA Stainless Steel',
    ".090 ALUM": '.090" ALUM',
    ".125 ALUM": '.125" ALUM',
}

# part_type_raw (verbatim callout) -> (category, human type_label, description template key)
TYPE_MAP = {
    "COLUMN COVER":     ("ColumnCover",     "Column Cover Segment",       "cover"),
    "RECESSED CAPITAL": ("RecessedCapital", "Recessed Capital Segment",   "recessed"),
    "RECESSED BASE":    ("RecessedBase",    "Recessed Base Segment",      "recessed"),
    "T-BAR":            ("TBar",            "Column Base T-Bracket Mount", "tbar"),
    "T-BRACKET":        ("TBar",            "Column Base T-Bracket Mount", "tbar"),
    "CAP":              ("SeamCap",         "Capital/Base Seam Cap",      "cap"),
    "SEAM CAP":         ("SeamCap",         "Capital/Base Seam Cap",      "cap"),
    "STIFFENER":        ("Stiffener",       "Stiffener",                  "stiffener"),
    "FLATBAR":          ("Flatbar",         "Flatbar",                    "flatbar"),
    "SCREW":            ("Fastener",        "Screw",                      "raw"),
}

# fallback: mark prefix -> part_type_raw key  (when the callout type text is missing)
PREFIX_TO_TYPE = [
    ("RC", "RECESSED CAPITAL"),
    ("RB", "RECESSED BASE"),
    ("TB", "T-BAR"),
    ("STF", "STIFFENER"),
    ("CP", "CAP"),
    ("F",  "FLATBAR"),
    ("C",  "COLUMN COVER"),   # keep last: C matches many, RC/CP already handled above
]


# --------------------------------------------------------------------------
# Field helpers
# --------------------------------------------------------------------------

def derive_assembly(mark):
    """C30A -> C30 ; C1.2C -> C1.2 ; RC1A -> RC1 ; standalone marks (RC29,TB1,STF2,CP1,F1) -> self.

    Rule: strip a single trailing capital letter only when it follows a digit
    (segment suffix). Marks that are their own assembly are returned unchanged.
    """
    if not mark:
        return ""
    m = re.match(r"^([A-Za-z]+[\d.]+)([A-Z])$", mark.strip())
    if m:
        return m.group(1)
    return mark.strip()


def categorize(part_type_raw, mark):
    key = (part_type_raw or "").strip().upper()
    if key in TYPE_MAP:
        return TYPE_MAP[key]
    # fallback via mark prefix
    um = (mark or "").upper()
    for prefix, tkey in PREFIX_TO_TYPE:
        if um.startswith(prefix):
            return TYPE_MAP[tkey]
    return ("Other", "", "raw")


def normalize_material(material_hint):
    if not material_hint:
        return ""
    key = material_hint.strip().upper().replace('"', "")
    return MATERIAL_NORMALIZE.get(key, material_hint.strip())


def resolve_finish(finish_code, legend):
    """finish_code (MTL.1/SS.1) -> goal-style finish text, via the page FINISH legend."""
    if not finish_code:
        return "", False
    raw = (legend or {}).get(finish_code)
    if not raw:
        return "", False
    key = re.sub(r"\s+", " ", raw.strip().upper())
    return FINISH_TEXT_NORMALIZE.get(key, raw.strip().title()), True


def _q(v):
    """Ensure an inch mark on a bare numeric dimension; pass through if already present/empty."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if s.endswith('"') or s.endswith("'") or s.lower().endswith("ht") or s.lower().endswith("dia"):
        return s
    if re.fullmatch(r'[\d./\- ]+', s):
        return s + '"'
    return s


# --------------------------------------------------------------------------
# Description builder  (the 100%-accuracy target)
# --------------------------------------------------------------------------

def build_description(rec):
    """Assemble the goal-style Description from a (partly) classified record.

    Never invents a value: missing pieces are omitted and recorded as flags by
    classify(). Returns the Description string.
    """
    tmpl = rec.get("_tmpl", "raw")
    mark = rec.get("part_mark", "")
    material = rec.get("material", "")
    finish = rec.get("finish", "")
    x, y, dia = _q(rec.get("dim_x")), _q(rec.get("dim_y")), _q(rec.get("dim_dia"))
    role = rec.get("segment_role", "")   # 'Anchor' / 'Keyway' if [B] resolved it

    if tmpl == "cover":
        # C30A / 16 GA Stainless Steel / Round Column Cover [Anchor] Segment / 14" arc x 108" Ht. in <finish>.
        name = "Round Column Cover Segment"
        if role:
            name = f"Round Column Cover {role} Segment"
        dims = ""
        if dia:
            dims = f'{dia} Dia x {y} Ht.' if y else f'{dia} Dia'
        elif x and y:
            dims = f'{x} arc x {y} Ht.'
        elif x:
            dims = f'{x} arc'
        parts = [p for p in [mark, material] if p]
        head = " ".join(parts)
        segs = [head, name]
        if dims:
            segs.append(dims)
        base = " / ".join(segs)
        return f"{base} in {finish}." if finish else base + "."

    if tmpl == "recessed":
        # RC1 / Recessed Capital Segment / 17 1/2" Dia x 6" ht / 16 GA Stainless Steel - Brushed #4 Finish.
        label = rec.get("type_label", "Recessed Segment")
        dims = ""
        if dia and y:
            dims = f'{dia} Dia x {y} ht'
        elif x and y:
            dims = f'{x} x {y} ht'
        elif dia:
            dims = f'{dia} Dia'
        tail = f"{material} - {finish}" if material and finish else (material or finish)
        segs = [mark, label]
        if dims:
            segs.append(dims)
        if tail:
            segs.append(tail)
        return " / ".join(segs) + "."

    if tmpl == "tbar":
        # TB1 / Column Base T-Bracket Mount / 1 1/2" x 1 1/2" x 5 3/4" / Mill Finish Alum.
        dims = rec.get("dims_other") or " x ".join([d for d in [x, y] if d])
        segs = [mark, "Column Base T-Bracket Mount"]
        if dims:
            segs.append(dims)
        if finish or material:
            segs.append(finish or material)
        return " / ".join(segs) + "."

    if tmpl == "cap":
        # C1 Capital/Base Seam Cap - 2" x 3" / Stainless Steel #4 Finish
        dims = " x ".join([d for d in [x, y] if d])
        head = f"{mark} Capital/Base Seam Cap"
        if dims:
            head += f" - {dims}"
        return f"{head} / {finish}" if finish else head

    if tmpl == "stiffener":
        # <MARK> / Stiffener / <x> x <y> / <material> <finish>.
        dims = " x ".join([d for d in [x, y] if d])
        tail = " ".join([t for t in [material, finish] if t])
        segs = [mark, "Stiffener"]
        if dims:
            segs.append(dims)
        if tail:
            segs.append(tail)
        return " / ".join(segs) + "."

    if tmpl == "flatbar":
        # F1 .125" ALUM Flatbar 2" x 99" Ht. Classic P212L Complimentary Finish
        dims = ""
        if x and y:
            dims = f'{x} x {y} Ht.'
        elif x:
            dims = x
        pieces = [p for p in [mark, material, "Flatbar", dims, finish] if p]
        return " ".join(pieces)

    # raw / fastener / unknown: use any provided free description verbatim
    return rec.get("raw_description") or rec.get("part_mark", "")


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def classify(raw):
    """RawPart dict -> PartRecord dict (see part_contract.md)."""
    sched = raw.get("schedule") or {}
    legend = raw.get("finish_legend") or {}
    mark = (raw.get("part_mark") or "").strip()

    category, type_label, tmpl = categorize(raw.get("part_type_raw"), mark)
    material = normalize_material(raw.get("material_hint"))
    finish, finish_ok = resolve_finish(sched.get("finish_code"), legend)

    dim_x = (sched.get("x") or "").strip()
    dim_y = (sched.get("y") or "").strip()
    dim_dia = (sched.get("dia") or raw.get("dia") or "").strip()

    qty_raw = sched.get("qty")
    qty = None
    if qty_raw not in (None, ""):
        m = re.search(r"\d+", str(qty_raw))
        if m:
            qty = int(m.group())

    rec = {
        "source_doc": raw.get("source_doc"),
        "source_page": raw.get("source_page"),
        "sheet_id": raw.get("sheet_id"),
        "cell_index": raw.get("cell_index"),
        "part_mark": mark,
        "assembly": derive_assembly(mark),
        "category": category,
        "type_label": type_label,
        "material": material,
        "finish_code": sched.get("finish_code"),
        "finish": finish,
        "dim_x": dim_x,
        "dim_y": dim_y,
        "dim_dia": dim_dia,
        "dims_other": (raw.get("dims_other") or "").strip(),
        "qty": qty,
        "crate": "",
        "segment_role": raw.get("segment_role", ""),
        "notes": "; ".join(raw.get("notes_raw", []) or []),
        "raw_description": raw.get("raw_description"),
        "_tmpl": tmpl,
    }

    # Build the Description, then flag anything the 100% bar cares about.
    rec["description"] = build_description(rec)

    flags = []
    if not mark:
        flags.append("NO_MARK")
    if qty is None and category != "Other":
        flags.append("MISSING_QTY")
    if sched.get("finish_code") and not finish_ok:
        flags.append("FINISH_CODE_UNRESOLVED")
    if category == "ColumnCover" and not rec["segment_role"]:
        flags.append("SEGMENT_ROLE_UNKNOWN")  # anchor vs keyway not resolved by [B]
    if category in ("ColumnCover", "RecessedCapital", "RecessedBase") and not (dim_x or dim_dia):
        flags.append("MISSING_DIMS")
    if not finish:
        flags.append("MISSING_FINISH")
    rec["flags"] = flags

    rec.pop("_tmpl", None)
    return rec
