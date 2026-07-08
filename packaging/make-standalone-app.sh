#!/usr/bin/env bash
# make-standalone-app.sh — build a SELF-CONTAINED CHATLabAI macOS app.
#
# The whole thing is inside the app: the prebuilt conda environment (Python/R +
# pi + docx), the CHATLabAI repo (skills, launcher, persona), and the PARCC key.
# Double-click → it unpacks everything under ~/.chatlab, writes the config, and
# launches CHATLabAI. NO repo download, NO Google Drive fetch at runtime — one
# file, one click, offline. (~700 MB, per the "don't care about size" call.)
#
# Output: packaging/dist/CHATLabAI.app  (+ a zipped CHATLabAI-mac.zip to hand out)
# The app CONTAINS the PARCC key — distribute privately, never commit/post.
#
# Prereq: packaging/dist/chatlab-env-osx-arm64.tar.gz exists (make-env-bundle.sh).
# Usage:  PARCC_API_KEY=sk-... bash packaging/make-standalone-app.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST="$SCRIPT_DIR/dist"
ENV_TARBALL="$DIST/chatlab-env-osx-arm64.tar.gz"
APP="$DIST/CHATLabAI.app"
KEY="${PARCC_API_KEY:-}"

die() { printf '[standalone] ERROR: %s\n' "$*" >&2; exit 1; }
say() { printf '[standalone] %s\n' "$*"; }

[[ -n "$KEY" ]]           || die "Set PARCC_API_KEY (the key is baked into the app)."
[[ -f "$ENV_TARBALL" ]]   || die "Missing $ENV_TARBALL — run make-env-bundle.sh first."

say "Building self-contained CHATLabAI.app…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# --- Info.plist -------------------------------------------------------------
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>CHATLabAI</string>
  <key>CFBundleDisplayName</key><string>CHATLabAI</string>
  <key>CFBundleIdentifier</key><string>edu.upenn.pcfn.chatlab</string>
  <key>CFBundleExecutable</key><string>CHATLabAI</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST

# --- Payload: the env + the repo -------------------------------------------
say "Embedding the prebuilt environment ($(du -h "$ENV_TARBALL" | awk '{print $1}'))…"
cp "$ENV_TARBALL" "$APP/Contents/Resources/env.tar.gz"

say "Embedding the CHATLabAI repo…"
tar -czf "$APP/Contents/Resources/repo.tar.gz" -C "$REPO_ROOT" \
  --exclude='.git' --exclude='.venv' --exclude='packaging/dist' \
  --exclude='.cache' --exclude='.pi/.cache' --exclude='.claude' \
  --exclude='*.tracked.docx' \
  bin .pi AGENTS.md README.md knowledge references calendar packaging data projects 2>/dev/null \
  || tar -czf "$APP/Contents/Resources/repo.tar.gz" -C "$REPO_ROOT" \
       --exclude='.git' --exclude='.venv' --exclude='packaging/dist' \
       --exclude='.cache' --exclude='.pi/.cache' --exclude='.claude' \
       bin .pi AGENTS.md README.md knowledge references calendar packaging

# --- setup.sh (runs on first launch; key baked in) --------------------------
# Placeholder __PARCC_KEY__ is substituted below.
cat > "$APP/Contents/Resources/setup.sh" <<'SETUP'
#!/bin/bash
# CHATLabAI self-contained setup + launch. Everything it needs is in ../Resources.
set -u
RES="$(cd "$(dirname "$0")" && pwd)"
CHATLAB_HOME="$HOME/.chatlab"
ENV="$CHATLAB_HOME/mm/envs/chatlab"
REPO="$HOME/CHATLabAI"
KEY="__PARCC_KEY__"

banner() {
  clear 2>/dev/null || true
  printf '\n   \033[38;5;245m══════════════════════════════════════════════════\033[0m\n'
  printf '    \033[1m\033[38;5;39mCHATLabAI\033[0m  \033[38;5;245m·  Penn Center for Neuroaesthetics\033[0m\n'
  printf '   \033[38;5;245m══════════════════════════════════════════════════\033[0m\n\n'
  printf '    \033[38;5;39m→ %s\033[0m\n\n' "$1"
}

