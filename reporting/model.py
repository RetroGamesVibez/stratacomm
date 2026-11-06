"""Business rules: channel sections, KPI targets, metrics, validation and pacing."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

VIDEO_SIZES = {":06", ":15", ":30", ":60", "1920x1080"}
AUDIO_LISTEN_SIZES = {":15", ":30", ":60"}

SECTION_ORDER = ["Display", "Video (CTV)", "Audio - Streaming", "Audio - Companion Banner", "OOH"]
SECTION_KPI = {  # primary KPI shown in summary tables
    "Display": "CTR",
    "Video (CTV)": "VCR",
    "Audio - Streaming": "LCR",
    "Audio - Companion Banner": "CTR",
    "OOH": "IMP",
}

MASTER_COLUMNS = [
    "vendor", "week_start", "week_end", "section", "channel", "tactic", "language", "placement",
    "added_value", "unit_name", "creative", "creative_size", "audience", "audience_target", "geo",
    "kpi", "kpi_target", "cost_method", "rate", "impressions", "clicks", "views", "completions",
    "thruplays", "reach_paid", "engagements", "radio_spots", "spend", "av_value",
    "source_file", "sheet_row",
]


def assign_section(row) -> str:
    ch = (row.get("channel") or "").lower()
    size = row.get("creative_size") or ""
    if ch == "display":
        return "Display"
    if ch == "video":
        return "Video (CTV)"
    if ch == "audio":
        return "Audio - Streaming" if size in AUDIO_LISTEN_SIZES else "Audio - Companion Banner"
    if ch == "ooh":
        return "OOH"
    return row.get("channel") or "Other"


TARGET_RE = re.compile(r"(\d*\.?\d+)\s*%\+?\s*(CTR|VCR|LTR|LCR|VTR)", re.I)


def parse_targets(text) -> dict:
    out = {}
    for num, kind in TARGET_RE.findall(str(text or "")):
        kind = kind.upper().replace("LTR", "LCR")
        out[kind] = float(num) / 100
    return out


def row_target(row):
    t = parse_targets(row.get("kpi_target_text")) or parse_targets(row.get("kpi"))
    return t.get(SECTION_KPI.get(row["section"], ""), np.nan)


def build_master(rows: pd.DataFrame) -> pd.DataFrame:
    df = rows.copy()
    df["section"] = df.apply(assign_section, axis=1)
    df["kpi_target"] = df.apply(row_target, axis=1)
    df["added_value"] = df["added_value"].str.upper().str[0]
    df["is_av"] = df["added_value"].eq("Y")
    df["is_video_view"] = (df["section"] == "Video (CTV)") & df["creative_size"].isin(VIDEO_SIZES)
    for c in ["impressions", "clicks", "views", "completions", "spend", "av_value"]:
        df[c] = df[c].fillna(0.0)
    return df


# ---------------------------------------------------------------- metrics
def _div(a, b):
    return float(a) / float(b) if b else np.nan


def section_metrics(df: pd.DataFrame) -> dict:
    paid = df[~df["is_av"]]
    m = {
        "spend": df["spend"].sum(),
        "av_value": df["av_value"].sum(),
        "impressions": df["impressions"].sum(),
        "paid_impressions": paid["impressions"].sum(),
        "av_impressions": df.loc[df["is_av"], "impressions"].sum(),
        "clicks": df["clicks"].sum(),
        "paid_clicks": paid["clicks"].sum(),
        "completions": df["completions"].sum(),
        "listens": df["views"].sum(),
    }
    m["ctr"] = _div(m["clicks"], m["impressions"])                   # blended
    m["paid_ctr"] = _div(m["paid_clicks"], m["paid_impressions"])
    m["cpc"] = _div(m["spend"], m["clicks"])                         # blended CPC
    m["paid_cpc"] = _div(m["spend"], m["paid_clicks"])
    m["cpm"] = _div(m["spend"] * 1000, m["paid_impressions"])
    vv = df[df["is_video_view"]]
    m["vcr"] = _div(vv["completions"].sum(), vv["impressions"].sum())
    m["video_impressions"] = vv["impressions"].sum()
    m["cpcv"] = _div(vv.loc[~vv["is_av"], "spend"].sum(), vv.loc[~vv["is_av"], "completions"].sum())
    m["lcr"] = _div(m["completions"], m["listens"])
    m["cpl"] = _div(m["spend"], df.loc[~df["is_av"], "views"].sum())
    return m


def kpi_value(section, m):
    return {"CTR": m["paid_ctr"], "VCR": m["vcr"], "LCR": m["lcr"]}.get(SECTION_KPI.get(section), np.nan)


def section_target(df):
    t = df.loc[~df["is_av"], "kpi_target"].dropna()
    if t.empty:
        t = df["kpi_target"].dropna()
    return float(t.mode().iloc[0]) if not t.empty else np.nan


def grouped(df, by, extra_cols=()):
    """Per-group metrics table used for 'top creatives', 'sizes', 'language' etc."""
    out = []
    keys = by if isinstance(by, list) else [by]
    df = df.copy()
    for k in keys:
        if df[k].dtype == object:
            df[k] = df[k].fillna("(not specified)")
    for key, g in df.groupby(by, dropna=False, sort=False):
        m = section_metrics(g)
        rec = dict(zip(by if isinstance(by, list) else [by], key if isinstance(key, tuple) else (key,)))
        rec.update(m)
        rec["kpi_target"] = section_target(g)
        for c in extra_cols:
            rec[c] = g[c].iloc[0]
        out.append(rec)
    res = pd.DataFrame(out)
    if not res.empty:
        res["impression_share"] = res["impressions"] / res["impressions"].sum()
    return res


def weekly(df):
    w = grouped(df, "week_start").sort_values("week_start")
    return w


# ---------------------------------------------------------------- validation
def validate_rows(df: pd.DataFrame, plan: pd.DataFrame) -> list[dict]:
    """Row-level checks. Severity: Error (blocks), Warning (review), Info (auto-fixed)."""
    issues = []

    def add(r, sev, fld, msg, val=None):
        issues.append({"vendor": r["vendor"], "file": r["source_file"], "sheet_row": int(r["sheet_row"]),
                       "severity": sev, "field": fld, "issue": msg, "value": val})

    plan_names = set(plan["placement"].dropna())
    for _, r in df.iterrows():
        for fld in ("partner", "week_start", "week_end", "channel", "placement"):
            if pd.isna(r.get(fld)) or r.get(fld) in (None, ""):
                add(r, "Error", fld, "Required field is blank")
        if pd.notna(r["week_start"]) and pd.notna(r["week_end"]):
            days = (r["week_end"] - r["week_start"]).days
            if days < 0:
                add(r, "Error", "week_end", "Week Ending is before Week Starting")
            elif days > 6:
                add(r, "Error", "week_end", f"Row covers {days + 1} days; each row must be one week")
        if r["placement"] and plan_names and r["placement"] not in plan_names:
            add(r, "Error", "placement", "Placement name not found in the IO / media plan", r["placement"])
        if r["is_av"]:
            if (r.get("cost_method") or "").lower() != "free":
                add(r, "Warning", "cost_method", "Added-value row should use Cost Method 'Free'", r.get("cost_method"))
            if r["spend"] > 0:
                add(r, "Error", "spend", "Added-value row has invoiced spend", r["spend"])
            if r["av_value"] == 0:
                add(r, "Warning", "av_value", "Added-value row is missing AV $")
        else:
            if (r.get("cost_method") or "").lower() == "free":
                add(r, "Warning", "cost_method", "Paid row (Added Value = N) uses Cost Method 'Free'")
            if (r.get("cost_method") or "").upper() == "CPM" and r.get("rate") and r["impressions"]:
                expected = r["impressions"] / 1000 * r["rate"]
                if expected and abs(r["spend"] - expected) / expected > 0.02:
                    add(r, "Warning", "spend",
                        f"Spend ${r['spend']:,.2f} doesn't match impressions x CPM rate (${expected:,.2f})", r["spend"])
        if r["clicks"] > r["impressions"] > 0:
            add(r, "Error", "clicks", "Clicks exceed impressions", r["clicks"])
        denom = r["views"] or r["impressions"]
        if r["completions"] > denom > 0:
            add(r, "Error", "completions",
                f"Completions ({r['completions']:,.0f}) exceed views/impressions ({denom:,.0f}): completion rate over 100%",
                r["completions"])
        if r["section"] == "Video (CTV)" and r["is_video_view"] and r["impressions"] and not r["completions"]:
            add(r, "Warning", "completions", "Video row has no completions reported")
        if r["section"] in ("Audio - Streaming",) and not r["views"]:
            add(r, "Warning", "views", "Audio row has no listens reported")
    # duplicates
    key = ["vendor", "week_start", "placement", "creative", "creative_size", "audience", "unit_name"]
    dup = df[df.duplicated(key, keep=False)]
    for _, r in dup.iterrows():
        add(r, "Warning", "row", "Possible duplicate row (same week, placement, creative, size, audience)")
    return issues


def expected_weeks(flight_start, flight_end):
    """Reporting weeks run Monday-Sunday; the first and last week can be partial."""
    weeks, start = [], flight_start
    while start <= flight_end:
        end = min(start + pd.Timedelta(days=6 - start.weekday()), flight_end)
        weeks.append((start, end))
        start = end + pd.Timedelta(days=1)
    return weeks


def submission_tracker(df, plan, as_of):
    out = []
    for vendor, p in plan.groupby("vendor"):
        fs, fe = p["flight_start"].min(), p["flight_end"].max()
        got = set(df.loc[df["vendor"] == vendor, "week_start"].dropna())
        for ws, we in expected_weeks(fs, fe):
            if we > as_of:
                status = "Not due yet"
            else:
                status = "Received" if ws in got else "MISSING"
            out.append({"vendor": vendor, "week_start": ws, "week_end": we, "status": status})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- pacing
def pacing(df, plan, as_of):
    plan_g = plan.groupby(["vendor", "placement"], as_index=False).agg(
        channel=("channel", "first"), language=("language", "first"), added_value=("added_value", "first"),
        cost_method=("cost_method", "first"), rate=("rate", "first"),
        planned_impressions=("planned_impressions", "sum"), planned_cost=("planned_cost", "sum"),
        flight_start=("flight_start", "min"), flight_end=("flight_end", "max"))
    deliv = df.groupby(["vendor", "placement"], as_index=False).agg(
        delivered_impressions=("impressions", "sum"), delivered_spend=("spend", "sum"),
        av_value=("av_value", "sum"), data_through=("week_end", "max"))
    p = plan_g.merge(deliv, on=["vendor", "placement"], how="left")
    vendor_through = df.groupby("vendor")["week_end"].max()
    p["data_through"] = p["vendor"].map(vendor_through)
    p[["delivered_impressions", "delivered_spend", "av_value"]] = p[
        ["delivered_impressions", "delivered_spend", "av_value"]].fillna(0)
    flight_days = (p["flight_end"] - p["flight_start"]).dt.days + 1
    through = p["data_through"].where(p["data_through"] < p["flight_end"], p["flight_end"])
    p["flight_elapsed_pct"] = ((through - p["flight_start"]).dt.days + 1).clip(lower=0) / flight_days
    p["delivered_pct"] = p["delivered_impressions"] / p["planned_impressions"]
    p["spend_pct"] = np.where(p["planned_cost"].fillna(0) > 0, p["delivered_spend"] / p["planned_cost"], np.nan)
    p["pace_index"] = p["delivered_pct"] / p["flight_elapsed_pct"]

    def status(r):
        if r["delivered_impressions"] == 0:
            return "Not delivering"
        idx = round(r["pace_index"], 2)
        if idx < 0.9:
            return "Under-pacing"
        if idx > 1.1:
            return "Over-pacing"
        return "On pace"
    p["status"] = p.apply(status, axis=1)
    p["remaining_impressions"] = (p["planned_impressions"] - p["delivered_impressions"]).clip(lower=0)
    return p.sort_values(["vendor", "channel", "placement"]).reset_index(drop=True)
