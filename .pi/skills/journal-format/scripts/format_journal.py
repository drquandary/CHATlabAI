#!/usr/bin/env python3
"""journal-format — format a manuscript for a target journal via pandoc + CSL.

Looks up the journal in knowledge/journals.md, converts the source (.md/.docx) to the
requested output format using pandoc, applies the journal's CSL citation style (if the
.csl file is bundled under knowledge/csl/), and prints a submission checklist.

CLI:
    python3 format_journal.py --in draft.md --journal "Journal of Cognitive Neuroscience" --out submission.docx
    python3 format_journal.py --list-journals

Dependencies:
    pandoc (system binary). If absent, prints a clear message and exits non-zero (no traceback).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

# Resolve paths relative to the workspace root (parent of .pi/skills/journal-format).
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
SKILLS_DIR = os.path.dirname(SKILL_DIR)
PI_DIR = os.path.dirname(SKILLS_DIR)
WORKSPACE_ROOT = os.path.dirname(PI_DIR)
JOURNALS_MD = os.path.join(WORKSPACE_ROOT, "knowledge", "journals.md")
CSL_DIR = os.path.join(WORKSPACE_ROOT, "knowledge", "csl")


def parse_journals_md(path):
    """Parse the markdown table in knowledge/journals.md into a list of dicts.

    Returns list of dicts with keys: journal, word_limit, abstract, section_order,
    csl_style, notes. Raises RuntimeError if the file is missing/unreadable.
    """
    if not os.path.isfile(path):
        raise RuntimeError(
            f"Could not find journals database at {path}. "
            "Ensure knowledge/journals.md exists."
        )
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    journals = []
    header_seen = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        # Skip the separator row (|---|---|...)
        if re.match(r"^\|[\s:|-]+\|?\s*$", stripped):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not header_seen:
            # Header row: Journal | Word limit | Abstract | Section order | CSL style | Notes
            header_seen = True
            continue
        if len(cells) < 6:
            continue
        journals.append({
            "journal": cells[0],
            "word_limit": cells[1],
            "abstract": cells[2],
            "section_order": cells[3],
            "csl_style": cells[4],
            "notes": cells[5],
        })
    return journals


def find_journal(journals, name):
    """Case-insensitive, trimmed lookup of a journal by name.

    Matches if the requested name is a substring of the journal entry or vice-versa,
    so 'journal of cognitive neuroscience' / 'JoCN' partials work.
    """
    needle = name.strip().lower()
    for j in journals:
        hay = j["journal"].strip().lower()
        if needle == hay or needle in hay or hay in needle:
            return j
    return None


def word_count(path):
    """Count words in a .md/.docx/.txt file (rough — strips markdown/cite keys)."""
    if not os.path.isfile(path):
        return None
    try:
        if path.lower().endswith(".docx"):
            try:
                from docx import Document  # type: ignore
            except ImportError:
                return None
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
    except Exception:
        return None
    # Strip pandoc/@cite keys and markdown symbols for a cleaner count.
    cleaned = re.sub(r"@\w+\d{4}", "", text)          # @Chatterjee2003
    cleaned = re.sub(r"[#*`>\[\]()-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return 0
    return len(cleaned.split())


def extract_limit_number(word_limit_str):
    """Extract the leading integer from a word-limit cell like '4000 words (main, excl. refs/figs)'."""
    if not word_limit_str or word_limit_str.strip().lower() == "verify":
        return None
    m = re.search(r"(\d[\d,]*)", word_limit_str)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def run_pandoc(in_path, out_path, csl_path=None):
    """Run pandoc to convert in_path -> out_path, optionally with a CSL.

    Returns (returncode, stderr_text). Raises FileNotFoundError if pandoc binary is missing.
    """
    if shutil.which("pandoc") is None:
        raise FileNotFoundError("pandoc")

    cmd = ["pandoc", in_path, "-o", out_path]
    if csl_path and os.path.isfile(csl_path):
        cmd += ["--csl", csl_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stderr


def resolve_csl(journal):
    """Return the path to the bundled CSL file for a journal, or None if missing/verify."""
    style = journal.get("csl_style", "").strip()
    if not style or style.lower() == "verify":
        return None
    # Some entries may include backticks; strip them.
    style = style.strip("`")
    csl_path = os.path.join(CSL_DIR, style)
    return csl_path if os.path.isfile(csl_path) else None


def build_checklist(journal, in_path, out_path, csl_used, actual_words):
    """Build the human-readable submission checklist string."""
    lines = []
    lines.append("=" * 64)
    lines.append("SUBMISSION CHECKLIST")
    lines.append("=" * 64)
    lines.append(f"Journal:     {journal['journal']}")
    lines.append(f"Input:       {in_path}")
    lines.append(f"Output:      {out_path}")
    lines.append("")

    # Word count vs limit
    limit_str = journal.get("word_limit", "verify")
    limit_num = extract_limit_number(limit_str)
    if actual_words is not None:
        lines.append(f"Word count:  {actual_words} words (in the source)")
        if limit_num:
            delta = actual_words - limit_num
            status = "OVER" if delta > 0 else "within"
            lines.append(f"Word limit:  {limit_num} words ({limit_str})")
            lines.append(f"             -> {abs(delta)} words {status} the limit")
        elif limit_str.strip().lower() == "verify":
            lines.append(f"Word limit:  {limit_str} — confirm against current author guidelines")
        else:
            lines.append(f"Word limit:  {limit_str}")
    else:
        lines.append("Word count:  (could not read input for counting)")
        lines.append(f"Word limit:  {limit_str}")

    lines.append("")
    lines.append(f"Abstract:    {journal.get('abstract', 'verify')}")
    lines.append(f"Sections:    {journal.get('section_order', 'verify')}")
    notes = journal.get('notes', '').strip()
    if notes:
        lines.append(f"Notes:       {notes}")
    lines.append("")

    # CSL / citations
    if csl_used:
        lines.append(f"Citations:   CSL applied ({os.path.basename(csl_used)})")
    else:
        style = journal.get("csl_style", "verify").strip().strip("`")
        if style.lower() == "verify":
            lines.append("Citations:   CSL style 'verify' in journals.md — supply manually")
        else:
            lines.append(
                f"Citations:   CSL style '{style}' NOT bundled in knowledge/csl/ — "
                "download from https://www.zotero.org/styles ; used pandoc default."
            )
    lines.append("")

    # Manual items
    lines.append("Manual items still to verify:")
    lines.append("  [ ] Section order matches the journal template")
    lines.append("  [ ] Abstract format (structured vs unstructured) and word budget")
    lines.append("  [ ] Figures/tables: placement, captions, permissions")
    lines.append("  [ ] Cover letter / significance statement if required")
    lines.append("  [ ] Reference list rendering (open output and spot-check)")
    lines.append("=" * 64)
    return "\n".join(lines)


def cmd_list_journals(args):
    journals = parse_journals_md(JOURNALS_MD)
    print(f"Configured journals ({len(journals)}):")
    for j in journals:
        csl = j["csl_style"].strip("`")
        bundled = "bundled" if resolve_csl(j) else "MISSING"
        print(f"  - {j['journal']}  |  words: {j['word_limit']}  |  "
              f"abstract: {j['abstract']}  |  CSL: {csl} ({bundled})")
    return 0


def cmd_format(args):
    # --- 1. journal lookup
    try:
        journals = parse_journals_md(JOURNALS_MD)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    journal = find_journal(journals, args.journal)
    if journal is None:
        print(f"ERROR: journal not found in knowledge/journals.md: {args.journal!r}", file=sys.stderr)
        print("Available journals:", file=sys.stderr)
        for j in journals:
            print(f"  - {j['journal']}", file=sys.stderr)
        return 2

    # --- 2. input check
    if not os.path.isfile(args.in_file):
        print(f"ERROR: input file not found: {args.in_file}", file=sys.stderr)
        return 2

    # --- 3. CSL resolution
    csl_path = resolve_csl(journal)
    csl_used = csl_path
    if csl_path is None:
        style = journal.get("csl_style", "").strip().strip("`")
        if style.lower() == "verify":
            warn = f"WARNING: CSL style is 'verify' in journals.md for {journal['journal']}."
        else:
            warn = (f"WARNING: CSL file '{style}' not found in {CSL_DIR}. "
                    "Download it from https://www.zotero.org/styles. "
                    "Using pandoc's default citation style.")
        print(warn, file=sys.stderr)

    # --- 4. pandoc
    try:
        rc, stderr = run_pandoc(args.in_file, args.out, csl_path=csl_path)
    except FileNotFoundError:
        print(
            "ERROR: pandoc is not installed. The journal-format skill requires pandoc.\n"
            "Install it from https://pandoc.org/installing.html or via:\n"
            "  macOS:   brew install pandoc\n"
            "  Ubuntu:  sudo apt-get install pandoc\n"
            "  Fedora:  sudo dnf install pandoc",
            file=sys.stderr,
        )
        return 3

    if rc != 0:
        print(f"ERROR: pandoc failed (exit {rc}).", file=sys.stderr)
        if stderr:
            print(stderr, file=sys.stderr)
        return rc

    print(f"Formatted: {args.in_file} -> {args.out}", file=sys.stderr)
    if csl_used:
        print(f"CSL applied: {os.path.basename(csl_used)}", file=sys.stderr)
    else:
        print("CSL: used pandoc default (no style file bundled)", file=sys.stderr)

    # --- 5. checklist
    actual_words = word_count(args.in_file)
    checklist = build_checklist(journal, args.in_file, args.out, csl_used, actual_words)
    print(checklist)
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="format_journal.py",
        description="Format a manuscript for a target journal via pandoc + CSL, "
                    "and print a submission checklist. Looks up journal metadata in "
                    "knowledge/journals.md.",
    )
    p.add_argument("--in", dest="in_file", required=False,
                   help="Input manuscript (.md or .docx)")
    p.add_argument("--journal", required=False,
                   help='Target journal name, e.g. "Journal of Cognitive Neuroscience"')
    p.add_argument("--out", required=False,
                   help="Output file (e.g. submission.docx). Format inferred by pandoc.")
    p.add_argument("--list-journals", action="store_true",
                   help="List journals configured in knowledge/journals.md and exit.")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_journals:
        return cmd_list_journals(args)

    if not args.in_file or not args.journal or not args.out:
        parser.error("the following arguments are required: --in, --journal, --out "
                     "(unless using --list-journals)")

    return cmd_format(args)


if __name__ == "__main__":
    sys.exit(main())
