#!/usr/bin/env python3
"""
docx_track.py — Surgical track-changes editing of .docx files.

Implements REAL Word tracked revisions (OOXML w:ins / w:del), author = CHATLabAI.
Uses python-docx for the document model and drops down to lxml for the revision
elements (python-docx has no native track-changes writer).

API (importable):
    apply_tracked_edits(in_path, edits, out_path, author="CHATLabAI", date=None)

    edits = [
        {
            "paragraph_index": 0,
            "find": "proves that architects hardwired a response in viewers",
            "replace": "is consistent with architects recruiting a response in viewers",
            "comment": "Rule 3: hedge mechanism verb",
        },
        ...
    ]

CLI:
    python3 docx_track.py --in draft.docx --edits edits.json --out draft.tracked.docx
    python3 docx_track.py --in draft.docx --edits edits.json --out draft.tracked.docx \
        --changelog change-log.md

The edits.json is a JSON list of objects with keys:
    paragraph_index (int), find (str), replace (str), comment (str, optional).

For each edit, the script:
  1. Locates the paragraph by index in the document body (0-based over paragraphs).
  2. Finds the `find` substring within the paragraph's concatenated run text.
  3. Splits the run(s) so only the matched text is isolated.
  4. Wraps the matched text in <w:del><w:r><w:delText> and the replacement in
     <w:ins><w:r><w:t>, each with w:author and w:date and a unique w:id.
  5. Optionally writes a change-log.md citing the comment (which should name the rule).

Safety:
  - Non-destructive: never modifies the input file; writes a new --out path.
  - If a `find` text is not found in the target paragraph, the edit is skipped with a
    clear warning (no silent failure).
  - Run splitting preserves as much of the original run formatting as possible: the
    replacement run inherits the formatting of the first run in the deleted span.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from typing import Any

# python-docx for the document model
try:
    from docx import Document
    from docx.oxml.ns import qn
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "ERROR: python-docx is required. Install with: pip install python-docx\n"
    )
    raise

# lxml is a dependency of python-docx; we use it directly for revision elements
from lxml import etree


# ---------------------------------------------------------------------------
# OOXML namespace helpers
# ---------------------------------------------------------------------------

# WordprocessingML namespace
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}

# Revision id counter (incremented per deleted/inserted element for uniqueness).
# Word requires w:id to be unique within the document for revision marks.


def _qn(tag: str) -> str:
    """Qualified name for a w: tag (shorthand)."""
    return f"{{{W_NS}}}{tag}"


def _make_run_props_clone(source_run_element: Any) -> Any:
    """
    Clone the <w:rPr> (run properties) from a source run element so the
    replacement/inserted text inherits formatting (bold, italic, font, size).
    Returns a new <w:rPr> element or None if the source has none.
    """
    rpr = source_run_element.find(_qn("rPr"))
    if rpr is None:
        return None
    # Deep copy so we don't link to the original tree
    from copy import deepcopy

    return deepcopy(rpr)


def _new_revision_id(counter: list[int]) -> int:
    """Return a monotonically increasing revision id and advance the counter."""
    val = counter[0]
    counter[0] += 1
    return val


# ---------------------------------------------------------------------------
# Core: locate text in a paragraph and split runs to isolate it
# ---------------------------------------------------------------------------


def _paragraph_runs(paragraph) -> list:
    """Return the list of <w:r> run elements in a paragraph, in document order."""
    return paragraph._p.findall(_qn("r"))


def _run_text(run_element: Any) -> str:
    """Concatenate all <w:t> text in a run element."""
    parts = []
    for t in run_element.findall(_qn("t")):
        parts.append(t.text or "")
    return "".join(parts)


def _set_run_text(run_element: Any, text: str) -> None:
    """
    Set the text of a run. Removes all existing <w:t> children and adds a single
    new <w:t xml:space="preserve"> with the given text.
    """
    # Remove existing <w:t> and <w:delText> children
    for child in list(run_element):
        tag = etree.QName(child).localname
        if tag in ("t", "delText"):
            run_element.remove(child)
    t = etree.SubElement(run_element, _qn("t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text


def _build_run_with_text(rpr: Any, text: str, tag: str = "t") -> Any:
    """
    Build a new <w:r> element with optional run properties and a <w:t>/<w:delText>
    child carrying `text`.
    """
    r = etree.Element(_qn("r"))
    if rpr is not None:
        from copy import deepcopy

        r.append(deepcopy(rpr))
    t = etree.SubElement(r, _qn(tag))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return r


def _find_and_split_run(paragraph, search_text: str):
    """
    Find `search_text` within the paragraph's run text. If found, split the runs
    so that the matched text occupies exactly one run, and return a tuple:
        (matched_run_element, char_start_in_paragraph, char_end_in_paragraph)
    If not found, return (None, -1, -1).

    Because text may span multiple runs, we first build a map of char positions
    to runs, then if the match spans runs we merge the text into a single run
    (preserving the formatting of the first run in the matched span).
    """
    runs = _paragraph_runs(paragraph)
    if not runs:
        return None, -1, -1

    # Build cumulative text and position map
    full_text = ""
    run_boundaries = []  # list of (run_element, start, end) char offsets
    for r in runs:
        rt = _run_text(r)
        run_boundaries.append((r, len(full_text), len(full_text) + len(rt)))
        full_text += rt

    idx = full_text.find(search_text)
    if idx == -1:
        return None, -1, -1

    end = idx + len(search_text)

    # Determine which run(s) the match spans
    first_run_i = None
    last_run_i = None
    for i, (r, rs, re_) in enumerate(run_boundaries):
        if first_run_i is None and re_ > idx:
            first_run_i = i
        if rs < end:
            last_run_i = i
    if first_run_i is None or last_run_i is None:
        return None, -1, -1

    # If the match is contained within a single run, split that run into up to 3.
    if first_run_i == last_run_i:
        r, rs, re_ = run_boundaries[first_run_i]
        rt = _run_text(r)
        # The matched text is rt[idx-rs : end-rs] within this run
        local_start = idx - rs
        local_end = end - rs
        before = rt[:local_start]
        matched = rt[local_start:local_end]
        after = rt[local_end:]

        parent = r.getparent()
        r_index = list(parent).index(r)

        # Capture formatting before we mutate
        rpr = _make_run_props_clone(r)

        # We'll rebuild: [before_run] [matched_run] [after_run]
        # Reuse the original run element for `before` if non-empty, else for matched.
        nodes_to_insert = []

        if before:
            nodes_to_insert.append(_build_run_with_text(rpr, before))
        # The matched run — reuse the original element's formatting
        matched_run = _build_run_with_text(rpr, matched)
        nodes_to_insert.append(matched_run)
        if after:
            nodes_to_insert.append(_build_run_with_text(rpr, after))

        # Remove original run and insert the new ones at the same position
        parent.remove(r)
        for offset, node in enumerate(nodes_to_insert):
            parent.insert(r_index + offset, node)

        return matched_run, idx, end

    # Match spans multiple runs: merge the matched portion into the first run,
    # preserving its formatting, and trim the remainder runs.
    first_r, first_rs, first_re = run_boundaries[first_run_i]
    last_r, last_rs, last_re = run_boundaries[last_run_i]

    # Collect the matched text
    matched_parts = []
    # First run: from idx to end of first run text
    matched_parts.append(_run_text(first_r)[idx - first_rs:])
    # Middle runs: entire text
    for i in range(first_run_i + 1, last_run_i):
        matched_parts.append(_run_text(run_boundaries[i][0]))
    # Last run: from start to end
    matched_parts.append(_run_text(last_r)[: end - last_rs])
    matched_text = "".join(matched_parts)

    rpr = _make_run_props_clone(first_r)
    parent = first_r.getparent()
    first_index = list(parent).index(first_r)

    # Build: trimmed first run (before match) + matched run
    before_text = _run_text(first_r)[: idx - first_rs]
    nodes_to_insert = []
    if before_text:
        nodes_to_insert.append(_build_run_with_text(rpr, before_text))
    matched_run = _build_run_with_text(rpr, matched_text)
    nodes_to_insert.append(matched_run)

    # After text from the last run
    after_text = _run_text(last_r)[end - last_rs:]
    if after_text:
        nodes_to_insert.append(_build_run_with_text(rpr, after_text))

    # Remove all runs from first_run_i to last_run_i
    runs_to_remove = [run_boundaries[i][0] for i in range(first_run_i, last_run_i + 1)]
    for r in runs_to_remove:
        parent.remove(r)
    for offset, node in enumerate(nodes_to_insert):
        parent.insert(first_index + offset, node)

    return matched_run, idx, end


# ---------------------------------------------------------------------------
# Core: apply a single tracked edit
# ---------------------------------------------------------------------------


def _apply_one_edit(
    paragraph,
    find_text: str,
    replace_text: str,
    author: str,
    date_iso: str,
    id_counter: list[int],
    comment: str | None,
    changelog: list[dict],
    edit_index: int,
) -> bool:
    """
    Apply one tracked edit to a paragraph. Returns True if applied, False if skipped.
    Appends to `changelog`.
    """
    matched_run, char_start, char_end = _find_and_split_run(paragraph, find_text)
    if matched_run is None:
        sys.stderr.write(
            f"  WARN: edit #{edit_index}: find-text not found in paragraph: "
            f"{find_text!r}\n"
        )
        changelog.append(
            {
                "edit_index": edit_index,
                "status": "skipped_not_found",
                "find": find_text,
                "replace": replace_text,
                "comment": comment or "",
            }
        )
        return False

    matched_text = _run_text(matched_run)
    parent = matched_run.getparent()
    r_index = list(parent).index(matched_run)
    rpr = _make_run_props_clone(matched_run)

    # 1. Build the <w:del> element wrapping the deleted run.
    #    Structure:
    #      <w:del w:id=".." w:author=".." w:date="..">
    #        <w:r><w:rPr>...</w:rPr><w:delText xml:space="preserve">matched</w:delText></w:r>
    #      </w:del>
    del_elem = etree.Element(_qn("del"))
    del_elem.set(_qn("id"), str(_new_revision_id(id_counter)))
    del_elem.set(_qn("author"), author)
    del_elem.set(_qn("date"), date_iso)
    del_run = _build_run_with_text(rpr, matched_text, tag="delText")
    del_elem.append(del_run)

    # 2. Build the <w:ins> element wrapping the inserted run.
    #    Structure:
    #      <w:ins w:id=".." w:author=".." w:date="..">
    #        <w:r><w:rPr>...</w:rPr><w:t xml:space="preserve">replacement</w:t></w:r>
    #      </w:ins>
    ins_elem = etree.Element(_qn("ins"))
    ins_elem.set(_qn("id"), str(_new_revision_id(id_counter)))
    ins_elem.set(_qn("author"), author)
    ins_elem.set(_qn("date"), date_iso)
    ins_run = _build_run_with_text(rpr, replace_text, tag="t")
    ins_elem.append(ins_run)

    # 3. Replace the matched run with [del, ins] in document order.
    parent.remove(matched_run)
    parent.insert(r_index, del_elem)
    parent.insert(r_index + 1, ins_elem)

    # Extract a rule number from the comment if present (e.g. "Rule 3: ...")
    rule_num = None
    if comment:
        m = re.search(r"rule\s*(\d+)", comment, re.IGNORECASE)
        if m:
            rule_num = m.group(1)

    changelog.append(
        {
            "edit_index": edit_index,
            "status": "applied",
            "paragraph_index": None,  # filled by caller
            "find": find_text,
            "replace": replace_text,
            "comment": comment or "",
            "rule": rule_num,
            "author": author,
            "date": date_iso,
        }
    )
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_tracked_edits(
    in_path: str,
    edits: list[dict],
    out_path: str,
    author: str = "CHATLabAI",
    date: str | None = None,
    changelog_path: str | None = None,
) -> dict:
    """
    Apply tracked edits to a .docx and write a redlined output.

    Args:
        in_path: path to the input .docx (not modified).
        edits: list of {paragraph_index, find, replace, comment?}.
        out_path: path for the redlined output .docx.
        author: revision author (default CHATLabAI).
        date: ISO-8601 datetime string; defaults to now.
        changelog_path: if given, write a change-log.md here.

    Returns:
        dict with keys: applied, skipped, total, changelog (list), out_path.
    """
    if date is None:
        date = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    if not os.path.exists(in_path):
        raise FileNotFoundError(f"Input docx not found: {in_path}")

    doc = Document(in_path)
    paragraphs = doc.paragraphs
    id_counter = [1]  # mutable counter for unique w:id values
    changelog: list[dict] = []

    # Track document-level edit tracking flag: ensure revisions are tracked
    settings = doc.settings.element
    # Add <w:trackChanges/> so Word shows revisions (optional but good practice)
    existing_track = settings.find(_qn("trackChanges"))
    if existing_track is None:
        track = etree.SubElement(settings, _qn("trackChanges"))
        # trackChanges has no attributes required, but id is conventional
        track.set(_qn("id"), "0")

    for i, edit in enumerate(edits):
        pidx = edit.get("paragraph_index")
        find_text = edit.get("find")
        replace_text = edit.get("replace")
        comment = edit.get("comment")

        if pidx is None or find_text is None or replace_text is None:
            sys.stderr.write(
                f"  WARN: edit #{i}: missing required key "
                f"(paragraph_index/find/replace). Skipping.\n"
            )
            changelog.append(
                {
                    "edit_index": i,
                    "status": "skipped_invalid",
                    "comment": comment or "",
                }
            )
            continue

        if pidx < 0 or pidx >= len(paragraphs):
            sys.stderr.write(
                f"  WARN: edit #{i}: paragraph_index {pidx} out of range "
                f"(0..{len(paragraphs) - 1}). Skipping.\n"
            )
            changelog.append(
                {
                    "edit_index": i,
                    "status": "skipped_out_of_range",
                    "paragraph_index": pidx,
                    "comment": comment or "",
                }
            )
            continue

        applied = _apply_one_edit(
            paragraphs[pidx],
            find_text,
            replace_text,
            author,
            date,
            id_counter,
            comment,
            changelog,
            i,
        )
        if applied:
            changelog[-1]["paragraph_index"] = pidx

    doc.save(out_path)

    applied_count = sum(1 for c in changelog if c.get("status") == "applied")
    skipped_count = len(changelog) - applied_count

    if changelog_path:
        _write_changelog_md(changelog_path, changelog, author, date, in_path, out_path)

    return {
        "applied": applied_count,
        "skipped": skipped_count,
        "total": len(edits),
        "changelog": changelog,
        "out_path": out_path,
    }


def _write_changelog_md(
    path: str,
    changelog: list[dict],
    author: str,
    date: str,
    in_path: str,
    out_path: str,
) -> None:
    """Write a human/markdown change-log citing the rule per edit."""
    lines = [
        "# Change Log",
        "",
        f"- **Source:** `{in_path}`",
        f"- **Redlined output:** `{out_path}`",
        f"- **Author:** {author}",
        f"- **Date:** {date}",
        "",
        "## Edits",
        "",
    ]
    if not changelog:
        lines.append("_No edits applied._\n")
    else:
        lines.append("| # | Status | Paragraph | Rule | Find → Replace | Comment |")
        lines.append("|---|--------|-----------|------|----------------|---------|")
        for c in changelog:
            num = c.get("edit_index", "")
            status = c.get("status", "")
            pidx = c.get("paragraph_index", "—")
            rule = c.get("rule", "—")
            find = (c.get("find", "") or "")[:60]
            replace = (c.get("replace", "") or "")[:60]
            comment = c.get("comment", "") or ""
            lines.append(
                f"| {num} | {status} | {pidx} | {rule} | "
                f"`{find}` → `{replace}` | {comment} |"
            )
        lines.append("")
        lines.append("## Rule citations")
        lines.append("")
        rule_edits = [c for c in changelog if c.get("rule")]
        if rule_edits:
            for c in rule_edits:
                lines.append(
                    f"- **Rule {c['rule']}** (edit #{c.get('edit_index', '?')}): "
                    f"{c.get('comment', '')}"
                )
        else:
            lines.append("_No explicit rule citations in comments._")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="docx_track.py",
        description=(
            "Apply surgical track-changes edits to a .docx as real Word tracked "
            "revisions (w:ins/w:del), author = CHATLabAI. Writes a redlined "
            "output .docx plus an optional change-log.md."
        ),
        epilog=(
            "edits.json format: a JSON list of objects with keys "
            "paragraph_index (int), find (str), replace (str), comment (str, optional). "
            "Example: "
            '[{"paragraph_index":0,"find":"proves","replace":"is consistent with",'
            '"comment":"Rule 3: hedge mechanism verb"}]'
        ),
    )
    parser.add_argument(
        "--in", dest="in_path", required=True, help="Input .docx path (not modified)."
    )
    parser.add_argument(
        "--edits",
        dest="edits_path",
        required=True,
        help="Path to edits.json (list of edit objects).",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        required=True,
        help="Output redlined .docx path.",
    )
    parser.add_argument(
        "--author",
        default="CHATLabAI",
        help="Revision author (default: CHATLabAI).",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="ISO-8601 datetime for revisions (default: now).",
    )
    parser.add_argument(
        "--changelog",
        dest="changelog_path",
        default=None,
        help="Path to write change-log.md (default: alongside output as change-log.md).",
    )
    args = parser.parse_args()

    if not os.path.exists(args.in_path):
        sys.stderr.write(f"ERROR: input file not found: {args.in_path}\n")
        return 2
    if not os.path.exists(args.edits_path):
        sys.stderr.write(f"ERROR: edits file not found: {args.edits_path}\n")
        return 2

    with open(args.edits_path, "r", encoding="utf-8") as f:
        edits = json.load(f)
    if not isinstance(edits, list):
        sys.stderr.write("ERROR: edits.json must be a JSON list of edit objects.\n")
        return 2

    changelog_path = args.changelog_path
    if changelog_path is None:
        out_dir = os.path.dirname(os.path.abspath(args.out_path)) or "."
        changelog_path = os.path.join(out_dir, "change-log.md")

    result = apply_tracked_edits(
        in_path=args.in_path,
        edits=edits,
        out_path=args.out_path,
        author=args.author,
        date=args.date,
        changelog_path=changelog_path,
    )

    print(f"Tracked edits applied: {result['applied']}/{result['total']}")
    print(f"Skipped: {result['skipped']}")
    print(f"Redlined output: {result['out_path']}")
    print(f"Change log:      {changelog_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
