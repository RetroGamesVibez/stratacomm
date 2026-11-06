"""PowerPoint version of the report, in the style of the client's monthly deck."""
from __future__ import annotations

import io
import math

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

from . import charts as C
from . import model as M
from . import narrative as N
from .fmt import money, num, pct, short

NAVY = RGBColor(0x01, 0x17, 0x48)
RED = RGBColor(0xBD, 0x2B, 0x2B)
BEIGE = RGBColor(0xD9, 0xD4, 0xCE)
GRAY = RGBColor(0x44, 0x44, 0x44)
FONT = "Arial"


def _text(slide, x, y, w, h, text, size=14, bold=False, color=GRAY, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, color, FONT
    return tb


def _rect(slide, x, y, w, h, color):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = color
    s.line.fill.background()
    return s


def _title(slide, text):
    _text(slide, 0.5, 0.3, 12.3, 1.0, text, size=26, bold=True, color=NAVY, anchor=MSO_ANCHOR.BOTTOM)
    _rect(slide, 0.5, 1.3, 12.33, 0.07, RED)


def _stats(slide, stats, x0=8.2):
    """2x2 grid of big numbers like the client's deck."""
    for i, (val, label) in enumerate(stats[:4]):
        cx, cy = x0 + (i % 2) * 2.55, 1.9 + (i // 2) * 2.6
        _rect(slide, cx + 0.85, cy, 0.8, 0.12, BEIGE)
        _text(slide, cx - 0.2, cy + 0.25, 2.9, 1.0, val, size=40, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
        _text(slide, cx - 0.2, cy + 1.25, 2.9, 0.5, label, size=15, color=GRAY, align=PP_ALIGN.CENTER)


def _image(slide, png, x=0.4, y=1.6, w=7.4):
    slide.shapes.add_picture(io.BytesIO(png), Inches(x), Inches(y), width=Inches(w))


def _table(slide, header, rows, x=0.5, y=1.7, w=12.3, col_w=None, size=12, bold_last=False):
    shp = slide.shapes.add_table(len(rows) + 1, len(header), Inches(x), Inches(y), Inches(w), Inches(0.4 * (len(rows) + 1)))
    t = shp.table
    for j, h in enumerate(header):
        c = t.cell(0, j)
        c.text = h
        c.fill.solid(); c.fill.fore_color.rgb = BEIGE
    for i, row in enumerate(rows, start=1):
        for j, v in enumerate(row):
            c = t.cell(i, j)
            c.text = str(v)
            c.fill.solid(); c.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for i in range(len(rows) + 1):
        for j in range(len(header)):
            for p in t.cell(i, j).text_frame.paragraphs:
                for r in p.runs:
                    r.font.size, r.font.name, r.font.color.rgb = Pt(size), FONT, RGBColor(0, 0, 0)
                    r.font.bold = i == 0 or (bold_last and i == len(rows))
    if col_w:
        for j, cw in enumerate(col_w):
            t.columns[j].width = Inches(cw)
    return t


def _divider(prs, text):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _rect(s, 0.5, 2.2, 0.85, 2.05, BEIGE)
    _rect(s, 0.5, 4.4, 0.85, 0.85, RED)
    _rect(s, 1.5, 2.2, 10.3, 3.05, NAVY)
    _rect(s, 11.97, 2.2, 0.85, 3.05, RED)
    _text(s, 1.5, 2.2, 10.3, 3.05, text.split("\n"), size=36, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF),
          align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def _kpi_stat(section, m):
    k = M.SECTION_KPI[section]
    if k == "CTR":
        return pct(m["paid_ctr"]), "CTR", money(m["paid_cpc"]), "CPC"
    if k == "VCR":
        return pct(m["vcr"]), "VCR", money(m["cpcv"]), "CPCV"
    if k == "LCR":
        return pct(m["lcr"]), "LCR", money(m["cpl"], 3), "Cost Per Listen"
    return money(m["cpm"]), "CPM", short(m["av_value"], "$"), "Added Value"


def build_deck(ctx, path):
    df, period = ctx["df"], ctx["period"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]

    # 1. cover
    s = prs.slides.add_slide(blank)
    _rect(s, 0.4, 0.4, 12.53, 5.0, NAVY)
    _text(s, 0.9, 1.6, 11.5, 2.5, [ctx["campaign"], "Automated Campaign Report"], size=40, bold=True,
          color=RGBColor(0xFF, 0xFF, 0xFF))
    _text(s, 0.6, 5.55, 12.3, 0.8, f"Campaign Report: {period}", size=30, bold=True, color=NAVY)
    _text(s, 0.6, 6.5, 12.3, 0.5, f"Generated automatically from vendor files received through {ctx['as_of']:%B %-d, %Y}",
          size=16, color=NAVY)

    # 2. cumulative snapshot
    m = M.section_metrics(df)
    s = prs.slides.add_slide(blank)
    _title(s, f"Cumulative Reporting Snapshot:\n{period}")
    by = df.groupby("section")["spend"].sum()
    _image(s, C.bar_chart(list(by.index), list(by.values), "Paid Spend by Channel"), y=1.7)
    _stats(s, [(short(m["impressions"]), "Impressions"), (short(m["spend"], "$"), "Investment"),
               (short(m["clicks"]), "Clicks"), (money(m["paid_cpc"]), "Overall CPC")])

    # 3. channel table
    s = prs.slides.add_slide(blank)
    _title(s, f"Reporting Snapshot by Channel:\n{period}")
    rows = []
    for sec in M.SECTION_ORDER:
        g = df[df["section"] == sec]
        if g.empty:
            continue
        sm = M.section_metrics(g)
        k = M.SECTION_KPI[sec]
        tgt = M.section_target(g)
        val = M.kpi_value(sec, sm)
        met = "" if (math.isnan(tgt) or math.isnan(val)) else (" ✓" if val >= tgt else " ✗")
        cv = num(sm["clicks"]) if k in ("CTR",) else num(sm["completions"]) if k in ("VCR", "LCR") else "—"
        cp = money(sm["paid_cpc"]) if k == "CTR" else money(sm["cpcv"]) if k == "VCR" else money(sm["cpl"], 3) if k == "LCR" else "—"
        kv = (pct(val) + f" {k}" + met) if not math.isnan(val) else "—"
        rows.append([sec, money(sm["spend"]), num(sm["impressions"]), cv, cp, kv])
    rows.append(["TOTAL / BLENDED", money(m["spend"]), num(m["impressions"]), num(m["clicks"]), money(m["paid_cpc"]), ""])
    _table(s, ["Channel", "Spent", "Impressions", "Clicks / Completions", "CPC / CPCV / CPL", "KPI result vs target"],
           rows, col_w=[2.9, 1.8, 1.9, 2.1, 1.9, 1.7], bold_last=True)

    # 4. per-tactic slides
    _divider(prs, "Paid Media\nPerformance By Tactic")
    for sec in M.SECTION_ORDER:
        g = df[df["section"] == sec]
        if g.empty:
            continue
        sm = M.section_metrics(g if sec != "Video (CTV)" else g)
        kv, kl, cv, cl = _kpi_stat(sec, sm)
        s = prs.slides.add_slide(blank)
        _title(s, f"{sec}: {period}")
        w = M.weekly(g if sec != "Video (CTV)" else g[g["is_video_view"]])
        key = {"CTR": "paid_ctr", "VCR": "vcr", "LCR": "lcr"}.get(M.SECTION_KPI[sec], "impressions")
        fmt = "pct" if key != "impressions" else "k"
        tgt = M.section_target(g)
        _image(s, C.line_chart(list(w["week_start"]), list(w[key]), f"Weekly {kl if key != 'impressions' else 'Impressions'}",
                               C.PURPLE if key != "impressions" else C.YELLOW, fmt,
                               None if math.isnan(tgt) else tgt, size=(7.4, 3.0), as_png=True), y=1.6)
        bullets = N.section_highlights(sec, g[g["is_video_view"]] if sec == "Video (CTV)" else g,
                                       M.grouped(g, ["creative"]), M.grouped(g, ["creative_size"]),
                                       M.grouped(g, ["language"]))[:3]
        _text(s, 0.5, 4.75, 7.3, 2.5, ["• " + b for b in bullets], size=12, color=GRAY)
        _stats(s, [(short(sm["impressions"]), "Impressions"), (short(sm["spend"], "$"), "Investment"), (kv, kl), (cv, cl)])

    # 5. pacing
    p = ctx["pace"]
    s = prs.slides.add_slide(blank)
    _title(s, f"Pacing vs. Plan (as of {ctx['as_of']:%B %-d, %Y})")
    cnt = p["status"].value_counts()
    _stats(s, [(str(int(cnt.get("On pace", 0))), "On pace"), (str(int(cnt.get("Under-pacing", 0))), "Under-pacing"),
               (str(int(cnt.get("Over-pacing", 0))), "Over-pacing"), (str(int(cnt.get("Not delivering", 0))), "Not delivering")])
    off = p[p["status"] != "On pace"].sort_values("pace_index").head(8)
    _table(s, ["Vendor", "Placement", "% Delivered", "% Flight", "Status"],
           [[r.vendor, (r.placement[:44] + "…") if len(r.placement) > 45 else r.placement, pct(r.delivered_pct, 0), pct(r.flight_elapsed_pct, 0), r.status] for r in off.itertuples()],
           x=0.4, y=1.7, w=7.6, col_w=[1.0, 3.6, 1.0, 0.9, 1.1], size=10)

    # 6. takeaways
    s = prs.slides.add_slide(blank)
    _title(s, "Key Takeaways (auto-drafted)")
    _text(s, 0.6, 1.7, 12, 5, ["• " + t for t in N.overview_takeaways(df, p, ctx["tracker"])], size=16)

    # 7. terms
    s = prs.slides.add_slide(blank)
    _title(s, "Report Terms")
    _text(s, 0.6, 1.7, 12, 5, [
        "• Impressions: number of times an ad was served.",
        "• CTR: clicks / impressions (paid delivery only unless noted as blended).",
        "• VCR: video completions / video impressions.   • LCR: audio completions / listens.",
        "• CPC / CPCV / CPL: paid spend / clicks, completed views or listens.",
        "• Added Value: impressions delivered by the vendor at no additional cost.",
        "• Pace index: % of planned impressions delivered / % of flight elapsed (on pace = 90–110%).",
    ], size=16)
    prs.save(path)
