#!/usr/bin/env bash
# make-env-bundle.sh — build a relocatable prebuilt bundle of the chatlab conda
# env for THIS platform, so lab members skip the ~1.5 GB conda solve entirely.
#
# Uses conda-pack: the whole env prefix (conda packages + the npm-installed pi +
# the docx-cli binary) is archived with a relocatable prefix; `conda-unpack` on
# the target fixes paths to wherever the user's ~/.chatlab lands. Output goes to
# packaging/dist/ (gitignored). Upload the artifact to a GitHub Release; the
# installer downloads + verifies + unpacks it (see ensure_env in the launchers).
#
# Prereqs: the chatlab env must already exist (run the bootstrap once), with pi
# and docx installed into it, and conda-pack available in the env.
#
# Usage:
#   bash packaging/make-env-bundle.sh                # build for this platform
#   bash packaging/make-env-bundle.sh --out DIR      # custom output dir
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
OUT_DIR="$SCRIPT_DIR/dist"
case "${1:-}" in
  --out) OUT_DIR="${2:?--out needs a dir}" ;;
  "")    : ;;
  *)     echo "Unknown arg: $1 (use --out DIR)" >&2; exit 2 ;;
esac

CHATLAB_HOME="${CHATLAB_HOME:-$HOME/.chatlab}"
MM_ROOT_PREFIX="$CHATLAB_HOME/mm"
MM_BIN="$CHATLAB_HOME/bin/micromamba"
ENV_NAME="chatlab"
ENV_PREFIX="$MM_ROOT_PREFIX/envs/$ENV_NAME"

say() { printf '[make-env-bundle] %s\n' "$*"; }
die() { printf '[make-env-bundle] ERROR: %s\n' "$*" >&2; exit 1; }
mm()  { "$MM_BIN" --root-prefix "$MM_ROOT_PREFIX" "$@"; }

detect_subdir() {
  local os arch
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os:$arch" in
    Darwin:arm64)   echo "osx-arm64" ;;
    Darwin:x86_64)  echo "osx-64" ;;
    Linux:x86_64)   echo "linux-64" ;;
    Linux:aarch64)  echo "linux-aarch64" ;;
    *) die "Unsupported platform: $os $arch" ;;
  esac
}

[[ -d "$ENV_PREFIX/conda-meta" ]] || die "chatlab env not found at $ENV_PREFIX — run the bootstrap first."
mm run -n "$ENV_NAME" python -c 'import conda_pack' 2>/dev/null \
  || { say "Installing conda-pack into the env…"; mm run -n "$ENV_NAME" pip install -q conda-pack || die "conda-pack install failed."; }

subdir="$(detect_subdir)"
out="$OUT_DIR/chatlab-env-$subdir.tar.gz"
mkdir -p "$OUT_DIR"

say "Packing $ENV_PREFIX → $out (this takes a few minutes)…"
# --ignore-missing-files: the docx re-sign / npm installs touch files conda's
# metadata doesn't track exactly; don't fail on that.
# --n-threads -1: use all cores. --force: overwrite an existing bundle.
mm run -n "$ENV_NAME" conda-pack -p "$ENV_PREFIX" -o "$out" \
  --format tar.gz --n-threads -1 --ignore-missing-files --force \
  || die "conda-pack failed."

# Checksum manifest (same shape the installer verifies).
( cd "$OUT_DIR" && shasum -a 256 "chatlab-env-$subdir.tar.gz" > "chatlab-env-$subdir.tar.gz.sha256" )

sz="$(du -h "$out" | awk '{print $1}')"
say "Built $out ($sz)"
say "SHA256: $(awk '{print $1}' "$out.sha256")"
say ""
say "Publish it to a GitHub Release, e.g.:"
say "  gh release create env-bundle-v1 --repo drquandary/CHATlabAI --title 'CHATLabAI env bundles' --notes 'Prebuilt conda envs' || true"
say "  gh release upload env-bundle-v1 --repo drquandary/CHATlabAI --clobber '$out' '$out.sha256'"
