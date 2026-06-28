#!/usr/bin/env python3
"""
litsearch.py — Neuroaesthetics literature search across free scholarly APIs.

Queries OpenAlex, PubMed E-utilities, and Crossref; merges and dedups by DOI;
ranks by relevance + citation count + recency; emits an annotated review.md and
appends valid BibTeX to references/library.bib.

Free APIs only. Polite: mailto in User-Agent, rate-limit between calls, cache
under .cache/. No external Python deps (stdlib urllib only).

Usage:
    python3 litsearch.py "neuroaesthetics face beauty" [--n 25] [--since 2015]
        [--bib references/library.bib] [--seed-terms a,b,c] [--out review.md]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]  # scripts -> lit-review -> skills -> .pi -> root
DEFAULT_BIB = WORKSPACE_ROOT / "references" / "library.bib"
LAB_INFO = WORKSPACE_ROOT / "knowledge" / "lab-info.md"
CACHE_DIR = WORKSPACE_ROOT / ".cache" / "lit-review"
MAILTO = os.environ.get("CHATLABAI_MAILTO", "research@neuroaesthetics.penn.edu")
USER_AGENT = f"CHATLabAI/1.0 (mailto:{MAILTO})"
RATE_LIMIT_SEC = 1.0          # polite pause between API calls
NETWORK_TIMEOUT = 15          # seconds per request
RETRY_ATTEMPTS = 2            # retries on 429/5xx

# Default seed terms derived from knowledge/lab-info.md domain vocabulary.
DEFAULT_SEED_TERMS = [
    "aesthetic triad",
    "empirical aesthetics",
    "beauty",
    "face perception",
    "art perception",
    "architecture perception",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[litsearch] {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"[litsearch] WARNING: {msg}", file=sys.stderr)


def die(msg: str, code: int = 1) -> None:
    print(f"[litsearch] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_seed_terms_from_lab_info() -> list[str]:
    """Parse the Domain vocabulary section of knowledge/lab-info.md."""
    if not LAB_INFO.exists():
        return DEFAULT_SEED_TERMS
    try:
        text = LAB_INFO.read_text(encoding="utf-8")
    except Exception:
        return DEFAULT_SEED_TERMS
    # Extract bold tokens from the Domain vocabulary section.
    vocab_section = ""
    if "## Domain vocabulary" in text:
        vocab_section = text.split("## Domain vocabulary", 1)[1]
        # Stop at next section heading.
        vocab_section = vocab_section.split("\n## ", 1)[0]
    else:
        vocab_section = text
    terms = re.findall(r"\*\*([^*]+)\*\*", vocab_section)
    # Normalize: lowercase, strip, filter out non-vocab boldings.
    cleaned = []
    for t in terms:
        t = t.strip().rstrip(":").strip().lower()
        if t and len(t) > 2 and t not in cleaned:
            cleaned.append(t)
    return cleaned if cleaned else DEFAULT_SEED_TERMS


def cache_get(key: str) -> str | None:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def cache_put(key: str, data: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(data, encoding="utf-8")
    except Exception:
        pass  # caching is best-effort


def cache_key(prefix: str, url: str) -> str:
    return hashlib.sha256(f"{prefix}:{url}".encode()).hexdigest()[:24]


def fetch_json(url: str, timeout: int = NETWORK_TIMEOUT) -> dict | list | None:
    """Fetch JSON with retry on 429/5xx; returns None on failure."""
    key = cache_key("fetch", url)
    cached = cache_get(key)
    if cached is not None:
        try:
            return json.loads(cached)
        except Exception:
            pass

    last_err = None
    for attempt in range(1, RETRY_ATTEMPTS + 2):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                cache_put(key, raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504) and attempt <= RETRY_ATTEMPTS:
                wait = RATE_LIMIT_SEC * attempt * 2
                warn(f"HTTP {e.code} on {url[:80]}... retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            return None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            last_err = e
            return None
        except Exception:
            return None
    if last_err:
        warn(f"Failed after retries: {url[:80]} — {last_err}")
    return None


# --------------------------------------------------------------------------- #
# API queries
# --------------------------------------------------------------------------- #
def query_openalex(query: str, n: int, since: int | None) -> list[dict]:
    """Query OpenAlex works search."""
    base = "https://api.openalex.org/works"
    params = {
        "search": query,
        "per-page": str(min(n, 50)),
        "sort": "relevance_score:desc",
    }
    if since:
        params["filter"] = f"from_publication_date:{since}-01-01"
    url = f"{base}?{urllib.parse.urlencode(params)}"
    data = fetch_json(url)
    if not data or not isinstance(data, dict):
        return []
    results = []
    for w in data.get("results", []) or []:
        doi = (w.get("doi") or "").replace("https://doi.org/", "").strip()
        if not doi:
            continue
        # Authors
        authors_raw = w.get("authorships") or []
        authors = []
        for a in authors_raw:
            name = (a.get("author") or {}).get("display_name") or ""
            if name:
                authors.append(name)
        venue = (w.get("primary_location") or {}).get("source") or {}
        venue_name = venue.get("display_name") or ""
        year = w.get("publication_year")
        cited = w.get("cited_by_count") or 0
        abstract = _reconstruct_openalex_abstract(w.get("abstract_inverted_index"))
        concepts = [c.get("display_name", "") for c in (w.get("concepts") or [])[:5]]
        results.append({
            "doi": doi.lower(),
            "title": (w.get("title") or "").strip(),
            "authors": authors,
            "year": year,
            "venue": venue_name,
            "cited_by_count": cited,
            "abstract": abstract,
            "concepts": concepts,
            "source": "openalex",
            "relevance": w.get("relevance_score") or 0.0,
        })
    return results


def _reconstruct_openalex_abstract(inverted_index: dict | None) -> str:
    """Reconstruct an OpenAlex abstract from its inverted index."""
    if not inverted_index:
        return ""
    pos_to_word = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            pos_to_word[pos] = word
    return " ".join(pos_to_word[i] for i in sorted(pos_to_word))


def query_pubmed(query: str, n: int, since: int | None) -> list[dict]:
    """Query PubMed E-utilities: esearch then efetch (JSON summary via esummary)."""
    esearch_params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(min(n, 50)),
        "retmode": "json",
        "tool": "CHATLabAI",
        "email": MAILTO,
    }
    if since:
        esearch_params["mindate"] = f"{since}/01/01"
        esearch_params["datetype"] = "pdat"
    esearch_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        + urllib.parse.urlencode(esearch_params)
    )
    data = fetch_json(esearch_url)
    if not data or not isinstance(data, dict):
        return []
    ids = data.get("esearchresult", {}).get("idlist") or []
    if not ids:
        return []
    time.sleep(RATE_LIMIT_SEC)

    # Use esummary for metadata (no DOI sometimes, but fast + structured).
    esummary_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
        + urllib.parse.urlencode({
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
            "tool": "CHATLabAI",
            "email": MAILTO,
        })
    )
    sdata = fetch_json(esummary_url)
    if not sdata or not isinstance(sdata, dict):
        return []
    results = []
    result_set = sdata.get("result") or {}
    for pmid in ids:
        rec = result_set.get(pmid) or {}
        if not rec:
            continue
        # Extract DOI from articleids.
        doi = ""
        for aid in rec.get("articleids") or []:
            if aid.get("idtype") == "doi":
                doi = (aid.get("value") or "").strip()
                break
        if not doi:
            continue
        authors = []
        for a in rec.get("authors") or []:
            name = a.get("name") or ""
            if name:
                authors.append(name)
        year_str = ""
        pubdate = rec.get("pubdate") or ""
        m = re.match(r"(\d{4})", pubdate)
        if m:
            year_str = m.group(1)
        year = int(year_str) if year_str else None
        results.append({
            "doi": doi.lower(),
            "title": (rec.get("title") or "").strip().rstrip("."),
            "authors": authors,
            "year": year,
            "venue": rec.get("fulljournalname") or rec.get("source") or "",
            "cited_by_count": 0,  # PubMed doesn't provide citations
            "abstract": "",
            "concepts": [],
            "source": "pubmed",
            "relevance": 0.0,
        })
    return results


def query_crossref(query: str, n: int, since: int | None) -> list[dict]:
    """Query Crossref works."""
    params = {
        "query": query,
        "rows": str(min(n, 50)),
    }
    if since:
        params["filter"] = f"from-pub-date:{since}-01-01"
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    data = fetch_json(url)
    if not data or not isinstance(data, dict):
        return []
    items = data.get("message", {}).get("items") or []
    results = []
    for item in items:
        doi = (item.get("DOI") or "").strip()
        if not doi:
            continue
        authors = []
        for a in item.get("author") or []:
            given = a.get("given") or ""
            family = a.get("family") or ""
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)
        year = None
        for date_key in ("published-print", "published-online", "published", "issued"):
            dp = item.get(date_key, {}).get("date-parts") or []
            if dp and dp[0] and dp[0][0]:
                year = dp[0][0]
                break
        abstract = item.get("abstract") or ""
        # Strip simple XML tags from Crossref abstract.
        if abstract:
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()
        results.append({
            "doi": doi.lower(),
            "title": (item.get("title") or [""])[0].strip() if item.get("title") else "",
            "authors": authors,
            "year": year,
            "venue": (item.get("container-title") or [""])[0] if item.get("container-title") else "",
            "cited_by_count": item.get("is-referenced-by-count") or 0,
            "abstract": abstract,
            "concepts": [],
            "source": "crossref",
            "relevance": 0.0,
        })
    return results


# --------------------------------------------------------------------------- #
# Merge, dedup, rank
# --------------------------------------------------------------------------- #
def normalize_doi(doi: str) -> str:
    return doi.lower().strip().replace("https://doi.org/", "").replace("http://doi.org/", "")


def merge_dedup(entries: list[dict]) -> list[dict]:
    """Merge entries by DOI; prefer the entry with richer metadata."""
    by_doi: dict[str, dict] = {}
    for e in entries:
        doi = normalize_doi(e["doi"])
        if not doi:
            continue
        if doi not in by_doi:
            by_doi[doi] = {**e, "doi": doi, "sources": [e["source"]]}
        else:
            existing = by_doi[doi]
            existing["sources"].append(e["source"])
            # Prefer non-empty fields.
            for key in ("title", "abstract", "venue", "year", "authors", "concepts"):
                if not existing.get(key) and e.get(key):
                    existing[key] = e[key]
            # Take max citation count.
            existing["cited_by_count"] = max(
                existing.get("cited_by_count") or 0, e.get("cited_by_count") or 0
            )
            existing["relevance"] = max(existing.get("relevance") or 0, e.get("relevance") or 0)
    return list(by_doi.values())


def score_entry(entry: dict, query: str) -> float:
    """Blend relevance, citation count (log-scaled), and recency into a 0-1 score."""
    query_lower = query.lower()
    text = f"{entry.get('title','')} {entry.get('abstract','')}".lower()

    # Relevance: token overlap + stored relevance score.
    query_tokens = set(re.findall(r"\w+", query_lower))
    text_tokens = set(re.findall(r"\w+", text))
    overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
    rel_stored = float(entry.get("relevance") or 0.0)
    # Normalize OpenAlex relevance (often >1) to ~0-1.
    rel_stored_norm = min(rel_stored / 10.0, 1.0) if rel_stored > 1 else rel_stored
    relevance = 0.5 * overlap + 0.5 * rel_stored_norm

    # Citations: log-scaled.
    cited = entry.get("cited_by_count") or 0
    citations = min(1.0, (1 + cited) / 100.0)

    # Recency: newer gets a slight boost.
    year = entry.get("year")
    recency = 0.0
    if year:
        current_year = datetime.now().year
        recency = max(0.0, min(1.0, (year - 2000) / (current_year - 2000 + 1)))

    return 0.5 * relevance + 0.3 * citations + 0.2 * recency


# --------------------------------------------------------------------------- #
# Output: review.md + BibTeX
# --------------------------------------------------------------------------- #
def _bibtex_escape(s: str) -> str:
    return s.replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("#", r"\#")


def make_bibtex_key(entry: dict) -> str:
    first_author = "anon"
    if entry.get("authors"):
        last_name = entry["authors"][0].split()[-1].lower()
        first_author = re.sub(r"[^a-z]", "", last_name) or "anon"
    year = entry.get("year") or "nd"
    # First content word of title.
    title_words = re.findall(r"[a-z]+", (entry.get("title") or "untitled").lower())
    word = title_words[0] if title_words else "untitled"
    return f"{first_author}{year}{word}"


def to_bibtex(entry: dict, key: str) -> str:
    authors = " and ".join(entry.get("authors") or [])
    title = entry.get("title") or "Untitled"
    year = entry.get("year") or ""
    venue = entry.get("venue") or ""
    doi = entry.get("doi") or ""
    lines = [
        f"@article{{{key},",
        f"  title   = {{{_bibtex_escape(title)}}},",
        f"  author  = {{{_bibtex_escape(authors)}}},",
        f"  year    = {{{year}}},",
    ]
    if venue:
        lines.append(f"  journal = {{{_bibtex_escape(venue)}}},")
    if doi:
        lines.append(f"  doi     = {{{doi}}},")
    lines.append("}")
    return "\n".join(lines)


def load_existing_dois(bib_path: Path) -> set[str]:
    """Parse existing DOIs from the .bib to avoid duplicates."""
    existing = set()
    if not bib_path.exists():
        return existing
    try:
        text = bib_path.read_text(encoding="utf-8")
    except Exception:
        return existing
    for m in re.finditer(r"doi\s*=\s*\{([^}]+)\}", text, re.IGNORECASE):
        existing.add(normalize_doi(m.group(1)))
    return existing


def append_bibtex(entries: list[dict], bib_path: Path) -> int:
    """Append BibTeX entries; skip DOIs already present. Returns count appended."""
    existing_dois = load_existing_dois(bib_path)
    to_write = []
    used_keys: set[str] = set()
    for e in entries:
        doi = normalize_doi(e["doi"])
        if doi in existing_dois:
            continue
        key = make_bibtex_key(e)
        # Ensure key uniqueness.
        base_key = key
        suffix = 1
        while key in used_keys:
            key = f"{base_key}{chr(96 + suffix)}"  # a, b, c...
            suffix += 1
        used_keys.add(key)
        to_write.append(to_bibtex(e, key))
        existing_dois.add(doi)  # prevent dups within this batch too
    if not to_write:
        return 0
    try:
        bib_path.parent.mkdir(parents=True, exist_ok=True)
        with open(bib_path, "a", encoding="utf-8") as f:
            f.write("\n")
            for b in to_write:
                f.write(b + "\n\n")
    except Exception as e:
        warn(f"Could not write BibTeX: {e}")
        return 0
    return len(to_write)


def generate_summary(entry: dict, query: str) -> str:
    """Build a 2-3 line summary + why-relevant note from available metadata."""
    abstract = entry.get("abstract") or ""
    title = entry.get("title") or ""
    concepts = entry.get("concepts") or []
    if abstract:
        # Take first ~2 sentences.
        sentences = re.split(r"(?<=[.!?])\s+", abstract)
        summary = " ".join(sentences[:2]).strip()
        if len(summary) > 300:
            summary = summary[:297].rsplit(" ", 1)[0] + "..."
    else:
        summary = f"Title topic: {title}." if title else "No abstract available."
    # Why relevant.
    why_parts = []
    query_lower = query.lower()
    text = f"{title} {abstract}".lower()
    for term in query_lower.split():
        if term in text:
            why_parts.append(f"matches '{term}'")
    if concepts:
        why_parts.append(f"concepts: {', '.join(concepts[:3])}")
    why = "; ".join(why_parts) if why_parts else "returned by API search for query"
    return f"{summary} Why relevant: {why}."


def write_review_md(entries: list[dict], query: str, out_path: Path) -> None:
    lines = [
        f"# Literature Review: {query}",
        "",
        f"> Generated by CHATLabAI `litsearch.py` on {datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        f"> {len(entries)} entries from OpenAlex, PubMed, and Crossref (deduped by DOI).",
        "",
    ]
    for i, e in enumerate(entries, 1):
        authors = e.get("authors") or []
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += " et al."
        year = e.get("year") or "n.d."
        title = e.get("title") or "Untitled"
        venue = e.get("venue") or ""
        doi = e.get("doi") or ""
        doi_url = f"https://doi.org/{doi}" if doi else ""
        sources = ", ".join(sorted(set(e.get("sources") or [e.get("source", "")])))
        cited = e.get("cited_by_count") or 0
        score = e.get("_score", 0.0)
        summary = generate_summary(e, query)
        lines.extend([
            f"## {i}. {title}",
            f"**{author_str}** ({year}). *{venue}.*",
            f"DOI: [{doi}]({doi_url}) | Cited by: {cited} | Sources: {sources} | Score: {score:.3f}",
            "",
            summary,
            "",
            "---",
            "",
        ])
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        warn(f"Could not write review.md: {e}")


# --------------------------------------------------------------------------- #
# Network check
# --------------------------------------------------------------------------- #
def check_network() -> bool:
    """Check connectivity to at least one scholarly API.

    An HTTP response (even 429/5xx) means the network is up and the server is
    reachable — that counts as available. Only true connection failures (DNS,
    socket timeout, connection refused) count as unavailable.
    """
    socket.setdefaulttimeout(NETWORK_TIMEOUT)
    test_urls = [
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?retmode=json",
        "https://api.crossref.org/works?rows=0",
        "https://api.openalex.org/",
    ]
    for url in test_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT)
            return True  # 200 OK
        except urllib.error.HTTPError:
            return True  # Got an HTTP response (e.g. 429) — server is reachable
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
            continue  # Try next URL
    return False


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="litsearch.py",
        description="Neuroaesthetics literature search across OpenAlex, PubMed, and Crossref. "
                    "Outputs an annotated review.md and appends BibTeX to references/library.bib.",
        epilog="Example: python3 litsearch.py 'neuroaesthetics face beauty' --n 25 --since 2015",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("query", help="Search query, e.g. 'neuroaesthetics face beauty'")
    p.add_argument("--n", type=int, default=25, help="Max results to return (default: 25)")
    p.add_argument("--since", type=int, default=None, help="Only papers from this year onward (e.g. 2015)")
    p.add_argument("--bib", type=str, default=str(DEFAULT_BIB),
                   help=f"BibTeX file to append to (default: {DEFAULT_BIB})")
    p.add_argument("--seed-terms", type=str, default=None,
                   help="Comma-separated seed terms (default: loaded from knowledge/lab-info.md)")
    p.add_argument("--out", type=str, default="review.md",
                   help="Output review.md path (default: review.md in cwd)")
    p.add_argument("--no-bib", action="store_true", help="Skip BibTeX append")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bib_path = Path(args.bib)
    out_path = Path(args.out)

    # Seed terms (for reference / future concept expansion).
    if args.seed_terms:
        seed_terms = [t.strip() for t in args.seed_terms.split(",") if t.strip()]
    else:
        seed_terms = load_seed_terms_from_lab_info()
    log(f"Seed terms: {', '.join(seed_terms)}")

    # Network check.
    if not check_network():
        print(
            "Network unavailable: cannot reach OpenAlex/PubMed/Crossref. "
            "Run this skill from a networked environment.",
            file=sys.stderr,
        )
        return 2

    query = args.query.strip()
    if not query:
        die("Query must not be empty.")
    log(f"Searching: '{query}' (n={args.n}, since={args.since or 'any'})")

    # Query all three sources.
    log("Querying OpenAlex...")
    openalex_results = query_openalex(query, args.n, args.since)
    log(f"  OpenAlex: {len(openalex_results)} results")

    time.sleep(RATE_LIMIT_SEC)
    log("Querying PubMed...")
    pubmed_results = query_pubmed(query, args.n, args.since)
    log(f"  PubMed: {len(pubmed_results)} results")

    time.sleep(RATE_LIMIT_SEC)
    log("Querying Crossref...")
    crossref_results = query_crossref(query, args.n, args.since)
    log(f"  Crossref: {len(crossref_results)} results")

    all_entries = openalex_results + pubmed_results + crossref_results
    log(f"Total before dedup: {len(all_entries)}")

    if not all_entries:
        print("No results found. Try a broader query or different terms.", file=sys.stderr)
        return 1

    # Merge + dedup.
    merged = merge_dedup(all_entries)
    log(f"After dedup: {len(merged)}")

    # Score + rank.
    for e in merged:
        e["_score"] = score_entry(e, query)
    merged.sort(key=lambda e: e["_score"], reverse=True)

    # Cap at N.
    top = merged[: args.n]
    log(f"Top {len(top)} entries selected")

    # Write review.md.
    write_review_md(top, query, out_path)
    log(f"Wrote {out_path}")

    # Append BibTeX.
    if not args.no_bib:
        appended = append_bibtex(top, bib_path)
        log(f"Appended {appended} new BibTeX entries to {bib_path} (skipped existing DOIs)")
    else:
        log("BibTeX append skipped (--no-bib)")

    # Print summary to stdout.
    print(f"\nLiterature review: '{query}'")
    print(f"  {len(top)} entries (from {len(merged)} deduped, {len(all_entries)} raw)")
    print(f"  Review:   {out_path}")
    if not args.no_bib:
        print(f"  BibTeX:   {bib_path}")
    print()
    for i, e in enumerate(top, 1):
        authors = e.get("authors") or []
        a = authors[0].split()[-1] if authors else "Anon"
        year = e.get("year") or "n.d."
        print(f"  {i:2d}. [{e.get('source','?')}] {a} et al. ({year}) — {e.get('title','')[:70]}")
        print(f"      doi: {e.get('doi','')}  cited: {e.get('cited_by_count',0)}  score: {e['_score']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