# 1. Environment (one-time unpack; ~2 GB on disk after).
if [[ ! -x "$ENV/bin/pi" ]]; then
  banner "Setting up CHATLabAI for the first time — a few minutes, then instant."
  echo "      Unpacking the environment…"
  mkdir -p "$ENV"
  tar -xzf "$RES/env.tar.gz" -C "$ENV" || { echo "Setup failed while unpacking the environment."; read -r _; exit 1; }
  echo "      Finalizing…"
  "$ENV/bin/python" "$ENV/bin/conda-unpack" 2>/dev/null || true
fi
# docx released binary carries an invalid ad-hoc signature on macOS → re-sign.
if [[ -f "$ENV/bin/docx" ]] && ! "$ENV/bin/docx" --version >/dev/null 2>&1; then
  codesign -s - --force "$ENV/bin/docx" 2>/dev/null || true
fi

# 2. Repo (skills, launcher, persona).
if [[ ! -d "$REPO/.pi" ]]; then
  mkdir -p "$REPO"
  tar -xzf "$RES/repo.tar.gz" -C "$REPO" || { echo "Setup failed while unpacking CHATLabAI."; read -r _; exit 1; }
fi

# 3. Private pi config with the baked-in PARCC key (never touches ~/.pi).
mkdir -p "$CHATLAB_HOME/pi-agent"
cat > "$CHATLAB_HOME/pi-agent/models.json" <<JSON
{
  "providers": {
    "parcc": {
      "baseUrl": "https://litellm.parcc.upenn.edu/v1",
      "api": "openai-completions",
      "apiKey": "$KEY",
      "models": [{ "id": "zai-org/GLM-5.2-FP8", "name": "GLM 5.2 FP8", "contextWindow": 1048576 }]
    }
  }
}
JSON
chmod 600 "$CHATLAB_HOME/pi-agent/models.json"

# 4. Launch CHATLabAI from the embedded env (no micromamba, no network needed).
export PI_CODING_AGENT_DIR="$CHATLAB_HOME/pi-agent"
export CONDA_PREFIX="$ENV"
export PATH="$ENV/bin:$PATH"
export CHATLAB_HOME
exec bash "$REPO/bin/chatlab" "$@"
SETUP
# Bake the key in.
python3 - "$APP/Contents/Resources/setup.sh" "$KEY" <<'PY'
import sys
p, key = sys.argv[1], sys.argv[2]
s = open(p).read().replace("__PARCC_KEY__", key)
open(p, "w").write(s)
PY
chmod +x "$APP/Contents/Resources/setup.sh"

# --- The app executable: open Terminal running setup.sh ---------------------
cat > "$APP/Contents/MacOS/CHATLabAI" <<'LAUNCHER'
#!/bin/bash
# Open a Terminal window running the embedded setup+launch, so the user gets a
# real terminal for pi's TUI. Unsigned bundle: first run, right-click → Open.
self="${BASH_SOURCE[0]:-$0}"
while [[ -L "$self" ]]; do d="$(cd "$(dirname "$self")" && pwd)"; self="$(readlink "$self")"; [[ "$self" != /* ]] && self="$d/$self"; done
here="$(cd "$(dirname "$self")" && pwd)"
res="$(cd "$here/../Resources" && pwd)"
osascript <<EOF 2>/dev/null || { echo "Could not open Terminal." >&2; exit 1; }
tell application "Terminal"
  activate
  do script "bash '$res/setup.sh'"
end tell
EOF
LAUNCHER
chmod +x "$APP/Contents/MacOS/CHATLabAI"

# --- Zip for handoff --------------------------------------------------------
say "Zipping for distribution…"
( cd "$DIST" && rm -f CHATLabAI-mac.zip && zip -qry CHATLabAI-mac.zip CHATLabAI.app )

sz_app="$(du -sh "$APP" | awk '{print $1}')"
sz_zip="$(du -h "$DIST/CHATLabAI-mac.zip" | awk '{print $1}')"
say "Built $APP ($sz_app)"
say "Handout: $DIST/CHATLabAI-mac.zip ($sz_zip) — contains the PARCC key, share privately."
say "Recipient: unzip → right-click CHATLabAI.app → Open (first time) → it sets up and launches."
