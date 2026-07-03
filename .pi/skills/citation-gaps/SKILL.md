---
name: citation-gaps
description: "Find citation gaps, what should I cite, literature gap, missing references, topic coverage, does this paper cite the key works, find gaps in my references, citation gap finder, coverage check by topic, what foundational work is missing. Also: get me the key citations, canonical literature for this theme, must-cite works, citation snowballing, what should I cite for this claim/question/sentence."
---

# Citation Gaps

Two sibling scripts, two different questions:

- **`find_gaps.py`** — topic-forward: "the paper makes claims in area X; what is the
  foundational + recent work on X that isn't cited?" Discovers literature via keyword search
  across claim-areas, scores gap-strength, subtracts what's already cited.
- **`key_citations.py`** — graph-based: "get me the KEY citations for this theme/question/
  sentence" — the works a domain expert would say you must cite. Does **citation-graph
  snowballing** on OpenAlex (not just keyword search) to find the canon, including works that
  use different vocabulary than your query.

Both complement callosum's built-in gap-finder (which is **library-backward**: works your
*other* papers cite but you don't have). Both are free-API, sequential, rate-limited, and can
seed callosum's wanted list so you acquire PDFs and later ground citations to them with page
numbers.

## When to use which

| Question | Script |
|---|---|
| "What is my draft missing?" / "does this cite the key works?" | `find_gaps.py --paper` |
| "Scope the literature on a theme, no specific paper" | either — see below |
| "Get me the canonical/must-cite literature for this theme/question/sentence" | `key_citations.py` |
| "What's the foundational vs. recent split on topic X, across several claim-areas?" | `find_gaps.py --theme` |
| "Which of the canonical works for this theme does my draft already have?" | `key_citations.py --paper` |

Rule of thumb: `find_gaps.py` is **keyword-forward** (multi-angle search + era-gating +
cross-area recurrence) — good for auditing a draft's claim-areas or scoping a topic broadly.
`key_citations.py` is **graph-forward** (citation snowballing + local in-degree centrality) —
good when you specifically want the canon, because keyword search alone misses classics cited
under different terms than your query vocabulary.

---

## `find_gaps.py` — topic-forward gap finder

Find literature the paper **should** engage but doesn't — forward from a topic or theme,
not just backward from what's already cited.

### How it decides what's missing (the method)

- **Multi-angle discovery per claim-area** (depth-budgeted, not adaptive): a *core* search,
  plus a *recent* era-gated slice (last ~5 yrs) and a *foundational* slice (<= ~2015), and at
  `deep` also a *reviews/surveys* angle and a *citation-chase* around the highest-cited hit.
  Era-gating is deliberate: engaging the recent slice but not the foundational one (or vice
  versa) is a temporal coverage gap.
- **Repeat-hit = strong gap.** A work that surfaces across **multiple claim-areas** but is
  absent from the paper's references is flagged *recurring/foundational* — the single
  strongest topic-forward gap signal.
- **Gap-strength** blends cross-area recurrence (dominant) + **citations-per-year (CPY)** +
  recency + OpenAlex relevance, labelled high / medium / low. CPY (not raw citations) so a
  recent high-impact paper isn't buried under ancient classics.
- **DOI-first subtraction**, then fuzzy title (token-Jaccard >= 0.6) so missing-DOI references
  are still matched and removed.
- **Three-count coverage audit** (pulled → unique → already-cited → new gaps), per area and
  overall, so the coverage claim is inspectable.

The **script** does all of the above deterministically. **You (CHATLabAI)** write the honest
one-line read per gap in Anjan's voice — why it matters to the argument — and mark weak gaps
weak (rule 13). When you choose claim-areas, deliberately include 1–2 that pressure-test
framings the paper OMITS (adjacent or competing literatures its own vocabulary would never
surface). That is what makes this topic-forward rather than keyword-confirmatory.

### What it produces

`gaps.md`: a coverage audit, a per-area summary table (pulled / unique / already-cited /
coverage% / new gaps), a **"Top gaps overall — start here"** list (highest-strength, deduped,
each with strength label, "surfaced in N areas", CPY, DOI, and an abstract snippet), then
per-area detail. A JSON sidecar (`--format json`) carries the same data plus per-candidate
`strength`, `strength_label`, `cpy`, `sub_area_count`, `also_areas`, `foundational`, `abstract`.

