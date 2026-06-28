#!/usr/bin/env python3
"""CHATLabAI lab style for matplotlib figures.

Defines a consistent visual style (palette, fonts, sizing, DPI) so every figure produced by
the data-viz skill matches. Importable by plot.py and brainmap.py:

    from lab_style import apply_lab_style, LAB_STYLE
    apply_lab_style()
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # headless; must be set before pyplot import
import matplotlib as mpl
import matplotlib.font_manager as fm

__all__ = ["LAB_STYLE", "apply_lab_style", "LAB_PALETTE"]

# Colorblind-safe palette (Okabe-Ito inspired) tuned for a neuroaesthetics lab.
LAB_PALETTE = [
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#009E73",  # bluish green
    "#CC79A7",  # reddish purple
    "#F0E442",  # yellow
    "#56B4E9",  # sky blue
    "#E69F00",  # orange
    "#999999",  # grey
]

LAB_STYLE = {
    "figure.figsize": (6.0, 4.0),
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "axes.edgecolor": "#333333",
    "axes.linewidth": 0.8,
    "axes.grid": True,
    "grid.color": "#DDDDDD",
    "grid.linewidth": 0.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.frameon": False,
    "legend.fontsize": 10,
}


def apply_lab_style() -> dict:
    """Apply the CHATLabAI matplotlib style and return the style dict.

    Safe to call multiple times. Also registers a color cycle from LAB_PALETTE.
    """
    mpl.rcParams.update(LAB_STYLE)
    mpl.rcParams["axes.prop_cycle"] = mpl.cycler(color=LAB_PALETTE)
    return LAB_STYLE


if __name__ == "__main__":
    apply_lab_style()
    print("CHATLabAI lab style applied.")
    print("Palette:", ", ".join(LAB_PALETTE))
