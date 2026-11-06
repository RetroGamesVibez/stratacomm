"""Render the campaign report as HTML (Data Studio look) and print it to PDF."""
from __future__ import annotations

import html
import math
import subprocess
from pathlib import Path

import pandas as pd

from . import charts as C
from . import model as M
from . import narrative as N
from .fmt import money, num, pct

CSS = """
@page { size: Letter; margin: 0.35in 0.35in; }
* { box-sizing: border-box; }
body { font-family: Roboto, Inter, 'DejaVu Sans', sans-serif; color: #424242; margin: 0; font-size: 9.5px; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
.banner { background: #616161; color: #fff; padding: 14px 18px; margin-bottom: 4px; }
.banner h1 { margin: 0; font-size: 20px; font-weight: 500; }
.banner .sub { font-size: 11px; opacity: .85; margin-top: 3px; }
h2 { text-align: center; font-size: 17px; font-weight: 600; color: #616161; margin: 14px 0 8px; }
h3 { text-align: center; font-size: 12.5px; font-weight: 600; color: #616161; margin: 9px 0 4px; }
table.compact td { font-size: 8.3px; padding: 2.5px 5px; } table.compact td:first-child { white-space: nowrap; }
.tiles { display: flex; justify-content: space-around; background: #f1f1f1; padding: 8px 4px; }
.tile { text-align: center; flex: 1; }
.tile .l { font-size: 8.5px; color: #8a8a8a; }
.tile .v { font-size: 18px; color: #555; }
.tile .d { font-size: 8px; color: #8a8a8a; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 16px; }
.chart { text-align: center; }
.chart .t { font-size: 11.5px; font-weight: 600; color: #616161; margin: 6px 0 0; }
.chart svg { width: 100%; height: auto; }
table { width: 100%; border-collapse: separate; border-spacing: 0; margin: 2px 0 6px; }
th { background: #eeeeee; color: #8a8a8a; font-weight: 600; text-align: left; padding: 5px 6px; font-size: 9px; }
th:first-child { border-top-left-radius: 7px; } th:last-child { border-top-right-radius: 7px; }
td { padding: 3.5px 6px; border-bottom: 1px solid #e3e3e3; font-size: 9px; }
td.r, th.r { text-align: right; } td.c, th.c { text-align: center; }
td.good { background: #c8e6c9; } td.bad { background: #ffcdd2; } td.warn { background: #fff3c4; }
.note { font-size: 8.5px; color: #616161; margin: 2px 2px 6px; }
.hl { background: #f1f1f1; border-radius: 8px; padding: 10px 16px; min-height: 60px; }
.hl ul { margin: 0; padding-left: 16px; } .hl li { margin: 3px 0; font-size: 10px; }
.hl .draft { font-size: 8px; color: #9e9e9e; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 4px; }
.alert { border-left: 4px solid #e53935; background: #fdecea; padding: 6px 10px; font-size: 9.5px; margin: 6px 0; }
.ok { border-left: 4px solid #43a047; background: #e8f5e9; padding: 6px 10px; font-size: 9.5px; margin: 6px 0; }
.pill { display: inline-block; padding: 1px 7px; border-radius: 9px; font-size: 8.5px; font-weight: 600; }
.p-ok { background: #c8e6c9; color: #1b5e20; } .p-under { background: #ffcdd2; color: #b71c1c; }
.p-over { background: #fff3c4; color: #7a5b00; } .p-none { background: #e0e0e0; color: #424242; }
.sev-Error { color: #c62828; font-weight: 600; } .sev-Warning { color: #a66b00; font-weight: 600; } .sev-Info { color: #1565c0; }
"""


def esc(v):
    return html.escape("" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v))


def tiles(items):
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="l">{esc(l)}</div><div class="v">{esc(v)}</div>'
        + (f'<div class="d">{esc(d)}</div>' if d else "") + "</div>"
        for l, v, *rest in items for d in [rest[0] if rest else ""]) + "</div>"


