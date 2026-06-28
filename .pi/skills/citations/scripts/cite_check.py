#!/usr/bin/env python3
"""
cite_check.py — CHATLabAI citations skill.

Validate and organize references; catch retractions; reconcile in-text cites with the .bib.

Free APIs only:
  - Crossref:  https://api.crossref.org/works/{doi}        (DOI resolution)
  - OpenAlex:  https://api.openalex.org/works/doi:{doi}     (is_retracted, update-notice types)

Polite API use: mailto in User-Agent, rate-limit, cache under .cache/cite_check/.
Degrades gracefully: if network or pybtex is unavailable, local-only checks still run.

Usage:
  python3 cite_check.py references/library.bib
  python3 cite_check.py references/library.bib --manuscript draft.docx
  python3 cite_check.py references/library.bib --to-csl references/library.csl.json
  python3 cite_check.py references/library.bib --offline
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

USER_AGENT = "CHATLabAI/1.0 (mailto:chatlab@pennmedicine.upenn.edu)"
CACHE_DIR = Path(".cache/cite_check")
REQUEST_DELAY = 1.0  # seconds between API requests (politeness)

# --------------------------------------------------------------------------- #
# BibTeX parsing (pybtex if available, else a stdlib fallback)
# --------------------------------------------------------------------------- #

def _parse_bibtex_pybtex(path: Path) -> List[Dict]:
    """Parse BibTeX with pybtex. Returns list of entry dicts with normalized fields."""
    from pybtex.database import parse_file  # type: ignore

    bib = parse_file(str(path))
    entries: List[Dict] = []
    for key, entry in bib.entries.items():
        fields = dict(entry.fields)
        # Collect authors as a single string.
        persons = entry.persons.get("author", [])
        if persons:
            fields["author"] = " and ".join(str(p) for p in persons)
        fields["_key"] = key
        fields["_type"] = entry.type
        entries.append(fields)
    return entries


# Stdlib BibTeX parser — handles the common entry forms robustly enough for local checks.
_BIB_ENTRY_RE = re.compile(
    r"@\s*(?P<type>[A-Za-z]+)\s*\{\s*(?P<key>[^,\s]+)\s*,",
)


def _parse_bibtex_stdlib(path: Path) -> List[Dict]:
    """Lightweight stdlib BibTeX parser. Returns list of entry dicts."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # Strip comments (lines starting with % outside entries).
    entries: List[Dict] = []
    pos = 0
    while True:
        m = _BIB_ENTRY_RE.search(text, pos)
        if not m:
            break
        etype = m.group("type").lower()
        ekey = m.group("key")
        # Find the matching closing brace for this entry. The opening '{' is
        # before the key, so walk back from the match start to locate it.
        brace_start = m.start()
        while brace_start < len(text) and text[brace_start] != "{":
            brace_start += 1
        depth = 0
        i = brace_start
        end = -1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
            i += 1
        if end == -1:
            break
        body = text[m.end():end]
        fields: Dict[str, str] = {"_key": ekey, "_type": etype}
        # Parse field=value pairs within body. The lookahead allows a field to be
        # followed by a comma OR to be the last field in the entry (end of body).
        for fm in re.finditer(r"(\w+)\s*=\s*[\{\"](.*?)[}\"](?=\s*(?:,|$))", body, re.DOTALL):
            fname = fm.group(1).lower()
            fval = fm.group(2).strip()
            # Collapse nested braces.
            fval = fval.replace("{", "").replace("}", "")
            fields[fname] = fval
        entries.append(fields)
        pos = end + 1
    return entries


def parse_bibtex(path: Path) -> Tuple[List[Dict], bool]:
    """Parse BibTeX. Returns (entries, used_pybtex). Falls back to stdlib parser."""
    try:
        return _parse_bibtex_pybtex(path), True
    except ImportError:
        return _parse_bibtex_stdlib(path), False
    except Exception as exc:  # pybtex present but parse error
        sys.stderr.write(f"[cite_check] pybtex parse failed ({exc}); using stdlib parser\n")
        return _parse_bibtex_stdlib(path), False


