#!/usr/bin/env python3
"""
find_gaps.py — topic-forward citation gap-finder for CHATLabAI's citation-gaps skill.

Finds literature a paper SHOULD engage but doesn't, working FORWARD from a topic/theme
(not just backward from existing citations). Deterministic layer here; the LLM (CHATLabAI)
writes the judgmental one-line reads in Anjan's voice.

Core ideas (adapted from proven research-skill techniques, free-APIs-only):
  * REPEAT-HIT gap detection: a work that surfaces across MULTIPLE claim-areas/angles but is
    absent from the manuscript's references is a strong, topic-forward gap.
  * GAP-STRENGTH = cross-area recurrence (dominant) + citations-per-year (CPY) + recency +
    relevance. CPY (not raw citations) so recent high-impact work isn't buried under classics.
  * MULTI-ANGLE discovery per area with fixed depth tiers (core / recent / foundational /
    reviews / citation-chase) — era-gating is a deliberate temporal-gap axis.
  * DOI-first dedup, then fuzzy-title (token Jaccard) — because subtracting the manuscript's
    existing citations is the core operation.
  * Three-count COVERAGE AUDIT (pulled / unique / already-cited / new gaps), inspectable.

Free APIs only (OpenAlex primary; optional PubMed/Crossref via lit-review's engine).
Sequential + rate-limited (>=1s between network calls). Never parallel. No paid services.

Usage:
  # Theme mode (no specific paper)
  find_gaps.py --theme "altered state phenomenology" --depth standard --n 12

  # Paper mode (find what THIS paper is missing; LLM passes the claim-areas)
  find_gaps.py --paper draft.docx --claim-areas "aesthetic triad" "appraisal theory" --n 10

  # Seed callosum's wanted list with the top uncited candidates
  find_gaps.py --paper draft.docx --claim-areas "appraisal theory" --seed-callosum --top-seed 5

  # Offline self-test (no network)
  find_gaps.py --self-test

Exit 0 on success, 1 on hard error / failed self-test. --quiet suppresses the stderr summary.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- reuse lit-review
SCRIPT_PATH = Path(__file__).resolve()
WORKSPACE_ROOT = SCRIPT_PATH.parents[4]  # scripts -> citation-gaps -> skills -> .pi -> root
LITREVIEW_SCRIPTS = WORKSPACE_ROOT / ".pi" / "skills" / "lit-review" / "scripts"
sys.path.insert(0, str(LITREVIEW_SCRIPTS))
from litsearch import query_openalex, fetch_json, _reconstruct_openalex_abstract  # noqa: E402

# Optional multi-source engines (present in lit-review). Guarded so a missing one never crashes.
try:
    from litsearch import query_pubmed  # noqa: E402
except Exception:  # pragma: no cover
    query_pubmed = None
try:
    from litsearch import query_crossref  # noqa: E402
except Exception:  # pragma: no cover
    query_crossref = None

CALLOSUM_BASE = os.environ.get("CALLOSUM_BASE_URL", "http://127.0.0.1:8080")

# ---- tunable constants (documented) ----
CURRENT_YEAR = 2026
REPEAT_HIT_THRESHOLD = 2      # surfaces in >= this many distinct areas => foundational/recurring
FOUNDATIONAL_CUTOFF = 2015    # era-gating "old" boundary (to_publication_date)
RECENT_WINDOW = 5             # last N years => "recent" (from_publication_date)
REQUEST_GAP = 1.0             # polite: >= this many seconds between network calls
FUZZY_TITLE_THRESHOLD = 0.60  # token-Jaccard >= this => treat as the same work (already cited)

# gap-strength weights (sum to 1.0). Cross-area recurrence is the strongest signal.
W_SUBAREA, W_CPY, W_RECENCY, W_RELEVANCE = 0.45, 0.30, 0.10, 0.15

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with", "from", "by",
    "at", "as", "is", "are", "be", "how", "what", "why", "when", "study", "paper",
    "review", "analysis", "using", "toward", "towards", "into", "via", "case",
}

# --------------------------------------------------------------------------- rate limiting
_last_call = [0.0]


def _throttle() -> None:
    """Enforce >= REQUEST_GAP seconds between network calls (polite free-API use)."""
    dt = time.time() - _last_call[0]
    if dt < REQUEST_GAP:
        time.sleep(REQUEST_GAP - dt)
    _last_call[0] = time.time()


# --------------------------------------------------------------------------- text / DOI helpers
def extract_text(path: Path) -> str:
    """Extract plain text from .docx (python-docx), else raw."""
    if path.suffix.lower() == ".docx":
        try:
            from docx import Document  # type: ignore
        except ImportError:
            sys.exit("ERROR: python-docx required for .docx. pip install python-docx")
        return "\n".join(p.text for p in Document(str(path)).paragraphs)
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_doi(doi: str) -> str:
    """Lowercase, strip URL prefix and trailing junk."""
    d = (doi or "").strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = d.lstrip("doi:").strip()
    d = re.sub(r"[).,;>\]\"']+$", "", d)
    return d


def extract_dois(text: str) -> set:
    """Pull normalized DOIs from text (references section or anywhere)."""
    dois = set()
    for m in re.finditer(r"\b10\.\d{4,9}/[^\s)>\]\"',]+", text, re.IGNORECASE):
        dois.add(normalize_doi(m.group(0)))
    return {d for d in dois if d}


def find_references_block(text: str) -> str:
    """Return the text from the References/Bibliography section onward, if present."""
    for line in text.splitlines():
        s = line.strip().lower()
        if s.startswith("references") or s.startswith("bibliography") or s.startswith("works cited"):
            return text[text.find(line):]
    return text


def title_tokens(title: str) -> frozenset:
    """Lowercase content-word token set for a title (stopwords + punctuation removed)."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def cited_title_sets(ref_block: str) -> List[frozenset]:
    """Token sets for reference-list lines (to catch missing-DOI citations by title)."""
    out = []
    for line in ref_block.splitlines():
        if len(line.strip()) > 25:
            ts = title_tokens(line)
            if len(ts) >= 3:
                out.append(ts)
    return out


