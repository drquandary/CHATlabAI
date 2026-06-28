#!/usr/bin/env bash
# CHATLabAI — one-command dependency installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/drquandary/CHATlabAI/main/install.sh | bash
#   # or, after cloning:
#   ./install.sh
#
# Portable: detects macOS/Linux, Python 3, R, pandoc. Installs the Python stat stack
# into a project-local venv (no system pollution), R packages into a user library,
# and bundles the launcher. Re-runnable / idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

PY_BIN="${PYTHON:-python3}"
R_BIN="${RSCRIPT:-Rscript}"
VENV_DIR=".venv"

log()  { printf '\033[1;34m[chatlab]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[chatlab]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[chatlab]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[chatlab]\033[0m %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- Python
log "Checking for Python 3..."
if ! have "$PY_BIN"; then
  warn "python3 not found. Installing via system package manager."
  if have brew; then
    brew install python3
  elif have apt-get; then
    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  elif have dnf; then
    sudo dnf install -y python3 python3-devel
  elif have yum; then
    sudo yum install -y python3
  else
    fail "Could not find a package manager to install python3. Please install Python 3.8+ manually."
  fi
fi
ok "Python: $($PY_BIN --version)"

# Project-local venv (keeps deps out of the system).
log "Creating project venv ($VENV_DIR)..."
"$PY_BIN" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip --quiet

log "Installing Python dependencies..."
python -m pip install --quiet -- \
  python-docx lxml pandas pingouin statsmodels nilearn matplotlib seaborn \
  icalendar requests pybtex
ok "Python stat stack installed."

# ---------------------------------------------------------------- pandoc
log "Checking for pandoc..."
if ! have pandoc; then
  warn "pandoc not found. Installing..."
  if have brew; then
    brew install pandoc
  elif have apt-get; then
    sudo apt-get install -y pandoc
  elif have dnf; then
    sudo dnf install -y pandoc
  else
    warn "Could not auto-install pandoc. The journal-format skill needs it: https://pandoc.org/installing.html"
  fi
else
  ok "pandoc: $(pandoc --version | head -1)"
fi

# ---------------------------------------------------------------- R
log "Checking for R..."
if ! have "$R_BIN"; then
  warn "R not found. The power-analysis and basic-analysis R scripts need it."
  if have brew; then
    brew install r
  elif have apt-get; then
    sudo apt-get install -y r-base
  elif have dnf; then
    sudo dnf install -y R
  else
    warn "Could not auto-install R. Skipping R packages (Python fallbacks still work for analytic cases)."
  fi
fi

if have "$R_BIN"; then
  ok "Rscript: $(Rscript --version 2>&1 | head -1)"
  log "Installing R packages (pwr, simr, lme4, afex, ggplot2) into a user library..."
  "$R_BIN" -e '
    lib <- Sys.getenv("R_LIBS_USER")
    dir.create(lib, recursive = TRUE, showWarnings = FALSE)
    .libPaths(c(lib, .libPaths()))
    pkgs <- c("pwr","simr","lme4","afex","ggplot2")
    for (p in pkgs) {
      if (!requireNamespace(p, quietly = TRUE)) {
        try(install.packages(p, repos = "https://cloud.r-project.org", quiet = TRUE))
      }
      cat(sprintf("  %s: %s\n", p,
        if (requireNamespace(p, quietly = TRUE)) "installed" else "MISSING (install manually)"))
    }
  ' || warn "Some R packages failed to install. R-based power analysis may be limited."
else
  warn "R not installed; R-based scripts (mixed models, simr) unavailable. Python analytic path still works."
fi

# ---------------------------------------------------------------- launcher
chmod +x bin/chatlab
ok "Launcher ready: ./bin/chatlab"

cat <<'BANNER'

  CHATLabAI dependencies installed.

  Next steps:
    1. Make sure pi is installed:       https://pi.dev  (npm i -g @earendil-works/pi-coding-agent)
    2. Configure the parcc provider once (see README.md).
    3. Launch:                           ./bin/chatlab

  To update dependencies later, re-run: ./install.sh

BANNER
