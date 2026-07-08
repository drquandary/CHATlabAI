@echo off
REM get-chatlab.cmd — standalone CHATLabAI installer (Windows).
REM
REM The ONLY file a new user needs: it downloads the CHATLabAI repository
REM (no git required), then runs packaging\chatlab-bootstrap.ps1, which
REM installs everything else (micromamba env, R/Python stack, pi, docx-cli,
REM callosum) and launches CHATLabAI. Double-click to run.
REM
REM EMBEDDED_PARCC_API_KEY is stamped by make-lab-installer.sh into
REM LAB-DISTRIBUTED copies only. MUST stay EMPTY in the repository — this
REM file is public on GitHub.
setlocal EnableExtensions
cls
echo.
echo    ==================================================
echo     CHATLabAI  -  Penn Center for Neuroaesthetics
echo    ==================================================
echo.
echo     -^> Getting CHATLabAI...
echo.
set "EMBEDDED_PARCC_API_KEY="
if not defined PARCC_API_KEY if defined EMBEDDED_PARCC_API_KEY set "PARCC_API_KEY=%EMBEDDED_PARCC_API_KEY%"
if not defined CHATLAB_REPO set "CHATLAB_REPO=%USERPROFILE%\CHATLabAI"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $dest=$env:CHATLAB_REPO; if (Test-Path (Join-Path $dest 'packaging\chatlab-bootstrap.ps1')) { Write-Host ('[chatlab] Repository already present at ' + $dest) } else { Write-Host '[chatlab] Downloading CHATLabAI...'; $zip=Join-Path $env:TEMP 'chatlab-main.zip'; Invoke-WebRequest -Uri 'https://github.com/drquandary/CHATlabAI/archive/refs/heads/main.zip' -OutFile $zip -UseBasicParsing; $tmp=Join-Path $env:TEMP ('chatlab-'+[guid]::NewGuid().ToString('N')); Expand-Archive -Path $zip -DestinationPath $tmp -Force; $un=Get-ChildItem -Directory $tmp | Select-Object -First 1; New-Item -ItemType Directory -Force -Path $dest | Out-Null; Copy-Item -Path (Join-Path $un.FullName '*') -Destination $dest -Recurse -Force; Remove-Item -Force $zip; Remove-Item -Recurse -Force $tmp; Write-Host ('[chatlab] Repository ready at ' + $dest) }"
if errorlevel 1 (
  echo [chatlab] ERROR: download failed. Are you online?
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%CHATLAB_REPO%\packaging\chatlab-bootstrap.ps1" %*
pause
