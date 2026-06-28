# CSL Styles

CSL (Citation Style Language) files for journal formatting. These are **not bundled** by
default — download the exact style you need from the Zotero CSL repository.

## How to get a CSL file

1. Browse: https://www.zotero.org/styles
2. Search for the journal name.
3. Download the `.csl` file and save it here as `knowledge/csl/<name>.csl`, where `<name>`
   matches the `CSL style` column in `knowledge/journals.md`.

## Direct download examples

| Journal | CSL filename (save as) | Zotero URL |
|---------|------------------------|------------|
| Journal of Cognitive Neuroscience | `journal-of-cognitive-neuroscience.csl` | https://www.zotero.org/styles/journal-of-cognitive-neuroscience |
| Cognition | `cognition.csl` | https://www.zotero.org/styles/cognition |
| Trends in Cognitive Sciences | `trends-in-cognitive-sciences.csl` | https://www.zotero.org/styles/trends-in-cognitive-sciences |
| Psychological Science | `psychological-science.csl` | https://www.zotero.org/styles/psychological-science |
| Brain | `brain.csl` | https://www.zotero.org/styles/brain |
| NeuroImage | `neuroimage.csl` | https://www.zotero.org/styles/neuroimage |
| Empirical Studies of the Arts | `empirical-studies-of-the-arts.csl` | https://www.zotero.org/styles/empirical-studies-of-the-arts |

## Fallback

If a CSL file is missing, `format_journal.py` warns and falls back to pandoc's default
citation style. The conversion still proceeds; only the citation rendering differs.
