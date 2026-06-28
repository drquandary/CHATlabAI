---
name: data-viz
description: Publication-quality figures with a consistent lab style and brain maps. Plot, visualize, make a figure, brain map, raincloud, violin, bar plot, scatter plot, correlation matrix, publication figure, ggplot.
---

# data-viz

Publication-quality figures for Chatterjee Lab manuscripts, with a consistent visual style
across Python (matplotlib/seaborn) and R (ggplot2), plus statistical brain maps via nilearn.

## When to use

- "plot / visualize / make a figure" for a paper
- bar+points, violin/raincloud, scatter+fit, box, correlation matrix
- "brain map" / glass-brain from a statistical NIfTI
- any figure that should match the lab's publication style

## Usage

All scripts run headless (Agg backend) and export PNG + SVG + PDF.

### General figures

```bash
# violin / raincloud
python3 scripts/plot.py --kind violin --data data.csv --x group --y score --out figure

# bar with individual points
python3 scripts/plot.py --kind bar --data data.csv --x group --y score --out figure

# scatter with linear fit
python3 scripts/plot.py --kind scatter --data data.csv --x age --y score --out figure

# correlation matrix heatmap
python3 scripts/plot.py --kind corr --data data.csv --out figure

# box plot
python3 scripts/plot.py --kind box --data data.csv --x group --y score --out figure
```

Each call writes `<out>.png`, `<out>.svg`, and `<out>.pdf` using the shared lab style.

### Brain maps

```bash
# glass-brain from a statistical NIfTI map
python3 scripts/brainmap.py --stat-map stat_map.nii.gz --out brain

# render a placeholder (no nilearn / no NIfTI installed)
python3 scripts/brainmap.py --out brain
```

Writes `<out>.png` (and `.svg`/`.pdf` when nilearn is available). If `nilearn` is not
installed or no `--stat-map` is given, it prints a clear message and writes a labeled
placeholder PNG instead of crashing.

### R (ggplot2) path

```bash
Rscript scripts/lab_style.R   # theme demo / renders sample
```

Import `scripts/lab_style.R` (`source("scripts/lab_style.R")`) to apply `theme_lab()` to
ggplot2 figures, mirroring the Python style.

## Lab style

Defined in `scripts/lab_style.py` (`apply_lab_style()`) and mirrored in `scripts/lab_style.R`
(`theme_lab()`). The style fixes fonts, a colorblind-safe palette, figure size, and DPI so every
figure is consistent and journal-ready. Import it rather than re-deriving settings.

## Dependencies

- Python: `matplotlib`, `pandas`, `numpy`, `seaborn` (optional — falls back to matplotlib),
  `nilearn` (optional — only for `brainmap.py`).
- R: `ggplot2`.

Install with the workspace `install.sh` or `pip install matplotlib pandas seaborn nilearn`.

## Safety

Read-only except for writing the requested output files. No network. Never modifies input data.
