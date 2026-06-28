#!/usr/bin/env python3
"""CHATLabAI publication figure generator.

Produces bar+points, violin/raincloud, scatter+fit, box, and correlation-matrix figures in the
lab style. Exports PNG + SVG + PDF.

Usage:
    python3 plot.py --kind violin --data data.csv --x group --y score --out figure
    python3 plot.py --kind bar --data data.csv --x group --y score --out figure
    python3 plot.py --kind scatter --data data.csv --x age --y score --out figure
    python3 plot.py --kind corr --data data.csv --out figure
    python3 plot.py --kind box --data data.csv --x group --y score --out figure
"""
from __future__ import annotations

import argparse
import os
import sys

# Ensure the sibling lab_style module is importable regardless of cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lab_style import apply_lab_style, LAB_PALETTE

try:
    import seaborn as sns
    _HAS_SNS = True
except ImportError:
    _HAS_SNS = False

KINDS = ("bar", "violin", "scatter", "corr", "box")


def _err(msg: str) -> None:
    print(f"[data-viz] ERROR: {msg}", file=sys.stderr)


def _save(fig: plt.Figure, out: str) -> list[str]:
    """Save figure to PNG, SVG, and PDF. Returns list of written paths."""
    written = []
    for ext in ("png", "svg", "pdf"):
        path = f"{out}.{ext}"
        fig.savefig(path)
        written.append(path)
    plt.close(fig)
    return written


def _check_df(df: pd.DataFrame, cols: list[str]) -> bool:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        _err(f"column(s) not found in data: {', '.join(missing)}")
        _err(f"available columns: {', '.join(df.columns.tolist())}")
        return False
    return True


def plot_bar(df: pd.DataFrame, x: str, y: str, out: str) -> list[str]:
    means = df.groupby(x)[y].agg(["mean", "sem"]).reset_index()
    fig, ax = plt.subplots()
    colors = LAB_PALETTE[: len(means)]
    bars = ax.bar(means[x], means["mean"], yerr=means["sem"],
                  color=colors, edgecolor="#333333", linewidth=0.6, capsize=3)
    # overlay individual points (jittered)
    for i, grp in enumerate(means[x]):
        sub = df[df[x] == grp]
        jit = np.random.default_rng(0).normal(i, 0.05, size=len(sub))
        ax.scatter(jit, sub[y], color="#333333", alpha=0.5, s=14, zorder=3)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_title(f"{y} by {x}")
    return _save(fig, out)


def plot_violin(df: pd.DataFrame, x: str, y: str, out: str) -> list[str]:
    fig, ax = plt.subplots()
    if _HAS_SNS:
        sns.violinplot(data=df, x=x, y=y, hue=x, palette=LAB_PALETTE, legend=False,
                       inner=None, cut=0, ax=ax)
        sns.stripplot(data=df, x=x, y=y, color="#333333", alpha=0.5, size=3, ax=ax)
    else:
        groups = sorted(df[x].unique())
        data = [df[df[x] == g][y].values for g in groups]
        parts = ax.violinplot(data, showmeans=True, showmedians=False)
        for i, body in enumerate(parts["bodies"]):
            body.set_facecolor(LAB_PALETTE[i % len(LAB_PALETTE)])
            body.set_edgecolor("#333333")
            body.set_alpha(0.7)
        # jittered points
        for i, g in enumerate(groups):
            sub = df[df[x] == g]
            jit = np.random.default_rng(0).normal(i + 1, 0.05, size=len(sub))
            ax.scatter(jit, sub[y], color="#333333", alpha=0.5, s=14, zorder=3)
        ax.set_xticks(range(1, len(groups) + 1))
        ax.set_xticklabels(groups)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_title(f"{y} by {x}")
    return _save(fig, out)


def _is_numeric_series(s: pd.Series) -> bool:
    """True if a pandas Series can be treated as numeric."""
    try:
        s.astype(float)
        return True
    except (ValueError, TypeError):
        return False


