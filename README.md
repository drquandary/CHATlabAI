# CHATLabAI

> A research-assistant workspace for the **Penn Center for Neuroaesthetics**
> (Anjan Chatterjee Lab). Built as a **[pi](https://pi.dev) workspace**: launching pi from
> this directory turns it into **CHATLabAI** — a research assistant with skills for manuscript
> review, track-changes editing, citation checking, literature review, journal formatting,
> power analysis, statistics, data visualization, data organization, and a lab calendar.

## What it is

CHATLabAI is *not* a new terminal UI — it is a **pi workspace**. The `AGENTS.md` persona,
`.pi/skills/`, and `.pi/settings.json` make a plain `pi` launch behave as the lab assistant,
pinned to the **GLM-5.2** model on the Penn `parcc` proxy.

### Skills

| Skill | What it does |
|-------|--------------|
| `paper-review` | Review a manuscript against Chatterjee's 12 writing rules |
| `agentic-edit` | Surgical track-changes editing of `.docx` (real Word revisions, author = CHATLabAI) |
| `citations` | Validate/reconcile references; catch retractions (Crossref/OpenAlex) |
| `lit-review` | Neuroaesthetics literature review from free scholarly APIs (OpenAlex/PubMed/Crossref) |
| `journal-format` | Format a manuscript for a target journal (pandoc + CSL) |
| `power-analysis` | Sample size / power, analytic + simulation (R `pwr`/`simr`, Python statsmodels) |
| `basic-analysis` | Descriptives + inferential tests with assumption checks (Python + R) |
| `data-viz` | Publication figures + brain maps in a consistent lab style |
| `data-organize` | BIDS-friendly data tree, inventory, dry-run move plan |
| `lab-calendar` | Self-contained lab calendar (`.ics` + readable mirror) |

### Principles

- **Free APIs only** (OpenAlex, Crossref, PubMed E-utilities). No MCP / no claude.ai / no Google auth.
- **No credential beyond the `parcc` key** already configured in pi.
- **Dry-run by default** for any destructive operation; plans are printed and require `--apply`.
- **Mechanism-cautious prose**: writing rules are enforced verbatim (see `knowledge/chatterjee-writing-rules.md`).

---

## Install (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/drquandary/CHATlabAI/main/install.sh | bash
```

…then `cd` into the cloned repo and launch. Or, after cloning:

```bash
git clone https://github.com/drquandary/CHATlabAI.git
cd CHATlabAI
./install.sh
```

The installer is portable (macOS/Linux), idempotent, and keeps dependencies in a project-local
Python venv + an R user library (no system pollution). It installs:

- **Python**: `python-docx lxml pandas pingouin statsmodels nilearn matplotlib seaborn icalendar requests pybtex`
- **R**: `pwr simr lme4 afex ggplot2`
- **pandoc** (system binary, for `journal-format`)

> Requires **[pi](https://pi.dev)**: `npm i -g @earendil-works/pi-coding-agent`.

### Configure the backend (once)

The `parcc` provider points at `https://litellm.parcc.upenn.edu/v1` (OpenAI-compatible).
Add it to your pi global config (`~/.pi/agent/models.json` or via `pi config`).

**Never paste a raw key into a file.** Export it as an environment variable and let pi
interpolate it (`$ENV_VAR` syntax) — this keeps the key out of any config file:

```bash
# put this in your ~/.zshrc or ~/.bashrc (one time)
export PARCC_API_KEY="your-parcc-key-here"
```

```json
{
  "providers": {
    "parcc": {
      "baseUrl": "https://litellm.parcc.upenn.edu/v1",
      "api": "openai-completions",
      "apiKey": "$PARCC_API_KEY",
      "models": [{ "id": "zai-org/GLM-5.2-FP8", "name": "GLM 5.2 FP8", "contextWindow": 1048576 }]
    }
  }
}
```

> No API key is stored in this repo. `CHATLabAI/.pi/settings.json` only pins the provider/model
> *names* (`parcc` / `zai-org/GLM-5.2-FP8`); the key lives only in your environment via
> `$PARCC_API_KEY`, referenced by your global pi config.

---

## Launch

```bash
./bin/chatlab                # from the workspace root
# or, after symlinking bin/chatlab onto PATH:
chatlab
```

Then ask naturally, e.g.:

- *"review this draft for overclaiming"*
- *"track changes on this docx, preserve my voice"*
- *"power for a mixed model, d=0.4"*
- *"find papers on neuroaesthetics face beauty"*
- *"format this for the Journal of Cognitive Neuroscience"*
- *"organize this data folder into BIDS"*

## Workspace layout

```
CHATLabAI/
├── AGENTS.md                    # persona + project context (auto-loaded by pi)
├── README.md                    # this file
├── install.sh                   # one-command dependency installer
├── bin/chatlab                  # launcher (chmod +x)
├── .pi/
│   ├── settings.json            # pins provider/model
│   ├── agents/chatlab.md        # named agent persona
│   └── skills/*                 # the 10 skills
├── knowledge/                   # writing rules, journals, lab info, glossary
├── references/library.bib       # master BibTeX
├── calendar/                    # .ics + readable mirror
├── data/                         # organized data root (BIDS-friendly)
└── projects/                    # per-manuscript working dirs
```

## Development

Each skill lives in `.pi/skills/<name>/` with a `SKILL.md` (YAML frontmatter + instructions)
and `scripts/`. Scripts are `argparse`-driven (Python) or `Rscript` (R), with `--help`.

```bash
# Example: run a skill's script directly
python3 .pi/skills/paper-review/scripts/lint_claims.py draft.docx --help
```

## License

MIT — see [LICENSE](LICENSE).
