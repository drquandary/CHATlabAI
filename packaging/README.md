# CHATLabAI packaging — slim launcher

This directory holds the **slim launcher** for CHATLabAI: a one-time bootstrap that
sets up everything CHATLabAI needs from a **prebuilt conda-forge** environment, so a
first-time user does no manual dependency setup. Nothing pollutes the system —
micromamba, the conda environment, and `pi` all install under a private prefix at
`~/.chatlab` (override with `CHATLAB_HOME`).

```
packaging/
├── environment.yml              # single source of truth for the package list
├── chatlab-bootstrap.sh         # macOS / Linux launcher
├── chatlab-bootstrap.ps1        # Windows launcher (faithful port)
├── chatlab.cmd                   # double-click entry point (Windows)
├── parity_check.py              # keeps .sh and .ps1 in lockstep
└── CHATLabAI.app/                # minimal unsigned macOS .app bundle
```

## What it does

1. **micromamba** — downloads the static micromamba binary into `~/.chatlab/bin`.
2. **conda-forge env** — creates a `chatlab` env from `environment.yml` (prebuilt for
   osx-arm64 / osx-64 / linux-64 / linux-aarch64 / win-64), so there's no local
   compilation. This is the heavy step (~1.5 GB, one-time).
3. **simr from CRAN** — `r-simr` is the one package not on conda-forge, so it is
   installed from CRAN after the env exists (pure R, no toolchain). On macOS the
   pure-R helpers `RLRsim` and `binom` come along too.
4. **pi via npm** — installs `@earendil-works/pi-coding-agent` into the env prefix
   (global npm inside the env, not the system), so `pi` lands on the env's PATH.
5. **parcc provider config** — writes the UPenn `parcc` LiteLLM provider block into
   `~/.pi/agent/models.json` (model `zai-org/GLM-5.2-FP8`), merging without
   clobbering any other providers you may have configured.

## First-run expectations

- **One-time ~1.5 GB download** of the conda-forge environment. Subsequent launches
  skip every step that's already done (idempotent).
- You will be asked to **paste your PARCC API key once** (it is a per-user secret
  and is never hardcoded). Set `PARCC_API_KEY` in your environment to skip the
  prompt.
- The backend (`https://litellm.parcc.upenn.edu/v1`) **requires UPenn network/VPN
  access**. On the launch line you'll see a note reminding you of this.

## How to run

### macOS
- **Double-click** `packaging/CHATLabAI.app`. The first time, macOS Gatekeeper will
  block the unsigned bundle — **right-click → Open**, confirm, and from then on it
  launches normally. The app opens a Terminal window running the bootstrap so you
  get a real terminal for pi's TUI and the one-time key prompt.
- Or from the command line: `bash packaging/chatlab-bootstrap.sh`

### Windows
- **Double-click** `packaging/chatlab.cmd`.
- Or from PowerShell:
  `powershell -ExecutionPolicy Bypass -File packaging\chatlab-bootstrap.ps1`

### Linux
- `bash packaging/chatlab-bootstrap.sh`

## The non-destructive self-test

Run `bash packaging/chatlab-bootstrap.sh --check` (macOS/Linux) or
`packaging\chatlab-bootstrap.ps1 -Check` (Windows) to verify the setup **without
downloading the ~1.5 GB env or touching your real `~/.pi` config**. It:

- **ENV SOLVE** — runs a `micromamba create --dry-run` against `environment.yml`
  for your platform and confirms the package set solves on conda-forge.
- **CONFIG JSON** — writes the parcc provider block to a *temporary* profile dir
  and verifies the merged `models.json` has the correct `baseUrl`, `apiKey`, `api`
  type, and model id (`zai-org/GLM-5.2-FP8`).
- Prints `CHECK PASSED` and exits 0 only if both pass. (On a non-Windows host the
  Windows `-Check` skips the win-64 solve but still runs + passes the config test.)

## Dev notes

- **`environment.yml` is the single source of truth** for the package list. Neither
  launcher hardcodes its own R/Python package list — both read this file. Edit it
  once and both platforms pick up the change.
- **`parity_check.py`** (`python3 packaging/parity_check.py`) asserts the `.sh` and
  `.ps1` launchers stay in lockstep: same provider constants, same logical steps,
  same help/check/dry-run entry points, and that neither duplicates the package
  list. Run it after touching either launcher.
- **`simr` is the only CRAN top-up** (not on conda-forge). Everything else — R base,
  pwr/lme4/afex/ggplot2, pandoc, nodejs, and the full Python stat stack — comes from
  the prebuilt conda-forge env.

## Exit behaviours

| Invocation | Behaviour |
|---|---|
| `bash chatlab-bootstrap.sh` (no args) | Full bootstrap (if needed) then launch pi. |
| `--check` / `-Check` | Non-destructive self-test; print `CHECK PASSED`, exit 0 only if all pass. |
| `--dry-run` / `-DryRun` | Print the 7 steps it would run, in order; exit 0. Does nothing. |
| `--help` / `-Help` | Print usage; exit 0. |
| macOS double-click `CHATLabAI.app` | Opens Terminal running the no-arg bootstrap. |
| Windows double-click `chatlab.cmd` | Runs the no-arg bootstrap via PowerShell. |
