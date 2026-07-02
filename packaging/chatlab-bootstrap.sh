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

# Private install prefix — everything lives here, nothing touches the system.
CHATLAB_HOME="${CHATLAB_HOME:-$HOME/.chatlab}"
MM_ROOT_PREFIX="$CHATLAB_HOME/mm"          # micromamba root prefix
MM_BIN="$CHATLAB_HOME/bin/micromamba"        # the micromamba binary itself

# parcc provider constants are kept inside the python merge (write_pi_config)
# and the dry-run/help text, not as shell vars, to avoid duplication.

# Callosum (local reference manager + MCP server). Lives at ~/callosum per the
# callosum README convention, outside CHATLAB_HOME. Uses the env's Python 3.11
# for both its app venv (.venv) and the MCP server venv (.mcp-venv). The MCP
# server is registered in ~/.pi/agent/mcp.json so pi can spawn it.
CALLOSUM_HOME="${CALLOSUM_HOME:-$HOME/callosum}"
CALLOSUM_REPO="https://github.com/cliffworkman/callosum.git"
MCP_CONFIG="$HOME/.pi/agent/mcp.json"

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
ensure_env() {
  if env_exists; then
    say "Conda env '$ENV_NAME' already exists — skipping create."
    return 0
  fi
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
# pi_installed: 0 if `pi` is on the env's PATH (i.e. npm -g installed into env).
# ---------------------------------------------------------------------------
pi_installed() {
  mm run -n "$ENV_NAME" which pi >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# ensure_pi: install pi into the env prefix via npm -g (lands in env's bin).
# ---------------------------------------------------------------------------
ensure_pi() {
  if pi_installed; then
    say "pi already installed in env — skipping."
    return 0
  fi
  say "Installing pi (@earendil-works/pi-coding-agent) into the env…"
  mm run -n "$ENV_NAME" npm install -g @earendil-works/pi-coding-agent \
    || die "Failed to install pi via npm."
}

# ---------------------------------------------------------------------------
# write_pi_config <key>: ensure $HOME/.pi/agent/models.json has a parcc provider
# block with the given API key, merged into any existing file without clobbering
# other providers. Uses python3 from the env (guaranteed present) for a robust
# JSON merge that preserves existing providers and other parcc models.
# Writes to $HOME/.pi/agent/models.json — respects a real or temp HOME.
# ---------------------------------------------------------------------------
write_pi_config() {
  local key="$1"
  local cfg_dir cfg_file
  cfg_dir="$HOME/.pi/agent"
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
# ensure_pi_config: write the parcc provider block into the real ~/.pi config.
# ---------------------------------------------------------------------------
ensure_pi_config() {
  local key
  key="$(get_api_key)"
  say "Writing parcc provider config to ~/.pi/agent/models.json…"
  write_pi_config "$key"
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
  note "Launching CHATLabAI…"
  note "Note: the backend (litellm.parcc.upenn.edu) requires UPenn network/VPN access."
  note "Note: callosum (reference manager) runs separately — start it with:"
  note "      cd ~/callosum && .venv/bin/uvicorn app.backend.api.app:app --port 8080"
  # micromamba run activates the env: CONDA_PREFIX=env root, env bin on PATH, so
  # `pi` (installed by npm -g into the env) and the env's node both resolve.
  exec mm run -n "$ENV_NAME" bash "$REPO_ROOT/bin/chatlab" "$@"
}

# ===========================================================================
# Subcommands
# ===========================================================================

do_help() {
  cat <<'USAGE'
chatlab-bootstrap.sh — one-time slim launcher for CHATLabAI (macOS/Linux)

Bootstraps a prebuilt conda-forge environment (micromamba -> chatlab env ->
simr from CRAN -> pi via npm) under ${CHATLAB_HOME:-$HOME/.chatlab}, then
launches CHATLabAI. Nothing pollutes the system.

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
  say "[DRY-RUN] 6. Write pi config (parcc provider block + key) to ~/.pi/agent/models.json"
  say "          (pi config merge: preserve other providers/models)"
  say "[DRY-RUN] 7. Set up callosum (local reference manager + MCP) at $CALLOSUM_HOME:"
  say "          git clone $CALLOSUM_REPO"
  say "          mm run -n chatlab python -m venv ~/callosum/.venv && pip install -r requirements.txt"
  say "          mm run -n chatlab python -m venv ~/callosum/.mcp-venv && pip install -r mcp_server/requirements.txt"
  say "          npm install + build_frontend.py (web UI)"
  say "          register callosum MCP server in ~/.pi/agent/mcp.json (preserve other servers)"
  say "[DRY-RUN] 8. Launch:"
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

  # --- CONFIG JSON: write_pi_config against a TEMP HOME, verify with python3 --
  local tmp_home tmp_cfg py_check
  tmp_home="$(mktemp -d "${TMPDIR:-/tmp}/chatlab-check.XXXXXX")"
  # Run the merge in an isolated HOME so the real ~/.pi is never touched.
  HOME="$tmp_home" write_pi_config "DUMMYKEY123" \
    || { warn "CONFIG JSON: FAILED — write_pi_config errored"; failed=1; }
  tmp_cfg="$tmp_home/.pi/agent/models.json"

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
  say "Setting up CHATLabAI (one-time, ~1.5 GB)…"
  ensure_micromamba
  ensure_env
  ensure_simr
  ensure_pi
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
