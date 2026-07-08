# setup-win.ps1 — CHATLabAI one-click first-run setup + launch (Windows).
#
# Shipped inside the CHATLabAI-win.exe (NSIS) alongside repo.tar.gz. On first
# run it DOWNLOADS the prebuilt Windows environment from Google Drive (the big
# part — the installer itself stays small so NSIS can build it), unpacks it +
# the repo under the user's profile, writes a private pi config (prompting once
# for the PARCC key — not baked into this build), and launches CHATLabAI from
# the downloaded env. No micromamba, no repo download. Later runs skip to launch.
#
# CHATLAB_SMOKE=1 → set up then print `pi --version` and exit (CI validation).
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Prebuilt win-64 environment on Google Drive (verified download + checksum).
$BundleUrl = 'https://drive.google.com/file/d/1FRMHbF8mEmjyMIVYS-Aa_27TPpBbb-8C/view?usp=share_link'
$BundleSha = 'acb96941c681ec92972fb996c267c36be04b04b27a12dce6a97a866db99cefba'

# Native Windows tar (bsdtar); a msys/GNU tar misreads "C:\..." as a remote host.
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

# Extract a Google Drive file id from a share link.
function Get-GDriveId([string]$Url) {
  if ($Url -match '/file/d/([^/?]+)') { return $Matches[1] }
  if ($Url -match '[?&]id=([^&]+)')   { return $Matches[1] }
  return ''
}

# --- 1. environment (download from Drive + unpack, one-time) -----------------
$envPi = Join-Path $EnvPrefix 'pi.cmd'
if (-not (Test-Path $envPi)) {
  Banner 'Setting up CHATLabAI for the first time - a few minutes, then instant.'
  New-Item -ItemType Directory -Force -Path $EnvPrefix | Out-Null
  $envTar = Join-Path $env:TEMP 'chatlab-env-win64.tar.gz'
  if (-not (Test-Path $envTar)) {
    Write-Host '      Downloading the environment (~1 GB, one-time)...'
    $id = Get-GDriveId $BundleUrl
    $dl = "https://drive.usercontent.google.com/download?id=$id&export=download&confirm=t"
    Invoke-WebRequest -Uri $dl -OutFile $envTar -UseBasicParsing
    # Reject an HTML interstitial (must be gzip 1f 8b).
    $fs = [System.IO.File]::OpenRead($envTar); $b0 = $fs.ReadByte(); $b1 = $fs.ReadByte(); $fs.Close()
    if (-not ($b0 -eq 0x1f -and $b1 -eq 0x8b)) { throw 'Environment download did not return a valid archive (Drive sharing must be "anyone with the link").' }
    $got = (Get-FileHash -Algorithm SHA256 -Path $envTar).Hash.ToLower()
    if ($got -ne $BundleSha.ToLower()) { throw "Environment checksum mismatch (got $got)." }
  }
  Write-Host '      Unpacking the environment...'
  & $tarExe -xzf $envTar -C $EnvPrefix
  if ($LASTEXITCODE -ne 0) { throw 'Failed to unpack the environment.' }
  Write-Host '      Finalizing...'
  $unpackExe = Join-Path $EnvPrefix 'Scripts\conda-unpack.exe'
  $unpackPy  = Join-Path $EnvPrefix 'Scripts\conda-unpack'
  $envPyExe  = Join-Path $EnvPrefix 'python.exe'
  if (Test-Path $unpackExe) { & $unpackExe }
  elseif ((Test-Path $envPyExe) -and (Test-Path $unpackPy)) { & $envPyExe $unpackPy }
  Remove-Item -Force $envTar -ErrorAction SilentlyContinue
}

# --- 2. repo (skills, launcher, persona) — embedded in the installer --------
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
