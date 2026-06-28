---
name: data-organize
description: Organize neuroimaging + behavioral data into a BIDS-friendly tree, make a manifest, inventory files, dedup by hash, rename these files, clean up the data folder, BIDS. Use when tidying a messy data folder or proposing a standardized layout. Dry-run by default.
---

# data-organize

## Purpose

Organize neuroimaging + behavioral/tabular data into a **BIDS-friendly** tree, generate an
inventory `manifest.csv`, perform light BIDS-name validation, and deduplicate files by sha256
hash. Designed for the Chatterjee lab's mix of fMRI (`.nii`/`.nii.gz`) and behavioral CSVs.

## When to use

- "organize this data folder"
- "make it BIDS"
- "clean up the data folder"
- "make a manifest / inventory of these files"
- "rename these files into BIDS"
- "are there duplicate files?"

## Behavior

- Scans a source directory recursively.
- Detects file type: `.nii`/`.nii.gz` (imaging), `.csv`/`.tsv` (behavioral/tabular),
  `.json` (sidecar/dict), `.dicom`/`.dcm` (dicom), `.log`/`.txt` (log), other.
- Proposes BIDS-friendly paths:
  - Imaging/dicom → `sub-<id>/ses-<id>/<datatype>/<basename>` (extracts `sub-`/`ses-` tokens
    from the filename; files lacking a `sub-` token go to `unknown/<datatype>/`).
  - Behavioral/sidecar/log → `behavioral/<basename>`.
  - Other → `other/<basename>`.
- Generates `manifest.csv` columns: `file, type, size_bytes, sha256, proposed_path, duplicate,
  duplicate_of, bids_warnings`.
- **Dedup by sha256**: the first occurrence of each hash is kept; later identical files are
  flagged `duplicate=yes` with `duplicate_of` pointing at the original. Duplicates are **never
  deleted** — they are flagged in the manifest and skipped during `--apply`.
- **Light BIDS validation**: warns (not errors) when imaging filenames lack a `sub-<label>`
  prefix, or when a subject-level table could be `participants.tsv`.
- **Data dictionary stub**: when tabular CSVs are found and `--apply` is used, writes a
  `<stem>_dictionary.json` next to each CSV with the detected columns as a fill-in stub.
- **Dry-run by default**: prints the move-plan and writes the manifest, but moves nothing.
  Pass `--apply` to perform the moves. `--apply` is **idempotent**: files already present at the
  destination (same content) are skipped; a re-run produces no error.

## Usage

```bash
# Dry-run (default): print plan + write manifest, move nothing
python3 .pi/skills/data-organize/scripts/organize.py <src> --dest data/

# Perform the moves
python3 .pi/skills/data-organize/scripts/organize.py <src> --dest data/ --apply

# Custom manifest path
python3 .pi/skills/data-organize/scripts/organize.py <src> --dest data/ --manifest my_manifest.csv

python3 .pi/skills/data-organize/scripts/organize.py --help
```

### Manifest location

- Default: `<dest>/manifest.csv`.
- Override with `--manifest <path>` (written even in dry-run so the plan is inspectable).

## Safety

- **Never deletes** source files or duplicates. Moves are `copy2` (source preserved); duplicates
  are flagged, not removed.
- **Dry-run by default.** `--apply` is required to touch anything.
- **Idempotent** on re-run: identical files already at the destination are skipped; a target
  with *different* content is never clobbered (it is skipped with a warning).
- No network access. Stdlib only.

## Script reference

- `scripts/organize.py` — the whole skill. `argparse` CLI, `--help` documented.