# --------------------------------------------------------------------------- #
# DOI helpers
# --------------------------------------------------------------------------- #

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)


def extract_doi(entry: Dict) -> Optional[str]:
    """Extract and normalize a DOI from an entry's 'doi' field or URL field."""
    raw = entry.get("doi") or ""
    if not raw:
        url = entry.get("url") or ""
        m = _DOI_RE.search(url)
        if m:
            raw = m.group(0)
    if not raw:
        return None
    # Strip URL prefix if present.
    raw = raw.strip()
    raw = re.sub(r"^https?://(dx\.)?doi\.org/", "", raw, flags=re.IGNORECASE)
    raw = raw.lstrip("doi:")
    m = _DOI_RE.search(raw)
    if not m:
        return None  # malformed
    return m.group(0).lower()


def normalize_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


# --------------------------------------------------------------------------- #
# Network (Crossref / OpenAlex) with cache + graceful degradation
# --------------------------------------------------------------------------- #

def _cache_get(key: str) -> Optional[dict]:
    p = CACHE_DIR / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _cache_put(key: str, data: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _http_get_json(url: str, params: Optional[dict] = None) -> Optional[dict]:
    """GET JSON with timeout + User-Agent. Returns None on failure."""
    import requests  # local import so missing dep doesn't break local-only runs

    try:
        r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
        if r.status_code == 404:
            return {"_status": 404}
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def resolve_crossref(doi: str) -> Optional[dict]:
    cache_key = f"crossref_{doi.replace('/', '_')}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    url = f"https://api.crossref.org/works/{doi}"
    data = _http_get_json(url)
    _cache_put(cache_key, data or {})
    time.sleep(REQUEST_DELAY)
    return data


def resolve_openalex(doi: str) -> Optional[dict]:
    cache_key = f"openalex_{doi.replace('/', '_')}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    url = f"https://api.openalex.org/works/doi:{doi}"
    data = _http_get_json(url)
    _cache_put(cache_key, data or {})
    time.sleep(REQUEST_DELAY)
    return data


# --------------------------------------------------------------------------- #
# Manuscript in-text key extraction
# --------------------------------------------------------------------------- #

_LATEX_CITE_RE = re.compile(r"\\cite[a-z]*\*?\{([^}]*)\}")
_PROSE_CITE_RE = re.compile(
    r"\(([A-Z][A-Za-z'\-]+(?:\s+(?:et al\.?|and|&)\s+[A-Z][A-Za-z'\-]+)?)\s*,\s*(\d{4}[a-z]?)\)"
)


def extract_keys_from_latex(text: str) -> List[str]:
    keys: List[str] = []
    for m in _LATEX_CITE_RE.finditer(text):
        for k in m.group(1).split(","):
            k = k.strip()
            if k:
                keys.append(k)
    return keys


def extract_keys_from_docx(path: Path) -> List[str]:
    """Extract (Author, Year) keys from a .docx as 'AuthorYear' tokens."""
    try:
        import docx  # python-docx
    except ImportError:
        sys.stderr.write("[cite_check] python-docx not installed; cannot parse .docx manuscript\n")
        return []
    doc = docx.Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs)
    keys: List[str] = []
    for m in _PROSE_CITE_RE.finditer(text):
        author = m.group(1)
        # Take the first surname only for the key heuristic.
        surname = re.split(r"\s+(?:et al\.?|and|&)\s+", author)[0].split()[-1]
        year = m.group(2)
        keys.append(f"{surname}{year}")
    return keys


def extract_keys_from_manuscript(path: Path) -> List[str]:
    suffix = path.suffix.lower()
    if suffix in (".tex", ".txt", ".md"):
        return extract_keys_from_latex(path.read_text(encoding="utf-8", errors="replace"))
    if suffix == ".docx":
        return extract_keys_from_docx(path)
    sys.stderr.write(f"[cite_check] unsupported manuscript format: {suffix}\n")
    return []