### Usage

```bash
# Theme mode — literature on a topic (no specific paper)
python3 .pi/skills/citation-gaps/scripts/find_gaps.py --theme "altered state phenomenology" --depth standard --n 12

# Paper mode — what THIS paper is missing (you pass the claim-areas; include an omitted framing)
python3 .pi/skills/citation-gaps/scripts/find_gaps.py --paper draft.docx \
  --claim-areas "aesthetic triad" "appraisal theory" "computational phenomenology" --depth standard

# Seed callosum's wanted list with the top uncited candidates
python3 .pi/skills/citation-gaps/scripts/find_gaps.py --paper draft.docx \
  --claim-areas "appraisal theory" --seed-callosum --top-seed 5

# Deeper search (adds reviews + citation-chase) and multi-source
python3 .pi/skills/citation-gaps/scripts/find_gaps.py --theme "psychedelic phenomenology" --depth deep --sources openalex,pubmed

# JSON for reading into your report; offline self-test
python3 .pi/skills/citation-gaps/scripts/find_gaps.py --theme "beauty and the brain" --format json
python3 .pi/skills/citation-gaps/scripts/find_gaps.py --self-test
```

**Flags:** `--paper` | `--theme` (one required), `--claim-areas` (paper mode; LLM-chosen),
`--depth {quick,standard,deep}` (default standard), `--sources openalex[,pubmed,crossref]`,
`--n` per-angle cap, `--seed-callosum` / `--top-seed`, `--format {markdown,json}`, `--out`,
`--self-test`, `--quiet`.

---

## `key_citations.py` — graph-based key-citation finder (citation snowballing)

Given a **theme, question, or sentence**, return the KEY citations for it — via **citation-
graph snowballing on OpenAlex**, not just keyword search. Keyword search finds papers sharing
your vocabulary; it misses canonical works cited under other terms. Snowballing + local-graph
centrality finds the canon.

### The graph method

1. **Seed round** — keyword-search each query angle (1 explicit query if you don't pass
   `--queries`, else your 2–5 decomposed angle queries); merge, dedup by DOI/W-id, take the top
   seeds by relevance (5 quick / 8 standard / 12 deep).
2. **Graph expansion** from the seed set:
   - **BACKWARD** — hydrate each seed's `referenced_works` (OpenAlex batch-resolve, up to 50
     ids/call) — what the seeds cite.
   - **FORWARD** — `filter=cites:W<id>` per seed — what cites the seeds.
   Every harvested work's own `referenced_works` list is kept too, building a real edge set
   (who-cites-whom), not just a node list.
3. **Saturation loop** — recompute local in-degree, expand the top newly-surfaced
   not-yet-expanded nodes, repeat. Stops when a round adds < 10% new nodes, the per-tier call
   budget is hit, or `--max-rounds` is reached (default 1 quick / 2 standard / 3 deep) — the
   stop reason is always reported, never silent.