def plot_scatter(df: pd.DataFrame, x: str, y: str, out: str) -> list[str]:
    fig, ax = plt.subplots()
    # If x is categorical, encode groups as 0..n with labels so we still scatter.
    x_numeric = _is_numeric_series(df[x])
    if x_numeric:
        xs = df[x]
        ax.scatter(xs, df[y], color=LAB_PALETTE[0], alpha=0.7, edgecolor="#333333", linewidth=0.4)
    else:
        cats = sorted(df[x].dropna().unique())
        code_map = {c: i for i, c in enumerate(cats)}
        xs = df[x].map(code_map)
        ax.scatter(xs, df[y], color=LAB_PALETTE[0], alpha=0.7, edgecolor="#333333", linewidth=0.4)
        ax.set_xticks(list(code_map.values()))
        ax.set_xticklabels(list(code_map.keys()))
    # linear fit only when x is numeric
    valid = df[[x, y]].dropna()
    if x_numeric and len(valid) >= 2:
        try:
            coef = np.polyfit(valid[x].astype(float), valid[y].astype(float), 1)
            xs_line = np.linspace(float(valid[x].min()), float(valid[x].max()), 100)
            ax.plot(xs_line, np.polyval(coef, xs_line), color=LAB_PALETTE[1], linewidth=1.5,
                    label=f"linear fit (slope={coef[0]:.3g})")
            ax.legend()
        except Exception:
            pass  # fit is a nicety, not required
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_title(f"{y} vs {x}")
    return _save(fig, out)


def plot_corr(df: pd.DataFrame, out: str) -> list[str]:
    numeric = df.select_dtypes(include="number")
    if numeric.shape[1] < 2:
        _err("need at least 2 numeric columns for a correlation matrix")
        return []
    corr = numeric.corr()
    fig, ax = plt.subplots()
    if _HAS_SNS:
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
                    square=True, linewidths=0.5, ax=ax, cbar_kws={"shrink": 0.8})
    else:
        im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(len(corr.columns)))
        ax.set_yticks(range(len(corr.index)))
        ax.set_xticklabels(corr.columns, rotation=45, ha="right")
        ax.set_yticklabels(corr.index)
        for i in range(len(corr.index)):
            for j in range(len(corr.columns)):
                ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center",
                        fontsize=8, color="#333333")
        fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title("Correlation matrix")
    return _save(fig, out)


def plot_box(df: pd.DataFrame, x: str, y: str, out: str) -> list[str]:
    fig, ax = plt.subplots()
    if _HAS_SNS:
        sns.boxplot(data=df, x=x, y=y, hue=x, palette=LAB_PALETTE, legend=False, ax=ax)
    else:
        groups = sorted(df[x].unique())
        data = [df[df[x] == g][y].values for g in groups]
        bp = ax.boxplot(data, patch_artist=True)
        for i, patch in enumerate(bp["boxes"]):
            patch.set_facecolor(LAB_PALETTE[i % len(LAB_PALETTE)])
            patch.set_edgecolor("#333333")
        ax.set_xticks(range(1, len(groups) + 1))
        ax.set_xticklabels(groups)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_title(f"{y} by {x}")
    return _save(fig, out)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Generate a publication-quality figure in the CHATLabAI lab style. "
                    "Exports PNG + SVG + PDF.")
    p.add_argument("--kind", choices=KINDS, required=True, help="figure type")
    p.add_argument("--data", required=True, help="path to CSV file")
    p.add_argument("--x", help="x-axis column (not used for --kind corr)")
    p.add_argument("--y", help="y-axis column (not used for --kind corr)")
    p.add_argument("--out", required=True, help="output basename (extensions added automatically)")
    args = p.parse_args()

    if not os.path.exists(args.data):
        _err(f"data file not found: {args.data}")
        return 1

    try:
        df = pd.read_csv(args.data)
    except Exception as e:
        _err(f"could not read CSV: {e}")
        return 1

    apply_lab_style()
    written: list[str] = []

    if args.kind == "corr":
        written = plot_corr(df, args.out)
    else:
        if not args.x or not args.y:
            _err(f"--x and --y are required for --kind {args.kind}")
            return 1
        if not _check_df(df, [args.x, args.y]):
            return 1
        if args.kind == "bar":
            written = plot_bar(df, args.x, args.y, args.out)
        elif args.kind == "violin":
            written = plot_violin(df, args.x, args.y, args.out)
        elif args.kind == "scatter":
            written = plot_scatter(df, args.x, args.y, args.out)
        elif args.kind == "box":
            written = plot_box(df, args.x, args.y, args.out)

    if not written:
        return 1
    print("[data-viz] wrote:")
    for w in written:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