# --------------------------------------------------------------------------- discovery
def _normalize_openalex_work(w: dict) -> Optional[dict]:
    """Normalize one raw OpenAlex work record into our candidate schema."""
    doi = normalize_doi((w.get("doi") or "").replace("https://doi.org/", ""))
    if not doi:
        return None
    authors = []
    for a in (w.get("authorships") or []):
        name = (a.get("author") or {}).get("display_name") or ""
        if name:
            authors.append(name)
    venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    return {
        "doi": doi,
        "title": (w.get("title") or "").strip(),
        "authors": authors,
        "year": w.get("publication_year"),
        "venue": venue,
        "cited_by_count": w.get("cited_by_count") or 0,
        "abstract": _reconstruct_openalex_abstract(w.get("abstract_inverted_index")),
        "relevance": w.get("relevance_score") or 0.0,
        "source": "openalex",
    }


def search_openalex(query: str, n: int, date_from: Optional[str] = None,
                    date_to: Optional[str] = None) -> List[dict]:
    """OpenAlex works search with optional era-gating (from/to publication date).

    Reuses lit-review's fetch_json. When no date filters are given, this is equivalent to
    lit-review's query_openalex; date filters enable the foundational/recent angles that a
    plain search can't express.
    """
    if date_from is None and date_to is None:
        _throttle()
        return query_openalex(query, n=n, since=None)
    params = {
        "search": query,
        "per-page": str(min(n, 50)),
        "sort": "relevance_score:desc",
        "mailto": "chatlab@pennmedicine.upenn.edu",
    }
    filt = []
    if date_from:
        filt.append(f"from_publication_date:{date_from}")
    if date_to:
        filt.append(f"to_publication_date:{date_to}")
    if filt:
        params["filter"] = ",".join(filt)
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    _throttle()
    data = fetch_json(url)
    if not data or not isinstance(data, dict):
        return []
    out = []
    for w in data.get("results", []) or []:
        c = _normalize_openalex_work(w)
        if c:
            out.append(c)
    return out