4. **Local-graph scoring** (computed offline from the harvested edge set):
   - `local_indegree` — # of OTHER harvested works that cite this one. **The primary signal**:
     canonical *for this theme's harvested graph*, regardless of global cite count or whether
     the work uses your query's vocabulary at all.
   - `seed_coupling` — # of seeds that cite this node (co-citation with the seed frontier).
   - `cpy` — citations-per-year (reuses `find_gaps.py`'s `cpy()`).
   - `query_relevance` — max OpenAlex relevance score across queries that directly surfaced it
     (0 if only reached via the graph).
   - Blended into `key_score` in [0,1]: indegree ~0.5 (dominant), seed_coupling ~0.2, cpy ~0.2,
     query_relevance ~0.1. Indegree/coupling normalized by the max observed in the run.

### Tiers in the report

- **Canonical core** — the must-cites: highest local in-degree, ranked within that tier by the
  full `key_score` blend (so a generic high-indegree methods citation with near-zero seed
  co-citation doesn't out-rank an actual theme classic). Each entry: score, "cited by N of M
  harvested works", CPY, year, venue, DOI, abstract snippet, and **provenance** ("seed" /
  "backward from \<seed title\>" / "forward-cites of \<title\>", with the round number).
- **Recent front** — high-CPY works from the last ~5 years with low local in-degree: the
  emerging edge the canon hasn't absorbed yet.
- **Reviews & bridges** — review/survey-signalled works, or works surfaced by >= 2 distinct
  query angles (bridging multiple framings).
- **`--paper PATH`** (subtract-mode, read-only) — reuses `find_gaps.py`'s `extract_dois` +
  `find_references_block` + fuzzy `is_cited` to mark each key citation ALREADY-CITED vs.
  MISSING; the canonical-core list leads with the MISSING ones (the highest-value gaps).
- A coverage/audit block: seeds, works harvested, rounds run, calls made, stop reason.

### Usage

```bash
# Theme mode, standard depth
python3 .pi/skills/citation-gaps/scripts/key_citations.py --theme "neural basis of aesthetic experience" --depth standard

# Multiple decomposed angle-queries (you normally supply 2-5 of these)
python3 .pi/skills/citation-gaps/scripts/key_citations.py --question "does prototypicality drive facial attractiveness?" \
  --queries "facial attractiveness prototypicality" "averageness beauty faces" --depth deep

# Subtract-mode: mark which key citations a specific paper already has
python3 .pi/skills/citation-gaps/scripts/key_citations.py --sentence "art appreciation recruits reward circuitry" --paper draft.docx

# Seed callosum's wanted list with the top canonical DOIs; append BibTeX
python3 .pi/skills/citation-gaps/scripts/key_citations.py --theme "beauty and the brain" --seed-callosum --top-seed 5 \
  --bib references/library.bib

# JSON for reading into your report; offline self-test
python3 .pi/skills/citation-gaps/scripts/key_citations.py --theme "beauty and the brain" --format json
python3 .pi/skills/citation-gaps/scripts/key_citations.py --self-test
```

**Flags:** `--theme` | `--question` | `--sentence` (one required), `--queries` (2-5
LLM-decomposed angle queries, optional — defaults to the input text as a single query),
`--paper` (optional subtract-mode), `--depth {quick,standard,deep}` (default standard,
quick=5 seeds/~15 calls, standard=8 seeds/~40 calls, deep=12 seeds/~100 calls), `--max-rounds`
(override the depth tier's default), `--seed-callosum` / `--top-seed`, `--bib PATH`
(append BibTeX for the canonical core, dedups against existing keys), `--format
{markdown,json}`, `--out`, `--self-test`, `--quiet`.

---

## Callosum integration

Both scripts' `--seed-callosum` push top DOIs to callosum's `/wanted` endpoint (needs the
callosum API on `127.0.0.1:8080`; `/wanted` is a user action, no agent-write toggle). Acquire
OA copies from callosum's web UI; once the PDFs are ingested, `find_passages` grounds citations
to them with page numbers — closing the loop. If callosum is down, both scripts skip seeding
and still report their results.

## Safety

- Read-only on any manuscript (parses references; never edits).
- Free APIs only (OpenAlex primary; `find_gaps.py` also supports optional PubMed/Crossref).
  Sequential + rate-limited (>= 1s between calls, polite `mailto`). No auth, no MCP writes, no
  data egress, no paid sources. `key_citations.py` additionally enforces a hard total-call cap
  per depth tier and stops after 3 consecutive failed requests, always reporting why it stopped.
- `--seed-callosum` and `--bib` are opt-in and additive (add to the wanted list / append to the
  .bib; nothing is deleted or overwritten).

## Note on metadata

OpenAlex occasionally reports a reprint/edition year for a classic (e.g. an 18th-century work
dated to a modern reprint), which inflates its CPY/recency. The report always shows the year,
and your judgmental read should catch "this is a classic, not a modern gap." For
`key_citations.py`, remember that `local_indegree` measures theme-local centrality in the
harvested graph, not universal importance — a generic methods/atlas citation that half the
field cites for unrelated reasons can still surface with high indegree; the report's `key_score`
(which folds in seed-coupling and relevance) is a better ranking signal than raw indegree alone
when judging whether a hit is really canonical-for-the-theme.
