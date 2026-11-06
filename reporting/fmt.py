import math


def _bad(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def money(v, d=2):
    return "-" if _bad(v) else f"${v:,.{d}f}"


def num(v):
    return "-" if _bad(v) else f"{v:,.0f}"


def pct(v, d=2):
    return "-" if _bad(v) else f"{v * 100:.{d}f}%"


def short(v, prefix=""):
    """39M / 356K / 1.25M style big numbers for the deck."""
    if _bad(v):
        return "-"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            x = v / div
            s = f"{x:.2f}".rstrip("0").rstrip(".") if x < 10 else f"{x:.1f}".rstrip("0").rstrip(".") if x < 100 else f"{x:.0f}"
            return f"{prefix}{s}{suf}"
    return f"{prefix}{v:,.0f}"
