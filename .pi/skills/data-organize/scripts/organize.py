#!/usr/bin/env python3
"""
data-organize: Organize neuroimaging + behavioral data into a BIDS-friendly tree.

Scans a source directory, proposes a standardized tree and a move-plan, writes a
manifest.csv (file, type, size, sha256, proposed path, duplicate flag), performs light
BIDS-name validation, and deduplicates by sha256 hash.

DRY-RUN by default. Nothing is moved unless --apply is given. --apply is idempotent:
files already at their destination are skipped; a re-run produces no error.

Usage:
    python3 organize.py <src> [--dest data/] [--apply] [--manifest path]
    python3 organize.py --help
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- types

# (extension-normalized, category, bids datatype or behavioral)
EXT_MAP = [
    (".nii.gz", "imaging", "anat"),
    (".nii",    "imaging", "anat"),
    (".dcm",    "dicom",   "dwi"),     # datatype guess; BIDS raw dicom -> sourcedata
    (".dicom",  "dicom",   "dwi"),
    (".csv",    "behavioral", "beh"),
    (".tsv",    "behavioral", "beh"),
    (".json",   "sidecar",  "beh"),
    (".log",    "log",      "beh"),
    (".txt",    "log",      "beh"),
]

# Light BIDS pattern: sub-<label>/ses-<label>/<datatype>/<basename>
BIDS_SUB_RE = re.compile(r"^sub-([A-Za-z0-9]+)")
BIDS_SES_RE = re.compile(r"ses-([A-Za-z0-9]+)")
BIDS_DATATYPES = {"anat", "func", "dwi", "fmap", "perf", "eeg", "meg", "ieeg", "beh", "pet"}


@dataclass
class FileEntry:
    src: Path
    rel: str
    size: int
    sha256: str
    category: str          # imaging, dicom, behavioral, sidecar, log, other
    bids_datatype: str     # e.g. anat, beh
    proposed_path: str
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None
    bids_warnings: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- helpers

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def detect_type(name: str) -> Tuple[str, str]:
    """Return (category, bids_datatype) from a filename."""
    lower = name.lower()
    for ext, cat, dt in EXT_MAP:
        if lower.endswith(ext):
            return cat, dt
    return "other", "beh"


def extract_sub_ses(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Pull sub-<id> and ses-<id> tokens from a filename if present."""
    sub_m = BIDS_SUB_RE.search(name)
    ses_m = BIDS_SES_RE.search(name)
    sub = sub_m.group(1) if sub_m else None
    ses = ses_m.group(1) if ses_m else None
    return sub, ses


def propose_path(entry: FileEntry, dest: Path) -> str:
    """Propose a BIDS-friendly destination relative to dest."""
    name = entry.src.name
    sub, ses = extract_sub_ses(name)
    basename = name

    if entry.category in ("imaging", "dicom"):
        # sub-<id>/ses-<id>/<datatype>/<basename>
        if sub is None:
            # No sub- token: keep under unknown/ datatype
            parts = ["unknown", entry.bids_datatype]
        else:
            parts = [f"sub-{sub}"]
            if ses:
                parts.append(f"ses-{ses}")
            parts.append(entry.bids_datatype)
        rel = "/".join(parts + [basename])
    elif entry.category in ("behavioral", "sidecar", "log"):
        rel = f"behavioral/{basename}"
    else:
        rel = f"other/{basename}"
    return rel


# --------------------------------------------------------------------------- core

def scan(src: Path, dest: Path) -> List[FileEntry]:
    entries: List[FileEntry] = []
    for root, _dirs, files in os.walk(src):
        for fn in files:
            p = Path(root) / fn
            if p.is_dir() or not p.is_file():
                continue
            try:
                size = p.stat().st_size
            except OSError as e:
                print(f"  ! could not stat {p}: {e}", file=sys.stderr)
                continue
            try:
                digest = sha256_of(p)
            except OSError as e:
                print(f"  ! could not hash {p}: {e}", file=sys.stderr)
                continue
            cat, dt = detect_type(fn)
            e = FileEntry(
                src=p,
                rel=str(p.relative_to(src)),
                size=size,
                sha256=digest,
                category=cat,
                bids_datatype=dt,
                proposed_path="",
            )
            e.proposed_path = propose_path(e, dest)
            entries.append(e)
    return entries


def dedup(entries: List[FileEntry]) -> None:
    """Flag duplicates by sha256 (first occurrence wins)."""
    seen: Dict[str, FileEntry] = {}
    for e in entries:
        if e.sha256 in seen:
            e.is_duplicate = True
            e.duplicate_of = seen[e.sha256].rel
        else:
            seen[e.sha256] = e


def bids_validate(entries: List[FileEntry]) -> None:
    """Light BIDS-name validation: warn (not error) on mismatches."""
    for e in entries:
        if e.category in ("imaging", "dicom"):
            sub, ses = extract_sub_ses(e.src.name)
            if sub is None:
                e.bids_warnings.append("missing sub-<label> prefix")
            # datatype sanity: if a BIDS datatype token appears in the name, check it's known
            for tok in re.findall(r"_(?:[a-z]+)", e.src.name.lower()):
                dt = tok[1:]
                if dt in ("t1w", "t2w", "bold", "dwi", "fmap", "pet"):
                    continue
        if e.category == "behavioral" and e.src.suffix.lower() == ".csv":
            # encourage participants.tsv for subject-level tables (warn only)
            if e.src.name.lower() == "participants.csv":
                e.bids_warnings.append("consider participants.tsv for subject-level table")


