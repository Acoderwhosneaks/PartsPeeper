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

import re
from typing import Any, Iterable

from .assemble import _f, _as_qty, build_rows


def _mark(rec):
    return (_f(rec, "part_mark") or "").strip()


def family_of(mark: str) -> str:
    """Part FAMILY = the leading alphabetic prefix of a mark.

    Generic structural rule (NOT a Miami lookup): C30A->'C', RC29->'RC',
    STF12->'STF', TB1->'TB', F1->'F'. Marks with no leading letter -> '?'.
    A different parts doc with marks like 'PL4' / 'W12' derives 'PL' / 'W' the
    same way, so coverage-by-family generalizes across sources.
    """
    m = (mark or "").strip()
    match = re.match(r"^([A-Za-z]+)", m)
    return match.group(1).upper() if match else "?"


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


def coverage_by_family(records: Iterable[Any],
                       expected_family_counts: dict | None = None):
    """Aggregate coverage view: distinct marks grouped by family.

    `expected_family_counts` is an OPTIONAL per-source profile map, e.g. the
    Miami fixture supplies {'C':60,'CP':46,'TB':46,'RC':42,'RB':42,'STF':42,...}.
    It is NEVER hardcoded in the core — pass it in from the fixture/profile so a
    different parts doc brings its own expectation (or none). When provided, a
    per-family or total mismatch is an ERROR (a dropped part or a phantom part —
    e.g. a 'BY OTHERS' item that slipped through — moves a count off target).
    When omitted, this is a pure informational distribution.
    """
    distinct: dict[str, set] = {}
    for rec in records:
        m = _mark(rec)
        if not m:
            continue
        distinct.setdefault(family_of(m), set()).add(m)
    actual = {fam: len(marks) for fam, marks in sorted(distinct.items())}

    errors, warnings = [], []
    if expected_family_counts is not None:
        expected = {str(k).upper(): int(v) for k, v in expected_family_counts.items()}
        for fam in sorted(set(expected) | set(actual)):
            exp = expected.get(fam)
            act = actual.get(fam, 0)
            if exp is None:
                errors.append({"type": "FAMILY_UNEXPECTED", "family": fam,
                               "actual": act,
                               "detail": f"family '{fam}' not in expected profile "
                                         "(possible phantom / BY-OTHERS leak)"})
            elif act != exp:
                errors.append({"type": "FAMILY_COUNT_MISMATCH", "family": fam,
                               "expected": exp, "actual": act,
                               "detail": f"family '{fam}': expected {exp}, got {act}"})
        exp_total = sum(expected.values())
        act_total = sum(actual.values())
        if exp_total != act_total:
            errors.append({"type": "TOTAL_COUNT_MISMATCH",
                           "expected": exp_total, "actual": act_total,
                           "detail": f"expected {exp_total} distinct parts, got {act_total}"})

    return {
        "actual": actual,
        "expected": expected_family_counts,
        "n_distinct_marks": sum(actual.values()),
        "errors": errors,
        "warnings": warnings,
    }


# --- independent-oracle adapter ---------------------------------------------
# ceres META RULE (seq65): completeness truth comes from the INDEPENDENT oracle
# (e.g. phobos's playtest/oracle.json), NEVER the pipeline's own counts. We consume
# the oracle's DATA output as the acceptance target; we import NONE of its code and
# NONE of the pipeline's extractor — that is what keeps this gate an independent check.

_ORACLE_MARK_KEYS = ("mark", "part_mark", "part_no", "partno", "part_number")


def _oracle_iter_parts(oracle):
    """Yield part dicts from an oracle in any of the tolerated shapes:
      - {"parts": [ {...}, ... ]}   (wrapper with a parts/records list)
      - [ {...}, ... ]              (bare list of part dicts)
      - { "C24A": {...}, ... }      (dict keyed by mark)
    """
    if isinstance(oracle, dict):
        for key in ("parts", "records", "expected", "items"):
            if isinstance(oracle.get(key), list):
                yield from oracle[key]
                return
        # dict keyed by mark -> synthesize {mark: key} if values lack a mark field
        for mark, val in oracle.items():
            if isinstance(val, dict):
                d = dict(val)
                if not any(k in d for k in _ORACLE_MARK_KEYS):
                    d["mark"] = mark
                yield d
            else:
                yield {"mark": mark}
        return
    if isinstance(oracle, list):
        yield from oracle


def _oracle_mark(part) -> str:
    if isinstance(part, str):
        return part.strip()
    if isinstance(part, dict):
        for k in _ORACLE_MARK_KEYS:
            if part.get(k):
                return str(part[k]).strip()
    return ""


