---
name: lit-review
description: Literature review, find papers on, what's known about, neuroaesthetics lit, search the literature, annotated bibliography. Searches OpenAlex, PubMed, and Crossref (free APIs, no auth), dedups by DOI, ranks by relevance+citations+recency, and writes an annotated review.md plus appends BibTeX.
---

# lit-review

Neuroaesthetics literature reviews from free scholarly APIs → annotated bibliography + BibTeX.

## When to use

- "find papers on X", "what's known about Y", "literature review", "annotated bibliography"
- Building a reference base for a manuscript or grant.
- Scoping what exists on a neuroaesthetics topic before writing.

## What it does

1. Queries three free scholarly APIs (no auth required):
   - **OpenAlex** — `api.openalex.org/works?search=...` (concepts, citation counts, abstracts).
   - **PubMed E-utilities** — `eutils.ncbi.nlm.nih.gov/entrez/eutils/` (esearch → esummary).
   - **Crossref** — `api.crossref.org/works?query=...` (bibliographic metadata).
2. Merges and deduplicates results by DOI.
3. Ranks by a blend of **relevance** (token overlap + API relevance score),
   **citation count** (log-scaled), and **recency**.
4. Caps at N (default 25) results.
5. Writes:
   - `review.md` — annotated entries: title, authors, year, venue, DOI link, 2–3 line summary, why-relevant.
   - Appends BibTeX to `references/library.bib` (skips DOIs already present — no duplicates).

## Usage

```bash
# Basic search
python3 .pi/skills/lit-review/scripts/litsearch.py "neuroaesthetics face beauty" --n 25

# Limit to recent papers
python3 .pi/skills/lit-review/scripts/litsearch.py "aesthetic triad" --n 15 --since 2015

# Custom seed terms (default loads from knowledge/lab-info.md)
python3 .pi/skills/lit-review/scripts/litsearch.py "beauty perception" --seed-terms "beauty,faces,art"

# Custom BibTeX output
python3 .pi/skills/lit-review/scripts/litsearch.py "empirical aesthetics" --bib references/library.bib --out my-review.md
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `query` | (required) | Search query |
| `--n` | 25 | Max results to return |
| `--since` | (none) | Only papers from this year onward (e.g. `2015`) |
| `--bib` | `references/library.bib` | BibTeX file to append to |
| `--seed-terms` | from `knowledge/lab-info.md` | Comma-separated seed terms |
| `--out` | `review.md` | Output review path |
| `--no-bib` | (flag) | Skip BibTeX append |

## Polite API use

- `mailto` in User-Agent (configurable via `CHATLABAI_MAILTO` env var).
- Rate-limiting between API calls (~1s).
- Responses cached under `.cache/lit-review/` to avoid redundant calls.
- Retries on HTTP 429/5xx with backoff.

## Seed terms

By default, seed terms load from the **Domain vocabulary** section of
`knowledge/lab-info.md` (aesthetic triad, empirical aesthetics, beauty, face perception,
art perception, architecture perception). Override with `--seed-terms a,b,c`.

## Graceful degradation

If no network is available, the script prints a clear message and exits non-zero
with guidance — it does **not** crash with a traceback.

## Safety

- Read-only against external APIs. The only write is appending to `references/library.bib`
  (deduped by DOI) and writing `review.md` to the path you specify.
- No credentials required beyond network access.
