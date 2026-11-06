"""Small line charts in the Data Studio style (SVG for the PDF, PNG for the deck)."""
from __future__ import annotations

import io
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

BLUE, YELLOW, PURPLE, GRAY, GREEN = "#4285F4", "#F4B400", "#AB47BC", "#616161", "#0F9D58"
plt.rcParams.update({"font.family": ["Inter", "DejaVu Sans"], "font.size": 8, "svg.fonttype": "path"})


def _k(v, _=None):
    for d, s in ((1e6, "M"), (1e3, "K")):
        if abs(v) >= d:
            return f"{v / d:.1f}".rstrip("0").rstrip(".") + s
    return f"{v:,.0f}" if abs(v) >= 1 or v == 0 else f"{v:.2f}"


FORMATS = {
    "k": _k,
    "money": lambda v, _=None: "$" + _k(v),
    "money2": lambda v, _=None: f"${v:,.2f}",
    "pct": lambda v, _=None: f"{v * 100:.2f}%" if abs(v) < 0.1 else f"{v * 100:.1f}%",
}


def line_chart(dates, values, title, color, fmt="k", target=None, size=(4.6, 1.45), as_png=False):
    fig, ax = plt.subplots(figsize=size, dpi=200 if as_png else 100)
    xs = list(range(len(dates)))
    vals = [None if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in values]
    ax.plot(xs, [v if v is not None else float("nan") for v in vals], color=color, marker="o", markersize=4,
            linewidth=2, label=title)
    f = FORMATS[fmt]
    for x, v in zip(xs, vals):
        if v is not None:
            ax.annotate(f(v), (x, v), textcoords="offset points", xytext=(0, 6), ha="center",
                        fontsize=7, color=color, fontweight="bold")
    top = max([v for v in vals if v is not None] + ([target] if target else []) + [0])
    if target is not None and not math.isnan(target):
        ax.axhline(target, color="#555", linestyle=(0, (5, 3)), linewidth=1)
        ax.text(-0.45, target, f" KPI Target ({f(target)}) ", fontsize=6.5, color="white", va="bottom",
                bbox=dict(boxstyle="square,pad=0.15", fc="#9e9e9e", ec="none"))
    ax.set_ylim(0, top * 1.45 if top else 1)
    ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.set_xlim(-0.5, len(xs) - 0.5)
    ax.set_xticks(xs)
    ax.set_xticklabels([d.strftime("%b %-d, %Y") for d in dates], fontsize=7, color="#444")
    ax.yaxis.set_major_formatter(FuncFormatter(f))
    ax.tick_params(axis="y", labelsize=7, colors="#444", length=0)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="#e6e6e6", linewidth=0.8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#666")
    ax.legend(loc="upper left", frameon=False, fontsize=7, handlelength=1.5, borderaxespad=0)
    fig.tight_layout(pad=0.4)
    buf = io.BytesIO() if as_png else io.StringIO()
    fig.savefig(buf, format="png" if as_png else "svg", transparent=not as_png, facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def multi_line_chart(dates, series, fmt="k", size=(4.6, 1.45)):
    """series: list of (label, values aligned to dates, color). Missing weeks are gaps."""
    fig, ax = plt.subplots(figsize=size, dpi=100)
    xs = list(range(len(dates)))
    f = FORMATS[fmt]
    top = 0
    for label, vals, color in series:
        ys = [float("nan") if v is None or (isinstance(v, float) and math.isnan(v)) else v for v in vals]
        ax.plot(xs, ys, color=color, marker="o", markersize=4, linewidth=2, label=label)
        for x, v in zip(xs, ys):
            if not math.isnan(v):
                top = max(top, v)
                ax.annotate(f(v), (x, v), textcoords="offset points", xytext=(0, 6), ha="center",
                            fontsize=7, color=color, fontweight="bold")
    ax.set_ylim(0, top * 1.45 if top else 1)
    ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.set_xlim(-0.5, len(xs) - 0.5)
    ax.set_xticks(xs)
    ax.set_xticklabels([d.strftime("%b %-d, %Y") for d in dates], fontsize=7, color="#444")
    ax.yaxis.set_major_formatter(FuncFormatter(f))
    ax.tick_params(axis="y", labelsize=7, colors="#444", length=0)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="#e6e6e6", linewidth=0.8)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#666")
    ax.legend(loc="upper right", frameon=False, fontsize=7, ncol=len(series), handlelength=1.5, borderaxespad=0)
    fig.tight_layout(pad=0.4)
    buf = io.StringIO()
    fig.savefig(buf, format="svg", transparent=True)
    plt.close(fig)
    return buf.getvalue()


def bar_chart(labels, values, title, color=BLUE, fmt="money", size=(7.4, 4.6)):
    """Horizontal bars, largest on top (PNG for the deck)."""
    fig, ax = plt.subplots(figsize=size, dpi=200)
    pairs = sorted(zip(labels, values), key=lambda p: p[1])
    ys = range(len(pairs))
    ax.barh(list(ys), [v for _, v in pairs], color=color, height=0.6)
    f = FORMATS[fmt]
    for y, (_, v) in zip(ys, pairs):
        ax.text(v, y, "  " + f(v), va="center", fontsize=10, color="#333", fontweight="bold")
    ax.set_yticks(list(ys))
    ax.set_yticklabels([l for l, _ in pairs], fontsize=10, color="#333")
    ax.set_xlim(0, max(values) * 1.25)
    ax.xaxis.set_visible(False)
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.set_title(title, fontsize=12, color="#444", loc="left", fontweight="bold")
    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()
