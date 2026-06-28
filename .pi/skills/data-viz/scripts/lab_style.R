#!/usr/bin/env Rscript
# CHATLabAI lab style for ggplot2 figures.
# Mirrors scripts/lab_style.py: palette, fonts, sizing, theme.
#
# Usage:
#   source("scripts/lab_style.R")
#   ggplot(data, aes(x, y)) + geom_point() + theme_lab()
#
# palette_lab() returns the lab color vector; theme_lab() returns a ggplot2 theme.

# ---- Lab palette (Okabe-Ito inspired, colorblind-safe) ----------------------
palette_lab <- function() {
  c("#0072B2", "#D55E00", "#009E73", "#CC79A7",
    "#F0E442", "#56B4E9", "#E69F00", "#999999")
}

# ---- Lab theme --------------------------------------------------------------
# A clean, publication-ready theme matching the Python matplotlib style.
theme_lab <- function(base_size = 11, base_family = "sans") {
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    stop("[data-viz] ggplot2 is required. Install with: install.packages('ggplot2')")
  }
  ggplot2::theme_minimal(base_size = base_size, base_family = base_family) +
    ggplot2::theme(
      plot.title = ggplot2::element_text(size = base_size + 1, face = "bold", hjust = 0),
      axis.title = ggplot2::element_text(size = base_size),
      axis.text  = ggplot2::element_text(size = base_size - 1, color = "#333333"),
      axis.line  = ggplot2::element_line(color = "#333333", linewidth = 0.6),
      panel.grid.major = ggplot2::element_line(color = "#DDDDDD", linewidth = 0.4),
      panel.grid.minor = ggplot2::element_blank(),
      panel.background = ggplot2::element_rect(fill = "white", color = NA),
      plot.background  = ggplot2::element_rect(fill = "white", color = NA),
      legend.position  = "bottom",
      legend.title     = ggplot2::element_blank(),
      legend.background = ggplot2::element_blank()
    )
}

# ---- Default export helper --------------------------------------------------
# Save a ggplot to PNG + SVG + PDF at publication DPI.
save_lab <- function(plot, basename, width = 6, height = 4, dpi = 300) {
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    stop("[data-viz] ggplot2 is required.")
  }
  for (ext in c("png", "svg", "pdf")) {
    path <- paste0(basename, ".", ext)
    ggplot2::ggsave(path, plot = plot, width = width, height = height, dpi = dpi,
                    device = if (ext == "svg") ggplot2::svglite::svglite else NULL)
  }
}

# ---- Demo (run this script standalone to sanity-check the style) -----------
if (sys.nframe() == 0L) {
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    cat("[data-viz] ggplot2 not installed; install with: install.packages('ggplot2')\n")
    quit(status = 0)
  }
  library(ggplot2)
  df <- data.frame(
    group = rep(c("A", "B", "C"), each = 10),
    score = c(rnorm(10, 5, 1), rnorm(10, 7, 1), rnorm(10, 6, 1.2))
  )
  p <- ggplot(df, aes(group, score, fill = group)) +
    geom_violin() +
    geom_jitter(width = 0.1, color = "#333333", alpha = 0.5) +
    scale_fill_manual(values = palette_lab()) +
    labs(title = "CHATLabAI lab style (R)") +
    theme_lab()
  cat("[data-viz] lab_style.R loaded. theme_lab() and palette_lab() available.\n")
  invisible(p)
}