# --------------------------------------------------------------------------- #
# CSL-JSON conversion
# --------------------------------------------------------------------------- #

def entries_to_csl_json(entries: List[Dict]) -> List[dict]:
    """Convert parsed BibTeX entries to CSL-JSON (best-effort)."""
    csl = []
    for e in entries:
        doi = extract_doi(e)
        authors = []
        raw_auth = e.get("author", "")
        for a in raw_auth.split(" and "):
            a = a.strip()
            if not a:
                continue
            if "," in a:
                family, given = a.split(",", 1)
                authors.append({"family": family.strip(), "given": given.strip()})
            else:
                authors.append({"family": a, "given": ""})
        item = {
            "id": e.get("_key", ""),
            "type": _csl_type(e.get("_type", "article")),
            "title": e.get("title", "").strip("{}"),
            "author": authors,
            "issued": _csl_year(e.get("year", "")),
        }
        if e.get("journal"):
            item["container-title"] = e["journal"]
        if e.get("volume"):
            item["volume"] = e["volume"]
        if e.get("pages"):
            item["page"] = e["pages"]
        if doi:
            item["DOI"] = doi
        csl.append(item)
    return csl


def _csl_type(bibtype: str) -> str:
    return {
        "article": "article-journal",
        "inproceedings": "paper-conference",
        "book": "book",
        "incollection": "chapter",
        "phdthesis": "thesis",
    }.get(bibtype, "article-journal")


def _csl_year(year: str) -> dict:
    y = re.search(r"\d{4}", year or "")
    return {"date-parts": [[int(y.group(0))]]} if y else {}


# --------------------------------------------------------------------------- #
# Main report
# --------------------------------------------------------------------------- #

