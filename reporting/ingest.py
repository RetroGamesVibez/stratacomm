"""Read vendor weekly reporting templates (.xlsx) into clean, typed rows.

The vendor template has an instructions block on top, a header row that starts
with "Row Status", and one data row per placement / creative / size / week.
Headers are matched by prefix so small wording changes between template
versions (e.g. an extra "Placement ID" column) don't break ingestion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import pandas as pd

# Order matters: longer / more specific prefixes first.
WEEKLY_HEADER_MAP = [
    ("row status", "row_status"),
    ("issue detail", "issue_detail"),
    ("partner notes", "partner_notes"),
    ("partner", "partner"),
    ("week starting", "week_start"),
    ("week ending", "week_end"),
    ("language", "language"),
    ("channel", "channel"),
    ("tactic", "tactic"),
    ("placement unit", "placement_unit"),
    ("unit name", "unit_name"),
    ("creative name", "creative"),
    ("audience target", "audience_target"),
    ("audience", "audience"),
    ("geo target", "geo"),
    ("added value element", "added_value"),
    ("placement id", "placement_id"),
    ("placement name", "placement"),
    ("creative size", "creative_size"),
    ("unit kpi %", "kpi_target_text"),
    ("unit kpi", "kpi"),
    ("cost method", "cost_method"),
    ("rate", "rate"),
    ("av applied", "av_rate"),
    ("impressions delivered", "impressions"),
    ("clicks", "clicks"),
    ("views / listens", "views"),
    ("thruplays", "thruplays"),
    ("completions", "completions"),
    ("reach - paid", "reach_paid"),
    ("reach - organic", "reach_organic"),
    ("engagements", "engagements"),
    ("radio spots", "radio_spots"),
    ("spend", "spend"),
    ("av $", "av_value"),
]

PLAN_HEADER_MAP = [
    ("campaign flight start", "flight_start"),
    ("campaign flight end", "flight_end"),
    ("campaign", "campaign"),
    ("partner placement name", "placement"),
    ("partner", "partner"),
    ("language", "language"),
    ("tactic benchmark", "kpi_target_text"),
    ("tactic", "tactic"),
    ("channel", "channel"),
    ("unit type", "unit_type"),
    ("audience", "audience"),
    ("geo target", "geo"),
    ("targeting details", "audience_target"),
    ("added value element", "added_value"),
    ("creative size", "creative_size"),
    ("creative", "creative_formats"),
    ("kpi", "kpi"),
    ("cost method", "cost_method"),
    ("rate", "rate"),
    ("av applied", "av_rate"),
    ("impressions units negotiated", "planned_impressions"),
    ("cost negotiated", "planned_cost"),
]

NUMERIC_WEEKLY = ["rate", "av_rate", "impressions", "clicks", "views", "thruplays",
                  "completions", "reach_paid", "reach_organic", "engagements",
                  "radio_spots", "spend", "av_value"]
NUMERIC_PLAN = ["rate", "av_rate", "planned_impressions", "planned_cost"]
TEXT_PLACEHOLDERS = {"", "-", "–", "—", "n/a", "na", "$-", "$ -"}


def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").replace("(Dropdown)", "")).strip().lower()


def _map_headers(raw_headers, header_map):
    mapped = {}
    for idx, h in enumerate(raw_headers):
        nh = _norm_header(h)
        if not nh:
            continue
        for prefix, key in header_map:
            if nh.startswith(prefix) and key not in mapped.values():
                mapped[idx] = key
                break
    return mapped


def clean_text(v):
    if v is None:
        return None
    s = str(v).replace("\xa0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s or None


def parse_number(v):
    """Return (value, was_placeholder_text). Treats '-', ' $ - ', nbsp etc. as blank."""
    if v is None:
        return None, False
    if isinstance(v, (int, float)):
        return float(v), False
    s = str(v).replace("\xa0", " ").strip()
    compact = s.replace(" ", "").lower()
    if compact in TEXT_PLACEHOLDERS:
        return None, bool(s)
    try:
        return float(compact.replace("$", "").replace(",", "").replace("%", "")), True
    except ValueError:
        return None, True


def normalize_size(v):
    s = clean_text(v)
    if not s:
        return None
    s2 = re.sub(r"\s*[xX]\s*", "x", s)
    return s2


@dataclass
class VendorFile:
    path: Path
    vendor: str
    rows: pd.DataFrame
    plan: pd.DataFrame
    file_issues: list = field(default_factory=list)  # (severity, message)
    cleaning_log: list = field(default_factory=list)  # (sheet_row, field, raw, cleaned)


def _find_header_row(ws, first_label="row status", max_scan=60):
    for r in range(1, max_scan + 1):
        if _norm_header(ws.cell(r, 1).value) == first_label:
            return r
    raise ValueError(f"Could not find header row starting with '{first_label}' in {ws.title}")


def read_vendor_file(path: Path, vendor_label: str | None = None) -> VendorFile:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Weekly Reporting"]
    hdr_row = _find_header_row(ws)
    raw_headers = [c.value for c in ws[hdr_row]]
    colmap = _map_headers(raw_headers, WEEKLY_HEADER_MAP)

    records, cleaning = [], []
    for r_idx, row in enumerate(ws.iter_rows(min_row=hdr_row + 1, values_only=True), start=hdr_row + 1):
        rec = {key: row[i] if i < len(row) else None for i, key in colmap.items()}
        if not clean_text(rec.get("partner")) and not clean_text(rec.get("placement")):
            continue
        rec["sheet_row"] = r_idx
        for k in NUMERIC_WEEKLY:
            if k in rec:
                raw = rec[k]
                val, flagged = parse_number(raw)
                if flagged:
                    cleaning.append((r_idx, k, raw, val))
                rec[k] = val
        for k in ("week_start", "week_end"):
            rec[k] = pd.to_datetime(rec.get(k), errors="coerce")
        raw_size = rec.get("creative_size")
        rec["creative_size"] = normalize_size(raw_size)
        if raw_size is not None and clean_text(raw_size) != rec["creative_size"]:
            cleaning.append((r_idx, "creative_size", raw_size, rec["creative_size"]))
        for k, v in list(rec.items()):
            if k not in NUMERIC_WEEKLY and k not in ("week_start", "week_end", "sheet_row", "creative_size"):
                rec[k] = clean_text(v)
        records.append(rec)

    rows = pd.DataFrame.from_records(records)
    rows["vendor"] = vendor_label or rows["partner"]
    rows["source_file"] = path.name

    plan = read_plan(wb)
    plan["vendor"] = vendor_label or plan.get("partner")

    vf = VendorFile(path=path, vendor=vendor_label or "", rows=rows, plan=plan, cleaning_log=cleaning)
    vf.file_issues = template_health_checks(wb, ws, hdr_row, rows)
    return vf


def read_plan(wb) -> pd.DataFrame:
    ws = wb["Resources"]
    raw_headers = [c.value for c in ws[1]]
    colmap = _map_headers(raw_headers, PLAN_HEADER_MAP)
    recs = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        rec = {key: row[i] if i < len(row) else None for i, key in colmap.items()}
        if not clean_text(rec.get("placement")):
            continue
        for k in NUMERIC_PLAN:
            rec[k] = parse_number(rec.get(k))[0]
        for k in ("flight_start", "flight_end"):
            rec[k] = pd.to_datetime(rec.get(k), errors="coerce")
        for k, v in list(rec.items()):
            if k not in NUMERIC_PLAN and k not in ("flight_start", "flight_end"):
                rec[k] = clean_text(v)
        recs.append(rec)
    return pd.DataFrame.from_records(recs)


def template_health_checks(wb, ws, hdr_row, rows: pd.DataFrame):
    """Problems with the vendor template itself (not the numbers)."""
    issues = []
    # 1. Formula errors in the template's own validation column
    if "issue_detail" in rows and rows["issue_detail"].astype(str).str.startswith("#").any():
        n = int(rows["issue_detail"].astype(str).str.startswith("#").sum())
        err = rows.loc[rows["issue_detail"].astype(str).str.startswith("#"), "issue_detail"].iloc[0]
        issues.append(("Warning", f"Template's built-in 'Issue Detail' check shows {err} on {n} of {len(rows)} rows, "
                                  f"so the vendor's own validation is not running."))
    # 2. Dropdown lists pointing at deleted ranges
    broken = [n for n, d in wb.defined_names.items() if "#REF!" in str(d.attr_text)]
    if broken:
        issues.append(("Warning", f"{len(broken)} dropdown lists in the template are broken (#REF!), e.g. "
                                  f"{', '.join(broken[:4])}. Vendors can type free text instead of picking approved values."))
    # 3. Rows not covered by the placement-name dropdown
    covered = set()
    for dv in ws.data_validations.dataValidation:
        if "placement" in str(dv.formula1).lower():
            for rng in dv.sqref.ranges:
                covered.update(range(rng.min_row, rng.max_row + 1))
    if covered:
        uncovered = sorted(set(rows["sheet_row"]) - covered)
        if uncovered:
            issues.append(("Warning", f"{len(uncovered)} data rows have no dropdown validation on Placement Name "
                                      f"(sheet rows {_ranges(uncovered)})."))
    return issues


def _ranges(nums):
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(out)


def read_vendor_summary(path: Path) -> pd.DataFrame:
    """The vendor's own 'Final Campaign Summary' tab: totals per placement (used to reconcile)."""
    ws = openpyxl.load_workbook(path, data_only=True)["Final Campaign Summary"]
    hdr = None
    for r in range(1, 30):
        if any(_norm_header(c.value).startswith("placement name") for c in ws[r]):
            hdr = r
            break
    if hdr is None:
        return pd.DataFrame()
    heads = [_norm_header(c.value) for c in ws[hdr]]
    ix = {k: next(i for i, h in enumerate(heads) if h.startswith(p)) for k, p in
          (("placement", "placement name"), ("impressions", "impressions delivered"), ("spend", "invoiced spend"))}
    recs = []
    for row in ws.iter_rows(min_row=hdr + 1, values_only=True):
        name = clean_text(row[ix["placement"]])
        if not name or name == "0":
            continue
        recs.append({"placement": name, "impressions": parse_number(row[ix["impressions"]])[0] or 0,
                     "spend": parse_number(row[ix["spend"]])[0] or 0})
    return pd.DataFrame(recs).drop_duplicates()
