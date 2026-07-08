; chatlab.nsi — NSIS script for the self-contained CHATLabAI Windows installer.
;
; Bundles the prebuilt Windows environment (env.tar.gz), the CHATLabAI repo
; (repo.tar.gz), and setup-win.ps1 into ONE double-clickable .exe. Running it
; extracts those to a per-user staging dir and launches setup-win.ps1 in a
; console (which unpacks the env under %USERPROFILE%\.chatlab, writes config —
; prompting once for the PARCC key — and launches CHATLabAI). One file, one
; double-click. No admin, no network for setup.
;
; Built in CI: env.tar.gz / repo.tar.gz / setup-win.ps1 are placed next to this
; script, then `makensis chatlab.nsi` produces CHATLabAI-win.exe.

Unicode true
Name "CHATLabAI"
OutFile "CHATLabAI-win.exe"
InstallDir "$LOCALAPPDATA\CHATLabAI\stage"
RequestExecutionLevel user
SilentInstall silent           ; no wizard — just stage the payload and run
SetCompress off                ; payload is already gzip-compressed; don't re-compress

Section
  SetOutPath "$INSTDIR"
  File "env.tar.gz"
  File "repo.tar.gz"
  File "setup-win.ps1"
  ; Open a console window running the setup+launch so pi's TUI has a terminal.
  Exec 'cmd.exe /c start "CHATLabAI" cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\setup-win.ps1"'
SectionEnd
