---
name: paper-review
description: "Review a manuscript against Chatterjee's 21 writing rules, check my draft, flag overclaiming, Chatterjee review, is the contribution clear, writing rules, does this overclaim, review this paper."
---

# Paper Review

Review a manuscript (`.docx`, `.md`, `.tex`, `.txt`) against Chatterjee's 21 writing rules
(see `knowledge/chatterjee-writing-rules.md`) **in Anjan Chatterjee's voice**
(see `knowledge/chatterjee-voice.md`). Produce a structured critique that a human
reviewer (or the `agentic-edit` skill) can act on.

## When to use

- The user asks to "review this paper", "check my draft", or "is this overclaiming".
- A manuscript needs a writing-rules pass before submission or track-changes editing.
- You want a deterministic flag sweep before the judgmental review.

## What it produces

A per-rule critique with, for each flagged rule:
- the quoted offending text,
- a concrete fix,
- the rule cited.

Plus these specific checks:
- **Rule 10 test:** can the contribution be stated in one sentence? If not, draft one.
- **Rule 3 scan:** every banned mechanism verb, with location and a hedged replacement
  (from `hedge_verbs`: *is consistent with*, *may have recruited*, *likely intensified*,
  *helps explain*, *offers a plausible account of*, *could*, *plausibly*,
  *would have made available*).
- **Rule 4:** check the evidence→interpretation chain is clean and ordered
  (documented → perceptually salient → research-plausible → interpretive).
- **Rule 6:** flag node-level/local claims presented as primary on small samples
  (the LLM judges this from context; the script cannot).
- **Rule 8:** flag inflated markers and overlong sentences.
- **Rule 18:** flag filler phrases ("It is important to note that," "within the context
  of," …) and filler adverbs ("deeply," "complexly," "richly") for deletion/tightening.
- **Rule 21:** flag "methodology" where "methods" is meant — one of Anjan's standing
  corrections. Suggest "methods" (reserve "methodology" for a paper about methods as a subject).

## How it works (division of labor)

This skill splits the review into two layers:

1. **Deterministic (script):** `scripts/lint_claims.py` scans for the machine-checkable
   patterns — banned mechanism verbs (rule 3), inflated markers (rule 8), filler phrases
   and adverbs (rule 18), "methodology" (rule 21), and overlong sentences (rule 8/clarity,
   >45 words) — each with line/offset and, for rule 3, a hedged replacement. Run this
   **first** so nothing is missed.
2. **Judgmental (LLM):** you (CHATLabAI) take the script's output and perform the full
   per-rule review: rule 10 (one-sentence contribution), rule 4 (chain ordering), rule 6
   (small-sample local claims), the new sentence-level rules (15–20) and rule 21, and
   concrete fixes for every flag. The script does not replace your judgment — it
   guarantees the mechanical catches.

## Usage

```bash
# Deterministic flag sweep (markdown report, default)
python3 .pi/skills/paper-review/scripts/lint_claims.py path/to/draft.docx

# JSON output (for piping into agentic-edit's edits.json)
python3 .pi/skills/paper-review/scripts/lint_claims.py draft.md --format json

# Use a custom rules file
python3 .pi/skills/paper-review/scripts/lint_claims.py draft.tex --rules-file ./my-rules.md
```

The script reads the machine-checkable blocks (`banned_mechanism_verbs`, `hedge_verbs`,
`inflated_markers`, `filler_phrases`, `filler_adverbs`, `methodology_flag`, `sentence_length`)
from `knowledge/chatterjee-writing-rules.md`. Supports `.docx` (via `python-docx`), `.md`,
`.tex`, and `.txt`.

After the script runs, you (CHATLabAI) read its report and produce the structured critique:
for each rule, pass or flag with the quoted text, the fix, and the rule cited. End with the
rule-10 one-sentence contribution (drafted if missing) and the rule-4 chain assessment.

## Safety

- Read-only: the script extracts text and prints a report; it does not modify the manuscript.
- No network: this skill makes no API calls. (Cross-referencing DOIs is the `citations` skill's job.)
- Optional dep: `python-docx` is required only for `.docx` input; the script fails with a clear
  message and install hint if it is missing.

## Script reference

- `scripts/lint_claims.py` — `python3 lint_claims.py <file> [--format json|markdown] [--rules-file PATH] [--quiet]`
