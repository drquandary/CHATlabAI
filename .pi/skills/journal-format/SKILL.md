---
name: journal-format
description: "Format a manuscript for a target journal — prepare submission, journal style, convert citations to, make it submission-ready, apply CSL. Wraps pandoc + CSL to convert .md/.docx into the journal's required format and prints a submission checklist (word count vs limit, section order, abstract format, figures/tables)."
---

# journal-format

Format a manuscript for a target journal: limits, section order, abstract style, citation style.

## When to use

- "format this for the Journal of Cognitive Neuroscience"
- "prepare submission", "make it submission-ready"
- "convert citations to" a journal's style
- "journal style" / "apply CSL"

## Behavior

1. Look up the target journal in `knowledge/journals.md` (word/section limits, abstract
   format, CSL style filename).
2. Convert the source (`.md` or `.docx`) to the requested output format via **pandoc**.
3. Apply the journal's **CSL** citation style from `knowledge/csl/<style>.csl` if present;
   otherwise warn and fall back to pandoc's default citation style.
4. Emit a **submission checklist**: word count vs. limit (with delta), abstract format and
   word budget, section order, figure/table placement, cover-letter/significance-statement notes.

## Usage

```bash
# Format a markdown draft to docx for a target journal
python3 .pi/skills/journal-format/scripts/format_journal.py \
  --in draft.md \
  --journal "Journal of Cognitive Neuroscience" \
  --out submission.docx

# List journals configured in knowledge/journals.md
python3 .pi/skills/journal-format/scripts/format_journal.py --list-journals
```

`--help` documents all flags.

## CSL styles

CSL files live in `knowledge/csl/`. They are **not bundled** by default (licensing/per-journal
naming varies). Download the exact style from the Zotero CSL repository:

- Browse: https://www.zotero.org/styles
- Direct example: https://www.zotero.org/styles/journal-of-cognitive-neuroscience

Save each as `knowledge/csl/<name>.csl` matching the `CSL style` column in `journals.md`.
If a CSL file is missing, the script warns and uses pandoc's default citation style.

## Dependencies

- **pandoc** (system binary). If absent, the script prints a clear message listing how to
  install it and exits cleanly (no traceback).
- `python3` stdlib only for the script itself.

## Safety

- Non-destructive: writes only the `--out` file; never modifies the source manuscript.
- All checks are read-only on the input.
