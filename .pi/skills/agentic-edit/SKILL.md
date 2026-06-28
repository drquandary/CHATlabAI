---
name: agentic-edit
description: Surgical track-changes editing of .docx that preserves the author's voice — minimal edits aligned to Chatterjee's writing rules, emitted as real Word tracked revisions (w:ins/w:del, author CHATLabAI). Use when you need to track changes, edit but preserve my writing, make surgical edits, redline a draft, produce a tracked changes docx, or redline a manuscript.
---

# Agentic Edit — Tracked-Changes Editing

## Purpose

Apply **surgical** track-changes edits to a `.docx` manuscript. Edits are minimal and
aligned to Chatterjee's 12 writing rules (`knowledge/chatterjee-writing-rules.md`):
overclaim → hedge, inflated phrase → plain phrase, buried payoff → surfaced. The output
is a redlined `.docx` with **real Word tracked revisions** (`w:ins`/`w:del`, author =
`CHATLabAI`) that are individually acceptable/rejectable in Word, plus a `change-log.md`
citing the rule per edit.

**Never silently rewrite whole paragraphs.** Preserve the author's wording wherever it
already complies. Propose the *smallest* edit that fixes each rule violation.

## When to use

- "track changes on this draft"
- "edit but preserve my writing"
- "surgical edits" / "redline" / "tracked changes docx"
- Reviewing output from `paper-review` and applying the fixes as Word revisions.

## How it works

1. Parse the `.docx` into paragraphs (python-docx).
2. For each proposed edit: locate the `find` text within the target paragraph, split the
   run(s) so only the matched text is isolated, then wrap it in `<w:del>` (deletion) and
   insert the replacement in `<w:ins>` (insertion) — each with `w:author=CHATLabAI`,
   `w:date`, and a unique `w:id`.
3. The replacement run inherits the formatting (font, bold, italic, size) of the deleted
   text's run, so the redline looks clean.
4. Write the redlined `.docx` and a `change-log.md` (rule cited per edit).

## Usage

### CLI

```bash
python3 .pi/skills/agentic-edit/scripts/docx_track.py \
    --in draft.docx \
    --edits edits.json \
    --out draft.tracked.docx
```

Optional flags:
- `--author CHATLabAI` — revision author (default `CHATLabAI`).
- `--date "2026-06-28T14:00:00-04:00"` — ISO datetime (default: now).
- `--changelog path/to/change-log.md` — custom changelog path (default: alongside `--out`).

### edits.json format

A JSON list of edit objects:

```json
[
  {
    "paragraph_index": 0,
    "find": "proves that architects hardwired a response in viewers",
    "replace": "is consistent with architects recruiting a response in viewers",
    "comment": "Rule 3: hedge mechanism verb"
  }
]
```

- `paragraph_index` (int, required): 0-based index over document paragraphs.
- `find` (str, required): exact substring to replace (must appear in the target paragraph).
- `replace` (str, required): the replacement text.
- `comment` (str, optional): human note; if it contains "Rule N", the changelog cites it.

### Python API (importable)

```python
from docx_track import apply_tracked_edits

result = apply_tracked_edits(
    in_path="draft.docx",
    edits=[{
        "paragraph_index": 0,
        "find": "proves",
        "replace": "is consistent with",
        "comment": "Rule 3: hedge mechanism verb",
    }],
    out_path="draft.tracked.docx",
    author="CHATLabAI",
)
print(result["applied"], "edits applied")
```

## Editing guidelines (how to choose edits)

Align every edit to a writing rule. The comment should name the rule.

| Rule | Edit pattern |
|------|-------------|
| 3 | banned mechanism verb → hedge verb (`proves` → `is consistent with`) |
| 8 | inflated marker → plain phrase (`instantiate` → `show`) |
| 2 | buried payoff → surfaced in first/last sentence |
| 4 | reorder evidence→interpretation chain |
| 6 | local claim presented as primary → mark exploratory |
| 7 | trailing caveat → uncertainty inside the claim |

Read the banned/hedge/inflated lists from the machine-checkable blocks in
`knowledge/chatterjee-writing-rules.md`.

## Safety

- **Non-destructive:** the input `.docx` is never modified; a new `--out` file is written.
- **No silent skips:** if `find` text is not found in the target paragraph, the edit is
  skipped with a clear warning and recorded as `skipped_not_found` in the changelog.
- **No network:** this script makes no network calls.
- **Verify before finalizing:** open the redlined `.docx` in Word and Accept/Reject each
  revision. The `change-log.md` documents every edit and its rule citation.

## Script reference

- `scripts/docx_track.py` — the technical core. `--help` for full CLI docs.