def run_report(bib_path: Path, manuscript: Optional[Path], to_csl: Optional[Path], offline: bool) -> int:
    if not bib_path.exists():
        sys.stderr.write(f"[cite_check] BibTeX file not found: {bib_path}\n")
        return 2

    entries, used_pybtex = parse_bibtex(bib_path)
    print(f"# Citation report: {bib_path}")
    print(f"- Entries parsed: {len(entries)}")
    print(f"- Parser: {'pybtex' if used_pybtex else 'stdlib (fallback)'}")
    print()

    # --- Local: DOI extraction + malformed detection ---
    doi_map: Dict[str, List[str]] = {}  # doi -> [keys]
    malformed: List[str] = []
    no_doi: List[str] = []
    for e in entries:
        key = e.get("_key", "?")
        raw = (e.get("doi") or "").strip()
        doi = extract_doi(e)
        if doi:
            doi_map.setdefault(doi, []).append(key)
        elif raw:
            malformed.append(f"{key} (doi field '{raw}' is not a valid DOI)")
        else:
            no_doi.append(key)

    print("## DOI extraction")
    if malformed:
        print(f"- Malformed DOIs ({len(malformed)}):")
        for m in malformed:
            print(f"    - {m}")
    else:
        print("- No malformed DOIs.")
    if no_doi:
        print(f"- Entries without DOI ({len(no_doi)}): {', '.join(no_doi)}")
    print()

    # --- Local: dedup by DOI or normalized title ---
    print("## Duplicates")
    dupes = []
    # by DOI
    for doi, keys in doi_map.items():
        if len(keys) > 1:
            dupes.append(f"DOI {doi}: keys {keys}")
    # by title
    title_map: Dict[str, List[str]] = {}
    for e in entries:
        t = normalize_title(e.get("title", ""))
        if t:
            title_map.setdefault(t, []).append(e.get("_key", "?"))
    for t, keys in title_map.items():
        if len(keys) > 1:
            dupes.append(f"Title '{t[:40]}...': keys {keys}")
    if dupes:
        for d in dupes:
            print(f"    - {d}")
    else:
        print("- No duplicates found.")
    print()

    # --- Network: Crossref + OpenAlex (graceful degradation) ---
    if offline:
        print("## DOI resolution / retraction check")
        print("- Skipped (--offline).")
        print()
    elif doi_map:
        print("## DOI resolution (Crossref) + retraction check (OpenAlex)")
        net_ok = True
        first_probe = True
        for doi in list(doi_map.keys()):
            keys = doi_map[doi]
            # Probe network on first request; if it fails, degrade gracefully.
            if first_probe:
                cr = resolve_crossref(doi)
                if cr is None:
                    net_ok = False
                    print("- Network unavailable (Crossref unreachable). Skipping online checks.")
                    print("  Local-only checks above still complete. Re-run without --offline when online.")
                    break
                first_probe = False
                _report_one_doi(doi, keys, cr)
            else:
                cr = resolve_crossref(doi)
                _report_one_doi(doi, keys, cr)
        if net_ok:
            print()
    else:
        print("## DOI resolution / retraction check")
        print("- No DOIs to resolve.")
        print()

    # --- Reconciliation ---
    if manuscript:
        if not manuscript.exists():
            sys.stderr.write(f"[cite_check] manuscript not found: {manuscript}\n")
        else:
            print(f"## Reconciliation with manuscript: {manuscript}")
            cited_keys = extract_keys_from_manuscript(manuscript)
            bib_keys = {e.get("_key", "") for e in entries}
            # missing from bib = cited in manuscript but not in bib
            missing_from_bib = [k for k in cited_keys if k not in bib_keys]
            never_cited = [k for k in sorted(bib_keys) if k not in set(cited_keys)]
            print(f"- In-text cites found: {len(cited_keys)} ({', '.join(cited_keys) or 'none'})")
            if missing_from_bib:
                print(f"- Cited but MISSING from .bib ({len(missing_from_bib)}):")
                for k in missing_from_bib:
                    print(f"    - {k}")
            else:
                print("- All in-text cites present in .bib.")
            if never_cited:
                print(f"- In .bib but NEVER cited ({len(never_cited)}):")
                for k in never_cited:
                    print(f"    - {k}")
            print()

    # --- CSL export ---
    if to_csl:
        csl = entries_to_csl_json(entries)
        to_csl.parent.mkdir(parents=True, exist_ok=True)
        to_csl.write_text(json.dumps(csl, indent=2), encoding="utf-8")
        print(f"- CSL-JSON written to {to_csl} ({len(csl)} entries).")
        print()

    return 0


def _report_one_doi(doi: str, keys: List[str], cr: Optional[dict]) -> None:
    if cr is None or cr.get("_status") == 404:
        print(f"- {doi} (keys: {keys}): UNRESOLVED (Crossref 404 / error)")
        return
    msg = cr.get("message", cr)
    title = ""
    if isinstance(msg.get("title"), list) and msg["title"]:
        title = msg["title"][0]
    oa = resolve_openalex(doi)
    retracted = bool(oa and oa.get("is_retracted"))
    flag = "  *** RETRACTED ***" if retracted else ""
    print(f"- {doi} (keys: {keys}): resolved{flag}")
    if title:
        print(f"    title: {title}")
    if retracted and oa and oa.get("retraction"):
        print(f"    retraction: {oa.get('retraction', {})}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cite_check.py",
        description="Validate references, catch retractions, reconcile in-text cites with a .bib.",
    )
    p.add_argument("bib", type=Path, help="Path to the BibTeX (.bib) file.")
    p.add_argument("--manuscript", type=Path, default=None,
                   help="Manuscript to reconcile (.tex, .docx, .txt, .md).")
    p.add_argument("--to-csl", type=Path, default=None,
                   help="Export BibTeX → CSL-JSON to this path.")
    p.add_argument("--offline", action="store_true",
                   help="Skip all network checks (local-only: dedup, malformed, reconcile).")
    args = p.parse_args(argv)
    return run_report(args.bib, args.manuscript, args.to_csl, args.offline)


if __name__ == "__main__":
    sys.exit(main())
