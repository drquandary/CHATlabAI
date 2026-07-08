# setup-win.ps1 — CHATLabAI self-contained first-run setup + launch (Windows).
#
# Shipped INSIDE the self-extracting installer alongside env.tar.gz + repo.tar.gz.
# On first run it unpacks the embedded environment + repo under the user's
# profile, writes a private pi config (prompting once for the PARCC key — the
# key is NOT baked into this build), and launches CHATLabAI from the embedded
# env. No micromamba, no repo download, no bundle download. Later runs skip
# straight to launch.
#
# CHATLAB_SMOKE=1 → set up then print `pi --version` and exit (CI validation,
# no interactive launch, no key needed).
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Use Windows' NATIVE tar (bsdtar in System32), NOT a msys/GNU tar that may be on
# PATH — GNU tar reads a Windows path like "D:\...\env.tar.gz" as a remote host
# "D:" (fails with "Cannot connect to D:"). bsdtar handles drive letters fine.
$tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path $tarExe)) { $tarExe = 'tar' }

$ChatlabHome = Join-Path $env:USERPROFILE '.chatlab'
$EnvPrefix   = Join-Path $ChatlabHome 'mm\envs\chatlab'
$Repo        = Join-Path $env:USERPROFILE 'CHATLabAI'
$PiAgent     = Join-Path $ChatlabHome 'pi-agent'

function Banner($msg) {
  try { Clear-Host } catch {}
  Write-Host ''
  Write-Host '   ==================================================' -ForegroundColor DarkGray
  Write-Host '    CHATLabAI  -  Penn Center for Neuroaesthetics' -ForegroundColor Cyan
  Write-Host '   ==================================================' -ForegroundColor DarkGray
  Write-Host ''
  Write-Host "    -> $msg" -ForegroundColor Cyan
  Write-Host ''
}

# --- 1. environment (one-time unpack of the embedded tarball) ---------------
$envPi = Join-Path $EnvPrefix 'pi.cmd'
if (-not (Test-Path $envPi)) {
  Banner 'Setting up CHATLabAI for the first time - a few minutes, then instant.'
  New-Item -ItemType Directory -Force -Path $EnvPrefix | Out-Null
  Write-Host '      Unpacking the environment...'
  & $tarExe -xzf (Join-Path $here 'env.tar.gz') -C $EnvPrefix
  if ($LASTEXITCODE -ne 0) { throw 'Failed to unpack the environment.' }
  Write-Host '      Finalizing...'
  $unpackExe = Join-Path $EnvPrefix 'Scripts\conda-unpack.exe'
  $unpackPy  = Join-Path $EnvPrefix 'Scripts\conda-unpack'
  $envPyExe  = Join-Path $EnvPrefix 'python.exe'
  if (Test-Path $unpackExe) { & $unpackExe }
  elseif ((Test-Path $envPyExe) -and (Test-Path $unpackPy)) { & $envPyExe $unpackPy }
}

# --- 2. repo (skills, launcher, persona) ------------------------------------
if (-not (Test-Path (Join-Path $Repo '.pi'))) {
  New-Item -ItemType Directory -Force -Path $Repo | Out-Null
  & $tarExe -xzf (Join-Path $here 'repo.tar.gz') -C $Repo
  if ($LASTEXITCODE -ne 0) { throw 'Failed to unpack CHATLabAI.' }
}

# --- 3. private pi config (prompt once for the PARCC key if missing) ---------
$models = Join-Path $PiAgent 'models.json'
if (-not (Test-Path $models)) {
  New-Item -ItemType Directory -Force -Path $PiAgent | Out-Null
  $key = $env:PARCC_API_KEY
  if (-not $key) {
    Write-Host ''
    Write-Host '    One-time setup: paste your PARCC API key (from the lab), then press Enter.' -ForegroundColor Yellow
    $key = Read-Host '    PARCC API key'
  }
  if (-not $key) { throw 'No PARCC API key provided.' }
  $json = @"
{
  "providers": {
    "parcc": {
      "baseUrl": "https://litellm.parcc.upenn.edu/v1",
      "api": "openai-completions",
      "apiKey": "$key",
      "models": [{ "id": "zai-org/GLM-5.2-FP8", "name": "GLM 5.2 FP8", "contextWindow": 1048576 }]
    }
  }
}
"@
  Set-Content -Path $models -Value $json -Encoding ascii
}

# --- 4. launch (or smoke-test) ----------------------------------------------
$env:PI_CODING_AGENT_DIR = $PiAgent
$env:PATH = "$EnvPrefix;$EnvPrefix\Scripts;$env:PATH"

if ($env:CHATLAB_SMOKE -eq '1') {
  Write-Host 'SMOKE: pi version =' (& (Join-Path $EnvPrefix 'pi.cmd') --version)
  if (Test-Path (Join-Path $EnvPrefix 'docx.exe')) { Write-Host 'SMOKE: docx version =' (& (Join-Path $EnvPrefix 'docx.exe') --version) }
  Write-Host 'SMOKE: OK'
  exit 0
}

& (Join-Path $EnvPrefix 'pi.cmd') `
  --provider parcc --model 'zai-org/GLM-5.2-FP8' --approve --no-skills `
  --skill (Join-Path $Repo '.pi\skills') `
  --append-system-prompt (Join-Path $Repo 'AGENTS.md') `
  --extension (Join-Path $Repo '.pi\extensions\welcome.ts')
