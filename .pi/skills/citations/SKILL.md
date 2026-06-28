---
name: citations
description: Check citations, validate references, organize the bibliography, any retracted papers, fix the bib, convert to CSL, reconcile in-text cites with the .bib. Validate DOIs via Crossref and flag retractions via OpenAlex.
---

# Citations

## Purpose

Validate and organize references; catch retractions; reconcile in-text cites with the master
BibTeX. Free APIs only — Crossref (DOI resolution) and OpenAlex (retraction flags). No external auth.

## When to use

- "check my citations"
- "validate references" / "any retracted papers?"
- "organize the bibliography" / "fix the bib"
- "reconcile in-text cites with the .bib"
- "convert to CSL-JSON"

## Usage

```bash
# Full report on the master BibTeX (resolve DOIs, flag retractions, dedup)
python3 scripts/cite_check.py references/library.bib

# Also reconcile against a manuscript (find missing/uncited keys)
python3 scripts/cite_check.py references/library.bib --manuscript draft.docx
python3 scripts/cite_check.py references/library.bib --manuscript paper.tex

# Export CSL-JSON alongside the report
python3 scripts/cite_check.py references/library.bib --to-csl references/library.csl.json

# Offline / local-only (skip network resolution entirely)
python3 scripts/cite_check.py references/library.bib --offline
```

## What it checks

1. **DOI resolution** — every `doi={...}` field resolved via Crossref
   (`api.crossref.org/works/{doi}`). Reports unresolved / malformed DOIs.
2. **Retraction / correction flags** — OpenAlex (`api.openalex.org/works/doi:{doi}`) →
   `is_retracted` field + update-notice types.
3. **Dedup** — entries with the same normalized DOI or title.
4. **Reconciliation** — scans the manuscript for in-text keys:
   - LaTeX: `\cite{key}`, `\citep{...}`, `\citet{...}` (also comma-separated lists).
   - Prose / Word (`.docx`): `(Author, Year)` and `(Author et al., Year)` heuristic via python-docx.
   Reports cites missing from the `.bib` and bib entries never cited.
5. **BibTeX → CSL-JSON** conversion (`--to-csl`).

## Polite API use

- `User-Agent: CHATLabAI/1.0 (mailto:chatlab@pennmedicine.upenn.edu)` (Crossref "plus" politeness).
- Rate-limited (sleep between requests).
- Responses cached under `.cache/cite_check/` (created as needed; keyed by DOI+source).

## Graceful degradation

If Crossref / OpenAlex is unreachable (no network, offline), the script prints a clear message and
still reports all **local-only** checks: malformed DOIs, dedup, and in-text reconciliation. If
`pybtex` is not installed, a built-in stdlib BibTeX parser is used so local checks always work;
`--to-csl` still produces valid CSL-JSON from that parser.

## Safety

Read-only by default. `--to-csl` writes a single JSON file to the path you specify; it never
overwrites the `.bib` itself. Reconciliation is non-destructive — it only reports.
