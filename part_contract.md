# PartRecord + CSV Contract  (draft v0.1 — mars, [C classify] owner)

Shared data contract for the "universal 2D parts input program".
Pipeline stages pass these structures; nobody reaches into another stage's internals.

Design constraints (operator #13/#14/#16):
- Output = **CSV, one row per part** found in the input.
- Retain **all spec fields exemplified by goal.pdf**, pulled from the input.
- **Various inputs** will be fed in -> keep everything input-agnostic. Discover parts by
  *structural cues* (a part callout `N TYPE - CODE` + an associated schedule row), NOT by a
  hardcoded part catalog tuned to this one Miami file.
- **Only parts + their specifications are relevant.** Drop all boilerplate (title blocks,
  legal text, drawing lists, general notes, project scope, revision blocks).
- Assembly grouping is a **column**, not a headerless grouping row — every emitted row is a
  real part with specs.

---

## Stage boundaries

[A extract]  PDF -> `Word[]` (text + x,y,w,h, page, rotation-corrected)   + optional page raster (QA only)
[B digest]   `Word[]` per page -> `RawPart[]`   (callouts spatially joined to schedule rows + page finish legend)
[C classify] `RawPart[]` -> `PartRecord[]`   (normalize type/assembly/finish/dims, build Description)
[D assemble] `PartRecord[]` -> dedupe/merge/qty-rollup -> `parts.csv` + validation report

---

## RawPart  (output of [B], input to [C])  — unnormalized, best-effort

```json
{
  "source_doc":   "parts input.pdf",
  "source_page":  16,            // 1-based doc page
  "sheet_id":     "P1",          // sheet tag in title block, if present
  "cell_index":   1,             // the leading N in "1 COLUMN COVER - C12A"
  "part_type_raw":"COLUMN COVER", // verbatim callout type text
  "part_mark":    "C12A",        // verbatim mark/code
  "schedule": {                   // the schedule row spatially matched to this mark (may be partial)
     "finish_code": "MTL.1",
     "x":  "14\"",               // X (arc length / width) verbatim
     "y":  "108\"",              // Y (height) verbatim
     "qty":"02"
  },
  "finish_legend": {"MTL.1":"STAINLESS STEEL 5WL TEXTURE","SS.1":"BRUSHED STAINLESS STEEL NO:4 FINISHED"},
  "material_hint": "16 GA SS",   // from page GENERAL NOTE / material callout
  "notes_raw":     ["DRILL THRU .19\" DIA. HOLE","HARDWARE IN MATCHING FINISH"],
  "raw_tokens":    ["...unmatched nearby tokens for QA fallback..."]
}
```

[B] must NOT emit boilerplate cells. A cell qualifies only if it has a `part_type_raw` +
`part_mark`. Unmatched schedule rows (mark present in a schedule but no drawn cell) should
still be emitted as a RawPart with `cell_index: null` so no part is lost.

---

## PartRecord  (output of [C], input to [D])  — normalized

```json
{
  "source_doc":"parts input.pdf", "source_page":16, "sheet_id":"P1", "cell_index":1,
  "part_mark":"C12A",
  "assembly":"C12",              // derived from mark prefix: C12A/B/C -> C12; RC12A -> RC12; TB1 -> TB1
  "category":"ColumnCover",      // normalized enum (see below)
  "type_label":"Column Cover",   // human label for CSV Type col
  "material":"16 GA Stainless Steel",
  "finish_code":"MTL.1",
  "finish":"Stainless Steel 5WL Texture",
  "dim_x":"14\"", "dim_y":"108\"", "dim_dia":null,
  "dimensions":"14\" (arc) x 108\" H",   // assembled human dims string
  "qty":2,
  "crate":"",
  "description":"C12A / Column Cover / 16 GA Stainless Steel / 14\" arc x 108\" H / Stainless Steel 5WL Texture",
  "notes":"Drill thru .19\" dia hole; hardware in matching finish",
  "flags":[]                     // QA flags: MISSING_QTY, NO_SCHEDULE_MATCH, AMBIG_FINISH, etc.
}
```

### category enum (extensible; driven by keyword map, not a fixed part list)
ColumnCover, RecessedCapital, RecessedBase, TBar, SeamCap, Stiffener, Flatbar, Fastener, Other

### assembly derivation
Strip the trailing segment letter(s) from an alpha-suffixed mark: `C12A/C12B/C12C -> C12`,
`RC1A/RC1B -> RC1`. Marks with no alpha suffix (`TB1`, `STF2`, `CP1`) are their own assembly.
General rule, not a lookup table -> survives "various inputs".

---

## parts.csv columns  (LOCKED by operator spec image #19)

The operator posted a crop of goal.pdf showing the ONLY columns to pull:

`PartNum, Qty, Description`

That's the entire output. The Crate / JC / PM / S/R checkbox columns are NOT pulled.
All the structured fields in PartRecord above stay **INTERNAL** — they exist only to (a)
assemble an accurate `Description` and (b) drive QA. Only these 3 columns are emitted.

### Column definitions
- `PartNum` = sequential line id, zero-padded 3 wide (`001, 002, 003, ...`). This is a LINE
  NUMBER, not the part mark. The mark (C12A, RC1, TB1, ...) lives inside `Description`.
  goal.pdf skips some numbers (001,002,...,006,008) — replicate our own clean sequence; do
  not try to reproduce goal's gaps (that was Sitka data).
- `Qty` = integer, or **blank** for assembly-header rows.
- `Description` = one goal-style spec string packing every spec (see format below).

### Row types (mirror goal.pdf structure)
1. **Assembly-header row**: `Qty` blank, `Description = "<AssemblyMark> Column"` (goal shows
   `001 C1 Column`, `008 C1.1 Column`). Emit one per column assembly, before its segment rows.
2. **Part row**: full `Description`, `Qty` = quantity.

### Description format (goal style — built by [C], the 100%-accuracy target)
`<MARK> <material> / <type name> [/ dims] [in/ <finish>].`
Examples pulled from goal.pdf (Sitka) — replicate this PHRASING with the INPUT's data:
- `C1A .090" ALUM / Round Column Cover Anchor Segment w/ electrical cut out / 18" Dia x 96" Ht. in Moz Patina 212L Fog Flat Interior Finish.`
- `RC1 / Recessed Capital Segment / 17 1/2" Dia x 6" ht / 16 GA Stainless Steel - Brushed #4 Finish.`
- `TB1 / Column Base T-Bracket Mount / 1 1/2" x 1 1/2" x 5 3/4" / Mill Finish Alum.`
- `F1 .125" ALUM Flatbar 2" x 99" Ht. Classic P212L Complimentary Finish`

For the Miami input the same shape is built from its schedule cells, e.g.:
`C30A / 16 GA Stainless Steel / Round Column Cover Anchor Segment / 14" arc x 108" Ht. in Stainless Steel 5WL Texture.`

Ordering: document order (source_page, cell_index), grouped under each assembly header.

## Acceptance bar (operator #19)
Parts + specs must be pulled **completely** (no part dropped) and at **100% accuracy**
(every dimension/finish/qty verbatim from the input). This is why [A]/[B] must be
coordinate-based (reading-order text scrambles the schedule columns) and why [D] runs a
coverage + validation pass.

## Open questions for the team / operator
1. Assembly-header rows: keep them (goal shows them) — confirm operator wants them in the CSV.
2. One row per distinct mark (goal style), or one row per physical segment? (goal = per-mark.)
3. Finish phrasing: use the input's FINISH SCHEDULE text verbatim, or normalize toward goal wording?
