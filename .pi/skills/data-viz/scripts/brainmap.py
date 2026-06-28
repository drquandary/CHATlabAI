#!/usr/bin/env python3
"""CHATLabAI brain-map renderer.

Renders a glass-brain / statistical map from a NIfTI file using nilearn. If nilearn is not
installed or no --stat-map is supplied, writes a clearly-labeled placeholder PNG instead of
crashing, so the skill degrades gracefully on minimal installs.

Usage:
    python3 brainmap.py --stat-map stat_map.nii.gz --out brain
    python3 brainmap.py --out brain   # placeholder (no nilearn / no NIfTI)
"""
from __future__ import annotations

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from lab_style import apply_lab_style

_HAS_NILEARN = False
try:
    from nilearn import plotting, image
    _HAS_NILEARN = True
except ImportError:
    pass


def _err(msg: str) -> None:
    print(f"[data-viz] ERROR: {msg}", file=sys.stderr)


def _write_placeholder(out: str, reason: str) -> str:
    """Write a labeled placeholder PNG so callers get a visible artifact."""
    apply_lab_style()
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.text(0.5, 0.6, "CHATLabAI — brain map placeholder",
            ha="center", va="center", fontsize=14, fontweight="bold")
    ax.text(0.5, 0.4, reason, ha="center", va="center", fontsize=10, color="#666666",
            wrap=True)
    ax.set_axis_off()
    path = f"{out}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> int:
    p = argparse.ArgumentParser(
        description="Render a glass-brain / statistical brain map from a NIfTI file using nilearn.")
    p.add_argument("--stat-map", help="path to a statistical NIfTI map (.nii / .nii.gz)")
    p.add_argument("--out", required=True, help="output basename (extensions added automatically)")
    p.add_argument("--threshold", type=float, default=None,
                   help="threshold for the stat map (optional)")
    args = p.parse_args()

    apply_lab_style()

    # No stat map given -> placeholder, do not crash.
    if not args.stat_map:
        path = _write_placeholder(
            args.out,
            "No --stat-map supplied. Provide a statistical NIfTI map (.nii.gz) to render a glass-brain.")
        print(f"[data-viz] no --stat-map given; wrote placeholder: {path}")
        return 0

    # Stat map given but nilearn missing -> placeholder, do not crash.
    if not _HAS_NILEARN:
        path = _write_placeholder(
            args.out,
            "nilearn is not installed. Install with: pip install nilearn\n"
            "Then re-run with --stat-map to render a real glass-brain.")
        print(f"[data-viz] nilearn not installed; wrote placeholder: {path}")
        print("[data-viz] install nilearn to render real brain maps: pip install nilearn")
        return 0

    if not os.path.exists(args.stat_map):
        _err(f"stat map not found: {args.stat_map}")
        return 1

    try:
        stat_img = image.load_img(args.stat_map)
    except Exception as e:
        _err(f"could not load NIfTI image: {e}")
        return 1

    written = []
    for ext in ("png", "svg", "pdf"):
        path = f"{args.out}.{ext}"
        display = plotting.plot_glass_brain(
            stat_img,
            threshold=args.threshold if args.threshold is not None else "auto",
            colorbar=True,
            plot_abs=False,
            title=os.path.basename(args.stat_map),
        )
        display.savefig(path)
        display.close()
        written.append(path)

    print("[data-viz] wrote:")
    for w in written:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