def expected_from_oracle(oracle):
    """Derive (expected_marks:set, expected_family_counts:dict) from the oracle.

    `oracle` is already-parsed JSON (list/dict) — the caller owns file IO so this
    stays pure and testable. Returns the exact set of marks the independent oracle
    says must exist, plus their per-family distribution, ready to feed straight
    into validate(records, expected_marks=..., expected_family_counts=...).
    """
    marks = set()
    for part in _oracle_iter_parts(oracle):
        m = _oracle_mark(part)
        if m:
            marks.add(m)
    fam_counts: dict[str, int] = {}
    for m in marks:
        fam_counts[family_of(m)] = fam_counts.get(family_of(m), 0) + 1
    return marks, fam_counts


def validate_against_oracle(records, oracle):
    """Full [D] validation with the acceptance target sourced from the oracle,
    reconciling MARK-BY-MARK (not just totals) per ceres seq65."""
    marks, fam_counts = expected_from_oracle(oracle)
    return validate(records, expected_marks=marks, expected_family_counts=fam_counts)


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
# Data-completeness flags block (op #19 requires COMPLETE specs); role/qty are soft;
# FINISH_INHERITED / FASTENER_QTY_UNVERIFIED are INFO — deliberate, ratified states
# that must NOT fail the build, but ARE surfaced as an audit trail for the 100% claim.
_FLAG_SEVERITY = {
    "NO_MARK": "error",
    "MISSING_DIMS": "error",
    "MISSING_FINISH": "error",           # only when finish unresolvable at ALL tiers
    "FINISH_CODE_UNRESOLVED": "error",
    "SEGMENT_ROLE_UNKNOWN": "warning",
    "MISSING_QTY": "warning",
    "FINISH_INHERITED": "info",          # finish resolved from page/assembly, not per-part
    "FASTENER_QTY_UNVERIFIED": "info",   # Jeff-ratified: qty blank, never fabricated
}


def flags_report(records: Iterable[Any]):
    """Ingest [C]'s per-record flags[] as validation signals (mars seq26).

    Routes each flag to error / warning / info by _FLAG_SEVERITY. Unknown flags
    default to warning (surface, don't silently swallow). info never blocks.
    """
    errors, warnings, info = [], [], []
    bucket = {"error": errors, "warning": warnings, "info": info}
    for rec in records:
        for flag in (_f(rec, "flags") or []):
            sev = _FLAG_SEVERITY.get(flag, "warning")
            entry = {"type": f"FLAG_{flag}", "part_mark": _mark(rec)}
            bucket[sev].append(entry)
    return {"errors": errors, "warnings": warnings, "info": info}


def qty_report(records: Iterable[Any]):
    """Every part row must carry a positive integer qty (assembly headers exempt)."""
    warnings = []
    for rec in records:
        q = _as_qty(_f(rec, "qty"))
        if q <= 0:
            warnings.append({"type": "MISSING_QTY", "part_mark": _mark(rec),
                             "value": _f(rec, "qty")})
    return {"warnings": warnings}


def validate(records: Iterable[Any],
             expected_marks: Iterable[str] | None = None,
             expected_family_counts: dict | None = None):
    records = list(records)
    cov = coverage_report(records, expected_marks)
    fam = coverage_by_family(records, expected_family_counts)
    verb = verbatim_report(records)
    qty = qty_report(records)
    flg = flags_report(records)
    rows = build_rows(records)

    errors = cov["errors"] + fam["errors"] + verb["errors"] + flg["errors"]
    warnings = cov["warnings"] + fam["warnings"] + verb["warnings"] + qty["warnings"] + flg["warnings"]
    info = flg["info"]
    return {
        "ok": len(errors) == 0,
        "n_input_records": len(records),
        "n_output_rows": len(rows),
        "n_header_rows": sum(1 for r in rows if r.kind == "header"),
        "n_part_rows": sum(1 for r in rows if r.kind == "part"),
        "coverage": cov,
        "coverage_by_family": fam,
        "verbatim": verb,
        "qty": qty,
        "flags": flg,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }


def format_report(report: dict) -> str:
    lines = []
    status = "PASS" if report["ok"] else "FAIL"
    lines.append(f"[D validation] {status}  "
                 f"({report['n_input_records']} records -> {report['n_output_rows']} rows: "
                 f"{report['n_header_rows']} headers + {report['n_part_rows']} parts)")
    fam = report.get("coverage_by_family")
    if fam:
        dist = ", ".join(f"{k}={v}" for k, v in fam["actual"].items())
        lines.append(f"  families ({fam['n_distinct_marks']} distinct): {dist or '(none)'}")
    if report["errors"]:
        lines.append(f"  ERRORS ({len(report['errors'])}):")
        for e in report["errors"]:
            lines.append(f"    - {e}")
    if report["warnings"]:
        lines.append(f"  warnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            lines.append(f"    - {w}")
    info = report.get("info") or []
    if info:
        lines.append(f"  info / audit trail ({len(info)}):")
        for i in info:
            lines.append(f"    - {i}")
    if not report["errors"] and not report["warnings"]:
        lines.append("  clean: no errors, no warnings.")
    return "\n".join(lines)
