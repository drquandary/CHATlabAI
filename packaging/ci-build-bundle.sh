#!/usr/bin/env bash
# ci-build-bundle.sh — build a prebuilt conda-pack env bundle in CI (or locally
# from scratch), for whatever platform this runner is. Unlike make-env-bundle.sh
# (which packs an already-installed ~/.chatlab env), this CREATES a fresh env
# from environment.yml, installs pi + docx into it, and packs it — so a Linux /
# Windows / Intel-Mac runner can produce that platform's bundle with no local
# CHATLabAI install.
#
# Runs under bash on macOS, Linux, AND Windows (git-bash on the GH runner).
# Requires: micromamba on PATH (the workflow installs it), curl, tar, npm/node
# come from the env.
#
# Output: dist/chatlab-env-<subdir>.tar.gz (+ .sha256) under $OUT_DIR.
#
# Usage: MAMBA_EXE=micromamba bash packaging/ci-build-bundle.sh [--out DIR]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_YML="$SCRIPT_DIR/environment.yml"
OUT_DIR="$SCRIPT_DIR/dist"
case "${1:-}" in --out) OUT_DIR="${2:?}";; esac

MAMBA="${MAMBA_EXE:-micromamba}"
BUILD_ROOT="${BUILD_ROOT:-$SCRIPT_DIR/.ci-build}"
ENV_PREFIX="$BUILD_ROOT/env"

say() { printf '[ci-build] %s\n' "$*"; }
die() { printf '[ci-build] ERROR: %s\n' "$*" >&2; exit 1; }
mm()  { "$MAMBA" --root-prefix "$BUILD_ROOT/mm" "$@"; }

# --- platform → conda subdir + docx asset + sha tool ------------------------
case "$(uname -s)" in
  Darwin) case "$(uname -m)" in
            arm64) SUBDIR=osx-arm64;  DOCX_ASSET=docx-darwin-arm64 ;;
            *)     SUBDIR=osx-64;     DOCX_ASSET=docx-darwin-x64 ;;
          esac ;;
  Linux)  case "$(uname -m)" in
            aarch64) SUBDIR=linux-aarch64; DOCX_ASSET=docx-linux-arm64 ;;
            *)       SUBDIR=linux-64;      DOCX_ASSET=docx-linux-x64 ;;
          esac ;;
  MINGW*|MSYS*|CYGWIN*) SUBDIR=win-64; DOCX_ASSET=docx-windows-x64.exe ;;
  *) die "Unsupported runner: $(uname -s) $(uname -m)" ;;
esac
say "Building bundle for $SUBDIR"

# sha256 helper (shasum on mac, sha256sum on linux/win-git-bash)
sha256() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1"; else sha256sum "$1"; fi; }

# --- 1. create the env ------------------------------------------------------
say "Creating env from environment.yml…"
mm create -y -p "$ENV_PREFIX" -f "$ENV_YML" || die "env solve failed"

# On Windows the env's bin dir is the prefix root + Scripts; elsewhere it's bin/.
if [[ "$SUBDIR" == win-64 ]]; then ENV_BIN="$ENV_PREFIX"; else ENV_BIN="$ENV_PREFIX/bin"; fi

# --- 2. pi into the env (explicit prefix) -----------------------------------
say "Installing pi into the env…"
mm run -p "$ENV_PREFIX" npm install -g --prefix "$ENV_PREFIX" @earendil-works/pi-coding-agent \
  || die "pi npm install failed"

# --- 3. docx-cli binary into the env ----------------------------------------
say "Installing docx-cli into the env…"
tag="$(curl -fsSL https://api.github.com/repos/kklimuk/docx-cli/releases/latest | sed -n 's/.*"tag_name"[^"]*"\([^"]*\)".*/\1/p' | head -1)"
[[ -n "$tag" ]] || die "could not resolve docx-cli release tag"
base="https://github.com/kklimuk/docx-cli/releases/download/$tag"
if [[ "$SUBDIR" == win-64 ]]; then docx_out="$ENV_BIN/docx.exe"; else docx_out="$ENV_BIN/docx"; fi
curl -fsSL "$base/$DOCX_ASSET" -o "$docx_out"
curl -fsSL "$base/SHA256SUMS" -o "$BUILD_ROOT/docx.sums"
exp="$(grep "$DOCX_ASSET" "$BUILD_ROOT/docx.sums" | awk '{print $1}' | head -1)"
act="$(sha256 "$docx_out" | awk '{print $1}')"
[[ "$exp" == "$act" ]] || die "docx checksum mismatch"
chmod +x "$docx_out" 2>/dev/null || true
# macOS released binaries carry an invalid ad-hoc signature → re-sign so they run.
[[ "$SUBDIR" == osx-* ]] && codesign -s - --force "$docx_out" 2>/dev/null || true

# --- 4. conda-pack ----------------------------------------------------------
say "Installing conda-pack + packing…"
mm run -p "$ENV_PREFIX" pip install -q conda-pack || die "conda-pack install failed"
mkdir -p "$OUT_DIR"
out="$OUT_DIR/chatlab-env-$SUBDIR.tar.gz"
mm run -p "$ENV_PREFIX" conda-pack -p "$ENV_PREFIX" -o "$out" \
  --format tar.gz --n-threads -1 --ignore-missing-files --force || die "conda-pack failed"

( cd "$OUT_DIR" && sha256 "chatlab-env-$SUBDIR.tar.gz" > "chatlab-env-$SUBDIR.tar.gz.sha256" )
say "Built $out ($(du -h "$out" | awk '{print $1}'))"
say "SHA256: $(awk '{print $1}' "$out.sha256")"
