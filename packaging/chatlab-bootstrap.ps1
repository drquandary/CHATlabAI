# requires: PowerShell 5.1+ ; Windows 10 17063+
<#
.SYNOPSIS
  chatlab-bootstrap.ps1 — one-time slim launcher for CHATLabAI (Windows).

.DESCRIPTION
  Faithful Windows port of packaging/chatlab-bootstrap.sh. Bootstraps everything
  CHATLabAI needs from a prebuilt conda-forge environment so a first-time user
  does no manual dependency setup. Nothing pollutes the system: micromamba, the
  conda env, and pi all live under $env:CHATLAB_HOME (default
  $env:USERPROFILE\.chatlab). Reuses the SHARED packaging/environment.yml — the
  package list is NOT duplicated here.

  Backend: the UPenn `parcc` LiteLLM proxy (https://litellm.parcc.upenn.edu/v1).
  The PARCC_API_KEY is a per-user secret — read from $env:PARCC_API_KEY or
  prompted on first run. Never hardcoded.

.PARAMETER Check
  Non-destructive self-test: dry-run conda-forge solve + config-merge test
  against a temp profile. Does NOT create the env, does NOT touch the real
  ~/.pi. Exits 0 only if every check passes.

.PARAMETER DryRun
  Print each step in order and exit 0 without performing them.

.PARAMETER Help
  Show this help.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File packaging\chatlab-bootstrap.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File packaging\chatlab-bootstrap.ps1 -Check
  powershell -NoProfile -ExecutionPolicy Bypass -File packaging\chatlab-bootstrap.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File packaging\chatlab-bootstrap.ps1 -Help
#>
[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$DryRun,
  [switch]$Help
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Resolve repo root: parent of the packaging dir that holds THIS script
# (PowerShell resolves the real path, so symlinks are followed).
# ---------------------------------------------------------------------------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = (Resolve-Path (Join-Path $ScriptDir '..')).Path

$EnvYml      = Join-Path $RepoRoot 'packaging\environment.yml'
$EnvName     = 'chatlab'

# Private install prefix — everything lives here, nothing touches the system.
$ChatlabHome = if ($env:CHATLAB_HOME) { $env:CHATLAB_HOME } else { Join-Path $env:USERPROFILE '.chatlab' }
$MmRootPrefix = Join-Path $ChatlabHome 'mm'        # micromamba root prefix
$MmBin        = Join-Path $ChatlabHome 'bin\micromamba.exe'  # the micromamba binary itself

# conda subdir for this launcher is always win-64.
$Subdir = 'win-64'

# Callosum (local reference manager + MCP server). Lives at ~/callosum per the
# callosum README convention, outside $ChatlabHome. Uses the env's Python 3.11
# for both its app venv (.venv) and the MCP server venv (.mcp-venv). The MCP
# server is registered in ~/.pi/agent/mcp.json so pi can spawn it.
$CallosumHome = if ($env:CALLOSUM_HOME) { $env:CALLOSUM_HOME } else { Join-Path $env:USERPROFILE 'callosum' }
$CallosumRepo = 'https://github.com/cliffworkman/callosum.git'
$McpConfig   = Join-Path $env:USERPROFILE '.pi\agent\mcp.json'

# ---------------------------------------------------------------------------
# Logging helpers.
# ---------------------------------------------------------------------------
function Say  { param([string]$Msg) Write-Host "[chatlab] $Msg" }
function Note { param([string]$Msg) Write-Host "[chatlab] $Msg" -ForegroundColor Yellow }
function Warn { param([string]$Msg) Write-Host "[chatlab] WARN: $Msg" -ForegroundColor Yellow }
function Die  { param([string]$Msg) Write-Host "[chatlab] ERROR: $Msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# Micromamba wrapper: always uses our root prefix. Returns the (possibly empty)
# stderr/stdout via the pipeline so callers can capture it.
# ---------------------------------------------------------------------------
function Invoke-Mm {
  param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$MmArgs
  )
  & $MmBin --root-prefix $MmRootPrefix @MmArgs
}

# ---------------------------------------------------------------------------
# Ensure-Micromamba: download the static micromamba.exe to $MmBin if missing.
# Idempotent: skip if already present and runnable.
# ---------------------------------------------------------------------------
function Ensure-Micromamba {
  if ((Test-Path $MmBin) -and $MmBin) {
    $v = $null
    try { $v = & $MmBin --version 2>$null } catch { }
    if ($LASTEXITCODE -eq 0 -and $v) { return $true }
  }
  $url = "https://micro.mamba.pm/api/micromamba/$Subdir/latest"
  Say "Downloading micromamba ($Subdir)..."
  $binDir = Split-Path -Parent $MmBin
  New-Item -ItemType Directory -Force -Path $binDir | Out-Null
  $tmpTar = Join-Path $ChatlabHome 'micromamba.tar.bz2'
  try {
    Invoke-WebRequest -Uri $url -OutFile $tmpTar -UseBasicParsing -ErrorAction Stop
  } catch {
    Die "Failed to download micromamba from $url : $($_.Exception.Message)"
  }
  # The archive member is Library/bin/micromamba.exe (win-64 layout). Windows 10
  # 17063+ ships tar.exe; -xf handles .tar.bz2 via its libarchive backend.
  Push-Location $ChatlabHome
  try {
    & tar -xf $tmpTar Library/bin/micromamba.exe
    if ($LASTEXITCODE -ne 0) { Die "Failed to extract micromamba archive (tar exit $LASTEXITCODE)." }
  } finally {
    Pop-Location
  }
  # Move the extracted exe into place.
  $extracted = Join-Path $ChatlabHome 'Library\bin\micromamba.exe'
  if (Test-Path $extracted) {
    Move-Item -Path $extracted -Destination $MmBin -Force
  }
  Remove-Item -Recurse -Force (Join-Path $ChatlabHome 'Library') -ErrorAction SilentlyContinue
  Remove-Item -Force $tmpTar -ErrorAction SilentlyContinue
  if (-not (Test-Path $MmBin)) { Die "micromamba.exe not found at $MmBin after extraction." }
  return $true
}

# ---------------------------------------------------------------------------
# Test-EnvExists: $true if the chatlab env is already created.
# ---------------------------------------------------------------------------
# Detect the env by its prefix directory, NOT by parsing `env list` JSON.
# micromamba env list --json returns env PATHS (e.g. ".../envs/chatlab"), not
# bare names, so matching the quoted name "chatlab" never matches a full path.
# A conda env exists iff <root-prefix>/envs/<name>/conda-meta is a directory --
# deterministic, needs no micromamba call. (Mirrors bash env_exists.)
function Test-EnvExists {
  $metaDir = Join-Path $MmRootPrefix "envs\$EnvName\conda-meta"
  return (Test-Path $metaDir -PathType Container)
}

# ---------------------------------------------------------------------------
# Ensure-Env: create the chatlab env from environment.yml if missing.
# ---------------------------------------------------------------------------
function Ensure-Env {
  if (Test-EnvExists) {
    Say "Conda env '$EnvName' already exists — skipping create."
    return
  }
  Say "Creating conda env '$EnvName' from environment.yml..."
  Invoke-Mm create -y -n $EnvName -f $EnvYml
  if ($LASTEXITCODE -ne 0) {
    Die "Failed to create conda env. Check your network (conda-forge must be reachable)."
  }
}

# ---------------------------------------------------------------------------
# Test-SimrInstalled: $true if simr is importable in the env.
# ---------------------------------------------------------------------------
function Test-SimrInstalled {
  try {
    $out = Invoke-Mm run -n $EnvName Rscript -e 'cat(if(requireNamespace("simr", quietly=TRUE)) "yes" else "no")' 2>$null
    if ($out -match 'yes') { return $true }
  } catch { }
  return $false
}

# ---------------------------------------------------------------------------
# Ensure-Simr: install simr from CRAN if not already installed. Pure R, no
# compilation. On Windows there are NO mac helpers — install just simr.
# ---------------------------------------------------------------------------
function Ensure-Simr {
  if (Test-SimrInstalled) {
    Say "R package 'simr' already installed — skipping."
    return
  }
  Say "Installing R package 'simr' from CRAN..."
  Invoke-Mm run -n $EnvName Rscript -e 'if(!requireNamespace("simr",quietly=TRUE)) install.packages("simr", repos="https://cloud.r-project.org")'
  if ($LASTEXITCODE -ne 0) { Die "Failed to install simr from CRAN." }
}

# ---------------------------------------------------------------------------
# Test-PiInstalled: $true if `pi` is on the env's PATH (npm -g into env).
# ---------------------------------------------------------------------------
function Test-PiInstalled {
  try {
    Invoke-Mm run -n $EnvName where.exe pi 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { return $true }
  } catch { }
  return $false
}

# ---------------------------------------------------------------------------
# Ensure-Pi: install pi into the env prefix via npm -g (lands in env's bin).
# ---------------------------------------------------------------------------
function Ensure-Pi {
  if (Test-PiInstalled) {
    Say "pi already installed in env — skipping."
    return
  }
  Say "Installing pi (@earendil-works/pi-coding-agent) into the env..."
  Invoke-Mm run -n $EnvName npm install -g '@earendil-works/pi-coding-agent'
  if ($LASTEXITCODE -ne 0) { Die "Failed to install pi via npm." }
}

# ---------------------------------------------------------------------------
# Get-PyForConfig: return a command array to run python3. Prefer the env's
# python (micromamba run -n chatlab python); fall back to system python if the
# env isn't available yet (Write-PiConfig is also called by -Check before the
# env exists; -Check must still succeed on a temp profile).
# Returns a hashtable with 'Prefix' (string to prepend) and 'Args' (array) so
# callers can build the invocation.
# ---------------------------------------------------------------------------
function Get-PyForConfig {
  $envOk = $false
  try {
    Invoke-Mm run -n $EnvName python -c 'pass' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $envOk = $true }
  } catch { }
  if ($envOk) {
    return @{ UseEnv = $true }
  }
  return @{ UseEnv = $false }
}

# ---------------------------------------------------------------------------
# Write-PiConfig -Key <k>: ensure $env:USERPROFILE\.pi\agent\models.json has a
# parcc provider block with the given API key, merged into any existing file
# without clobbering other providers. Uses the SAME JSON-merge python snippet
# as the bash script (write_pi_config), so behaviour is identical. Respects a
# real or temp USERPROFILE (the -Check path sets $env:USERPROFILE to a temp dir).
# ---------------------------------------------------------------------------
function Write-PiConfig {
  param([Parameter(Mandatory = $true)][string]$Key)

  $cfgDir  = Join-Path $env:USERPROFILE '.pi\agent'
  $cfgFile = Join-Path $cfgDir 'models.json'
  New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null

  $py = Get-PyForConfig

  # The embedded python merge — identical logic to packaging/chatlab-bootstrap.sh.
  $pyScript = @'
import json, os, sys
cfg_file, key = sys.argv[1], sys.argv[2]
PARCC_BASEURL = "https://litellm.parcc.upenn.edu/v1"
PARCC_API_TYPE = "openai-completions"
MODEL_ID = "zai-org/GLM-5.2-FP8"
MODEL_NAME = "GLM 5.2 FP8"
MODEL_CTX = 1048576

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

models = parcc.setdefault("models", [])
have_glm = any(isinstance(m, dict) and m.get("id") == MODEL_ID for m in models)
if not have_glm:
    models.append({"id": MODEL_ID, "name": MODEL_NAME, "contextWindow": MODEL_CTX})

with open(cfg_file, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
'@

  # Write the merge script to a temp file, then run it under the chosen python,
  # so we avoid quoting pitfalls and keep the python body byte-identical.
  $tmpPy = (Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N') + '.py'))
  Set-Content -Path $tmpPy -Value $pyScript -Encoding UTF8

  try {
    if ($py.UseEnv) {
      Invoke-Mm run -n $EnvName python $tmpPy $cfgFile $Key 2>&1 | Out-Null
      $rc = $LASTEXITCODE
    } else {
      & python $tmpPy $cfgFile $Key 2>&1 | Out-Null
      $rc = $LASTEXITCODE
    }
    if ($rc -ne 0) { Die "Write-PiConfig: python merge failed (exit $rc)." }
  } finally {
    Remove-Item -Force $tmpPy -ErrorAction SilentlyContinue
  }
}

# ---------------------------------------------------------------------------
# Get-ApiKey: from $env:PARCC_API_KEY, else prompt interactively.
# ---------------------------------------------------------------------------
function Get-ApiKey {
  if ($env:PARCC_API_KEY) { return $env:PARCC_API_KEY }
  $key = Read-Host 'Paste your PARCC API key'
  if (-not $key) { Die 'No API key provided. Set PARCC_API_KEY or paste it when prompted.' }
  return $key
}

# ---------------------------------------------------------------------------
# Ensure-PiConfig: write the parcc provider block into the real ~/.pi config.
# ---------------------------------------------------------------------------
function Ensure-PiConfig {
  $key = Get-ApiKey
  Say 'Writing parcc provider config to ~/.pi/agent/models.json...'
  Write-PiConfig -Key $key
}

# ---------------------------------------------------------------------------
# Ensure-CallosMcpConfig: write/merge the callosum MCP server block into
# ~/.pi/agent/mcp.json, preserving any other servers (e.g. cua-driver). Uses
# python from the env for a robust JSON merge.
# ---------------------------------------------------------------------------
function Ensure-CallosMcpConfig {
  $cfgDir = Split-Path -Parent $McpConfig
  if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null }

  $py = Get-PyForConfig
  $mergePy = @'
import json, os, sys
cfg_file, callosum_home = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(cfg_file):
    try:
        with open(cfg_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}
servers = data.setdefault("mcpServers", {})
servers["callosum"] = {
    "command": os.path.join(callosum_home, ".mcp-venv", "Scripts", "python.exe"),
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
'@
  $tmpPy = (Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N') + '.py'))
  Set-Content -Path $tmpPy -Value $mergePy -Encoding UTF8
  try {
    & $py $tmpPy $McpConfig $CallosumHome
  } finally {
    Remove-Item $tmpPy -ErrorAction SilentlyContinue
  }
}

# ---------------------------------------------------------------------------
# Ensure-Callosum: clone callosum to ~/callosum and create its two venvs.
# Callosum needs Python 3.11+; the chatlab conda env provides it (Invoke-Mm run).
# Two venvs (per the callosum mcp_server README): .venv for the app, .mcp-venv
# for the standalone MCP server (mcp + httpx only). Idempotent.
# ---------------------------------------------------------------------------
function Ensure-Callosum {
  # Need git to clone.
  $git = Get-Command git -ErrorAction SilentlyContinue
  if (-not $git) {
    Warn 'git not found — skipping callosum setup. Install git and re-run to enable the reference manager.'
    return
  }

  # 1. Clone if missing.
  if (-not (Test-Path (Join-Path $CallosumHome '.git'))) {
    Say "Cloning callosum (local reference manager) to $CallosumHome..."
    & git clone --depth 1 $CallosumRepo $CallosumHome
    if ($LASTEXITCODE -ne 0) { Die "Failed to clone callosum." }
  } else {
    Say "callosum already cloned at $CallosumHome — skipping clone."
  }

  # 2. App venv (.venv) — callosum's own deps. Needs Python 3.11+ from the env.
  $appPy = Join-Path $CallosumHome '.venv\Scripts\python.exe'
  if (-not (Test-Path $appPy)) {
    Say 'Creating callosum app venv (.venv, Python 3.11 from the env)...'
    Invoke-Mm run -n $EnvName python -m venv (Join-Path $CallosumHome '.venv')
    if ($LASTEXITCODE -ne 0) { Die 'Failed to create callosum .venv.' }
    Say 'Installing callosum requirements into .venv (heavy: PyMuPDF, sentence-transformers, sklearn)...'
    & (Join-Path $CallosumHome '.venv\Scripts\pip.exe') install --quiet --upgrade pip
    & (Join-Path $CallosumHome '.venv\Scripts\pip.exe') install --quiet -r (Join-Path $CallosumHome 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { Die 'Failed to install callosum requirements.' }
  } else {
    Say 'callosum .venv already exists — skipping.'
  }

  # 3. MCP server venv (.mcp-venv) — lightweight: mcp + httpx only.
  $mcpPy = Join-Path $CallosumHome '.mcp-venv\Scripts\python.exe'
  if (-not (Test-Path $mcpPy)) {
    Say 'Creating callosum MCP server venv (.mcp-venv)...'
    Invoke-Mm run -n $EnvName python -m venv (Join-Path $CallosumHome '.mcp-venv')
    if ($LASTEXITCODE -ne 0) { Die 'Failed to create callosum .mcp-venv.' }
    & (Join-Path $CallosumHome '.mcp-venv\Scripts\pip.exe') install --quiet --upgrade pip
    & (Join-Path $CallosumHome '.mcp-venv\Scripts\pip.exe') install --quiet -r (Join-Path $CallosumHome 'mcp_server\requirements.txt')
    if ($LASTEXITCODE -ne 0) { Die 'Failed to install callosum mcp_server requirements.' }
  } else {
    Say 'callosum .mcp-venv already exists — skipping.'
  }

  # 4. Build the single-file frontend (callosum-app.html). Needs node (from the
  #    env, for esbuild) AND callosum's .venv python (for the fastapi import the
  #    build script pulls in). npm install first (pinned esbuild), then build.
  $builtHtml = Join-Path $CallosumHome 'callosum-app.html'
  if (-not (Test-Path $builtHtml)) {
    Say 'Building callosum frontend (one-time)...'
    Invoke-Mm run -n $EnvName bash -c "cd `"$CallosumHome`" && npm install --silent" 2>$null
    $venvPy = Join-Path $CallosumHome '.venv\Scripts\python.exe'
    if (Test-Path $venvPy) {
      # .venv python has fastapi; env's node is on PATH for esbuild.
      Invoke-Mm run -n $EnvName bash -c "cd `"$CallosumHome`" && .venv/Scripts/python tools/build_frontend.py" 2>$null
      if ($LASTEXITCODE -ne 0) {
        Warn 'callosum frontend build failed — the API still works; the web UI may not. Rebuild manually in ~/callosum.'
      }
    } else {
      Warn 'callosum .venv missing — cannot build frontend. The API still works.'
    }
  } else {
    Say 'callosum frontend already built — skipping.'
  }

  # 5. Register the MCP server in pi mcp.json (idempotent merge).
  Ensure-CallosMcpConfig
}

# ---------------------------------------------------------------------------
# Launch-Lab: launch CHATLabAI. On Windows the launcher (bin/chatlab) is bash,
# so prefer the env's bash if present; otherwise replicate bin/chatlab's exact
# pi invocation in PowerShell. The env's bin is put on PATH so `pi` resolves.
# Optional pass-through args after a leading existing-dir path start there.
# ---------------------------------------------------------------------------
function Launch-Lab {
  param([string[]]$PassArgs)

  Note 'Launching CHATLabAI...'
  Note 'Note: the backend (litellm.parcc.upenn.edu) requires UPenn network/VPN access.'

  # Default working dir is the workspace root; a leading existing-dir arg
  # overrides it (mirrors bin/chatlab).
  $workDir = $RepoRoot
  $piArgs = [System.Collections.Generic.List[string]]::new()
  if ($PassArgs.Count -gt 0 -and ($PassArgs[0] -notmatch '^-') -and (Test-Path $PassArgs[0] -PathType Container)) {
    $workDir = (Resolve-Path $PassArgs[0]).Path
    if ($PassArgs.Count -gt 1) { $piArgs.AddRange($PassArgs[1..($PassArgs.Count - 1)]) }
  } elseif ($PassArgs.Count -gt 0) {
    $piArgs.AddRange($PassArgs)
  }

  # Exact flags copied from bin/chatlab:
  #   --provider parcc --model zai-org/GLM-5.2-FP8 --approve --no-skills
  #   --skill <repo>\.pi\skills
  #   --append-system-prompt <repo>\AGENTS.md
  $skillArg   = Join-Path $RepoRoot '.pi\skills'
  $agentsArg  = Join-Path $RepoRoot 'AGENTS.md'

  # Try the env's bash running bin/chatlab first (keeps one source of truth).
  $bashLauncher = Join-Path $RepoRoot 'bin\chatlab'
  $haveBash = $false
  try {
    Invoke-Mm run -n $EnvName where.exe bash 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $haveBash = $true }
  } catch { }

  Set-Location $workDir
  if ($haveBash) {
    # micromamba run activates the env (env bin on PATH) so pi resolves.
    Invoke-Mm run -n $EnvName bash $bashLauncher @piArgs
    exit $LASTEXITCODE
  } else {
    # Replicate bin/chatlab's pi invocation directly. micromamba run activates
    # the env, putting the env's bin (where npm -g installed pi) on PATH.

    # Best-effort auto-update before launch (mirrors bin/chatlab). Keeps pi and
    # extensions current so the "Update Available" banner never shows. Skipped
    # when CHATLAB_NO_UPDATE=1, or if the update fails — never block launch.
    if ($env:CHATLAB_NO_UPDATE -ne '1') {
      try { Invoke-Mm run -n $EnvName pi update --all 2>$null | Out-Null } catch { }
    }

    Invoke-Mm run -n $EnvName pi --provider parcc --model 'zai-org/GLM-5.2-FP8' --approve --no-skills --skill $skillArg --append-system-prompt $agentsArg @piArgs
    exit $LASTEXITCODE
  }
}

# ===========================================================================
# Subcommands
# ===========================================================================

function Show-Help {
  @'
chatlab-bootstrap.ps1 — one-time slim launcher for CHATLabAI (Windows)

Bootstraps a prebuilt conda-forge environment (micromamba -> chatlab env ->
simr from CRAN -> pi via npm) under $env:CHATLAB_HOME (default
$env:USERPROFILE\.chatlab), then launches CHATLabAI. Nothing pollutes the
system. Reuses the shared packaging/environment.yml (no duplicated package list).

Usage:
  powershell -File packaging\chatlab-bootstrap.ps1                full bootstrap, then launch pi
  powershell -File packaging\chatlab-bootstrap.ps1 -Check           non-destructive self-test, then exit
  powershell -File packaging\chatlab-bootstrap.ps1 -DryRun         print steps it WOULD run, exit 0
  powershell -File packaging\chatlab-bootstrap.ps1 -Help           this message

Flags:
  -Check     Verify the environment solves and the pi config JSON merge is
             correct — WITHOUT creating the full env or touching the real
             ~/.pi. Downloads only the small micromamba binary and runs a
             conda-forge dry-run solve. Exits 0 only if every check passes.
             (On a non-Windows host the win-64 micromamba.exe can't run, so the
             solve is SKIPPED and -Check still passes as long as the config
             merge test passes.)
  -DryRun    Print each step in order and exit 0 without performing them.
  -Help      Show this help.

Environment:
  CHATLAB_HOME   Install prefix (default: $env:USERPROFILE\.chatlab).
  PARCC_API_KEY  UPenn PARCC LiteLLM API key. If unset, prompted on first run.
'@ | Write-Host
}

function Show-DryRun {
  Say "[DRY-RUN] 1. Detect platform -> conda subdir: $Subdir"
  Say "[DRY-RUN] 2. Ensure micromamba at $MmBin"
  Say "          (Invoke-WebRequest https://micro.mamba.pm/api/micromamba/$Subdir/latest | tar -xf - Library/bin/micromamba.exe)"
  Say "[DRY-RUN] 3. Create conda env '$EnvName' if missing:"
  Say "          micromamba create -n chatlab -f packaging/environment.yml (root prefix $MmRootPrefix)"
  Say "[DRY-RUN] 4. Install simr from CRAN if missing:"
  Say "          micromamba run -n chatlab Rscript -e 'install.packages(\"simr\")'"
  Say "[DRY-RUN] 5. Install pi into the env if missing:"
  Say "          micromamba run -n chatlab npm install -g @earendil-works/pi-coding-agent"
  Say "[DRY-RUN] 6. Write pi config (parcc provider block + key) to ~/.pi/agent/models.json"
  Say "          (pi config merge: preserve other providers/models)"
  Say "[DRY-RUN] 7. Set up callosum (local reference manager + MCP) at $CallosumHome:"
  Say "          git clone $CallosumRepo"
  Say "          mm run -n chatlab python -m venv ~/callosum/.venv && pip install -r requirements.txt"
  Say "          mm run -n chatlab python -m venv ~/callosum/.mcp-venv && pip install -r mcp_server/requirements.txt"
  Say "          npm install + build_frontend.py (web UI)"
  Say "          register callosum MCP server in ~/.pi/agent/mcp.json (preserve other servers)"
  Say "[DRY-RUN] 8. Launch:"
  Say "          micromamba run -n chatlab (bash bin/chatlab | pi ...)  [launch CHATLabAI]"
  exit 0
}

function Invoke-Check {
  # Non-destructive self-test. Must NOT create the chatlab env, must NOT modify
  # the real $env:USERPROFILE\.pi, must NOT download 1.5GB. MAY download
  # micromamba (but the win-64 binary can't run on a non-Windows host).
  $failed = $false
  Say 'Running non-destructive self-test...'
  Say "PLATFORM: $Subdir"

  # --- ENV SOLVE: dry-run create for win-64 --------------------------------
  # The win-64 micromamba.exe only runs on Windows. On a non-Windows host we
  # cannot execute it, so degrade gracefully: skip the solve and still run the
  # config-merge test, then pass.
  $isWindows = ($PSVersionTable.Platform -ne 'Unix' -and $PSVersionTable.OS -notmatch 'Linux|Darwin')
  # $PSVersionTable.Platform is 'Win*' or absent on Windows PowerShell; on pwsh
  # it is 'Unix' on Linux/macOS. Also guard via the env var.
  if (-not $isWindows) { $isWindows = ($PSVersionTable.PSEdition -eq 'Desktop') }

  $mmReady = $false
  if ($isWindows) {
    try { Ensure-Micromamba | Out-Null; $mmReady = $true } catch { Warn "micromamba setup failed: $($_.Exception.Message)" }
  } else {
    Say 'ENV SOLVE: SKIPPED (non-Windows host)'
  }

  if ($isWindows -and $mmReady -and (Test-Path $MmBin)) {
    Say "MICROMAMBA: $((& $MmBin --version 2>&1 | Select-Object -First 1))"
    $solveOut = $null
    try {
      $solveOut = Invoke-Mm create --dry-run -n probe -f $EnvYml 2>&1
    } catch {
      $solveOut = $_.Exception.Message
    }
    $solveRc = $LASTEXITCODE
    if ($solveOut -match '(?i)could not solve|does not exist|conflict|failed') {
      Warn 'ENV SOLVE: FAILED — solver reported a problem:'
      ($solveOut -split "`n" | Select-Object -Last 20) | ForEach-Object { Write-Host "    $_" }
      $failed = $true
    } elseif ($solveRc -ne 0) {
      Warn "ENV SOLVE: FAILED — micromamba create --dry-run exited $solveRc"
      ($solveOut -split "`n" | Select-Object -Last 20) | ForEach-Object { Write-Host "    $_" }
      $failed = $true
    } else {
      Say 'ENV SOLVE: OK'
    }
  } elseif ($isWindows) {
    Warn 'ENV SOLVE: SKIPPED (micromamba unavailable)'
    $failed = $true
  }

  # --- CONFIG JSON: Write-PiConfig against a TEMP profile, verify with python3 --
  # Use a temp USERPROFILE so the real ~/.pi is never touched.
  $tempProfile = Join-Path ([System.IO.Path]::GetTempPath()) ("chatlab-check-" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tempProfile | Out-Null
  $oldProfile = $env:USERPROFILE
  $env:USERPROFILE = $tempProfile
  $tmpCfg = Join-Path $tempProfile '.pi\agent\models.json'

  $mergeOk = $true
  try {
    Write-PiConfig -Key 'DUMMYKEY123'
  } catch {
    Warn "CONFIG JSON: FAILED — Write-PiConfig errored: $($_.Exception.Message)"
    $mergeOk = $false
  }
  $env:USERPROFILE = $oldProfile

  if ($mergeOk -and (Test-Path $tmpCfg)) {
    # Verify with the chosen python (env python if available, else system).
    $py = Get-PyForConfig
    $verifyPy = @'
import json, sys
cfg = json.load(open(sys.argv[1]))
p = cfg["providers"]["parcc"]
assert p["baseUrl"] == "https://litellm.parcc.upenn.edu/v1", p.get("baseUrl")
assert p["apiKey"] == "DUMMYKEY123", p.get("apiKey")
assert p["api"] == "openai-completions", p.get("api")
ids = [m["id"] for m in p["models"]]
assert "zai-org/GLM-5.2-FP8" in ids, ids
print("CONFIG JSON: OK")
'@
    $tmpVerify = (Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N') + '.py'))
    Set-Content -Path $tmpVerify -Value $verifyPy -Encoding UTF8
    $verifyOut = $null
    try {
      if ($py.UseEnv) {
        $verifyOut = Invoke-Mm run -n $EnvName python $tmpVerify $tmpCfg 2>&1
      } else {
        $verifyOut = & python $tmpVerify $tmpCfg 2>&1
      }
      $vrc = $LASTEXITCODE
    } catch {
      $verifyOut = $_.Exception.Message
      $vrc = 1
    } finally {
      Remove-Item -Force $tmpVerify -ErrorAction SilentlyContinue
    }
    if ($vrc -eq 0 -and "$verifyOut" -match 'CONFIG JSON: OK') {
      Say 'CONFIG JSON: OK'
    } else {
      Warn 'CONFIG JSON: FAILED — verification (baseUrl/apiKey/model id) did not pass'
      Write-Host "    $verifyOut"
      $failed = $true
    }
  } else {
    Warn "CONFIG JSON: FAILED — models.json not written to $tmpCfg"
    $failed = $true
  }

  # Clean up temp profile.
  Remove-Item -Recurse -Force $tempProfile -ErrorAction SilentlyContinue

  if (-not $failed) {
    Say 'CHECK PASSED'
    exit 0
  } else {
    Warn 'CHECK FAILED — see messages above.'
    exit 1
  }
}

function Invoke-Full {
  Say 'Setting up CHATLabAI (one-time, ~1.5 GB)...'
  Ensure-Micromamba
  Ensure-Env
  Ensure-Simr
  Ensure-Pi
  Ensure-PiConfig
  Ensure-Callosum
  Launch-Lab -PassArgs @($script:PassThroughArgs)
}

# ---------------------------------------------------------------------------
# Arg dispatch.
# ---------------------------------------------------------------------------
# Collect any non-switch args to pass through to the launcher.
$script:PassThroughArgs = @($args | Where-Object { $_ -isnot [switch] })

if ($Help) { Show-Help; exit 0 }
if ($DryRun) { Show-DryRun }   # exits
if ($Check) { Invoke-Check }   # exits
Invoke-Full
