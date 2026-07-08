#!/usr/bin/env bash
# make-lab-installer.sh — build the lab-distributable CHATLabAI installers.
#
# Produces packaging/dist/ (GITIGNORED — never commit it):
#   get-chatlab.sh            macOS/Linux terminal installer (curl-able too)
#   get-chatlab.cmd           Windows double-click installer
#   Install CHATLabAI.app/    macOS double-click installer (unsigned)
#   Install-CHATLabAI.zip     the .app zipped for email/AirDrop/Canvas
#
# If a PARCC key is supplied, it is STAMPED into each artifact so lab members
# are never prompted for it — the bootstrap writes it straight into their
# ~/.pi/agent/models.json. The stamped files therefore CONTAIN the key:
# distribute them privately (email/AirDrop/Slack DM), never commit or post
# them publicly. The copies in git stay key-free.
#
# Usage:
#   bash packaging/make-lab-installer.sh                # key from $PARCC_API_KEY, or none
#   bash packaging/make-lab-installer.sh --key sk-...   # explicit key
#   bash packaging/make-lab-installer.sh --no-key       # build unstamped (users get prompted)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DIST="$SCRIPT_DIR/dist"

say() { printf '[make-lab-installer] %s\n' "$*"; }
die() { printf '[make-lab-installer] ERROR: %s\n' "$*" >&2; exit 1; }

KEY="${PARCC_API_KEY:-}"
case "${1:-}" in
  --key)    KEY="${2:-}"; [[ -n "$KEY" ]] || die "--key requires a value" ;;
  --no-key) KEY="" ;;
  "")       : ;;
  *)        die "Unknown argument: $1 (use --key K | --no-key)" ;;
esac

rm -rf "$DIST"
mkdir -p "$DIST"

# ---------------------------------------------------------------- sh + cmd
cp "$SCRIPT_DIR/get-chatlab.sh"  "$DIST/get-chatlab.sh"
cp "$SCRIPT_DIR/get-chatlab.cmd" "$DIST/get-chatlab.cmd"
chmod +x "$DIST/get-chatlab.sh"

if [[ -n "$KEY" ]]; then
  # Stamp the key. perl keeps the .cmd's CRLF line endings intact.
  perl -pi -e 's/^EMBEDDED_PARCC_API_KEY=""$/EMBEDDED_PARCC_API_KEY="'"$KEY"'"/' \
    "$DIST/get-chatlab.sh"
  perl -pi -e 's/^set "EMBEDDED_PARCC_API_KEY="\r$/set "EMBEDDED_PARCC_API_KEY='"$KEY"'"\r/' \
    "$DIST/get-chatlab.cmd"
  grep -q "$KEY" "$DIST/get-chatlab.sh"  || die "key stamping failed for get-chatlab.sh"
  grep -q "$KEY" "$DIST/get-chatlab.cmd" || die "key stamping failed for get-chatlab.cmd"
  say "Stamped PARCC key into get-chatlab.sh and get-chatlab.cmd."
else
  say "No key supplied — building UNSTAMPED installers (users will be prompted once)."
fi

# ---------------------------------------------------------------- macOS .app
APP="$DIST/Install CHATLabAI.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>Install CHATLabAI</string>
	<key>CFBundleIdentifier</key>
	<string>edu.upenn.pcfn.chatlab.installer</string>
	<key>CFBundleExecutable</key>
	<string>Install-CHATLabAI</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleVersion</key>
	<string>1.0</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>LSMinimumSystemVersion</key>
	<string>11.0</string>
</dict>
</plist>
PLIST

# The (possibly stamped) installer script rides inside the bundle, so the app
# is fully self-contained and the key never appears on a Terminal command line.
cp "$DIST/get-chatlab.sh" "$APP/Contents/Resources/get-chatlab.sh"

cat > "$APP/Contents/MacOS/Install-CHATLabAI" <<'LAUNCHER'
#!/usr/bin/env bash
# Install CHATLabAI.app — double-click installer.
# Opens a Terminal window running the bundled get-chatlab.sh, which downloads
# the CHATLabAI repository and bootstraps everything (one-time ~1.5 GB).
# Unsigned bundle: on first run, right-click the app -> Open to pass Gatekeeper.
set -euo pipefail

self="${BASH_SOURCE[0]:-$0}"
while [[ -L "$self" ]]; do
  dir="$(cd "$(dirname "$self")" && pwd)"
  self="$(readlink "$self")"
  [[ "$self" != /* ]] && self="$dir/$self"
done
here="$(cd "$(dirname "$self")" && pwd)"          # .../Contents/MacOS
res="$(cd "$here/../Resources" && pwd)"

if [[ ! -f "$res/get-chatlab.sh" ]]; then
  osascript -e 'display alert "Install CHATLabAI is damaged" message "get-chatlab.sh is missing from the app bundle. Re-download the installer." as critical' 2>/dev/null || true
  exit 1
fi

# Single-quote the path so the AppleScript string stays well-formed.
cmd="bash '$res/get-chatlab.sh'"
osascript <<EOF 2>/dev/null || { echo "ERROR: could not open Terminal.app" >&2; exit 1; }
tell application "Terminal"
  activate
  do script "$cmd"
end tell
EOF
LAUNCHER
chmod +x "$APP/Contents/MacOS/Install-CHATLabAI"

# Zip the app for distribution (email/AirDrop strip nothing; unzip preserves +x).
(cd "$DIST" && zip -qry "Install-CHATLabAI.zip" "Install CHATLabAI.app")

say "Built:"
say "  $DIST/get-chatlab.sh          (macOS/Linux: bash get-chatlab.sh)"
say "  $DIST/get-chatlab.cmd         (Windows: double-click)"
say "  $DIST/Install CHATLabAI.app   (macOS: double-click; first run right-click -> Open)"
say "  $DIST/Install-CHATLabAI.zip   (the .app, ready to send)"
if [[ -n "$KEY" ]]; then
  say ""
  say "These artifacts CONTAIN the lab PARCC key — share privately, never commit/post."
fi
