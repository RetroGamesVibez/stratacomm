"""Auto-drafted highlight bullets, built from the numbers with simple rules.

These are a first draft for the account team to edit, not final copy. The same
inputs could be passed to an LLM for richer wording; rules keep the demo
deterministic and auditable.
"""
from __future__ import annotations

import math

from . import model as M
from .fmt import money, num, pct


def _vs_target(label, value, target):
    if value is None or target is None or math.isnan(value) or math.isnan(target):
        return None
    diff = value / target - 1
    verb = "beat" if value >= target else "fell short of"
    return f"{label} of {pct(value)} {verb} the {pct(target)} target ({diff:+.0%})."


def section_highlights(section, df, creatives, sizes, languages):
    m = M.section_metrics(df)
    tgt = M.section_target(df)
    kpi = M.SECTION_KPI[section]
    val = M.kpi_value(section, m)
    out = []
    label = {"CTR": "Paid CTR", "VCR": "Video completion rate", "LCR": "Listen-through rate"}.get(kpi)
    if label:
        s = _vs_target(label, val, tgt)
        if s:
            out.append(s)
    if m["av_value"] > 0:
        out.append(f"Vendors delivered {money(m['av_value'], 0)} in added value "
                   f"({num(m['av_impressions'])} free impressions) on top of {money(m['spend'], 0)} paid.")
    metric_col = {"CTR": "paid_ctr", "VCR": "vcr", "LCR": "lcr"}.get(kpi)
    if metric_col and creatives is not None and len(creatives) > 1:
        c = creatives.dropna(subset=[metric_col])
        c = c[c["impressions"] >= 0.02 * c["impressions"].sum()]
        if len(c) > 1:
            best, worst = c.loc[c[metric_col].idxmax()], c.loc[c[metric_col].idxmin()]
            out.append(f"'{best['creative']}' led creatives at {pct(best[metric_col])} {kpi}; "
                       f"'{worst['creative']}' trailed at {pct(worst[metric_col])}.")
    if kpi == "CTR" and sizes is not None and len(sizes) > 1:
        s = sizes[sizes["impression_share"] >= 0.02].dropna(subset=["ctr"])
        if len(s) > 1:
            top = s.loc[s["impressions"].idxmax()]
            best = s.loc[s["ctr"].idxmax()]
            out.append(f"{top['creative_size']} carried {pct(top['impression_share'], 0)} of impressions; "
                       f"{best['creative_size']} had the strongest CTR ({pct(best['ctr'])}).")
    if languages is not None and len(languages) > 1 and metric_col:
        l = languages.dropna(subset=[metric_col])
        if len(l) > 1:
            parts = [f"{r['language']} {pct(r[metric_col])}" for _, r in l.iterrows()]
            out.append(f"{kpi} by language: " + ", ".join(parts) + ".")
    if section == "OOH":
        out.append("OOH is bought on reach/frequency; vendors don't report reach in the weekly template, "
                   "so delivery is tracked on impressions and spend only.")
    return out


def overview_takeaways(df, pace, tracker):
    m = M.section_metrics(df)
    out = [f"{money(m['spend'], 0)} invested across {df['vendor'].nunique()} vendors and "
           f"{df['section'].nunique()} channels, delivering {num(m['impressions'])} impressions "
           f"(incl. {num(m['av_impressions'])} added-value)."]
    met, missed = [], []
    for s, g in df.groupby("section"):
        tgt, val = M.section_target(g), M.kpi_value(s, M.section_metrics(g))
        if not (math.isnan(tgt) or math.isnan(val)):
            (met if val >= tgt else missed).append(s)
    if met:
        out.append(f"KPI targets met in: {', '.join(met)}." + (f" Missed in: {', '.join(missed)}." if missed else ""))
    under = pace[pace["status"].isin(["Under-pacing", "Not delivering"])]
    if len(under):
        worst = under.loc[under["pace_index"].idxmin()]
        out.append(f"{len(under)} of {len(pace)} placements are behind plan; furthest behind: "
                   f"{worst['placement']} ({worst['vendor']}) at {pct(worst['delivered_pct'], 0)} delivered vs "
                   f"{pct(worst['flight_elapsed_pct'], 0)} of its flight elapsed.")
    missing = tracker[tracker["status"] == "MISSING"]
    if len(missing):
        vs = missing.groupby("vendor").size()
        out.append("Missing weekly submissions: " + ", ".join(f"{v} ({n} wk)" for v, n in vs.items())
                   + ". Totals for those vendors are understated until files arrive.")
    return out
