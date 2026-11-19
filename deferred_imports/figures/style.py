"""Shared look for all paper figures (IEEE column width, serif font, 300 dpi)."""

from __future__ import annotations

from pathlib import Path

COLUMN = 3.4          # inches, one IEEE column


def plt():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot
    pyplot.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
        "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "pdf.fonttype": 42,
    })
    return pyplot


def save(fig, out: Path) -> None:
    from matplotlib import pyplot
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", pad_inches=0.02, dpi=300)
    pyplot.close(fig)
    print(f"wrote {out}")