def chart(title, svg):
    return f'<div class="chart"><div class="t">{esc(title)}</div>{svg}</div>'


def table(df, cols, kpi_col=None, target_col="kpi_target", sort=None, limit=None):
    """cols: list of (header, key, formatter, align)."""
    if df is None or df.empty:
        return '<div class="note">No data.</div>'
    d = df.sort_values(sort, ascending=False) if sort else df
    if limit:
        d = d.head(limit)
    head = "".join(f'<th class="{a}">{esc(h)}</th>' for h, _, _, a in cols)
    body = []
    for _, r in d.iterrows():
        tds = []
        for h, k, f, a in cols:
            v = r.get(k)
            cls = a
            if k == kpi_col and target_col in r and not _isnan(v) and not _isnan(r[target_col]):
                cls += " good" if v >= r[target_col] else ""
            tds.append(f'<td class="{cls}">{esc(f(v) if f else v)}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


def _isnan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def highlights(items, title):
    lis = "".join(f"<li>{esc(i)}</li>" for i in items) or "<li>No notable changes.</li>"
    return (f'<h3>{esc(title)}</h3><div class="hl"><div class="draft">Auto-drafted from the data. '
            f'Review before sending</div><ul>{lis}</ul></div>')


def weekly_charts(df, specs):
    w = M.weekly(df)
    dates = list(w["week_start"])
    out = []
    for title, key, color, fmt, target in specs:
        out.append(chart(title, C.line_chart(dates, list(w[key]), title.replace("Weekly ", ""), color, fmt, target)))
    return '<div class="grid2">' + "".join(out) + "</div>"


T = lambda v: pct(v)  # noqa: E731


VENDOR_COLORS = [C.BLUE, C.YELLOW, C.GREEN, C.PURPLE, C.GRAY]


def vendor_trend(df):
    weeks = sorted(df["week_start"].dropna().unique())
    dates = [pd.Timestamp(w) for w in weeks]
    out = []
    for title, key, fmt in (("Weekly Spend", "spend", "money"), ("Weekly Impressions", "impressions", "k")):
        series = []
        for i, (v, g) in enumerate(df.groupby("vendor")):
            w = g.groupby("week_start")[key].sum()
            series.append((v, [w.get(d) for d in weeks], VENDOR_COLORS[i % len(VENDOR_COLORS)]))
        out.append(chart(title, C.multi_line_chart(dates, series, fmt)))
    return '<div class="grid2">' + "".join(out) + "</div>"


def cpc_fmt(v):
    return money(v) if v and not _isnan(v) else "-"


# --------------------------------------------------------------- pages
def page_overview(ctx):
    df, period = ctx["df"], ctx["period"]
    m = M.section_metrics(df)
    rows = []
    for s in M.SECTION_ORDER:
        g = df[df["section"] == s]
        if g.empty:
            continue
        sm = M.section_metrics(g)
        rows.append({"section": s, "kpi": M.SECTION_KPI[s], "kpi_target": M.section_target(g),
                     "spend": sm["spend"], "impressions": sm["impressions"], "clicks": sm["clicks"] or None,
                     "cpc": sm["paid_cpc"] if sm["paid_clicks"] else None,
                     "ctr": sm["paid_ctr"] if sm["paid_clicks"] else None,
                     "vcr_lcr": sm["vcr"] if s.startswith("Video") else sm["lcr"] if s == "Audio - Streaming" else None,
                     "kpi_value": M.kpi_value(s, sm), "av_value": sm["av_value"]})
    summ = pd.DataFrame(rows)
    summ["kpi_target_fmt"] = summ.apply(lambda r: pct(r["kpi_target"]) if r["kpi"] != "IMP" else "-", axis=1)
    cols = [("Channel", "section", None, ""), ("KPI", "kpi", None, ""), ("KPI Target", "kpi_target_fmt", None, ""),
            ("Paid Spend", "spend", money, "r"), ("Added Value", "av_value", money, "r"),
            ("Impressions", "impressions", num, "r"), ("Clicks", "clicks", num, "r"), ("Paid CPC", "cpc", money, "r"),
            ("Paid CTR", "ctr", T, "r"), ("VCR / LCR", "vcr_lcr", T, "r")]
    # green on whichever column holds the section KPI
    html_rows = []
    for _, r in summ.sort_values("spend", ascending=False).iterrows():
        tds = []
        for h, k, f, a in cols:
            v = r[k]
            cls = a
            kcol = {"CTR": "ctr", "VCR": "vcr_lcr", "LCR": "vcr_lcr"}.get(r["kpi"])
            if k == kcol and not _isnan(v) and not _isnan(r["kpi_target"]):
                cls += " good" if v >= r["kpi_target"] else " bad"
            tds.append(f'<td class="{cls}">{esc(f(v) if f else v)}</td>')
        html_rows.append("<tr>" + "".join(tds) + "</tr>")
    summary_tbl = "<table><tr>" + "".join(f'<th class="{a}">{h}</th>' for h, _, _, a in cols) + "</tr>" + "".join(html_rows) + "</table>"

    tracker = ctx["tracker"]
    missing = tracker[tracker["status"] == "MISSING"]
    completeness = (f'<div class="alert"><b>Data completeness:</b> {len(missing)} weekly vendor submission(s) missing ('
                    + ", ".join(f"{r.vendor}: week of {r.week_start:%b %-d}" for r in missing.itertuples())
                    + "). Figures below include only files received.</div>") if len(missing) else \
        '<div class="ok"><b>Data completeness:</b> all expected vendor submissions received.</div>'

    vend = M.grouped(df, "vendor")
    vend_tbl = table(vend, [("Vendor", "vendor", None, ""), ("Paid Spend", "spend", money, "r"),
                            ("Added Value", "av_value", money, "r"), ("Impressions", "impressions", num, "r"),
                            ("Clicks", "clicks", num, "r"), ("Paid CPM", "cpm", money, "r")], sort="spend")
    return f"""
<div class="page">
  <div class="banner"><h1>{esc(ctx['campaign'])}</h1><div class="sub">Campaign Report · {period} · generated automatically from vendor files</div></div>
  <h2>Cumulative Totals ({period})</h2>
  {tiles([("Paid Spend", money(m['spend'])), ("Added Value", money(m['av_value'])),
          ("Impressions", num(m['impressions'])), ("Clicks", num(m['clicks'])), ("Paid CPM", money(m['cpm']))])}
  {completeness}
  <h3>Week-over-Week Trend by Vendor</h3>
  {vendor_trend(df)}
  <h3>Cumulative Channel Summary ({period})</h3>
  {summary_tbl}
  <div class="note">Paid CPC / CTR use paid delivery only; added-value (free) delivery is shown separately. Green = KPI target met, red = missed.</div>
  <h3>Delivery by Vendor</h3>
  {vend_tbl}
  {highlights(N.overview_takeaways(df, ctx['pace'], tracker), 'Key Takeaways')}
</div>"""


def page_display(ctx):
    df = ctx["df"][ctx["df"]["section"] == "Display"]
    if df.empty:
        return ""
    m, tgt = M.section_metrics(df), M.section_target(df)
    cr = M.grouped(df, ["creative", "language"])
    sz = M.grouped(df, ["creative_size"])
    lg = M.grouped(df, ["language"])
    for t in (cr, sz, lg):
        t["kpi"] = "CTR"
    return f"""
<div class="page">
  <h2>Display Overview</h2>
  {tiles([("Paid Spend", money(m['spend'])), ("Total Impressions", num(m['impressions'])), ("Total Clicks", num(m['clicks'])),
          ("Paid CPC", money(m['paid_cpc'])), (f"Paid CTR (Target: {pct(tgt)})", pct(m['paid_ctr'])),
          ("Blended CTR", pct(m['ctr'])), ("Paid CPM", money(m['cpm']))])}
  <div class="note">Paid CPC, CPM and CTR use paid delivery only. Total Clicks, Total Impressions and Blended CTR also include added-value delivery ({money(m['av_value'], 0)}).</div>
  {weekly_charts(df, [("Weekly Spend", "spend", C.BLUE, "money", None), ("Weekly Impressions", "impressions", C.YELLOW, "k", None),
                      ("Weekly CTR", "paid_ctr", C.PURPLE, "pct", tgt), ("Weekly CPC", "paid_cpc", C.GRAY, "money2", None)])}
  <h3>Performance of Top Creatives</h3>
  {table(cr, [("Creative", "creative", None, ""), ("Language", "language", None, ""), ("KPI", "kpi", None, "c"),
              ("KPI Target", "kpi_target", T, "c"), ("Spend", "spend", money, "r"), ("Impressions", "impressions", num, "r"),
              ("Clicks", "clicks", num, "r"), ("Blended CPC", "cpc", cpc_fmt, "r"), ("CTR", "ctr", T, "r")],
         kpi_col="ctr", sort="spend", limit=8)}
  <div class="note">Added-value banners are measured against their own 0.14% CTR benchmark; paid high-impact units against 0.40%.</div>
  <h3>Comparison of Top Creative Sizes</h3>
  {table(sz, [("Creative Size", "creative_size", None, ""), ("KPI", "kpi", None, "c"), ("KPI Target", "kpi_target", T, "c"),
              ("Spend", "spend", money, "r"), ("Impressions", "impressions", num, "r"),
              ("Impression Share", "impression_share", T, "r"), ("Clicks", "clicks", num, "r"),
              ("Blended CPC", "cpc", cpc_fmt, "r"), ("CTR", "ctr", T, "r")], kpi_col="ctr", sort="impressions", limit=6)}
  {highlights(N.section_highlights('Display', df, cr, sz, lg), 'Display Performance Highlights')}
</div>"""


def page_video(ctx):
    df = ctx["df"][ctx["df"]["section"] == "Video (CTV)"]
    if df.empty:
        return ""
    m, tgt = M.section_metrics(df), M.section_target(df)
    vv = df[df["is_video_view"]]
    pl = M.grouped(df, ["vendor", "placement"])
    au = M.grouped(vv, ["audience_target"]) if vv["audience_target"].notna().any() else None
    lg = M.grouped(vv, ["language"])
    cr = M.grouped(vv, ["creative"])
    for t in [x for x in (pl, au, lg, cr) if x is not None]:
        t["kpi"] = "VCR"
        t["kpi_target"] = tgt
    pl["vcr_txt"] = pl.apply(lambda r: r["vcr"], axis=1)
    sponsor = df[~df["is_video_view"]]
    sp_note = (f'<div class="note">Includes {num(sponsor["impressions"].sum())} impressions / {num(sponsor["clicks"].sum())} clicks '
               f'from CTV sponsorship display units (marquee/billboard), which have no completion metric and are excluded from VCR.</div>'
               if len(sponsor) else "")
    au_html = (f"<h3>Audience Performance</h3>" + table(au, [("Audience Target", "audience_target", None, ""), ("KPI", "kpi", None, "c"),
               ("KPI Target", "kpi_target", T, "c"), ("Spend", "spend", money, "r"), ("Impression Share", "impression_share", T, "r"),
               ("VCR", "vcr", T, "r")], kpi_col="vcr", sort="spend")) if au is not None else ""
    return f"""
<div class="page">
  <h2>CTV / OLV Overview</h2>
  {tiles([("Paid Spend", money(m['spend'])), ("Impressions", num(m['impressions'])), ("Completions", num(m['completions'])),
          ("Paid CPCV", money(m['cpcv'], 3)), (f"VCR (Target: {pct(tgt, 0)})", pct(m['vcr'])), ("Paid CPM", money(m['cpm'])),
          ("Added Value", money(m['av_value'], 0))])}
  {sp_note}
  {weekly_charts(df, [("Weekly Spend", "spend", C.BLUE, "money", None), ("Weekly Impressions", "impressions", C.YELLOW, "k", None),
                      ("Weekly VCR", "vcr", C.PURPLE, "pct", tgt), ("Weekly CPCV", "cpcv", C.GRAY, "money2", None)])}
  <h3>Performance of Top Placements</h3>
  {table(pl, [("Vendor", "vendor", None, ""), ("Placement Name", "placement", None, ""), ("KPI Target", "kpi_target", T, "c"),
              ("Spend", "spend", money, "r"), ("Impressions", "impressions", num, "r"), ("VCR", "vcr", T, "r")],
         kpi_col="vcr", sort="impressions", limit=8)}
  {au_html}
  <h3>Language Performance</h3>
  {table(lg, [("Language", "language", None, ""), ("KPI", "kpi", None, "c"), ("KPI Target", "kpi_target", T, "c"),
              ("Spend", "spend", money, "r"), ("Impression Share", "impression_share", T, "r"), ("VCR", "vcr", T, "r")],
         kpi_col="vcr", sort="spend")}
  {highlights(N.section_highlights('Video (CTV)', vv, cr, None, lg), 'CTV / OLV Performance Highlights')}
</div>"""


def page_audio(ctx):
    d = ctx["df"]
    st, cb = d[d["section"] == "Audio - Streaming"], d[d["section"] == "Audio - Companion Banner"]
    if st.empty and cb.empty:
        return ""
    both = pd.concat([st, cb])
    ms, mc, mb = M.section_metrics(st), M.section_metrics(cb), M.section_metrics(both)
    ts, tc = M.section_target(st), M.section_target(cb)
    sp = M.grouped(st, ["placement"]); sp["kpi"] = "LCR"; sp["kpi_target"] = ts
    cp = M.grouped(cb, ["placement"]); cp["kpi"] = "CTR"; cp["kpi_target"] = tc
    cr = M.grouped(both, ["creative", "creative_size"])
    cr["kpi"] = cr["creative_size"].map(lambda s: "LCR" if s in M.AUDIO_LISTEN_SIZES else "CTR")
    cr["kpi_target"] = cr["kpi"].map({"LCR": ts, "CTR": tc})
    cr["kpi_value"] = cr.apply(lambda r: r["lcr"] if r["kpi"] == "LCR" else r["ctr"], axis=1)

    w_st, w_cb = M.weekly(st), M.weekly(cb)
    dates = list(M.weekly(both)["week_start"])
    g = '<div class="grid2">' + "".join([
        chart("Weekly Spend", C.line_chart(dates, list(M.weekly(both)["spend"]), "Spend", C.BLUE, "money")),
        chart("Weekly Impressions", C.line_chart(dates, list(M.weekly(both)["impressions"]), "Impressions", C.YELLOW, "k")),
        chart("Weekly LCR", C.line_chart(list(w_st["week_start"]), list(w_st["lcr"]), "LCR", C.PURPLE, "pct", ts)),
        chart("Weekly Companion Banner CTR", C.line_chart(list(w_cb["week_start"]), list(w_cb["ctr"]), "CTR", C.GRAY, "pct", tc)),
    ]) + "</div>"
    return f"""
<div class="page">
  <h2>Audio Overview</h2>
  {tiles([("Paid Spend", money(mb['spend'])), ("Audio Impressions", num(ms['impressions'])), ("Banner Impressions", num(mc['impressions'])),
          ("Completions", num(ms['completions'])), ("Clicks", num(mc['clicks'])), (f"Audio LCR (Target: {pct(ts, 0)})", pct(ms['lcr'])),
          (f"Banner CTR (Target: {pct(tc)})", pct(mc['paid_ctr'])), ("Cost Per Listen", money(ms['cpl']))])}
  {g}
  <h3>Digital Audio Performance</h3>
  {table(sp, [("Placement Name", "placement", None, ""), ("KPI Type", "kpi", None, "c"), ("KPI Target", "kpi_target", T, "c"),
              ("Spend", "spend", money, "r"), ("Impression Share", "impression_share", T, "r"), ("LCR", "lcr", T, "r")],
         kpi_col="lcr", sort="spend")}
  <h3>Companion Banner Performance</h3>
  {table(cp, [("Placement Name", "placement", None, ""), ("KPI Type", "kpi", None, "c"), ("KPI Target", "kpi_target", T, "c"),
              ("Spend", "spend", money, "r"), ("Impression Share", "impression_share", T, "r"), ("CTR", "ctr", T, "r")],
         kpi_col="ctr", sort="spend")}
  <h3>Performance of Creatives</h3>
  {table(cr, [("Creative Name", "creative", None, ""), ("Creative Size", "creative_size", None, "c"), ("KPI", "kpi", None, "c"),
              ("KPI Target", "kpi_target", T, "c"), ("Spend", "spend", money, "r"), ("Impressions", "impressions", num, "r"),
              ("Clicks", "clicks", num, "r"), ("Result", "kpi_value", T, "r")], kpi_col="kpi_value", sort="spend", limit=6)}
  {highlights(N.section_highlights('Audio - Streaming', st, M.grouped(st, ['creative']), None, None)
              + N.section_highlights('Audio - Companion Banner', cb, M.grouped(cb, ['creative']), None, None)[:1],
              'Audio Performance Highlights')}
</div>"""


def page_ooh(ctx):
    df = ctx["df"][ctx["df"]["section"] == "OOH"]
    if df.empty:
        return ""
    m = M.section_metrics(df)
    sz = M.grouped(df, ["creative_size"])
    cr = M.grouped(df, ["creative", "added_value"])
    return f"""
<div class="page">
  <h2>Digital OOH Overview</h2>
  {tiles([("Paid Spend", money(m['spend'])), ("Paid Impressions", num(m['paid_impressions'])),
          ("Added-Value Impressions", num(m['av_impressions'])), ("Added Value", money(m['av_value'])), ("Paid CPM", money(m['cpm']))])}
  {weekly_charts(df, [("Weekly Spend", "spend", C.BLUE, "money", None), ("Weekly Impressions", "impressions", C.YELLOW, "k", None)])}
  <h3>Performance by Creative</h3>
  {table(cr, [("Creative", "creative", None, ""), ("Added Value", "added_value", None, "c"), ("Spend", "spend", money, "r"),
              ("AV $", "av_value", money, "r"), ("Impressions", "impressions", num, "r"), ("Impression Share", "impression_share", T, "r")],
         sort="impressions")}
  <h3>Comparison of Screen Sizes</h3>
  {table(sz, [("Screen Size", "creative_size", None, ""), ("Spend", "spend", money, "r"), ("AV $", "av_value", money, "r"),
              ("Impressions", "impressions", num, "r"), ("Impression Share", "impression_share", T, "r")], sort="impressions", limit=6)}
  {highlights(N.section_highlights('OOH', df, None, None, None), 'OOH Performance Highlights')}
</div>"""


def page_pacing(ctx):
    p = ctx["pace"].copy()
    pill = {"On pace": "p-ok", "Under-pacing": "p-under", "Over-pacing": "p-over", "Not delivering": "p-none"}
    rows = []
    for _, r in p.iterrows():
        rows.append(
            f"<tr><td>{esc(r['vendor'])}</td><td>{esc(r['channel'])}</td><td>{esc(r['placement'])}</td>"
            f"<td class='r'>{num(r['planned_impressions'])}</td><td class='r'>{num(r['delivered_impressions'])}</td>"
            f"<td class='r'>{pct(r['delivered_pct'], 0)}</td><td class='r'>{pct(r['flight_elapsed_pct'], 0)}</td>"
            f"<td class='r'>{money(r['delivered_spend'], 0)}</td><td class='r'>{money(r['planned_cost'], 0) if r['planned_cost'] else 'AV'}</td>"
            f"<td class='c'><span class='pill {pill[r['status']]}'>{esc(r['status'])}</span></td></tr>")
    counts = p["status"].value_counts()
    return f"""
<div class="page">
  <h2>Pacing vs. Plan (IO)</h2>
  {tiles([(s, str(int(counts.get(s, 0)))) for s in ["On pace", "Under-pacing", "Over-pacing", "Not delivering"]])}
  <div class="note">Plan = 'Resources' tab of each vendor template (negotiated impressions and cost). Expected delivery is the share of each
  placement's flight elapsed up to the latest week the vendor has reported. On pace = 90–110% of expected.</div>
  <table class='compact'><tr><th>Vendor</th><th>Channel</th><th>Placement</th><th class='r'>Planned Imps</th><th class='r'>Delivered</th>
  <th class='r'>% Delivered</th><th class='r'>% Flight</th><th class='r'>Spend</th><th class='r'>Planned $</th><th class='c'>Status</th></tr>
  {''.join(rows)}</table>
</div>"""


def page_quality(ctx):
    tr, issues, file_issues, cleaned = ctx["tracker"], ctx["issues"], ctx["file_issues"], ctx["cleaned"]
    trk = "".join(
        f"<tr><td>{esc(r.vendor)}</td><td>{r.week_start:%b %-d} – {r.week_end:%b %-d, %Y}</td>"
        f"<td class='c'><span class='pill {'p-ok' if r.status == 'Received' else 'p-under' if r.status == 'MISSING' else 'p-none'}'>{esc(r.status)}</span></td></tr>"
        for r in tr.itertuples())
    fi = "".join(f"<tr><td>{esc(v)}</td><td class='sev-{s}'>{s}</td><td>{esc(msg)}</td></tr>" for v, s, msg in file_issues)
    iss = issues.copy()
    if not iss.empty:
        iss = (iss.groupby(["vendor", "severity", "field", "issue"]).agg(rows=("sheet_row", lambda x: ", ".join(map(str, sorted(x)))),
                                                                      n=("sheet_row", "size")).reset_index())
        order = {"Error": 0, "Warning": 1, "Info": 2}
        iss = iss.sort_values(["severity", "vendor"], key=lambda s: s.map(order) if s.name == "severity" else s)
    ri = "".join(f"<tr><td>{esc(r.vendor)}</td><td class='sev-{r.severity}'>{r.severity}</td><td>{esc(r.issue)}</td>"
                 f"<td class='r'>{r.n}</td><td>{esc(r.rows)}</td></tr>" for r in iss.itertuples()) if not iss.empty else ""
    held = ctx.get("held_back", 0)
    held_note = (f'<div class="alert"><b>{held} row(s) held back</b> from this report because of blocking errors. '
                 f'They are included automatically once the vendor sends a corrected file.</div>') if held else ""
    rc = ctx.get("recon")
    recon_note = ""
    if rc is not None and len(rc):
        in_v = rc[(rc["impressions_vendor"] > 0) | (rc["spend_vendor"] > 0)]
        missing_v = rc[(rc["impressions_vendor"] == 0) & (rc["spend_vendor"] == 0)]
        ok = int(in_v["match"].sum())
        recon_note = (f'<div class="{"ok" if ok == len(in_v) else "alert"}"><b>Reconciliation:</b> imported totals match the vendors\' own '
                      f'"Final Campaign Summary" tab exactly for {ok} of {len(in_v)} placements (impressions and invoiced spend).</div>')
        if len(missing_v):
            for v, g in missing_v.groupby("vendor"):
                recon_note += (f'<div class="alert"><b>{esc(v)}\'s own summary tab is incomplete:</b> it omits {len(g)} placements that are '
                               f'in its weekly data ({num(g["impressions_ours"].sum())} impressions, {money(g["spend_ours"].sum(), 0)} spend), '
                               f'so any report built from that tab would understate delivery.</div>')
    cl = "".join(f"<li>{esc(v)}: {n} value(s) auto-cleaned ({esc(k)})</li>" for (v, k), n in cleaned.items())
    return f"""
<div class="page">
  <h2>Data Quality & Submission Tracker</h2>
  <div class="note">Every vendor file is checked automatically on arrival. Errors block the data from reporting until fixed; warnings are flagged for review.</div>
  {held_note}
  {recon_note}
  <h3>Weekly Submission Tracker</h3>
  <table><tr><th>Vendor</th><th>Reporting Week</th><th class='c'>Status</th></tr>{trk}</table>
  <h3>Row-level Issues Found</h3>
  <table class='compact'><tr><th>Vendor</th><th>Severity</th><th>Issue</th><th class='r'>Rows</th><th>Sheet rows</th></tr>{ri}</table>
  <h3>Vendor Template Health</h3>
  <table class='compact'><tr><th>Vendor</th><th>Severity</th><th>Finding</th></tr>{fi}</table>
  <h3>Auto-fixed on Import</h3>
  <div class="hl"><ul>{cl}</ul></div>
</div>"""


def page_definitions():
    defs = [("CPM", "Average cost to show an ad 1,000 times.", "(Paid Spend / Paid Impressions) × 1,000"),
            ("CPC (Paid)", "Average cost per click on paid placements.", "Paid Spend / Paid Clicks"),
            ("Blended CPC", "Paid spend spread across all clicks, including added value clicks.", "Paid Spend / All Clicks"),
            ("CTR (Paid)", "Share of paid impressions that were clicked.", "Paid Clicks / Paid Impressions"),
            ("Blended CTR", "Click-through rate including paid and added-value delivery.", "All Clicks / All Impressions"),
            ("VCR", "Share of video ads played to the end.", "Video Completions / Video Impressions"),
            ("CPCV", "Cost per completed video view.", "Paid Spend / Paid Completions"),
            ("LCR", "Share of audio ads played to the end.", "Audio Completions / Listens"),
            ("Cost Per Listen", "Average cost each time an audio ad was played.", "Paid Spend / Listens"),
            ("Added Value", "Impressions and clicks provided by the vendor at no additional cost.", "Impressions × AV applied rate (vendor-reported AV $)"),
            ("Pace Index", "Delivery vs. where the placement should be at this point of its flight.", "% of planned impressions delivered / % of flight elapsed")]
    rows = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in defs)
    return f'<div class="page"><h2>Reference: KPI Definitions</h2><table><tr><th>KPI</th><th>Definition</th><th>How It\'s Calculated</th></tr>{rows}</table></div>'


def build_html(ctx) -> str:
    pages = [page_overview(ctx), page_display(ctx), page_video(ctx), page_audio(ctx), page_ooh(ctx),
             page_pacing(ctx), page_quality(ctx), page_definitions()]
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(ctx['campaign'])} Report</title>"
            f"<style>{CSS}</style></head><body>{''.join(p for p in pages if p)}</body></html>")


def html_to_pdf(html_path: Path, pdf_path: Path):
    js = (
        "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();"
        "const p=await b.newPage();await p.goto('file://'+process.argv[1],{waitUntil:'networkidle'});"
        "await p.pdf({path:process.argv[2],format:'Letter',printBackground:true,"
        "margin:{top:'0.35in',bottom:'0.35in',left:'0.35in',right:'0.35in'}});await b.close();})();"
    )
    subprocess.run(["node", "-e", js, str(html_path.resolve()), str(pdf_path.resolve())], check=True)
