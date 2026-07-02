#!/usr/bin/env python3
"""
lint_claims.py — deterministic claim-linting for CHATLabAI's paper-review skill.

Reviews a manuscript (.docx, .md, .tex, .txt) against Chatterjee's 21 writing rules by
flagging the machine-checkable patterns defined in knowledge/chatterjee-writing-rules.md:

  - banned_mechanism_verbs (rule 3)  — overclaiming mechanism
  - inflated_markers        (rule 8) — inflated theoretical language
  - filler_phrases          (rule 18) — filler phrases to delete
  - filler_adverbs          (rule 18) — filler adverbs to tighten
  - methodology_flag        (rule 21) — "methodology" where "methods" is meant
  - sentence_length         (rule 8 / clarity) — sentences over 45 words

For each flag it reports the matched phrase, line/offset, and (for rule 3) a hedged
replacement suggestion drawn from the hedge_verbs block.

The LLM (pi, via the paper-review skill) does the judgmental review; this script does the
deterministic flagging so nothing is missed.

Usage:
    python3 lint_claims.py <file> [--format json|markdown] [--rules-file PATH]

Exit code is nonzero if any flags are found (useful for CI); --quiet suppresses summary text.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Resolve workspace root relative to this script.
# Script lives at <root>/.pi/skills/paper-review/scripts/lint_claims.py
# parents: [0]=scripts [1]=paper-review [2]=skills [3]=.pi [4]=<root>
SCRIPT_PATH = Path(__file__).resolve()
WORKSPACE_ROOT = SCRIPT_PATH.parents[4]
DEFAULT_RULES_FILE = WORKSPACE_ROOT / "knowledge" / "chatterjee-writing-rules.md"

# Rule 8 / clarity threshold (words). Parsed from the rules file but this is the fallback.
DEFAULT_MAX_SENTENCE_WORDS = 45


# --------------------------------------------------------------------------- data model
@dataclass
class Flag:
    rule: str
    category: str
    match: str
    line: int          # 1-indexed line in the extracted text
    offset: int        # 0-indexed char offset within the line
    suggestion: str = ""
    context: str = ""  # the sentence the match occurs in


@dataclass
class LintResult:
    file: str
    rules_file: str
    flags: List[Flag] = field(default_factory=list)
    sentence_count: int = 0
    word_count: int = 0


# --------------------------------------------------------------------------- rules parsing
def parse_rules(rules_text: str) -> Tuple[List[str], List[str], List[str], List[str], List[str], int]:
    """Parse the machine-checkable blocks from the writing-rules markdown.

    Returns (banned_verbs, inflated_markers, filler_phrases, filler_adverbs,
    methodology_terms, max_sentence_words).
    """
    banned: List[str] = []
    inflated: List[str] = []
    filler_phrases: List[str] = []
    filler_adverbs: List[str] = []
    methodology: List[str] = []
    hedge: List[str] = []
    max_words = DEFAULT_MAX_SENTENCE_WORDS

    # Multi-word phrases live in these blocks; they are intentionally longer than
    # 4 words (e.g. "it is important to note that"), so the prose-fragment skip
    # must not apply to them.
    multiword_sections = {"filler_phrases"}

    # The blocks live under a "## Machine-checkable blocks" heading, each as a "### name" block.
    section = None
    for line in rules_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            name = stripped[4:].split("(")[0].strip().lower().replace(" ", "_")
            section = name
            continue
        if stripped.startswith("## "):
            section = None  # a new top-level section ends any active block
            continue
        if not section or not stripped:
            continue
        # The sentence_length block is descriptive prose ending in "over N words"; parse N.
        if section == "sentence_length":
            m = re.search(r"over\s+(\d+)\s+words", stripped, re.IGNORECASE)
            if m:
                max_words = int(m.group(1))
            continue
        # The verb/marker/phrase blocks are comma-separated lists (possibly with
        # inline prose before the list). Take the trailing comma-list if present,
        # else the whole stripped line.
        if "," in stripped:
            items = [w.strip().strip(".") for w in stripped.split(",")]
        else:
            items = [stripped.strip(".")]
        for w in items:
            w = w.strip().strip("`").strip()
            if not w:
                continue
            # Skip obvious prose fragments that aren't terms — but NOT in the
            # multi-word phrase blocks, whose entries are deliberately long.
            if section not in multiword_sections and len(w.split()) > 4:
                continue
            if section == "banned_mechanism_verbs":
                banned.append(w)
            elif section == "hedge_verbs":
                hedge.append(w)
            elif section == "inflated_markers":
                inflated.append(w)
            elif section == "filler_phrases":
                filler_phrases.append(w)
            elif section == "filler_adverbs":
                filler_adverbs.append(w)
            elif section == "methodology_flag":
                methodology.append(w)
    # Dedup preserving order.
    def _dedup(xs: List[str]) -> List[str]:
        seen = set()
        return [x for x in xs if not (x in seen or seen.add(x))]
    banned = _dedup(banned)
    inflated = _dedup(inflated)
    filler_phrases = _dedup(filler_phrases)
    filler_adverbs = _dedup(filler_adverbs)
    methodology = _dedup(methodology)
    return banned, inflated, filler_phrases, filler_adverbs, methodology, max_words


# --------------------------------------------------------------------------- text extraction
def extract_text(path: Path) -> str:
    """Extract plain text from .docx (python-docx), .md/.tex/.txt (raw)."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            from docx import Document  # type: ignore
        except ImportError:
            sys.exit(
                "ERROR: python-docx is required to read .docx files. "
                "Install it with: pip install python-docx"
            )
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    # plain text family
    return path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- sentence splitting
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def split_sentences(text: str) -> List[Tuple[str, int, int]]:
    """Split into sentences. Returns [(sentence, line_no, start_offset_in_line)]."""
    sentences: List[Tuple[str, int, int]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        start = 0
        for sent in _SENTENCE_END.split(line):
            sent = sent.strip()
            if not sent:
                continue
            offset = line.find(sent, start)
            if offset == -1:
                offset = 0
            sentences.append((sent, line_no, offset))
            start = offset + len(sent)
        # If the whole line was one sentence (no split), the loop handled it.
    return sentences


# --------------------------------------------------------------------------- linting
def lint(
    text: str,
    banned: List[str],
    inflated: List[str],
    filler_phrases: List[str],
    filler_adverbs: List[str],
    methodology: List[str],
    max_words: int,
) -> Tuple[List[Flag], int, int]:
    flags: List[Flag] = []
    sentences = split_sentences(text)
    word_count = sum(len(s.split()) for s, _, _ in sentences)

    # Word-boundary regex for single-word terms (verbs, markers, adverbs).
    # Escape terms; longer first for greedy match.
    def build_regex(terms: List[str]) -> re.Pattern:
        if not terms:
            return re.compile(r"(?!)")
        ordered = sorted(set(terms), key=len, reverse=True)
        return re.compile(r"\b(" + "|".join(re.escape(t) for t in ordered) + r")\b", re.IGNORECASE)

    # Phrase regex for multi-word terms (e.g. "it is important to note that").
    # No \b word boundaries around the whole alternation — a phrase ending in
    # "...that" is matched cleanly before trailing punctuation without requiring
    # a word boundary that would break on it. Case-insensitive. re.escape handles
    # the spaces (as escaped spaces, which match literal spaces in the text).
    def build_phrase_regex(terms: List[str]) -> re.Pattern:
        if not terms:
            return re.compile(r"(?!)")
        ordered = sorted(set(terms), key=len, reverse=True)
        return re.compile("|".join(re.escape(t) for t in ordered), re.IGNORECASE)

    banned_re = build_regex(banned)
    inflated_re = build_regex(inflated)
    filler_phrase_re = build_phrase_regex(filler_phrases)
    filler_adverb_re = build_regex(filler_adverbs)
    methodology_re = build_regex(methodology)

    for sent, line_no, offset in sentences:
        # Rule 3 — banned mechanism verbs.
        for m in banned_re.finditer(sent):
            # Find absolute offset within the line.
            rel = m.start()
            flags.append(
                Flag(
                    rule="rule-3",
                    category="banned_mechanism_verbs",
                    match=m.group(0),
                    line=line_no,
                    offset=offset + rel,
                    suggestion="is consistent with",  # default hedge; refine below
                    context=sent,
                )
            )
        # Rule 8 — inflated markers.
        for m in inflated_re.finditer(sent):
            rel = m.start()
            flags.append(
                Flag(
                    rule="rule-8",
                    category="inflated_markers",
                    match=m.group(0),
                    line=line_no,
                    offset=offset + rel,
                    suggestion="plain, direct phrasing",
                    context=sent,
                )
            )
        # Rule 18 — filler phrases (multi-word). Suggest deletion.
        for m in filler_phrase_re.finditer(sent):
            rel = m.start()
            flags.append(
                Flag(
                    rule="rule-18",
                    category="filler_phrase",
                    match=m.group(0),
                    line=line_no,
                    offset=offset + rel,
                    suggestion="delete this phrase",
                    context=sent,
                )
            )
        # Rule 18 — filler adverbs (single-word). Suggest deletion.
        for m in filler_adverb_re.finditer(sent):
            rel = m.start()
            flags.append(
                Flag(
                    rule="rule-18",
                    category="filler_adverb",
                    match=m.group(0),
                    line=line_no,
                    offset=offset + rel,
                    suggestion="delete or replace with a plain word",
                    context=sent,
                )
            )
        # Rule 21 — "methodology" where "methods" is meant. Anjan's standing
        # correction: it's methods, not methodology.
        for m in methodology_re.finditer(sent):
            rel = m.start()
            flags.append(
                Flag(
                    rule="rule-21",
                    category="methodology_flag",
                    match=m.group(0),
                    line=line_no,
                    offset=offset + rel,
                    suggestion='use "methods" (reserve "methodology" for a paper about methods as a subject)',
                    context=sent,
                )
            )
        # Rule 8 / clarity — overlong sentences.
        words = sent.split()
        if len(words) > max_words:
            flags.append(
                Flag(
                    rule="rule-8",
                    category="overlong_sentence",
                    match=f"{len(words)} words",
                    line=line_no,
                    offset=offset,
                    suggestion=f"tighten to <= {max_words} words",
                    context=sent,
                )
            )
    return flags, len(sentences), word_count


# --------------------------------------------------------------------------- output
def to_json(result: LintResult) -> str:
    return json.dumps(
        {
            "file": result.file,
            "rules_file": result.rules_file,
            "sentence_count": result.sentence_count,
            "word_count": result.word_count,
            "flag_count": len(result.flags),
            "flags": [asdict(f) for f in result.flags],
        },
        indent=2,
    )


def to_markdown(result: LintResult) -> str:
    out: List[str] = []
    out.append(f"# Paper Review — Claim Lint Report")
    out.append("")
    out.append(f"- **File:** `{result.file}`")
    out.append(f"- **Rules:** `{result.rules_file}`")
    out.append(f"- **Sentences:** {result.sentence_count} | **Words:** {result.word_count}")
    out.append(f"- **Flags:** {len(result.flags)}")
    out.append("")
    if not result.flags:
        out.append("No deterministic flags. The LLM should still perform the full 21-rule review.")
        return "\n".join(out)

    # Group by rule.
    by_rule: Dict[str, List[Flag]] = {}
    for f in result.flags:
        by_rule.setdefault(f.rule, []).append(f)

    rule_titles = {
        "rule-3": "Rule 3 — Do not overclaim mechanism (banned verbs)",
        "rule-8": "Rule 8 — Cut inflated language / overlong sentences",
        "rule-18": "Rule 18 — Cut filler phrases and adverbs",
        "rule-21": "Rule 21 — Methods, not methodology",
    }
    for rule in sorted(by_rule):
        out.append(f"## {rule_titles.get(rule, rule)}")
        out.append("")
        for f in by_rule[rule]:
            out.append(f"- **`{f.match}`** (line {f.line}, col {f.offset}) — *{f.category}*")
            if f.suggestion:
                out.append(f"  - Suggestion: {f.suggestion}")
            out.append(f"  - Context: \"{f.context}\"")
        out.append("")
    out.append("---")
    out.append(
        "The LLM should now perform the full judgmental review: per-rule pass/flag with "
        "concrete fixes, the rule-10 one-sentence contribution test, and the rule-4 "
        "evidence→interpretation chain check."
    )
    return "\n".join(out)


# --------------------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="lint_claims.py",
        description="Deterministically flag banned mechanism verbs (rule 3), inflated markers "
        "(rule 8), filler phrases/adverbs (rule 18), and overlong sentences (rule 8/clarity) "
        "in a manuscript. Reads machine-checkable blocks from knowledge/chatterjee-writing-rules.md.",
    )
    p.add_argument("file", help="Manuscript file: .docx, .md, .tex, or .txt")
    p.add_argument(
        "--rules-file",
        default=str(DEFAULT_RULES_FILE),
        help=f"Path to chatterjee-writing-rules.md (default: {DEFAULT_RULES_FILE})",
    )
    p.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress the human summary on stderr")
    args = p.parse_args(argv)

    src = Path(args.file)
    if not src.is_file():
        sys.exit(f"ERROR: file not found: {src}")

    rules_path = Path(args.rules_file)
    if not rules_path.is_file():
        sys.exit(f"ERROR: rules file not found: {rules_path}")

    rules_text = rules_path.read_text(encoding="utf-8")
    banned, inflated, filler_phrases, filler_adverbs, methodology, max_words = parse_rules(rules_text)

    text = extract_text(src)
    flags, n_sent, n_words = lint(text, banned, inflated, filler_phrases, filler_adverbs, methodology, max_words)

    result = LintResult(
        file=str(src),
        rules_file=str(rules_path),
        flags=flags,
        sentence_count=n_sent,
        word_count=n_words,
    )

    out = to_json(result) if args.format == "json" else to_markdown(result)
    print(out)

    if not args.quiet:
        n_flags = len(flags)
        sys.stderr.write(
            f"\n[{n_flags} flag(s): "
            f"{sum(1 for f in flags if f.category=='banned_mechanism_verbs')} banned-verb, "
            f"{sum(1 for f in flags if f.category=='inflated_markers')} inflated, "
            f"{sum(1 for f in flags if f.category=='filler_phrase')} filler-phrase, "
            f"{sum(1 for f in flags if f.category=='filler_adverb')} filler-adverb, "
            f"{sum(1 for f in flags if f.category=='methodology_flag')} methodology, "
            f"{sum(1 for f in flags if f.category=='overlong_sentence')} overlong]\n"
        )

    # Nonzero exit if flags found (CI-friendly).
    return 1 if flags else 0


if __name__ == "__main__":
    raise SystemExit(main())
