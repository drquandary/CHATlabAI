#!/usr/bin/env bash
# get-chatlab.sh — standalone CHATLabAI installer (macOS/Linux).
#
# The ONLY file a new user needs: it downloads the CHATLabAI repository itself
# (git if available, otherwise a GitHub tarball — no git required), then hands
# off to packaging/chatlab-bootstrap.sh, which installs everything else
# (micromamba env, R/Python stack, pi, docx-cli, callosum) and launches.
#
# Usage (either):
#   curl -fsSL https://raw.githubusercontent.com/drquandary/CHATlabAI/main/packaging/get-chatlab.sh | bash
#   bash get-chatlab.sh            # if handed the file directly
#
# Environment:
#   CHATLAB_REPO   Where to put the repo (default: $HOME/CHATLabAI).
#   CHATLAB_HOME   Passed through to the bootstrap (default: $HOME/.chatlab).
set -euo pipefail

# Lab key, stamped by make-lab-installer.sh into LAB-DISTRIBUTED copies only.
# MUST stay EMPTY in the repository — this file is public on GitHub, and a key
# committed here is a key published to the internet.
EMBEDDED_PARCC_API_KEY=""

REPO_SLUG="drquandary/CHATlabAI"
BRANCH="main"
DEST="${CHATLAB_REPO:-$HOME/CHATLabAI}"
TARBALL_URL="https://github.com/${REPO_SLUG}/archive/refs/heads/${BRANCH}.tar.gz"
GIT_URL="https://github.com/${REPO_SLUG}.git"

say()  { printf '[chatlab] %s\n' "$*"; }
die()  { printf '[chatlab] ERROR: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Minimal branded splash so the very first thing on a double-click is CHATLabAI,
# not a bare download. (The full boot screen lives in the repo we're about to
# fetch; this is a self-contained teaser that needs no downloaded helper.)
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  printf '\033[2J\033[H\n'
  printf '   \033[38;5;245m══════════════════════════════════════════════════\033[0m\n'
  printf '    \033[1m\033[38;5;39mCHATLabAI\033[0m  \033[38;5;245m·  Penn Center for Neuroaesthetics\033[0m\n'
  printf '   \033[38;5;245m══════════════════════════════════════════════════\033[0m\n\n'
  printf '    \033[38;5;39m→ Getting CHATLabAI…\033[0m\n\n'
fi

fetch_tarball() {
  # Download + unpack the branch tarball into $DEST (no git needed).
  have curl || die "curl is required. Please install curl and re-run."
  local tmp
  tmp="$(mktemp -d)"
  say "Downloading CHATLabAI (${REPO_SLUG}@${BRANCH})…"
  curl -fsSL "$TARBALL_URL" | tar -xz -C "$tmp" \
    || { rm -rf "$tmp"; die "Download failed. Are you online? ($TARBALL_URL)"; }
  # The tarball unpacks to a single <name>-<branch> directory.
  local unpacked
  unpacked="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
  [[ -n "$unpacked" && -f "$unpacked/packaging/chatlab-bootstrap.sh" ]] \
    || { rm -rf "$tmp"; die "Unexpected archive layout — packaging/chatlab-bootstrap.sh not found."; }
  mkdir -p "$(dirname "$DEST")"
  if [[ -d "$DEST" ]]; then
    # Refresh in place: replace tracked content, keep user files (projects/, data/).
    say "Refreshing existing copy at ${DEST}…"
    cp -R "$unpacked/." "$DEST/"
  else
    mv "$unpacked" "$DEST"
  fi
  rm -rf "$tmp"
}

# ---------------------------------------------------------------- get the repo
if [[ -d "$DEST/.git" ]] && have git; then
  say "Updating existing CHATLabAI checkout at ${DEST}…"
  git -C "$DEST" pull --ff-only || say "Note: could not fast-forward (local changes?) — continuing with what's there."
elif [[ -f "$DEST/packaging/chatlab-bootstrap.sh" ]]; then
  fetch_tarball   # refresh a previous tarball install
elif have git; then
  say "Cloning CHATLabAI to ${DEST}…"
  git clone --depth 1 --branch "$BRANCH" "$GIT_URL" "$DEST" || fetch_tarball
else
  fetch_tarball
fi

[[ -f "$DEST/packaging/chatlab-bootstrap.sh" ]] \
  || die "Install failed: $DEST/packaging/chatlab-bootstrap.sh not found."

# ---------------------------------------------------------------- hand off
# An embedded lab key means the user is never prompted for one.
if [[ -n "$EMBEDDED_PARCC_API_KEY" && -z "${PARCC_API_KEY:-}" ]]; then
  export PARCC_API_KEY="$EMBEDDED_PARCC_API_KEY"
fi

# Test hook: fetch the repo but skip the bootstrap (used by CI/self-tests).
if [[ -n "${CHATLAB_FETCH_ONLY:-}" ]]; then
  say "CHATLAB_FETCH_ONLY set — repository fetched to $DEST, skipping bootstrap."
  exit 0
fi

say "Repository ready at $DEST — starting the CHATLabAI bootstrap…"
exec bash "$DEST/packaging/chatlab-bootstrap.sh" "$@"