def _merge_by_doi(cands: List[dict]) -> List[dict]:
    """Dedup a candidate list by normalized DOI, keeping the copy with the highest relevance."""
    best: Dict[str, dict] = {}
    for c in cands:
        d = c["doi"]
        if d not in best or (c.get("relevance") or 0) > (best[d].get("relevance") or 0):
            best[d] = c
    return list(best.values())


def discover_area(area: str, n: int, depth: str, sources: List[str]) -> List[dict]:
    """Run the multi-angle search budget for one claim-area. Returns deduped candidates."""
    angles: List[dict] = []
    # core
    angles += search_openalex(area, n)
    if depth in ("standard", "deep"):
        # recent era-gated + foundational era-gated
        angles += search_openalex(area, n, date_from=f"{CURRENT_YEAR - RECENT_WINDOW}-01-01")
        angles += search_openalex(area, n, date_to=f"{FOUNDATIONAL_CUTOFF}-12-31")
    if depth == "deep":
        # reviews/surveys angle
        angles += search_openalex(f"{area} review", n)
        # citation-chase: re-query around the highest-cited hit so far
        pool = _merge_by_doi(angles)
        if pool:
            top = max(pool, key=lambda c: c.get("cited_by_count") or 0)
            if top.get("title"):
                angles += search_openalex(top["title"], n)
    # optional multi-source (core query only, to stay polite)
    if "pubmed" in sources and query_pubmed:
        try:
            angles += [_coerce(x) for x in query_pubmed(area, n=n, since=None)]
        except Exception as e:
            sys.stderr.write(f"[find_gaps] pubmed skipped: {e}\n")
    if "crossref" in sources and query_crossref:
        try:
            angles += [_coerce(x) for x in query_crossref(area, n=n, since=None)]
        except Exception as e:
            sys.stderr.write(f"[find_gaps] crossref skipped: {e}\n")
    return _merge_by_doi(angles)


def _coerce(x: dict) -> dict:
    """Coerce a foreign-source dict into our candidate schema (defensive)."""
    x = dict(x)
    x["doi"] = normalize_doi(x.get("doi", ""))
    x.setdefault("title", "")
    x.setdefault("authors", [])
    x.setdefault("year", None)
    x.setdefault("venue", "")
    x.setdefault("cited_by_count", 0)
    x.setdefault("abstract", "")
    x.setdefault("relevance", 0.0)
    return x


# --------------------------------------------------------------------------- scoring
def cpy(c: dict) -> float:
    """Citations per year — normalizes for age so recent high-impact work isn't buried."""
    yr = c.get("year") or 0
    if not isinstance(yr, int) or yr <= 0:
        return float(c.get("cited_by_count") or 0)
    return round((c.get("cited_by_count") or 0) / max(CURRENT_YEAR - yr, 1), 2)


def gap_strength(c: dict, n_areas: int) -> float:
    """Blend cross-area recurrence + CPY + recency + relevance into [0,1]."""
    sub = min(c.get("sub_area_count", 1), max(n_areas, 1)) / max(n_areas, 1)
    cpy_norm = min(math.log1p(c.get("cpy", 0.0)) / math.log1p(50.0), 1.0)
    yr = c.get("year") or 0
    recency = 1.0 if (isinstance(yr, int) and yr >= CURRENT_YEAR - RECENT_WINDOW) else 0.0
    rel_norm = min(float(c.get("relevance") or 0.0) / 100.0, 1.0)
    s = W_SUBAREA * sub + W_CPY * cpy_norm + W_RECENCY * recency + W_RELEVANCE * rel_norm
    return round(min(s, 1.0), 3)


def strength_label(s: float) -> str:
    return "high" if s >= 0.66 else "medium" if s >= 0.33 else "low"


# --------------------------------------------------------------------------- subtraction
def is_cited(c: dict, cited_dois: set, cited_titles: List[frozenset]) -> bool:
    """True if the manuscript already cites this work (DOI exact, else fuzzy title)."""
    if c["doi"] in cited_dois:
        return True
    ct = title_tokens(c.get("title", ""))
    if len(ct) < 3:
        return False
    return any(jaccard(ct, t) >= FUZZY_TITLE_THRESHOLD for t in cited_titles)


