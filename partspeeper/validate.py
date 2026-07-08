"""[D] validation harness — enforce operator #19: parts pulled COMPLETELY and at
100% ACCURACY.

Two independent checks:

  coverage_report(records, expected_marks)
      Every mark the upstream schedules detected must appear exactly once in the
      output. Flags MISSING (dropped part) and DUPLICATE (same mark emitted twice
      with a conflicting spec). `expected_marks` is the set [B]/[C] believe exist
      (e.g. every PART NO cell parsed from every schedule table). If not supplied,
      coverage is self-referential (checks internal duplication only).

  verbatim_report(records)
      Every emitted Description must contain the record's dimension and finish
      tokens verbatim — no rounding, no re-spelling. Catches a [C] Description
      that silently drops or alters a spec token.

validate(...) bundles both into one report dict; `ok` is True only if there are
zero errors (warnings are allowed).
"""
from __future__ import annotations

from typing import Any, Iterable

from .assemble import _f, _as_qty, build_rows


def _mark(rec):
    return (_f(rec, "part_mark") or "").strip()


def coverage_report(records: Iterable[Any], expected_marks: Iterable[str] | None = None):
    records = list(records)
    seen: dict[str, int] = {}
    for rec in records:
        m = _mark(rec)
        seen[m] = seen.get(m, 0) + 1

    errors, warnings = [], []

    if expected_marks is not None:
        expected = {str(m).strip() for m in expected_marks if str(m).strip()}
        missing = sorted(expected - set(seen))
        for m in missing:
            errors.append({"type": "MISSING", "part_mark": m,
                           "detail": "expected by upstream schedule but not in output"})
        extra = sorted(set(seen) - expected)
        for m in extra:
            warnings.append({"type": "UNEXPECTED", "part_mark": m,
                             "detail": "in output but not in expected-mark set"})

    # duplicates that survived merge = conflicting-spec occurrences (flagged CONFLICT)
    for m, c in sorted(seen.items()):
        if c > 1:
            warnings.append({"type": "DUPLICATE", "part_mark": m, "count": c,
                             "detail": "same mark emitted more than once (spec conflict)"})

    return {
        "n_records": len(records),
        "n_distinct_marks": len(seen),
        "errors": errors,
        "warnings": warnings,
    }


def _tokens_present(haystack: str, token) -> bool:
    if token in (None, "", "-"):
        return True
    return str(token).strip() in (haystack or "")


def verbatim_report(records: Iterable[Any]):
    """Description must carry the record's own spec tokens.

    DIMENSIONS are an ERROR if dropped/altered — a dimension must be exact (op #19).
    FINISH is a WARNING only: [C] may normalize finish phrasing ("Brushed #4 Finish")
    away from the raw FINISH SCHEDULE text pending the operator's phrasing decision,
    so an exact-substring miss on finish is surfaced but non-blocking.
    """
    errors, warnings = [], []
    for rec in records:
        desc = (_f(rec, "description") or "")
        m = _mark(rec)
        if not desc.strip():
            errors.append({"type": "EMPTY_DESCRIPTION", "part_mark": m})
            continue
        # the mark itself should lead the description (goal style)
        if m and m not in desc:
            errors.append({"type": "MARK_NOT_IN_DESCRIPTION", "part_mark": m,
                           "detail": f"mark '{m}' absent from its Description"})
        # dimensions must be verbatim
        for field in ("dim_x", "dim_y", "dim_dia"):
            val = _f(rec, field)
            if not _tokens_present(desc, val):
                errors.append({"type": "DIM_TOKEN_DROPPED", "part_mark": m,
                               "field": field, "value": val,
                               "detail": f"dimension '{val}' not found verbatim in Description"})
        # finish: warn (phrasing may be normalized by [C])
        fin = _f(rec, "finish")
        if not _tokens_present(desc, fin):
            warnings.append({"type": "FINISH_PHRASING_DIFFERS", "part_mark": m,
                             "value": fin,
                             "detail": f"finish '{fin}' not verbatim in Description "
                                       "(ok if [C] normalized phrasing; verify vs input)"})
    return {"errors": errors, "warnings": warnings}


# flags emitted by [C] (mars) -> severity in D's report.
# Data-completeness flags block (op #19 requires COMPLETE specs); role/qty are soft.
_FLAG_SEVERITY = {
    "NO_MARK": "error",
    "MISSING_DIMS": "error",
    "MISSING_FINISH": "error",
    "FINISH_CODE_UNRESOLVED": "error",
    "SEGMENT_ROLE_UNKNOWN": "warning",
    "MISSING_QTY": "warning",
}


def flags_report(records: Iterable[Any]):
    """Ingest [C]'s per-record flags[] as validation signals (mars seq26)."""
    errors, warnings = [], []
    for rec in records:
        for flag in (_f(rec, "flags") or []):
            sev = _FLAG_SEVERITY.get(flag, "warning")
            entry = {"type": f"FLAG_{flag}", "part_mark": _mark(rec)}
            (errors if sev == "error" else warnings).append(entry)
    return {"errors": errors, "warnings": warnings}


def qty_report(records: Iterable[Any]):
    """Every part row must carry a positive integer qty (assembly headers exempt)."""
    warnings = []
    for rec in records:
        q = _as_qty(_f(rec, "qty"))
        if q <= 0:
            warnings.append({"type": "MISSING_QTY", "part_mark": _mark(rec),
                             "value": _f(rec, "qty")})
    return {"warnings": warnings}


def validate(records: Iterable[Any], expected_marks: Iterable[str] | None = None):
    records = list(records)
    cov = coverage_report(records, expected_marks)
    verb = verbatim_report(records)
    qty = qty_report(records)
    flg = flags_report(records)
    rows = build_rows(records)

    errors = cov["errors"] + verb["errors"] + flg["errors"]
    warnings = cov["warnings"] + verb["warnings"] + qty["warnings"] + flg["warnings"]
    return {
        "ok": len(errors) == 0,
        "n_input_records": len(records),
        "n_output_rows": len(rows),
        "n_header_rows": sum(1 for r in rows if r.kind == "header"),
        "n_part_rows": sum(1 for r in rows if r.kind == "part"),
        "coverage": cov,
        "verbatim": verb,
        "qty": qty,
        "flags": flg,
        "errors": errors,
        "warnings": warnings,
    }


def format_report(report: dict) -> str:
    lines = []
    status = "PASS" if report["ok"] else "FAIL"
    lines.append(f"[D validation] {status}  "
                 f"({report['n_input_records']} records -> {report['n_output_rows']} rows: "
                 f"{report['n_header_rows']} headers + {report['n_part_rows']} parts)")
    if report["errors"]:
        lines.append(f"  ERRORS ({len(report['errors'])}):")
        for e in report["errors"]:
            lines.append(f"    - {e}")
    if report["warnings"]:
        lines.append(f"  warnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            lines.append(f"    - {w}")
    if not report["errors"] and not report["warnings"]:
        lines.append("  clean: no errors, no warnings.")
    return "\n".join(lines)
