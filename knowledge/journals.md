# Target Journals — Chatterjee Lab

> Values marked `verify` are unknown and must be confirmed against the journal's current
> author guidelines before submission. Do not guess.

CSL style files are bundled under `knowledge/csl/` when available; otherwise pandoc will use
its built-in styles or the file must be supplied manually.

| Journal | Word limit | Abstract | Section order | CSL style | Notes |
|---------|-----------|----------|----------------|-----------|-------|
| Journal of Cognitive Neuroscience | verify | Structured (~250 words) | verify | `journal-of-cognitive-neuroscience.csl` | MIT Press; empirical + theoretical |
| Cognition | verify | Unstructured (~150 words) | verify | `cognition.csl` | Elsevier; empirical |
| Trends in Cognitive Sciences | verify | Unstructured (~150 words) | verify | `trends-in-cognitive-sciences.csl` | Elsevier; review/TiCS format |
| Psychological Science | 4000 words (main, excl. refs/figs) | Unstructured (~150 words) | IMRaD | `psychological-science.csl` | SAGE/APS; short report format common |
| Brain | verify | Structured (~200 words) | verify | `brain.csl` | Oxford; clinical/empirical neurology |
| NeuroImage | verify | Structured (~250 words) | verify | `neuroimage.csl` | Elsevier; methods-heavy |
| Cognitive and Behavioral Neurology | verify | Structured (~250 words) | verify | verify | LWW; clinical neuropsych |
| Empirical Studies of the Arts | verify | Unstructured (~150 words) | verify | `empirical-studies-of-the-arts.csl` | SAGE; empirical aesthetics |

## Common checklist items (applied by `journal-format`)

- Word count vs. limit (report delta).
- Abstract format: structured vs. unstructured; word budget.
- Section order matches journal template.
- Citation style applied via CSL.
- Figures/tables: placement, captions, permissions.
- Cover letter / significance statement if required.
