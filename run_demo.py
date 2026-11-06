"""End-to-end demo: vendor Excel files in, clean data + pacing + report + deck out.

    python3 run_demo.py

Inputs : data/vendor_files/*.xlsx   (vendor weekly reporting templates, as received)
Outputs: output/
    master_dataset.csv / .xlsx   one clean row per vendor/week/placement/creative/size (the Google Sheet feed for Data Studio)
    validation_report.xlsx       submission tracker, row-level issues, template problems, auto-fixes
    pacing.xlsx                  delivered vs. planned per placement
    campaign_report.html / .pdf  Data Studio-style report
    campaign_deck.pptx           PowerPoint version
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from reporting import model as M
from reporting.deck import build_deck
from reporting.ingest import read_vendor_file, read_vendor_summary
from reporting.report import build_html, html_to_pdf

ROOT = Path(__file__).parent
CONFIG = {
    "campaign": "Impaired Driving Campaign (Demo)",
    # Vendor names in the sample files are anonymised ("[Vendor]", "Vendor"), so label them here.
    # With real files the Partner column is used directly.
    "files": {
        "data/vendor_files/vendor_a_weekly.xlsx": "Vendor A",
        "data/vendor_files/vendor_b_weekly.xlsx": "Vendor B",
    },
    "as_of": "2026-09-07",  # report date: campaign end
}


def main():
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    files = [read_vendor_file(ROOT / f, label) for f, label in CONFIG["files"].items()]
    rows = pd.concat([f.rows for f in files], ignore_index=True)
    plan = pd.concat([f.plan for f in files], ignore_index=True)
    as_of = pd.Timestamp(CONFIG["as_of"])

    df = M.build_master(rows)
    issues = pd.DataFrame(M.validate_rows(df, plan))
    tracker = M.submission_tracker(df, plan, as_of)
    file_issues = [(f.vendor, sev, msg) for f in files for sev, msg in f.file_issues]
    cleaned = Counter()
    for f in files:
        for _, fld, raw, val in f.cleaning_log:
            kind = "size format standardised" if fld == "creative_size" else "text placeholder like '-' or ' $ - ' treated as blank"
            cleaned[(f.vendor, kind)] += 1

    # rows with blocking errors are kept in the feed but flagged
    err_rows = set()
    if not issues.empty:
        err_rows = set(map(tuple, issues.loc[issues["severity"] == "Error", ["file", "sheet_row"]].values))
    df["validation_status"] = [("Error" if (f, r) in err_rows else "OK") for f, r in zip(df["source_file"], df["sheet_row"])]
    # KPIs use clean rows only; pacing uses every row because impressions are still valid when e.g. completions are wrong
    clean = df[df["validation_status"] == "OK"].copy()
    pace = M.pacing(df, plan, as_of)

    # reconcile our per-placement totals with each vendor's own summary tab
    recon = []
    for f, label in CONFIG["files"].items():
        vs = read_vendor_summary(ROOT / f).groupby("placement", as_index=False)[["impressions", "spend"]].max()
        ours = df[df["vendor"] == label].groupby("placement", as_index=False)[["impressions", "spend"]].sum()
        mrg = vs.merge(ours, on="placement", how="outer", suffixes=("_vendor", "_ours")).fillna(0)
        mrg["match"] = ((mrg["impressions_vendor"] - mrg["impressions_ours"]).abs() < 1) & \
                       ((mrg["spend_vendor"] - mrg["spend_ours"]).abs() < 0.05)
        mrg.insert(0, "vendor", label)
        recon.append(mrg)
    recon = pd.concat(recon, ignore_index=True)

    # ---- outputs
    master = df[M.MASTER_COLUMNS + ["validation_status"]].copy()
    master["week_start"] = master["week_start"].dt.date
    master["week_end"] = master["week_end"].dt.date
    master.to_csv(out / "master_dataset.csv", index=False)
    master.to_excel(out / "master_dataset.xlsx", index=False, sheet_name="vendor_data")

    with pd.ExcelWriter(out / "validation_report.xlsx") as xw:
        t = tracker.copy(); t["week_start"] = t["week_start"].dt.date; t["week_end"] = t["week_end"].dt.date
        t.to_excel(xw, sheet_name="Submission Tracker", index=False)
        (issues if not issues.empty else pd.DataFrame([{"issue": "none"}])).to_excel(xw, sheet_name="Row Issues", index=False)
        pd.DataFrame(file_issues, columns=["vendor", "severity", "finding"]).to_excel(xw, sheet_name="Template Health", index=False)
        pd.DataFrame([{"vendor": v, "fix": k, "values": n} for (v, k), n in cleaned.items()]).to_excel(xw, sheet_name="Auto-fixes", index=False)
        recon.to_excel(xw, sheet_name="Reconciliation", index=False)

    pc = pace.copy()
    for c in ("flight_start", "flight_end", "data_through"):
        pc[c] = pc[c].dt.date
    pc.to_excel(out / "pacing.xlsx", index=False, sheet_name="Pacing")

    d0, d1 = df["week_start"].min(), max(df["week_end"].max(), as_of)
    period = f"{d0:%B %-d, %Y}–{d1:%B %-d, %Y}" if d0.year != d1.year else f"{d0:%B %-d}–{d1:%B %-d, %Y}"
    ctx = dict(campaign=CONFIG["campaign"], period=period, as_of=as_of, df=clean,
               recon=recon, held_back=int((df["validation_status"] == "Error").sum()), plan=plan, pace=pace, tracker=tracker, issues=issues, file_issues=file_issues, cleaned=cleaned)
    html_path = out / "campaign_report.html"
    html_path.write_text(build_html(ctx), encoding="utf-8")
    html_to_pdf(html_path, out / "campaign_report.pdf")
    build_deck(ctx, out / "campaign_deck.pptx")

    n_err = int((issues["severity"] == "Error").sum()) if not issues.empty else 0
    n_warn = int((issues["severity"] == "Warning").sum()) if not issues.empty else 0
    print(f"Ingested {len(df)} rows from {len(files)} vendor files; {n_err} errors, {n_warn} warnings, "
          f"{int((tracker['status'] == 'MISSING').sum())} missing submissions.")
    in_v = recon[(recon["impressions_vendor"] > 0) | (recon["spend_vendor"] > 0)]
    print(f"Reconciliation: {int(in_v['match'].sum())}/{len(in_v)} placements in the vendors' summary tabs match exactly; "
          f"{len(recon) - len(in_v)} placements are missing from those tabs.")
    print(f"Outputs written to {out}/")


if __name__ == "__main__":
    main()
