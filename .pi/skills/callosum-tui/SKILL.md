---
name: callosum-tui
description: "Drive the full callosum library from the terminal: manage the library, wanted list, reading queue, tags, axes, citation gaps, feed, methods audits (statcheck, GRIM, p-curve, retraction, transparency, citation equity, LMM), summaries, my-publications dashboard, duplicates, scans, OCR. Use for any callosum feature the MCP tools don't cover — 'show my wanted list', 'add to reading queue', 'tag this paper', 'run statcheck on the library', 'check retractions', 'refresh my gaps', 'who cites me', 'find duplicates', 'is callosum healthy'."
---

# Callosum TUI

The callosum MCP tools cover search/read plus four writes. For **everything else** in
callosum — wanted list, reading queue, gaps, feed, methods audits, summaries, dashboards,
library ops — drive the terminal client. It exposes every feature of the running app as one-shot
subcommands generated from a single registry.

## Invocation

Always this shape (agent mode + JSON, from the callosum checkout):

```bash
cd ~/callosum && .venv/bin/python -m tui --agent <group> <action> [flags] --format json
```

`--agent` is **mandatory** for you: it restricts writes to callosum's gated, audited, revertible
`/agent/*` endpoints and refuses everything destructive. Never run without `--agent`; if a task
needs a human-only action (delete, merge, metadata edit, adding to the wanted list), tell Anjan
what to run or point him at the web UI / interactive TUI (`python -m tui`, numbered menus).

Discover anything: `python -m tui --help`, `python -m tui <group> --help`.

## Groups

`papers` `fulltext` `discovery` `wanted` `queue` `tags` `gaps` `methods` `citations`
`summaries` `mypubs` `library` `status`

## Worked examples

```bash
# Library
… --agent papers list --q "beauty" --limit 20 --format json
… --agent papers get 42 --format json
… --agent fulltext search --q "default mode network" --format json

# Wanted list & reading queue (reads; adding to /wanted is a user action — see below)
… --agent wanted list --format json
… --agent wanted coverage --format json
… --agent queue list --format json

# The four audited writes (all revertible; each returns a write_id)
… --agent tags add 42 --tag "predictive-processing" --format json
… --agent tags axis-add-paper 3 --paper-id 42 --format json
… --agent papers save-reference --identifier "10.1093/brain/awt162" --format json
… --agent papers annotate 42 --text "Key for the framing section." --format json

# Audit trail
… --agent status agent-writes --format json
… --agent status agent-revert <write_id> --format json

# Gaps, methods audits, dashboards (job endpoints poll to completion; --no-wait to submit only)
… --agent gaps list --format json
… --agent gaps refresh --format json
… --agent methods statcheck 42 --format json
… --agent methods retraction-summary --format json
… --agent mypubs dashboard --format json
```

## Rules

- **Adding to the wanted list is a user action** (same rule as `knowledge/callosum.md`): agent
  mode refuses `wanted add`. To bring a paper in yourself, use `papers save-reference` with its
  DOI (audited), or give Anjan the one-liner to run.
- Writes need the gate: if a write exits 3 saying agent writes are disabled, tell Anjan to
  enable them in callosum Settings → AI agent. Check first with `status agent-status`.
- If callosum is down (exit 2, "isn't reachable"), fall back to OpenAlex/Crossref for discovery
  questions and tell Anjan to start callosum:
  `cd ~/callosum && .venv/bin/uvicorn app.backend.api.app:app --host 127.0.0.1 --port 8080`
- Job commands (`gaps refresh`, `methods statcheck-run`, `library scan`…) block until done by
  default. For long ones pass `--no-wait`, tell Anjan it's running, and poll later with the
  matching status action and the returned `job_id`.
- Prefer the callosum MCP tools when they cover the task (search_library, find_passages,
  format_citation…) — they're cheaper than shelling out. This skill is for the rest of the
  surface.
- Escape hatches when a flag isn't modeled: `--extra-query k=v` and `--body '<json>'`.