# --------------------------------------------------------------------------- aggregation
def aggregate(area_to_cands: List[Tuple[str, List[dict]]]) -> Dict[str, dict]:
    """Cross-area repeat-hit aggregation keyed by normalized DOI.

    Returns {doi: candidate} where each candidate carries sub_area_count + also_areas
    (the distinct areas it surfaced in) and the best (highest-relevance) metadata copy.
    """
    agg: Dict[str, dict] = {}
    for area, cands in area_to_cands:
        for c in cands:
            d = c["doi"]
            if d not in agg:
                cc = dict(c)
                cc["areas"] = {area}
                agg[d] = cc
            else:
                agg[d]["areas"].add(area)
                # keep the richer/more-relevant copy's scalar fields
                if (c.get("relevance") or 0) > (agg[d].get("relevance") or 0):
                    for k in ("relevance", "abstract", "venue", "cited_by_count", "year", "title", "authors"):
                        if c.get(k):
                            agg[d][k] = c[k]
    for d, c in agg.items():
        c["sub_area_count"] = len(c["areas"])
        c["also_areas"] = sorted(c["areas"])
        c["foundational"] = c["sub_area_count"] >= REPEAT_HIT_THRESHOLD
        c["cpy"] = cpy(c)
    return agg


# --------------------------------------------------------------------------- callosum seeding
def seed_callosum(dois: List[str]) -> List[dict]:
    """Push DOIs to callosum's /wanted list. Degrades gracefully if callosum is down."""
    results = []
    for doi in dois:
        body = json.dumps({"doi": doi}).encode()
        try:
            req = urllib.request.Request(
                f"{CALLOSUM_BASE}/wanted", data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                results.append({"doi": doi, "ok": True, "detail": r.read().decode()[:200]})
        except urllib.error.HTTPError as e:
            results.append({"doi": doi, "ok": False, "detail": f"HTTP {e.code}: {e.read().decode()[:120]}"})
        except Exception as e:
            results.append({"doi": doi, "ok": False, "detail": f"skipped (callosum down?): {e}"})
    return results


# --------------------------------------------------------------------------- report build
def build_report(mode: str, paper: Optional[str], areas: List[str],
                 area_to_all: List[Tuple[str, List[dict]]],
                 cited_dois: set, cited_titles: List[frozenset],
                 depth: str, sources: List[str]) -> dict:
    """Assemble the full report: per-area coverage, overall top gaps, three-count audit."""
    n_areas = len(areas)
    agg = aggregate(area_to_all)

    # per-area coverage + uncited candidates
    area_reports = []
    audit_pulled = audit_unique = audit_cited = audit_gaps = 0
    for area, cands in area_to_all:
        pulled = len(cands)
        unique = {c["doi"] for c in cands}
        cited_here = sum(1 for d in unique if agg[d] and is_cited(agg[d], cited_dois, cited_titles))
        # uncited candidates for this area, scored + sorted
        gaps = []
        for c in cands:
            ac = agg[c["doi"]]
            if is_cited(ac, cited_dois, cited_titles):
                continue
            ac["strength"] = gap_strength(ac, n_areas)
            ac["strength_label"] = strength_label(ac["strength"])
            gaps.append(ac)
        gaps = _merge_by_doi(gaps)
        gaps.sort(key=lambda c: c.get("strength", 0), reverse=True)
        coverage = round(100.0 * cited_here / len(unique), 1) if unique else 0.0
        area_reports.append({
            "area": area, "pulled": pulled, "unique": len(unique),
            "already_cited": cited_here, "coverage_pct": coverage,
            "new_gaps": len(gaps), "candidates": gaps,
        })
        audit_pulled += pulled
        audit_unique += len(unique)
        audit_cited += cited_here
        audit_gaps += len(gaps)

    # overall top gaps: all uncited, deduped, scored, sorted; foundational first
    overall = {}
    for c in agg.values():
        if is_cited(c, cited_dois, cited_titles):
            continue
        c["strength"] = gap_strength(c, n_areas)
        c["strength_label"] = strength_label(c["strength"])
        overall[c["doi"]] = c
    top_gaps = sorted(
        overall.values(),
        key=lambda c: (c.get("foundational", False), c.get("strength", 0)),
        reverse=True,
    )

    return {
        "mode": mode, "paper": paper, "depth": depth, "sources": sources,
        "cited_count": len(cited_dois) if mode == "paper" else None,
        "areas": area_reports,
        "top_gaps": top_gaps,
        "audit": {
            "candidates_pulled": audit_pulled,
            "unique_after_dedup": len(agg),
            "already_cited": audit_cited,
            "new_gaps_unique": len(overall),
        },
        "callosum_seed": None,
    }


def _authors_str(c: dict) -> str:
    a = c.get("authors") or []
    return ", ".join(a[:3]) + (" et al." if len(a) > 3 else "") if a else "—"


def to_markdown(report: dict) -> str:
    o = ["# Citation Gap Report", ""]
    o.append(f"- **Mode:** {report['mode']}  |  **Depth:** {report['depth']}  "
             f"|  **Sources:** {', '.join(report['sources'])}")
    if report.get("paper"):
        o.append(f"- **Paper:** `{report['paper']}`")
    if report.get("cited_count") is not None:
        o.append(f"- **Existing citations (DOIs found):** {report['cited_count']}")
    a = report["audit"]
    o.append("")
    o.append("## Coverage audit")
    o.append(f"- Candidates pulled: **{a['candidates_pulled']}**  →  unique after dedup: "
             f"**{a['unique_after_dedup']}**  →  already cited: **{a['already_cited']}**  →  "
             f"new gaps: **{a['new_gaps_unique']}**")
    o.append("")
    # summary table
    o.append("## By claim-area")
    o.append("")
    o.append("| Claim-area | pulled | unique | already-cited | coverage% | new gaps |")
    o.append("|---|---:|---:|---:|---:|---:|")
    for ar in report["areas"]:
        o.append(f"| {ar['area']} | {ar['pulled']} | {ar['unique']} | {ar['already_cited']} "
                 f"| {ar['coverage_pct']} | {ar['new_gaps']} |")
    o.append("")
    # top gaps overall
    o.append("## Top gaps overall (start here)")
    o.append("")
    if not report["top_gaps"]:
        o.append("_No uncited candidates — the paper engages these areas well._")
    for c in report["top_gaps"][:15]:
        rec = f"surfaced in {c['sub_area_count']} area(s)" if c.get("sub_area_count") else ""
        found = " **[recurring]**" if c.get("foundational") else ""
        o.append(f"- **[{c.get('strength_label','?')}]**{found} **{c['title']}** — "
                 f"{_authors_str(c)} ({c.get('year')}), *{c.get('venue') or '—'}*. "
                 f"cited {c.get('cited_by_count')} (CPY {c.get('cpy')}). {rec}. `doi:{c['doi']}`")
        snip = (c.get("abstract") or "").strip().replace("\n", " ")
        if snip:
            o.append(f"    - {snip[:220]}{'…' if len(snip) > 220 else ''}")
    o.append("")
    # per-area detail
    for ar in report["areas"]:
        o.append(f"## {ar['area']}  ({ar['coverage_pct']}% covered, {ar['new_gaps']} gaps)")
        o.append("")
        if not ar["candidates"]:
            o.append("_No uncited candidates found (this area looks well-covered)._")
            o.append("")
            continue
        for c in ar["candidates"][:12]:
            o.append(f"- **[{c.get('strength_label','?')}]** **{c['title']}** — {_authors_str(c)} "
                     f"({c.get('year')}), *{c.get('venue') or '—'}*. cited {c.get('cited_by_count')} "
                     f"(CPY {c.get('cpy')}). `doi:{c['doi']}`")
        o.append("")
    if report.get("callosum_seed"):
        ok = sum(1 for s in report["callosum_seed"] if s["ok"])
        o.append(f"_Seeded to callosum wanted list: {ok}/{len(report['callosum_seed'])} DOIs._")
        o.append("")
    o.append("---")
    o.append("What next?  1) write the one-line reads (Anjan's voice)  2) seed callosum's "
             "wanted list (top 5)  3) draft a grounded citation for a specific gap  4) widen "
             "the search / add an adjacent framing   (or just tell me what you want)")
    o.append("")
    o.append("_The LLM (CHATLabAI) writes the honest one-line read per gap in Anjan's voice — "
             "why it matters to the argument — and marks weak gaps weak (rule 13). Deliberately "
             "probe framings the paper OMITS, not just its own vocabulary._")
    return "\n".join(o)


# --------------------------------------------------------------------------- self-test
def _self_test() -> int:
    """Offline checks on the pure functions. No network."""
    checks = []

    def ck(name, cond):
        checks.append((name, bool(cond)))
        print(f"  [{'ok' if cond else 'FAIL'}] {name}")

    # DOI normalize + dedup
    ck("normalize_doi strips URL/junk",
       normalize_doi("https://doi.org/10.1/AbC).") == "10.1/abc")
    merged = _merge_by_doi([
        {"doi": "10.1/x", "relevance": 1.0}, {"doi": "10.1/x", "relevance": 5.0},
        {"doi": "10.1/y", "relevance": 2.0},
    ])
    ck("dedup by DOI keeps highest relevance",
       len(merged) == 2 and max(c["relevance"] for c in merged if c["doi"] == "10.1/x") == 5.0)

    # fuzzy title subtraction
    cited_titles = [title_tokens("Neuroscience of aesthetic experience and beauty")]
    ck("fuzzy-title subtraction catches missing-DOI cite",
       is_cited({"doi": "10.9/z", "title": "The neuroscience of aesthetic experience & beauty"},
                set(), cited_titles))
    ck("unrelated title is NOT subtracted",
       not is_cited({"doi": "10.9/w", "title": "Reinforcement learning for robots"},
                    set(), cited_titles))
    ck("exact DOI subtraction", is_cited({"doi": "10.1/a", "title": "x"}, {"10.1/a"}, []))

    # CPY
    ck("cpy normalizes for age",
       cpy({"cited_by_count": 100, "year": 2024}) == 50.0
       and cpy({"cited_by_count": 300, "year": 1996}) == 10.0)

    # strength ordering: recent multi-area high-CPY beats old single-area
    hot = {"sub_area_count": 3, "cpy": 50.0, "year": 2024, "relevance": 80.0}
    cold = {"sub_area_count": 1, "cpy": 10.0, "year": 1996, "relevance": 30.0}
    sh, sc = gap_strength(hot, 3), gap_strength(cold, 3)
    ck("gap_strength ranks hot>cold", sh > sc)
    ck("strength_label bands", strength_label(0.7) == "high" and strength_label(0.4) == "medium"
       and strength_label(0.1) == "low")

    # cross-area repeat-hit aggregation
    a1 = [{"doi": "10.1/rep", "title": "Repeat", "relevance": 1.0, "cited_by_count": 200, "year": 2020},
          {"doi": "10.1/one", "title": "OnlyA", "relevance": 1.0, "cited_by_count": 5, "year": 2020}]
    a2 = [{"doi": "10.1/rep", "title": "Repeat", "relevance": 2.0, "cited_by_count": 200, "year": 2020}]
    agg = aggregate([("areaA", a1), ("areaB", a2)])
    rep = agg["10.1/rep"]
    ck("repeat-hit gets sub_area_count=2 + foundational",
       rep["sub_area_count"] == 2 and rep["foundational"] and rep["also_areas"] == ["areaA", "areaB"])
    ck("single-area is not foundational", not agg["10.1/one"]["foundational"])

    # coverage + markdown render end-to-end
    report = build_report(
        mode="theme", paper=None, areas=["areaA", "areaB"],
        area_to_all=[("areaA", a1), ("areaB", a2)],
        cited_dois={"10.1/one"}, cited_titles=[], depth="standard", sources=["openalex"],
    )
    ck("coverage audit counts present",
       report["audit"]["unique_after_dedup"] == 2 and report["audit"]["already_cited"] >= 1)
    ck("top_gaps excludes cited + includes repeat first",
       report["top_gaps"] and report["top_gaps"][0]["doi"] == "10.1/rep"
       and all(c["doi"] != "10.1/one" for c in report["top_gaps"]))
    md = to_markdown(report)
    ck("to_markdown renders", isinstance(md, str) and "Top gaps overall" in md and "Coverage audit" in md)

    passed = all(ok for _, ok in checks)
    print("SELF-TEST PASSED" if passed else "SELF-TEST FAILED")
    return 0 if passed else 1


# --------------------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="find_gaps.py",
        description="Topic-forward citation gap-finder: discovers literature a paper should "
                    "engage but doesn't (OpenAlex; optional PubMed/Crossref), scores gap "
                    "strength by cross-area recurrence + citations-per-year + recency, and "
                    "optionally seeds callosum's wanted list.",
    )
    p.add_argument("--self-test", action="store_true", help="Run offline self-checks and exit.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--paper", help="Manuscript (.docx/.md/.tex/.txt): extract its citations + find gaps.")
    g.add_argument("--theme", help="Free-text topic/theme (no specific paper).")
    p.add_argument("--claim-areas", nargs="+", help="Claim-areas to search (paper mode). Best passed by the LLM.")
    p.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard",
                   help="Search budget per area: quick=core; standard=+era-gated; deep=+reviews+citation-chase.")
    p.add_argument("--sources", default="openalex",
                   help="Comma list of sources: openalex[,pubmed,crossref] (default: openalex).")
    p.add_argument("--n", type=int, default=12, help="Max candidates per angle (default: 12).")
    p.add_argument("--out", default="gaps.md", help="Output markdown report (default: gaps.md).")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.add_argument("--seed-callosum", action="store_true", help="Push top uncited DOIs to callosum /wanted.")
    p.add_argument("--top-seed", type=int, default=5, help="How many top DOIs to seed (default: 5).")
    p.add_argument("--quiet", action="store_true", help="Suppress the stderr summary.")
    args = p.parse_args(argv)

    if args.self_test:
        return _self_test()

    if not args.paper and not args.theme:
        p.error("one of --paper / --theme is required (or --self-test)")

    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]

    # Determine mode + areas + existing citations.
    cited_dois: set = set()
    cited_titles: List[frozenset] = []
    paper_path = None
    if args.paper:
        mode = "paper"
        paper_path = Path(args.paper)
        if not paper_path.is_file():
            sys.exit(f"ERROR: paper not found: {paper_path}")
        text = extract_text(paper_path)
        ref_block = find_references_block(text)
        cited_dois = extract_dois(ref_block)
        cited_titles = cited_title_sets(ref_block)
        areas = args.claim_areas or []
        if not areas:
            sys.exit("ERROR: --claim-areas required in paper mode. The LLM should extract them "
                     "from the paper and pass them (its judgment beats keyword extraction). "
                     "Include 1-2 areas that pressure-test framings the paper OMITS.")
    else:
        mode = "theme"
        areas = [args.theme]

    # Discover per area (multi-angle), aggregate, score, subtract, build report.
    area_to_all: List[Tuple[str, List[dict]]] = []
    for area in areas:
        cands = discover_area(area, n=args.n, depth=args.depth, sources=sources)
        area_to_all.append((area, cands))

    report = build_report(mode, str(paper_path) if paper_path else None, areas,
                          area_to_all, cited_dois, cited_titles, args.depth, sources)

    # Callosum seeding (opt-in) — top uncited by strength.
    if args.seed_callosum:
        top_dois = [c["doi"] for c in report["top_gaps"][:args.top_seed]]
        report["callosum_seed"] = seed_callosum(top_dois)

    if args.format == "json":
        # strip non-serializable sets before dumping
        for c in report["top_gaps"]:
            c.pop("areas", None)
        for ar in report["areas"]:
            for c in ar["candidates"]:
                c.pop("areas", None)
        print(json.dumps(report, indent=2, default=list))
    else:
        Path(args.out).write_text(to_markdown(report), encoding="utf-8")
        print(f"Wrote {args.out}")

    if not args.quiet:
        a = report["audit"]
        sys.stderr.write(f"\n[{a['new_gaps_unique']} unique gap(s) from {a['unique_after_dedup']} "
                         f"works across {len(areas)} area(s); {a['already_cited']} already cited]\n")
        if report.get("callosum_seed"):
            ok = sum(1 for s in report["callosum_seed"] if s["ok"])
            sys.stderr.write(f"[callosum seeded: {ok}/{len(report['callosum_seed'])} DOIs]\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
