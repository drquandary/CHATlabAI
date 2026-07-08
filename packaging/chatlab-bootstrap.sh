#!/usr/bin/env bash
# chatlab-bootstrap.sh — one-time slim launcher for CHATLabAI (macOS/Linux).
#
# Bootstraps everything CHATLabAI needs from a prebuilt conda-forge environment so
# a first-time user does no manual dependency setup. Nothing pollutes the system:
# micromamba, the conda env, and pi all live under ${CHATLAB_HOME:-$HOME/.chatlab}.
#
# Usage:
#   bash packaging/chatlab-bootstrap.sh            # full bootstrap, then launch pi
#   bash packaging/chatlab-bootstrap.sh --check    # non-destructive self-test, then exit
#   bash packaging/chatlab-bootstrap.sh --dry-run  # print steps it WOULD run, exit 0
#   bash packaging/chatlab-bootstrap.sh --help    # this message
#
# Backend: the UPenn `parcc` LiteLLM proxy (https://litellm.parcc.upenn.edu/v1).
# The PARCC_API_KEY is a per-user secret — read from $PARCC_API_KEY or prompted on
# first run. Never hardcoded.
set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve repo root: parent of the packaging/ dir that holds THIS script,
# following symlinks (same trick bin/chatlab uses).
# ---------------------------------------------------------------------------
_self="${BASH_SOURCE[0]:-$0}"
while [[ -L "$_self" ]]; do
  _dir="$(cd "$(dirname "$_self")" && pwd)"
  _self="$(readlink "$_self")"
  [[ "$_self" != /* ]] && _self="$_dir/$_self"
done
SCRIPT_DIR="$(cd "$(dirname "$_self")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_YML="$REPO_ROOT/packaging/environment.yml"
ENV_NAME="chatlab"

# Shared "PARCC is booting" splash (cosmetic; degrades to no-ops if absent).
if [[ -f "$SCRIPT_DIR/chatlab-bootscreen.sh" ]]; then
  # shellcheck disable=SC1091
  . "$SCRIPT_DIR/chatlab-bootscreen.sh"
fi
have_bootscreen() { command -v chatlab_bootscreen >/dev/null 2>&1; }

# Private install prefix — everything lives here, nothing touches the system.
CHATLAB_HOME="${CHATLAB_HOME:-$HOME/.chatlab}"
MM_ROOT_PREFIX="$CHATLAB_HOME/mm"          # micromamba root prefix
MM_BIN="$CHATLAB_HOME/bin/micromamba"        # the micromamba binary itself
ENV_PREFIX="$MM_ROOT_PREFIX/envs/$ENV_NAME"  # the chatlab env root (bin/, lib/)

# Prebuilt env bundle (conda-pack). When one exists for the user's platform,
# ensure_env downloads + unpacks it (seconds, no solve) instead of solving
# environment.yml from conda-forge (~1.5 GB, minutes). Falls back to the solve
# automatically if there's no bundle for the platform, the download fails, the
# checksum doesn't match, or CHATLAB_NO_BUNDLE=1. Built by make-env-bundle.sh.
#
# Bundles are hosted on Google Drive (per-file share links). Fill the tables
# below once each file is uploaded ("anyone with the link" sharing):
#   bundle_url_for  <subdir> -> the share link (or a direct URL); empty = none
#   bundle_sha_for  <subdir> -> the file's SHA-256 (from make-env-bundle.sh);
#     the checksum is PINNED here so a wrong/corrupt download is rejected.
# CHATLAB_BUNDLE_URL / CHATLAB_BUNDLE_SHA env vars override for the current
# platform (handy for testing a new upload before editing this file).
bundle_url_for() {
  case "$1" in
    osx-arm64)   echo "" ;;   # TODO: paste the Google Drive link for chatlab-env-osx-arm64.tar.gz
    osx-64)      echo "" ;;   # TODO: Intel-Mac bundle link
    linux-64)    echo "" ;;   # TODO: linux-64 bundle link
    linux-aarch64) echo "" ;;
    *)           echo "" ;;
  esac
}
bundle_sha_for() {
  case "$1" in
    osx-arm64)   echo "38505e94b2c75404d06b7968cca0bf49d069ed77f2a96b51b9af5cc6529de522" ;;
    osx-64)      echo "" ;;
    linux-64)    echo "" ;;
    linux-aarch64) echo "" ;;
    win-64)      echo "acb96941c681ec92972fb996c267c36be04b04b27a12dce6a97a866db99cefba" ;;
    *)           echo "" ;;
  esac
}

# ISOLATION: CHATLabAI keeps its OWN pi config dir under $CHATLAB_HOME instead
# of writing the user's real ~/.pi/agent. pi honours $PI_CODING_AGENT_DIR
# (default ~/.pi/agent), so pointing it here means the parcc provider block and
# the callosum MCP registration land in a private dir and never touch a config
# the user (or a colleague) already uses for their own pi work. Overridable so
# --check can redirect it to a temp path.
PI_AGENT_DIR="${CHATLAB_PI_AGENT_DIR:-$CHATLAB_HOME/pi-agent}"

# parcc provider constants are kept inside the python merge (write_pi_config)
# and the dry-run/help text, not as shell vars, to avoid duplication.

# Callosum (local reference manager + MCP server). Lives at ~/callosum per the
# callosum README convention, outside CHATLAB_HOME. Uses the env's Python 3.11
# for both its app venv (.venv) and the MCP server venv (.mcp-venv). The MCP
# server is registered in CHATLabAI's private pi-agent dir so pi can spawn it.
CALLOSUM_HOME="${CALLOSUM_HOME:-$HOME/callosum}"
CALLOSUM_REPO="https://github.com/cliffworkman/callosum.git"
MCP_CONFIG="$PI_AGENT_DIR/mcp.json"

# ---------------------------------------------------------------------------
# Logging helpers (plain, no colour codes in --dry-run so grep matches are clean).
# ---------------------------------------------------------------------------
say()  { printf '[chatlab] %s\n' "$*"; }
note() { printf '[chatlab] %s\n' "$*" >&2; }
warn() { printf '[chatlab] WARN: %s\n' "$*" >&2; }
die()  { printf '[chatlab] ERROR: %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Platform detection -> conda subdir.
# ---------------------------------------------------------------------------
detect_subdir() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os:$arch" in
    Darwin:arm64)   echo "osx-arm64" ;;
    Darwin:x86_64)  echo "osx-64" ;;
    Darwin:aarch64) echo "osx-arm64" ;;
    Linux:x86_64)   echo "linux-64" ;;
    Linux:aarch64)  echo "linux-aarch64" ;;
    *) printf '[chatlab] ERROR: Unsupported platform: %s %s. This launcher supports macOS (arm64/x86_64) and Linux (x86_64/aarch64).\n' "$os" "$arch" >&2; exit 2 ;;
  esac
}

# ---------------------------------------------------------------------------
# ensure_micromamba: download the static micromamba binary to $MM_BIN if missing.
# Idempotent: skip if already present and runnable.
# ---------------------------------------------------------------------------
ensure_micromamba() {
  if [[ -x "$MM_BIN" ]] && "$MM_BIN" --version >/dev/null 2>&1; then
    return 0
  fi
  local subdir url tmp_tar
  subdir="$(detect_subdir)"
  url="https://micro.mamba.pm/api/micromamba/${subdir}/latest"
  say "Downloading micromamba ($subdir)…"
  mkdir -p "$CHATLAB_HOME/bin"
  tmp_tar="$CHATLAB_HOME/micromamba.tar.bz2"
  # Use a curl that follows redirects and fails on HTTP errors.
  if ! command -v curl >/dev/null 2>&1; then
    die "curl is required to download micromamba. Please install curl and re-run."
  fi
  curl -fsSL "$url" -o "$tmp_tar" || die "Failed to download micromamba from $url"
  # Archive contains bin/micromamba; extract just that member.
  tar -xjf "$tmp_tar" -C "$CHATLAB_HOME" bin/micromamba \
    || die "Failed to extract micromamba archive."
  rm -f "$tmp_tar"
  chmod +x "$MM_BIN"
  [[ -x "$MM_BIN" ]] || die "micromamba binary not found at $MM_BIN after extraction."
}

# micromamba wrapper: always uses our root prefix.
mm() {
  "$MM_BIN" --root-prefix "$MM_ROOT_PREFIX" "$@"
}

# ---------------------------------------------------------------------------
# env_exists: 0 if the chatlab env is already created.
# ---------------------------------------------------------------------------
# Detect the env by its prefix directory, NOT by parsing `env list` JSON.
# micromamba env list --json returns env PATHS (e.g. ".../envs/chatlab"), not
# bare names, so matching the quoted name "chatlab" never matches a full path.
# A conda env exists iff <root-prefix>/envs/<name>/conda-meta is a directory —
# deterministic, needs no micromamba call.
env_exists() {
  [[ -d "$MM_ROOT_PREFIX/envs/$ENV_NAME/conda-meta" ]]
}

# ---------------------------------------------------------------------------
# ensure_env: create the chatlab env from environment.yml if missing.
# ---------------------------------------------------------------------------
# gdrive_id: extract a Google Drive file id from any share-link shape, else "".
#   https://drive.google.com/file/d/<ID>/view?usp=sharing
#   https://drive.google.com/open?id=<ID>   |   ...?id=<ID>&...
gdrive_id() {
  case "$1" in
    *drive.google.com*|*drive.usercontent.google.com*) : ;;
    *) echo ""; return ;;
  esac
  printf '%s' "$1" | sed -n \
    -e 's#.*/file/d/\([^/?]*\).*#\1#p' \
    -e 's#.*[?&]id=\([^&]*\).*#\1#p' | head -1
}

# download_bundle URL DEST: fetch a bundle to DEST. Handles Google Drive's
# large-file virus-scan interstitial (a plain curl of a share link returns an
# HTML page, not the file) by hitting the usercontent download endpoint with a
# confirm token; verifies the result is really gzip (magic 1f 8b), not HTML.
download_bundle() {
  local url="$1" dest="$2" id
  id="$(gdrive_id "$url")"
  if [[ -n "$id" ]]; then
    local ep="https://drive.usercontent.google.com/download?id=$id&export=download&confirm=t"
    curl -fsSL -c "$dest.cookie" "$ep" -o "$dest" 2>/dev/null || return 1
    # If Google still returned the interstitial HTML, dig out the confirm token
    # (uuid) from it and retry once.
    if ! is_gzip "$dest"; then
      local tok
      tok="$(sed -n 's/.*name="uuid" value="\([^"]*\)".*/\1/p' "$dest" | head -1)"
      [[ -n "$tok" ]] && curl -fsSL -b "$dest.cookie" \
        "https://drive.usercontent.google.com/download?id=$id&export=download&confirm=t&uuid=$tok" \
        -o "$dest" 2>/dev/null
    fi
    rm -f "$dest.cookie"
  else
    curl -fsSL "$url" -o "$dest" 2>/dev/null || return 1
  fi
  is_gzip "$dest"
}

# is_gzip FILE: 0 iff FILE begins with the gzip magic bytes (1f 8b) — guards
# against saving an HTML error/interstitial page as if it were the tarball.
is_gzip() {
  [[ -s "$1" ]] || return 1
  local magic
  magic="$(od -An -tx1 -N2 "$1" 2>/dev/null | tr -d ' \n')"
  [[ "$magic" == "1f8b" ]]
}

# ensure_env_from_bundle: try to fetch + unpack the prebuilt conda-pack bundle
# for this platform. Returns 0 on success (env ready), 1 if no usable bundle
# (caller then falls back to the solve). Never leaves a half-unpacked env.
ensure_env_from_bundle() {
  [[ "${CHATLAB_NO_BUNDLE:-0}" == "1" ]] && return 1
  have curl || return 1
  local subdir url expected tarball tmp actual
  subdir="$(detect_subdir)"
  url="${CHATLAB_BUNDLE_URL:-$(bundle_url_for "$subdir")}"
  expected="${CHATLAB_BUNDLE_SHA:-$(bundle_sha_for "$subdir")}"
  # No bundle configured for this platform, or no pinned checksum → solve.
  [[ -n "$url" && -n "$expected" ]] || return 1

  say "Downloading prebuilt environment ($subdir) — skips the conda solve…"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/chatlab-env.XXXXXX")"
  tarball="$tmp/env.tar.gz"
  if ! download_bundle "$url" "$tarball"; then
    warn "Prebuilt env download failed (or wasn't a valid archive) — falling back to a fresh solve."
    rm -rf "$tmp"; return 1
  fi

  # Verify against the PINNED checksum — a wrong/corrupt/tampered file is rejected.
  actual="$(shasum -a 256 "$tarball" | awk '{print $1}')"
  if [[ "$expected" != "$actual" ]]; then
    warn "Prebuilt env checksum mismatch (expected $expected) — falling back to a fresh solve."
    rm -rf "$tmp"; return 1
  fi

  # Unpack into the env prefix, then conda-unpack to fix paths to THIS machine.
  mkdir -p "$ENV_PREFIX"
  if ! tar -xzf "$tarball" -C "$ENV_PREFIX"; then
    warn "Prebuilt env failed to unpack — falling back to a fresh solve."
    rm -rf "$tmp" "$ENV_PREFIX"; return 1
  fi
  rm -rf "$tmp"
  # conda-unpack rewrites absolute paths (shebangs, R's hardcoded R_HOME, etc.)
  # to THIS machine's location. Invoke it THROUGH the env's python — the script's
  # own shebang still points at the build machine's python, so `./conda-unpack`
  # alone fails with "env: python: No such file or directory" and R stays broken.
  if [[ -x "$ENV_PREFIX/bin/conda-unpack" && -x "$ENV_PREFIX/bin/python" ]]; then
    "$ENV_PREFIX/bin/python" "$ENV_PREFIX/bin/conda-unpack" 2>/dev/null \
      || { warn "conda-unpack failed on the prebuilt env — re-solving."; rm -rf "$ENV_PREFIX"; return 1; }
  fi
  env_exists || { warn "Unpacked env looks incomplete — re-solving."; rm -rf "$ENV_PREFIX"; return 1; }
  say "Prebuilt environment ready (no solve needed)."
  return 0
}

# ---------------------------------------------------------------------------
# ensure_env: create the chatlab env. Prefer the prebuilt bundle (fast); fall
# back to solving environment.yml from conda-forge.
# ---------------------------------------------------------------------------
ensure_env() {
  if env_exists; then
    say "Conda env '$ENV_NAME' already exists — skipping create."
    return 0
  fi
  ensure_env_from_bundle && return 0
  say "Creating conda env '$ENV_NAME' from environment.yml…"
  mm create -y -n "$ENV_NAME" -f "$ENV_YML" \
    || die "Failed to create conda env. Check your network (conda-forge must be reachable)."
}

# ---------------------------------------------------------------------------
# simr_installed: 0 if simr is importable in the env.
# ---------------------------------------------------------------------------
simr_installed() {
  mm run -n "$ENV_NAME" Rscript \
    -e 'cat(if(requireNamespace("simr", quietly=TRUE)) "yes" else "no")' \
    2>/dev/null | grep -q yes
}

# ---------------------------------------------------------------------------
# ensure_simr: install simr (+ pure-R macOS helpers RLRsim, binom) from CRAN
# if not already installed. Pure R, no compilation.
# ---------------------------------------------------------------------------
ensure_simr() {
  if simr_installed; then
    say "R package 'simr' already installed — skipping."
    return 0
  fi
  say "Installing R package 'simr' (+ macOS helpers) from CRAN…"
  mm run -n "$ENV_NAME" Rscript -e \
    'p<-c("simr"); if(Sys.info()[["sysname"]]=="Darwin") p<-c("RLRsim","binom",p); for(x in p) if(!requireNamespace(x,quietly=TRUE)) install.packages(x, repos="https://cloud.r-project.org")' \
    || die "Failed to install simr from CRAN."
}

# ---------------------------------------------------------------------------
# pi_installed: 0 iff pi is installed IN THE ENV. We test the concrete env path,
# NOT `which pi` — a user's system pi on PATH (e.g. ~/.local/bin/pi) would make
# `which` lie, so ensure_pi would skip and the launch would silently use their
# pi instead of ours. Checking the env's own bin is the isolation guarantee.
# ---------------------------------------------------------------------------
pi_installed() {
  [[ -x "$ENV_PREFIX/bin/pi" ]]
}

# ---------------------------------------------------------------------------
# ensure_pi: install pi INTO the env prefix. We pass `--prefix "$ENV_PREFIX"`
# explicitly so a user's global npm prefix override (a ~/.npmrc pointing
# elsewhere, e.g. ~/.hermes/node) can't divert the binary out of the env — the
# command-line flag wins over npmrc. Result: pi always lands in $ENV_PREFIX/bin.
# ---------------------------------------------------------------------------
ensure_pi() {
  if pi_installed; then
    say "pi already installed in env — skipping."
    return 0
  fi
  say "Installing pi (@earendil-works/pi-coding-agent) into the env…"
  mm run -n "$ENV_NAME" npm install -g --prefix "$ENV_PREFIX" @earendil-works/pi-coding-agent \
    || die "Failed to install pi via npm."
  [[ -x "$ENV_PREFIX/bin/pi" ]] \
    || die "pi did not land in $ENV_PREFIX/bin after install (npm prefix override?)."
}

# ---------------------------------------------------------------------------
# docx_installed: 0 if the `docx` binary (docx-cli) resolves on the env's PATH.
# ---------------------------------------------------------------------------
docx_installed() {
  # Env path only (not `mm run docx` — a user's global docx, e.g. ~/.bun/bin,
  # would shadow it and make us skip the env install).
  [[ -x "$ENV_PREFIX/bin/docx" ]] && "$ENV_PREFIX/bin/docx" --version >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# ensure_docx: install the docx-cli binary (Word-document CLI, github.com/
# kklimuk/docx-cli) into the env's bin. Delegates to the docx-cli skill's own
# bootstrap, which pins the latest release TAG and SHA-256-verifies the binary
# (never pipes a moving script into a shell). PREFIX targets the env bin so
# the binary resolves at launch; PATH is prepended so the bootstrap's own
# reachability check sees it.
# ---------------------------------------------------------------------------
ensure_docx() {
  if docx_installed; then
    say "docx (docx-cli) already installed in env — skipping."
    return 0
  fi
  say "Installing docx-cli (Word-document CLI) into the env…"
  local env_bin="$ENV_PREFIX/bin"
  mkdir -p "$env_bin"
  # The skill bootstrap can exit nonzero on macOS even after a good install:
  # the released darwin binaries carry an invalid ad-hoc signature, and macOS
  # (arm64 especially) SIGKILLs them until re-signed. Don't die yet — repair
  # below, then verify for real.
  PREFIX="$env_bin" PATH="$env_bin:$PATH" \
    sh "$REPO_ROOT/.pi/skills/docx-cli/scripts/bootstrap.sh" || true
  if [[ "$(uname -s)" == "Darwin" && -f "$env_bin/docx" ]] \
      && ! "$env_bin/docx" --version >/dev/null 2>&1; then
    say "Re-signing docx ad hoc (released binary's signature is invalid on macOS)…"
    codesign -s - --force "$env_bin/docx" 2>/dev/null || true
  fi
  "$env_bin/docx" --version >/dev/null 2>&1 \
    || die "Failed to install docx-cli (see github.com/kklimuk/docx-cli)."
}

# ---------------------------------------------------------------------------
# write_pi_config <key>: ensure CHATLabAI's OWN pi config ($PI_AGENT_DIR/
# models.json) has a parcc provider block with the given API key, merged into
# any existing file without clobbering other providers. Writing to the private
# $PI_AGENT_DIR (not the user's ~/.pi) is the isolation guarantee — a colleague
# who already uses pi for other work keeps their config untouched.
# ---------------------------------------------------------------------------
write_pi_config() {
  local key="$1"
  local cfg_dir cfg_file
  cfg_dir="$PI_AGENT_DIR"
  cfg_file="$cfg_dir/models.json"
  mkdir -p "$cfg_dir"

  # python3 from the env (robust merge). Falls back to system python3 if the env
  # somehow isn't available yet (write_pi_config is also called by --check before
  # the env exists; --check uses a temp HOME and must still succeed, so we allow
  # a system python3 fallback).
  local py
  py="mm run -n $ENV_NAME python"
  if ! mm run -n "$ENV_NAME" python -c 'pass' >/dev/null 2>&1; then
    py="python3"
  fi

  $py - "$cfg_file" "$key" <<'PYEOF'
import json, os, sys
cfg_file, key = sys.argv[1], sys.argv[2]
PARCC_BASEURL = "https://litellm.parcc.upenn.edu/v1"
PARCC_API_TYPE = "openai-completions"
MODEL_ID = "zai-org/GLM-5.2-FP8"
MODEL_NAME = "GLM 5.2 FP8"
MODEL_CTX = 1048576

# Load existing if present and well-formed; else start fresh.
data = {}
if os.path.exists(cfg_file):
    try:
        with open(cfg_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}

providers = data.setdefault("providers", {})
parcc = providers.setdefault("parcc", {})
parcc["baseUrl"] = PARCC_BASEURL
parcc["api"] = PARCC_API_TYPE
parcc["apiKey"] = key

# Ensure the GLM 5.2 FP8 model is present in the parcc model list, without
# dropping any other models the user may have added.
models = parcc.setdefault("models", [])
have_glm = any(isinstance(m, dict) and m.get("id") == MODEL_ID for m in models)
if not have_glm:
    models.append({"id": MODEL_ID, "name": MODEL_NAME, "contextWindow": MODEL_CTX})

with open(cfg_file, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
}

# ---------------------------------------------------------------------------
# get_api_key: from $PARCC_API_KEY, else prompt interactively.
# ---------------------------------------------------------------------------
get_api_key() {
  if [[ -n "${PARCC_API_KEY:-}" ]]; then
    printf '%s' "$PARCC_API_KEY"
    return 0
  fi
  printf 'Paste your PARCC API key: ' >&2
  read -r key
  [[ -n "$key" ]] || die "No API key provided. Set PARCC_API_KEY or paste it when prompted."
  printf '%s' "$key"
}

# ---------------------------------------------------------------------------
# ensure_pi_config: write the parcc provider block into CHATLabAI's PRIVATE pi
# config dir ($PI_AGENT_DIR), never the user's ~/.pi.
# ---------------------------------------------------------------------------
ensure_pi_config() {
  local key
  key="$(get_api_key)"
  say "Writing parcc provider config to $PI_AGENT_DIR/models.json…"
  write_pi_config "$key"
  # The file holds the API key — keep it owner-only.
  chmod 600 "$PI_AGENT_DIR/models.json" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# ensure_callosum: clone callosum to ~/callosum and create its two venvs.
# Callosum needs Python 3.11+; the chatlab conda env provides it (mm run -n).
# Two venvs (per the callosum mcp_server README): .venv for the app, .mcp-venv
# for the standalone MCP server (mcp + httpx only, kept out of the app's deps).
# Idempotent: a present clone and venvs are left alone.
# ---------------------------------------------------------------------------
ensure_callosum() {
  # Need git to clone.
  if ! have git; then
    warn "git not found — skipping callosum setup. Install git and re-run to enable the reference manager."
    return 0
  fi

  # 1. Clone if missing.
  if [[ ! -d "$CALLOSUM_HOME/.git" ]]; then
    say "Cloning callosum (local reference manager) to $CALLOSUM_HOME…"
    git clone --depth 1 "$CALLOSUM_REPO" "$CALLOSUM_HOME" \
      || die "Failed to clone callosum."
  else
    say "callosum already cloned at $CALLOSUM_HOME — skipping clone."
  fi

  # 2. App venv (.venv) — callosum's own deps. Callosum requires Python 3.11+,
  #    which the chatlab env provides.
  if [[ ! -x "$CALLOSUM_HOME/.venv/bin/python" ]]; then
    say "Creating callosum app venv (.venv, Python 3.11 from the env)…"
    mm run -n "$ENV_NAME" python -m venv "$CALLOSUM_HOME/.venv" \
      || die "Failed to create callosum .venv."
    say "Installing callosum requirements into .venv (heavy: PyMuPDF, sentence-transformers, sklearn)…"
    "$CALLOSUM_HOME/.venv/bin/pip" install --quiet --upgrade pip
    "$CALLOSUM_HOME/.venv/bin/pip" install --quiet -r "$CALLOSUM_HOME/requirements.txt" \
      || die "Failed to install callosum requirements."
  else
    say "callosum .venv already exists — skipping."
  fi

  # 3. MCP server venv (.mcp-venv) — lightweight: mcp + httpx only.
  if [[ ! -x "$CALLOSUM_HOME/.mcp-venv/bin/python" ]]; then
    say "Creating callosum MCP server venv (.mcp-venv)…"
    mm run -n "$ENV_NAME" python -m venv "$CALLOSUM_HOME/.mcp-venv" \
      || die "Failed to create callosum .mcp-venv."
    "$CALLOSUM_HOME/.mcp-venv/bin/pip" install --quiet --upgrade pip
    "$CALLOSUM_HOME/.mcp-venv/bin/pip" install --quiet -r "$CALLOSUM_HOME/mcp_server/requirements.txt" \
      || die "Failed to install callosum mcp_server requirements."
  else
    say "callosum .mcp-venv already exists — skipping."
  fi

  # 4. Build the single-file frontend (callosum-app.html). Needs node (from the
  #    env, for esbuild) AND callosum's .venv python (for the fastapi import the
  #    build script pulls in). npm install first (pinned esbuild), then build.
  if [[ ! -f "$CALLOSUM_HOME/callosum-app.html" ]]; then
    say "Building callosum frontend (one-time)…"
    mm run -n "$ENV_NAME" bash -c "cd '$CALLOSUM_HOME' && npm install --silent" \
      || warn "callosum npm install failed — frontend build skipped."
    if [[ -x "$CALLOSUM_HOME/.venv/bin/python" ]]; then
      # .venv python has fastapi; env's node is on PATH for esbuild.
      mm run -n "$ENV_NAME" bash -c "cd '$CALLOSUM_HOME' && .venv/bin/python tools/build_frontend.py" \
        || warn "callosum frontend build failed — the API still works; the web UI may not. Rebuild manually in ~/callosum."
    else
      warn "callosum .venv missing — cannot build frontend. The API still works."
    fi
  else
    say "callosum frontend already built — skipping."
  fi

  # 5. Register the MCP server in pi's mcp.json (idempotent merge).
  ensure_callosum_mcp_config
}

# ---------------------------------------------------------------------------
# ensure_callosum_mcp_config: write/merge the callosum MCP server block into
# ~/.pi/agent/mcp.json, preserving any other servers (e.g. cua-driver). Uses
# python from the env for a robust JSON merge.
# ---------------------------------------------------------------------------
ensure_callosum_mcp_config() {
  mkdir -p "$(dirname "$MCP_CONFIG")"

  # python3 from the env (robust merge), system python3 fallback.
  local py
  py="mm run -n $ENV_NAME python"
  if ! mm run -n "$ENV_NAME" python -c 'pass' >/dev/null 2>&1; then
    py="python3"
  fi

  $py - "$MCP_CONFIG" "$CALLOSUM_HOME" <<'PYEOF'
import json, os, sys
cfg_file, callosum_home = sys.argv[1], sys.argv[2]

# Load existing if present and well-formed; else start fresh.
data = {}
if os.path.exists(cfg_file):
    try:
        with open(cfg_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}

servers = data.setdefault("mcpServers", {})
# The callosum block mirrors the mcp_server README's recommended config.
# Absolute paths to the dedicated .mcp-venv python and the repo (cwd must be
# the repo root for `python -m mcp_server` to resolve the import).
servers["callosum"] = {
    "command": os.path.join(callosum_home, ".mcp-venv", "bin", "python"),
    "args": ["-m", "mcp_server"],
    "cwd": callosum_home,
    "env": {
        "CALLOSUM_BASE_URL": "http://127.0.0.1:8080",
        "CALLOSUM_MCP_TOKEN": "",
        "CALLOSUM_DISABLE_AGENT_WRITES": "",
    },
    "lifecycle": "lazy",
    "idleTimeout": 30,
}

with open(cfg_file, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("callosum MCP server registered in", cfg_file)
PYEOF
}

# ---------------------------------------------------------------------------
# launch: exec the existing launcher under the activated env so `pi` (npm -g in
# the env) resolves and the env's node is used.
# ---------------------------------------------------------------------------
launch() {
  # bin/chatlab paints the "PARCC is booting…" splash (with the VPN note) just
  # before pi starts, so we don't duplicate it here. Callosum's optional
  # start-command hint isn't on that splash, so leave it as one dim line.
  note "callosum (reference manager) is optional — start it with:"
  note "      cd ~/callosum && .venv/bin/uvicorn app.backend.api.app:app --port 8080"
  # Export CHATLabAI's private pi config dir so pi reads OUR models.json /
  # mcp.json, not the user's ~/.pi. micromamba run activates the env
  # (CONDA_PREFIX=env root, env bin first on PATH); bin/chatlab then launches
  # the env's pi by absolute path.
  export PI_CODING_AGENT_DIR="$PI_AGENT_DIR"
  exec mm run -n "$ENV_NAME" bash "$REPO_ROOT/bin/chatlab" "$@"
}

# ===========================================================================
# Subcommands
# ===========================================================================

do_help() {
  cat <<'USAGE'
chatlab-bootstrap.sh — one-time slim launcher for CHATLabAI (macOS/Linux)

Bootstraps a prebuilt conda-forge environment (micromamba -> chatlab env ->
simr from CRAN -> pi via npm -> docx-cli binary) under
${CHATLAB_HOME:-$HOME/.chatlab}, then launches CHATLabAI. Nothing pollutes
the system.

Usage:
  bash packaging/chatlab-bootstrap.sh             full bootstrap, then launch pi
  bash packaging/chatlab-bootstrap.sh --check     non-destructive self-test, then exit
  bash packaging/chatlab-bootstrap.sh --dry-run   print steps it WOULD run, exit 0
  bash packaging/chatlab-bootstrap.sh --help      this message

Flags:
  --check     Verify the environment solves, micromamba works, and the pi
              config JSON merge is correct — WITHOUT creating the full env or
              touching the real ~/.pi. Downloads only the small micromamba
              binary and runs a conda-forge dry-run solve. Exits 0 only if
              every check passes.
  --dry-run   Print each step in order and exit 0 without performing them.
  --help      Show this help.

Environment:
  CHATLAB_HOME   Install prefix (default: $HOME/.chatlab).
  PARCC_API_KEY  UPenn PARCC LiteLLM API key. If unset, prompted on first run.

USAGE
}

do_dry_run() {
  local subdir
  subdir="$(detect_subdir)"
  say "[DRY-RUN] 1. Detect platform -> conda subdir: $subdir"
  say "[DRY-RUN] 2. Ensure micromamba at $MM_BIN"
  say "          (curl -fsSL https://micro.mamba.pm/api/micromamba/${subdir}/latest | tar -xjf - bin/micromamba)"
  say "[DRY-RUN] 3. Create conda env '$ENV_NAME' if missing:"
  say "          micromamba create -n chatlab -f packaging/environment.yml (root prefix $MM_ROOT_PREFIX)"
  say "[DRY-RUN] 4. Install simr (+ macOS RLRsim/binom) from CRAN if missing:"
  say "          micromamba run -n chatlab Rscript -e 'install.packages(c(\"simr\", ...))'"
  say "[DRY-RUN] 5. Install pi into the env if missing:"
  say "          micromamba run -n chatlab npm install -g @earendil-works/pi-coding-agent"
  say "[DRY-RUN] 6. Install docx-cli (Word-document CLI) into the env if missing:"
  say "          .pi/skills/docx-cli/scripts/bootstrap.sh (pinned release, SHA-256-verified)"
  say "[DRY-RUN] 7. Write pi config (parcc provider block + key) to $PI_AGENT_DIR/models.json"
  say "          (private config dir — the user's real ~/.pi is never touched)"
  say "[DRY-RUN] 8. Set up callosum (local reference manager + MCP) at $CALLOSUM_HOME:"
  say "          git clone $CALLOSUM_REPO"
  say "          mm run -n chatlab python -m venv ~/callosum/.venv && pip install -r requirements.txt"
  say "          mm run -n chatlab python -m venv ~/callosum/.mcp-venv && pip install -r mcp_server/requirements.txt"
  say "          npm install + build_frontend.py (web UI)"
  say "          register callosum MCP server in $PI_AGENT_DIR/mcp.json (preserve other servers)"
  say "[DRY-RUN] 9. Launch:"
  say "          micromamba run -n chatlab bash bin/chatlab"
  exit 0
}

do_check() {
  # Non-destructive self-test. Must NOT create the chatlab env, must NOT modify
  # the real $HOME/.pi, must NOT download 1.5GB. MAY download micromamba.
  local failed=0 subdir
  say "Running non-destructive self-test…"
  subdir="$(detect_subdir)"
  say "PLATFORM: $subdir"

  # --- micromamba present (download if needed; small binary only) -----------
  ensure_micromamba
  say "MICROMAMBA: $("$MM_BIN" --version 2>&1 | head -1)"
  [[ -x "$MM_BIN" ]] || { warn "micromamba not usable"; failed=1; }

  # --- ENV SOLVE: dry-run create against the host platform ------------------
  if [[ -x "$MM_BIN" ]]; then
    local solve_out solve_rc
    # Dry-run solve into a throwaway probe env name; never actually creates it.
    solve_out="$(mm create --dry-run -n probe -f "$ENV_YML" 2>&1)" || true
    solve_rc=$?
    # micromamba --dry-run may still exit 0 with a solve; detect failure by
    # scanning for solver failure phrases. A clean solve prints the plan and
    # returns 0.
    if printf '%s\n' "$solve_out" | grep -qiE "could not solve|does not exist|conflict|failed"; then
      warn "ENV SOLVE: FAILED — solver reported a problem:"
      printf '%s\n' "$solve_out" | tail -20 | sed 's/^/    /' >&2
      failed=1
    elif [[ $solve_rc -ne 0 ]]; then
      warn "ENV SOLVE: FAILED — micromamba create --dry-run exited $solve_rc"
      printf '%s\n' "$solve_out" | tail -20 | sed 's/^/    /' >&2
      failed=1
    else
      say "ENV SOLVE: OK"
    fi
  else
    warn "ENV SOLVE: SKIPPED (no micromamba)"
    failed=1
  fi

  # --- CONFIG JSON: write_pi_config into a TEMP dir, verify with python3 -------
  local tmp_home tmp_cfg py_check
  tmp_home="$(mktemp -d "${TMPDIR:-/tmp}/chatlab-check.XXXXXX")"
  # Redirect CHATLabAI's config dir to the temp path so neither the real ~/.pi
  # NOR the real $PI_AGENT_DIR (~/.chatlab/pi-agent) is touched by --check.
  tmp_cfg="$tmp_home/pi-agent/models.json"
  PI_AGENT_DIR="$tmp_home/pi-agent" HOME="$tmp_home" write_pi_config "DUMMYKEY123" \
    || { warn "CONFIG JSON: FAILED — write_pi_config errored"; failed=1; }

  # Choose a python3 for verification: prefer the env's, fall back to system.
  py_check="mm run -n $ENV_NAME python"
  if ! mm run -n "$ENV_NAME" python -c 'pass' >/dev/null 2>&1; then
    py_check="python3"
  fi

  if [[ -f "$tmp_cfg" ]]; then
    # Verify the merged JSON: baseUrl, apiKey, api, and model id. Write the
    # checker to a temp file then run it, capturing output — avoids the
    # `! cmd <<heredoc ... then` parser quirk by separating the heredoc from
    # the conditional.
    local verify_py verify_out verify_rc
    verify_py="$(mktemp "${TMPDIR:-/tmp}/chatlab-verify.XXXXXX.py")"
    cat > "$verify_py" <<'PYEOF'
import json, sys
cfg = json.load(open(sys.argv[1]))
p = cfg["providers"]["parcc"]
assert p["baseUrl"] == "https://litellm.parcc.upenn.edu/v1", p.get("baseUrl")
assert p["apiKey"] == "DUMMYKEY123", p.get("apiKey")
assert p["api"] == "openai-completions", p.get("api")
ids = [m["id"] for m in p["models"]]
assert "zai-org/GLM-5.2-FP8" in ids, ids
print("CONFIG JSON: OK")
PYEOF
    verify_out="$( $py_check "$verify_py" "$tmp_cfg" 2>&1 )" || true
    verify_rc=$?
    rm -f "$verify_py"
    if [[ $verify_rc -eq 0 ]] && printf '%s\n' "$verify_out" | grep -q 'CONFIG JSON: OK'; then
      say "CONFIG JSON: OK"
    else
      warn "CONFIG JSON: FAILED — verification (baseUrl/apiKey/model id) did not pass"
      warn "Wrote temp config to: $tmp_cfg"
      printf '%s\n' "$verify_out" | sed 's/^/    /' >&2
      failed=1
    fi
  else
    warn "CONFIG JSON: FAILED — models.json not written to $tmp_cfg"
    failed=1
  fi

  # Clean up temp HOME.
  rm -rf "$tmp_home"

  # --- final verdict --------------------------------------------------------
  if [[ $failed -eq 0 ]]; then
    say "CHECK PASSED"
    exit 0
  else
    warn "CHECK FAILED — see messages above."
    exit 1
  fi
}

do_full() {
  # Branded boot screen up front. On a genuine first run (no env yet) it warns
  # about the one-time download so a multi-minute setup never looks frozen; on a
  # returning launch it's a quick "PARCC is booting…" splash before pi.
  if have_bootscreen; then
    if env_exists; then
      chatlab_bootscreen "PARCC is booting…" "Checking your environment and starting CHATLabAI."
    else
      chatlab_bootscreen "PARCC is booting for the first time…" \
        "One-time setup — a few minutes (≈1.5 GB download). Later launches are instant."
    fi
  else
    say "Setting up CHATLabAI (one-time, ~1.5 GB)…"
  fi
  ensure_micromamba
  ensure_env
  ensure_simr
  ensure_pi
  ensure_docx
  ensure_pi_config
  ensure_callosum
  launch "$@"
}

# ---------------------------------------------------------------------------
# Arg dispatch.
# ---------------------------------------------------------------------------
main() {
  case "${1:-}" in
    --help|-h) do_help ;;
    --dry-run) do_dry_run ;;
    --check)   do_check ;;
    "")        do_full "$@" ;;
    *)         die "Unknown argument: $1. Run with --help." ;;
  esac
}

main "$@"