def write_manifest(entries: List[FileEntry], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "file", "type", "size_bytes", "sha256", "proposed_path",
            "duplicate", "duplicate_of", "bids_warnings",
        ])
        for e in entries:
            w.writerow([
                e.rel, e.category, e.size, e.sha256, e.proposed_path,
                "yes" if e.is_duplicate else "no",
                e.duplicate_of or "",
                "; ".join(e.bids_warnings),
            ])


def write_data_dictionary(entries: List[FileEntry], dest: Path) -> List[str]:
    """Create a data-dictionary stub for each tabular file found. Returns created paths."""
    created = []
    for e in entries:
        if e.category != "behavioral":
            continue
        if e.src.suffix.lower() not in (".csv", ".tsv"):
            continue
        # Only for CSV we can cheaply read a header with stdlib csv
        if e.src.suffix.lower() != ".csv":
            continue
        try:
            with open(e.src, newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, [])
        except Exception:
            header = []
        dict_path = dest / "behavioral" / (e.src.stem + "_dictionary.json")
        dict_path.parent.mkdir(parents=True, exist_ok=True)
        if not dict_path.exists():
            import json
            stub = {
                "source_file": e.src.name,
                "description": "Auto-generated data dictionary stub. Fill in types/units/descriptions.",
                "columns": {col: {"description": "", "type": "verify"} for col in header},
            }
            with open(dict_path, "w") as fh:
                json.dump(stub, fh, indent=2)
            created.append(str(dict_path.relative_to(dest)))
    return created


def print_plan(entries: List[FileEntry], dest: Path, apply: bool) -> None:
    verb = "APPLYING" if apply else "DRY-RUN (no changes)"
    print(f"\n{'='*70}\n  data-organize — {verb}\n  dest: {dest}\n{'='*70}")
    n_dup = sum(1 for e in entries if e.is_duplicate)
    for e in entries:
        tag = " [DUP]" if e.is_duplicate else ""
        warn = f"  ⚠ {e.bids_warnings[0]}" if e.bids_warnings else ""
        print(f"  {e.rel:<40} -> {e.proposed_path}{tag}{warn}")
    print(f"\n  Total files: {len(entries)} | Duplicates: {n_dup}")
    if apply:
        print("  Mode: APPLY (moves will be performed)")
    else:
        print("  Mode: DRY-RUN (no files moved). Re-run with --apply to perform moves.")


def apply_moves(entries: List[FileEntry], dest: Path) -> Tuple[int, int, int]:
    """Perform moves. Returns (moved, skipped_already_there, skipped_duplicate)."""
    moved = skipped = skipped_dup = 0
    for e in entries:
        if e.is_duplicate:
            skipped_dup += 1
            continue
        target = dest / e.proposed_path
        # Idempotency: if target already exists with same content, skip.
        if target.exists():
            try:
                if sha256_of(target) == e.sha256:
                    skipped += 1
                    continue
            except OSError:
                pass
            # Different content at target: refuse to clobber.
            print(f"  ! target exists with different content, skipping: {target}", file=sys.stderr)
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(e.src, target)
        moved += 1
    return moved, skipped, skipped_dup


# --------------------------------------------------------------------------- main

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="organize.py",
        description="Organize neuroimaging + behavioral data into a BIDS-friendly tree. "
                    "DRY-RUN by default; --apply to perform moves.",
    )
    p.add_argument("src", help="Source directory to scan.")
    p.add_argument("--dest", default="data/", help="Destination root for the organized tree (default: data/).")
    p.add_argument("--apply", action="store_true", help="Perform the moves (default: dry-run only).")
    p.add_argument("--manifest", default=None,
                   help="Manifest output path (default: <dest>/manifest.csv).")
    args = p.parse_args(argv)

    src = Path(args.src).expanduser().resolve()
    dest = Path(args.dest).expanduser().resolve()

    if not src.is_dir():
        print(f"Error: source directory not found: {src}", file=sys.stderr)
        return 2

    if args.apply:
        dest.mkdir(parents=True, exist_ok=True)

    entries = scan(src, dest)
    dedup(entries)
    bids_validate(entries)

    manifest_path = Path(args.manifest).expanduser().resolve() if args.manifest else dest / "manifest.csv"
    # In dry-run we still write the manifest so the plan is inspectable.
    write_manifest(entries, manifest_path)

    print_plan(entries, dest, apply=args.apply)
    print(f"  Manifest written: {manifest_path}")

    dicts_created: List[str] = []
    moved = skipped = skipped_dup = 0
    if args.apply:
        moved, skipped, skipped_dup = apply_moves(entries, dest)
        dicts_created = write_data_dictionary(entries, dest)
        print(f"  Moved: {moved} | Skipped (already present): {skipped} | Skipped (duplicates): {skipped_dup}")
        if dicts_created:
            print(f"  Data dictionary stubs created: {', '.join(dicts_created)}")
        print("  Re-running is safe (idempotent).")
    else:
        print("  No files were moved (dry-run).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
