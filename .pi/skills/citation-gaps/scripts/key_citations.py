#!/usr/bin/env python3
"""
key_citations.py — graph-based citation-snowballing "get me the canonical literature" tool
for CHATLabAI's citation-gaps skill.

Sibling to find_gaps.py. Where find_gaps.py works FORWARD from a topic to find what a paper
is MISSING, this script answers a different question: given a THEME, QUESTION, or SENTENCE,
what are the KEY citations for it — the works a domain expert would say you must cite?

Keyword search alone finds papers sharing your vocabulary; it misses canonical works cited
under other terms (different eras, different subfields, different jargon). This script instead
does CITATION-GRAPH SNOWBALLING on OpenAlex:
  1. seed with keyword search,
  2. expand the graph BACKWARD (what the seeds cite) and FORWARD (what cites the seeds),
  3. score every harvested work by LOCAL in-degree — how many of the OTHER harvested works
     cite it — which is a theme-local centrality signal, not global popularity or vocabulary
     overlap. A work cited by 5 of your 40 harvested works is canonical *for this theme*
     regardless of whether it uses your search terms or has more total citations than
     everything else on Google Scholar.

Reuses find_gaps.py's helpers directly (extract_text/extract_dois/find_references_block/
is_cited/title_tokens/cpy/seed_callosum/CURRENT_YEAR) and lit-review's litsearch.py
(query_openalex/fetch_json/_reconstruct_openalex_abstract/append_bibtex) — no new pip deps,
no duplicated logic. Deterministic layer here; the LLM (CHATLabAI) writes the judgmental
one-line reads in Anjan's voice, same division of labor as find_gaps.py.

Free APIs only (OpenAlex primary graph source). Sequential + rate-limited (>=1s between
network calls, `mailto` in every request — polite pool). Never parallel. Hard per-depth-tier
call budget, enforced (see DEPTH_CONFIG); truncation is always logged, never silent.

Usage:
  # Theme mode, standard depth, markdown report
  key_citations.py --theme "neural basis of aesthetic experience" --depth standard

  # Multiple decomposed angle-queries (LLM normally supplies 2-5 of these)
  key_citations.py --question "does prototypicality drive facial attractiveness?" \\
      --queries "facial attractiveness prototypicality" "averageness beauty faces" --depth deep

  # Subtract-mode: mark which key citations a specific paper already has
  key_citations.py --sentence "art appreciation recruits reward circuitry" --paper draft.docx

  # Seed callosum's wanted list with the top canonical DOIs; append BibTeX
  key_citations.py --theme "beauty and the brain" --seed-callosum --top-seed 5 \\
      --bib references/library.bib

  # Offline self-test (no network)
  key_citations.py --self-test

Exit 0 on success, 1 on hard error / failed self-test. --quiet suppresses the stderr summary.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------------- reuse sibling + lit-review
SCRIPT_PATH = Path(__file__).resolve()
SCRIPTS_DIR = SCRIPT_PATH.parent                      # .../citation-gaps/scripts
WORKSPACE_ROOT = SCRIPT_PATH.parents[4]               # scripts -> citation-gaps -> skills -> .pi -> root
LITREVIEW_SCRIPTS = WORKSPACE_ROOT / ".pi" / "skills" / "lit-review" / "scripts"

sys.path.insert(0, str(LITREVIEW_SCRIPTS))
from litsearch import query_openalex, fetch_json, _reconstruct_openalex_abstract, append_bibtex  # noqa: E402

sys.path.insert(0, str(SCRIPTS_DIR))
import find_gaps as fg  # noqa: E402  — reuse extract_text/extract_dois/is_cited/cpy/seed_callosum/etc.

MAILTO = "chatlab@pennmedicine.upenn.edu"
OPENALEX_WORKS = "https://api.openalex.org/works"

# --------------------------------------------------------------------------- tunable constants (documented)
CURRENT_YEAR = fg.CURRENT_YEAR          # keep in sync with the sibling script
RECENT_WINDOW = 5                       # "recent front" = published within the last N years
SATURATION_THRESHOLD = 0.10             # a round adding < this fraction of new nodes => stop
REVIEW_RE = re.compile(r"\b(review|survey|meta-analys(is|es)|systematic review)\b", re.IGNORECASE)

# key_score weights (sum to 1.0). Local in-degree is the PRIMARY signal — canonical-for-this-
# -theme, independent of global cite count or vocabulary overlap with the query.
W_INDEGREE, W_COUPLING, W_CPY, W_RELEVANCE = 0.5, 0.2, 0.2, 0.1

# Depth tiers: seed count, per-seed forward-citation page size, max expansion rounds, and a
# HARD total-call cap (search + hydrate-batch + forward-cites calls all count). The cap is
# enforced in GraphFetcher._get(); truncation is always logged (never silent).
DEPTH_CONFIG = {
    "quick":    {"seeds": 5,  "forward_k": 5,  "max_rounds": 1, "call_cap": 15},
    "standard": {"seeds": 8,  "forward_k": 8,  "max_rounds": 2, "call_cap": 40},
    "deep":     {"seeds": 12, "forward_k": 12, "max_rounds": 3, "call_cap": 100},
}


def log(msg: str) -> None:
    print(f"[key_citations] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- OpenAlex node normalization
def _wid(raw_id: str) -> str:
    """Extract the bare W-id from an OpenAlex URL/id string ('https://openalex.org/W123' -> 'W123')."""
    if not raw_id:
        return ""
    return raw_id.rsplit("/", 1)[-1]


def _normalize_work(w: dict) -> Optional[dict]:
    """Normalize one raw OpenAlex work record into our node schema. Keeps referenced_works
    (the backward edges) — this is the field find_gaps.py's normalizer discards but that this
    script's entire method depends on."""
    wid = _wid(w.get("id") or "")
    if not wid:
        return None
    doi = fg.normalize_doi((w.get("doi") or "").replace("https://doi.org/", ""))
    authors = []
    for a in (w.get("authorships") or []):
        name = (a.get("author") or {}).get("display_name") or ""
        if name:
            authors.append(name)
    venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    refs = [_wid(r) for r in (w.get("referenced_works") or []) if r]
    return {
        "id": wid,
        "doi": doi,
        "title": (w.get("title") or "").strip(),
        "authors": authors,
        "year": w.get("publication_year"),
        "venue": venue,
        "cited_by_count": w.get("cited_by_count") or 0,
        "abstract": _reconstruct_openalex_abstract(w.get("abstract_inverted_index")),
        "referenced_works": refs,
        "relevance_score": w.get("relevance_score") or 0.0,
        "type": (w.get("type") or "").lower(),
    }


# --------------------------------------------------------------------------- network layer (swappable)
class GraphFetcher:
    """All network I/O lives here, isolated from scoring/tiering so the self-test never touches
    it. Sequential + rate-limited (reuses find_gaps.py's _throttle — same >=1s polite pacing),
    15s timeout per request (via litsearch.fetch_json), hard call cap per depth tier, and a
    3-consecutive-failure abort (partial results still get reported, never silently dropped)."""

    def __init__(self, call_cap: int):
        self.call_cap = call_cap
        self.calls = 0
        self.consecutive_failures = 0
        self.stopped_reason: Optional[str] = None
        self._cap_logged = False

    def _get(self, url: str) -> Optional[dict]:
        if self.calls >= self.call_cap:
            if not self._cap_logged:
                log(f"call budget cap ({self.call_cap}) reached — truncating further graph "
                    f"expansion (coverage is partial, not silently dropped)")
                self._cap_logged = True
            return None
        if self.stopped_reason:
            return None
        fg._throttle()
        self.calls += 1
        data = fetch_json(url)
        if data is None:
            self.consecutive_failures += 1
            log(f"request failed ({self.consecutive_failures}/3 consecutive): {url[:110]}")
            if self.consecutive_failures >= 3:
                self.stopped_reason = "3 consecutive failed requests — stopped expansion, reporting partial results"
            return None
        self.consecutive_failures = 0
        return data

    def search(self, query: str, n: int) -> List[dict]:
        params = {
            "search": query,
            "per-page": str(min(n, 50)),
            "sort": "relevance_score:desc",
            "mailto": MAILTO,
        }
        url = f"{OPENALEX_WORKS}?{urllib.parse.urlencode(params)}"
        data = self._get(url)
        if not data or not isinstance(data, dict):
            return []
        out = []
        for w in data.get("results", []) or []:
            n2 = _normalize_work(w)
            if n2:
                out.append(n2)
        return out

    def hydrate(self, wids: List[str]) -> List[dict]:
        """Batch-resolve up to 50 W-ids per call into full records (for referenced_works)."""
        out: List[dict] = []
        for i in range(0, len(wids), 50):
            if self.stopped_reason or self.calls >= self.call_cap:
                break
            chunk = [w for w in wids[i:i + 50] if w]
            if not chunk:
                continue
            params = {
                "filter": "openalex_id:" + "|".join(chunk),
                "per-page": str(len(chunk)),
                "mailto": MAILTO,
            }
            url = f"{OPENALEX_WORKS}?{urllib.parse.urlencode(params)}"
            data = self._get(url)
            if not data or not isinstance(data, dict):
                continue
            for w in data.get("results", []) or []:
                n2 = _normalize_work(w)
                if n2:
                    out.append(n2)
        return out

    def forward_citations(self, wid: str, k: int) -> List[dict]:
        """Works that cite `wid` (forward edges)."""
        params = {"filter": f"cites:{wid}", "per-page": str(k), "mailto": MAILTO}
        url = f"{OPENALEX_WORKS}?{urllib.parse.urlencode(params)}"
        data = self._get(url)
        if not data or not isinstance(data, dict):
            return []
        out = []
        for w in data.get("results", []) or []:
            n2 = _normalize_work(w)
            if n2:
                out.append(n2)
        return out


# --------------------------------------------------------------------------- pure scoring/tiering
# Every function below takes an already-harvested node table (Dict[wid -> node dict]) and never
# touches the network. This is what the self-test exercises directly with a synthetic graph.

def compute_indegree(nodes: Dict[str, dict]) -> Dict[str, int]:
    """local_indegree[wid] = # of OTHER harvested works whose referenced_works include wid.
    This is the PRIMARY signal: canonical *for this harvested theme-graph*, independent of
    global cited_by_count or vocabulary overlap with the seed queries."""
    indeg = {wid: 0 for wid in nodes}
    for wid, n in nodes.items():
        for ref in n.get("referenced_works") or []:
            if ref in indeg and ref != wid:
                indeg[ref] += 1
    return indeg


def compute_seed_coupling(nodes: Dict[str, dict], seed_ids: Set[str]) -> Dict[str, int]:
    """seed_coupling[wid] = # of seeds whose referenced_works include wid (co-citation with the
    seed frontier — a secondary, seed-anchored centrality signal)."""
    coup = {wid: 0 for wid in nodes}
    for sid in seed_ids:
        seed = nodes.get(sid)
        if not seed:
            continue
        for ref in seed.get("referenced_works") or []:
            if ref in coup:
                coup[ref] += 1
    return coup


def compute_key_scores(nodes: Dict[str, dict], indegree: Dict[str, int],
                       coupling: Dict[str, int]) -> None:
    """Blend local_indegree (dominant, ~0.5) + seed_coupling (~0.2) + cpy (~0.2) +
    query_relevance (~0.1) into key_score in [0,1]. Mutates each node in place, setting
    local_indegree/seed_coupling/cpy/key_score. Indegree and coupling are normalized by the
    max observed IN THIS RUN (not a global constant) — that's what makes this theme-local."""
    max_indeg = max(indegree.values(), default=0) or 1
    max_coup = max(coupling.values(), default=0) or 1
    for wid, n in nodes.items():
        n["cpy"] = fg.cpy(n)
        indeg = indegree.get(wid, 0)
        coup = coupling.get(wid, 0)
        indeg_norm = indeg / max_indeg
        coup_norm = coup / max_coup
        cpy_norm = min(math.log1p(n["cpy"]) / math.log1p(50.0), 1.0)
        rel_norm = min(float(n.get("query_relevance") or 0.0) / 100.0, 1.0)
        score = (W_INDEGREE * indeg_norm + W_COUPLING * coup_norm
                + W_CPY * cpy_norm + W_RELEVANCE * rel_norm)
        n["local_indegree"] = indeg
        n["seed_coupling"] = coup
        n["key_score"] = round(min(score, 1.0), 3)


def label_tiers(nodes: Dict[str, dict], indegree: Dict[str, int]) -> None:
    """Sets node['tier'] to 'canonical' (top ~20% by local_indegree, must have indegree > 0),
    'core' (next ~40%), or 'peripheral' (the rest, or anything with zero local_indegree)."""
    ranked = sorted(nodes.keys(), key=lambda w: indegree.get(w, 0), reverse=True)
    n_total = len(ranked)
    canonical_cut = max(1, math.ceil(n_total * 0.2))
    core_cut = max(canonical_cut, math.ceil(n_total * 0.6))
    for rank, wid in enumerate(ranked):
        if indegree.get(wid, 0) <= 0:
            nodes[wid]["tier"] = "peripheral"
        elif rank < canonical_cut:
            nodes[wid]["tier"] = "canonical"
        elif rank < core_cut:
            nodes[wid]["tier"] = "core"
        else:
            nodes[wid]["tier"] = "peripheral"


def select_canonical_core(nodes: Dict[str, dict], limit: int = 15) -> List[dict]:
    """Tier MEMBERSHIP (label_tiers) is by raw local_indegree, per spec. But WITHIN that
    canonical set we display by key_score (the full indegree+coupling+cpy+relevance blend),
    not raw indegree alone — a work cited by many things that happen to also be huge citation
    hubs (a stats-atlas methods citation, say) can out-rank real theme classics on raw indegree
    even though its seed_coupling/relevance are near zero. key_score corrects for that while
    still keeping indegree dominant (its weight is 0.5 of key_score)."""
    items = [n for n in nodes.values() if n.get("tier") == "canonical"]
    items.sort(key=lambda n: (n.get("key_score", 0), n.get("local_indegree", 0)), reverse=True)
    return items[:limit]


def select_recent_front(nodes: Dict[str, dict], current_year: int = CURRENT_YEAR,
                        window: int = RECENT_WINDOW, indegree_max: int = 1,
                        limit: int = 10) -> List[dict]:
    """High-CPY, low-local-indegree, last ~window years — the emerging edge the canon hasn't
    absorbed yet (as opposed to canonical core, which is already-absorbed classics)."""
    items = [n for n in nodes.values()
             if isinstance(n.get("year"), int) and n["year"] >= current_year - window
             and n.get("local_indegree", 0) <= indegree_max]
    items.sort(key=lambda n: n.get("cpy", 0.0), reverse=True)
    return items[:limit]


def select_reviews_bridges(nodes: Dict[str, dict], limit: int = 10) -> List[dict]:
    """Reviews/surveys by title/type signal, OR works that bridge >= 2 distinct query angles."""
    items = []
    for n in nodes.values():
        is_review = bool(REVIEW_RE.search(n.get("title") or "")) or n.get("type") == "review"
        bridges = len(n.get("surfaced_by_queries") or []) >= 2
        if is_review or bridges:
            items.append(n)
    items.sort(key=lambda n: n.get("key_score", 0.0), reverse=True)
    return items[:limit]


def saturation_reached(new_count: int, total_before: int,
                       threshold: float = SATURATION_THRESHOLD) -> bool:
    """True if a round added < `threshold` fraction of new nodes relative to what existed
    before that round (the stopping rule for the snowball loop)."""
    if total_before <= 0:
        return False
    return (new_count / total_before) < threshold


# --------------------------------------------------------------------------- paper-mode subtraction
def mark_paper_citations(nodes: Dict[str, dict], cited_dois: set,
                         cited_titles: List[frozenset]) -> None:
    """Subtract-mode: mark each node ALREADY-CITED vs MISSING against a manuscript's existing
    references. Reuses find_gaps.py's is_cited (DOI-exact, else fuzzy token-Jaccard title)."""
    for n in nodes.values():
        n["already_cited"] = fg.is_cited(n, cited_dois, cited_titles)


# --------------------------------------------------------------------------- graph-snowball pipeline
def run_snowball(queries: List[str], depth: str, max_rounds_override: Optional[int] = None,
                 quiet: bool = False) -> dict:
    """The network-touching orchestration. Everything it produces (a node table + run metadata)
    feeds the pure scoring/tiering functions above."""
    cfg = DEPTH_CONFIG[depth]
    max_rounds = max_rounds_override or cfg["max_rounds"]
    fetcher = GraphFetcher(cfg["call_cap"])

    nodes: Dict[str, dict] = {}
    surfaced_by: Dict[str, Set[str]] = defaultdict(set)   # wid -> queries that DIRECTLY surfaced it
    relevance_by_query: Dict[str, Dict[str, float]] = defaultdict(dict)  # wid -> {query: relevance}

    # --- 1. seed round: keyword search per query, merge + dedup, take the top `seeds` by relevance
    for q in queries:
        hits = fetcher.search(q, n=max(cfg["seeds"], 10))
        for w in hits:
            surfaced_by[w["id"]].add(q)
            relevance_by_query[w["id"]][q] = w.get("relevance_score") or 0.0
            if w["id"] not in nodes:
                nodes[w["id"]] = w

    ranked = sorted(
        nodes.values(),
        key=lambda n: max(relevance_by_query.get(n["id"], {}).values() or [0.0]),
        reverse=True,
    )
    seeds = ranked[: cfg["seeds"]]
    seed_ids = {s["id"] for s in seeds}
    for s in seeds:
        qs = ", ".join(sorted(surfaced_by[s["id"]]))
        s["provenance"] = [f"seed (query: {qs})"]
    for wid, n in nodes.items():
        n.setdefault("provenance", [f"seed (query: {', '.join(sorted(surfaced_by[wid]))})"])

    if not seeds and not fetcher.stopped_reason and fetcher.calls < fetcher.call_cap:
        log("no seeds found for the given queries")

    # --- 2/3. graph expansion rounds: backward-hydrate referenced_works + forward-cites, per node
    expanded_ids: Set[str] = set()

    def expand_node(n: dict, round_num: int) -> None:
        title = (n.get("title") or "?")[:60]
        new_ref_ids = [r for r in (n.get("referenced_works") or []) if r not in nodes]
        for h in fetcher.hydrate(new_ref_ids):
            if h["id"] not in nodes:
                h["provenance"] = [f"backward from '{title}' (round {round_num})"]
                nodes[h["id"]] = h
        for f in fetcher.forward_citations(n["id"], cfg["forward_k"]):
            if f["id"] not in nodes:
                f["provenance"] = [f"forward-cites of '{title}' (round {round_num})"]
                nodes[f["id"]] = f
        expanded_ids.add(n["id"])

    round_num = 0
    stop_reason: Optional[str] = None
    if seeds:
        round_num = 1
        before = len(nodes)
        for s in seeds:
            if fetcher.stopped_reason or fetcher.calls >= fetcher.call_cap:
                break
            expand_node(s, round_num)
        added = len(nodes) - before
        if fetcher.stopped_reason:
            stop_reason = fetcher.stopped_reason
        elif fetcher.calls >= fetcher.call_cap:
            stop_reason = f"call budget cap ({cfg['call_cap']}) reached after round {round_num}"
        elif max_rounds <= 1:
            stop_reason = f"max-rounds ({max_rounds}) reached"
        elif saturation_reached(added, before):
            stop_reason = f"round {round_num} added <10% new nodes ({added}/{before}) — saturated"

        # further rounds: recompute local in-degree, expand the top not-yet-expanded nodes
        while stop_reason is None and round_num < max_rounds:
            indeg_now = compute_indegree(nodes)
            candidates = sorted(
                (n for wid, n in nodes.items() if wid not in expanded_ids),
                key=lambda n: indeg_now.get(n["id"], 0), reverse=True,
            )
            to_expand = candidates[: cfg["seeds"]]
            if not to_expand:
                stop_reason = "no further not-yet-expanded nodes — saturated"
                break
            round_num += 1
            before = len(nodes)
            for n in to_expand:
                if fetcher.stopped_reason or fetcher.calls >= fetcher.call_cap:
                    break
                expand_node(n, round_num)
            added = len(nodes) - before
            if fetcher.stopped_reason:
                stop_reason = fetcher.stopped_reason
            elif fetcher.calls >= fetcher.call_cap:
                stop_reason = f"call budget cap ({cfg['call_cap']}) reached after round {round_num}"
            elif round_num >= max_rounds:
                stop_reason = f"max-rounds ({max_rounds}) reached"
            elif saturation_reached(added, before):
                stop_reason = f"round {round_num} added <10% new nodes ({added}/{before}) — saturated"
    else:
        stop_reason = fetcher.stopped_reason or "no seeds — nothing to expand"

    # --- finalize per-node fields the scoring layer needs
    for wid, n in nodes.items():
        qmap = relevance_by_query.get(wid)
        n["query_relevance"] = max(qmap.values()) if qmap else 0.0
        n["surfaced_by_queries"] = sorted(surfaced_by.get(wid, []))

    indeg = compute_indegree(nodes)
    coup = compute_seed_coupling(nodes, seed_ids)
    compute_key_scores(nodes, indeg, coup)
    label_tiers(nodes, indeg)

    if not quiet:
        log(f"harvested {len(nodes)} works from {len(seeds)} seed(s) across {fetcher.calls} "
            f"call(s), {round_num} round(s). stop reason: {stop_reason}")

    return {
        "nodes": nodes,
        "seed_ids": seed_ids,
        "queries": queries,
        "depth": depth,
        "calls_made": fetcher.calls,
        "call_cap": cfg["call_cap"],
        "rounds_run": round_num,
        "stop_reason": stop_reason,
    }


# --------------------------------------------------------------------------- callosum seeding
# (reuses find_gaps.py's seed_callosum() verbatim — same POST /wanted pattern, same graceful
# degrade if callosum isn't running.)


# --------------------------------------------------------------------------- report build
def _authors_str(n: dict) -> str:
    a = n.get("authors") or []
    return ", ".join(a[:3]) + (" et al." if len(a) > 3 else "") if a else "—"


def _node_public(n: dict, paper_mode: bool) -> dict:
    out = {
        "id": n.get("id"),
        "doi": n.get("doi"),
        "title": n.get("title"),
        "authors": n.get("authors"),
        "year": n.get("year"),
        "venue": n.get("venue"),
        "cited_by_count": n.get("cited_by_count"),
        "abstract": n.get("abstract"),
        "key_score": n.get("key_score"),
        "local_indegree": n.get("local_indegree"),
        "seed_coupling": n.get("seed_coupling"),
        "cpy": n.get("cpy"),
        "query_relevance": n.get("query_relevance"),
        "tier": n.get("tier"),
        "provenance": n.get("provenance"),
        "surfaced_by_queries": n.get("surfaced_by_queries"),
    }
    if paper_mode:
        out["already_cited"] = n.get("already_cited", False)
    return out


def build_report(mode: str, input_text: str, run: dict, paper_path: Optional[str],
                 cited_count: Optional[int], depth: str) -> dict:
    nodes = run["nodes"]
    paper_mode = paper_path is not None
    canonical = select_canonical_core(nodes)
    recent = select_recent_front(nodes)
    reviews = select_reviews_bridges(nodes)

    if paper_mode:
        # lead with the MISSING canonical ones — the highest-value gap list
        canonical.sort(key=lambda n: (n.get("already_cited", False),
                                      -(n.get("local_indegree", 0))))

    report = {
        "mode": mode,
        "input_text": input_text,
        "paper": paper_path,
        "depth": depth,
        "queries": run["queries"],
        "harvested": len(nodes),
        "seed_count": len(run["seed_ids"]),
        "rounds_run": run["rounds_run"],
        "calls_made": run["calls_made"],
        "call_cap": run["call_cap"],
        "stop_reason": run["stop_reason"],
        "cited_count": cited_count,
        "canonical_core": [_node_public(n, paper_mode) for n in canonical],
        "recent_front": [_node_public(n, paper_mode) for n in recent],
        "reviews_bridges": [_node_public(n, paper_mode) for n in reviews],
        "callosum_seed": None,
    }
    return report


def to_markdown(report: dict) -> str:
    o = ["# Key Citations Report", ""]
    o.append(f"- **Mode:** {report['mode']}  |  **Depth:** {report['depth']}  "
             f"|  **Queries:** {', '.join(report['queries'])}")
    if report.get("paper"):
        o.append(f"- **Paper:** `{report['paper']}`  (existing citations found: {report.get('cited_count')})")
    o.append("")
    o.append("## Coverage / audit")
    o.append(f"- Seeds: **{report['seed_count']}**  |  Works harvested: **{report['harvested']}**  "
             f"|  Rounds run: **{report['rounds_run']}**  |  Calls made: **{report['calls_made']}"
             f"/{report['call_cap']}**")
    o.append(f"- Stop reason: {report.get('stop_reason')}")
    o.append("")

    def render_section(title: str, items: List[dict], note: str) -> None:
        o.append(f"## {title}")
        o.append("")
        o.append(f"_{note}_")
        o.append("")
        if not items:
            o.append("_None surfaced at this depth — try `--depth deep` or add an angle query._")
            o.append("")
            return
        for n in items:
            tag = ""
            if n.get("already_cited") is True:
                tag = " **[ALREADY-CITED]**"
            elif n.get("already_cited") is False:
                tag = " **[MISSING]**"
            prov = "; ".join(n.get("provenance") or [])
            o.append(f"- **{n['title']}** — {_authors_str(n)} ({n.get('year')}), *{n.get('venue') or '—'}*."
                     f"{tag}")
            o.append(f"    - score {n.get('key_score')} | indegree: cited by {n.get('local_indegree')} "
                     f"of {report['harvested']} harvested works | CPY {n.get('cpy')} | "
                     f"seed-coupling {n.get('seed_coupling')} | `doi:{n.get('doi') or '—'}`")
            o.append(f"    - via: {prov or 'unknown'}")
            snip = (n.get("abstract") or "").strip().replace("\n", " ")
            if snip:
                o.append(f"    - {snip[:220]}{'…' if len(snip) > 220 else ''}")
        o.append("")

    render_section("Canonical core (the must-cites)", report["canonical_core"],
                   "Highest local in-degree — cited by the most OTHER harvested works. "
                   "In paper mode, MISSING ones lead (the highest-value gaps).")
    render_section("Recent front (the emerging edge)", report["recent_front"],
                   f"High citations-per-year, published in the last ~{RECENT_WINDOW} years, "
                   f"low local in-degree — the canon hasn't absorbed these yet.")
    render_section("Reviews & bridges", report["reviews_bridges"],
                   "Review/survey-type works, or works surfaced by >= 2 distinct query angles.")

    if report.get("callosum_seed"):
        ok = sum(1 for s in report["callosum_seed"] if s["ok"])
        o.append(f"_Seeded to callosum wanted list: {ok}/{len(report['callosum_seed'])} DOIs._")
        o.append("")

    o.append("---")
    o.append("What next?  1) write one-line reads for the canonical core (Anjan's voice)  "
             "2) append BibTeX to references/library.bib (`--bib`)  3) seed callosum's wanted "
             "list with the top canonical DOIs (`--seed-callosum --top-seed N`)  4) go deeper "
             "(`--depth deep`) or add another angle query   (or just tell me what you want)")
    o.append("")
    o.append("_The LLM (CHATLabAI) writes the honest one-line read per canonical citation in "
             "Anjan's voice, and flags any classic OpenAlex has mis-dated to a modern reprint/"
             "edition year (a known metadata quirk — check the year before trusting the CPY)._")
    return "\n".join(o)


# --------------------------------------------------------------------------- self-test (OFFLINE)
def _self_test() -> int:
    """Offline checks on the pure scoring/tiering/subtraction/render functions. Builds a
    synthetic 8-work node/edge graph by hand and NEVER touches GraphFetcher/network — the
    "injected node set" approach the spec allows as an alternative to monkeypatching."""
    checks = []

    def ck(name, cond):
        checks.append((name, bool(cond)))
        print(f"  [{'ok' if cond else 'FAIL'}] {name}")

    # Synthetic graph: W1 is cited (referenced_works) by W2..W6 => local_indegree(W1) == 5.
    # W7 has a huge global cited_by_count but nobody in the harvested set cites it => indegree 0.
    # W8 is recent (this year) with high CPY and low indegree => should land in "recent front".
    def mk(wid, title, year, cited_by, refs, doi=None, wtype="article"):
        return {
            "id": wid, "doi": doi or f"10.1/{wid.lower()}", "title": title, "authors": ["A. Author"],
            "year": year, "venue": "Journal of Testing", "cited_by_count": cited_by,
            "abstract": f"Synthetic abstract for {title}.", "referenced_works": refs,
            "relevance_score": 10.0, "type": wtype,
        }

    nodes = {
        "W1": mk("W1", "The Canonical Foundational Work", 2005, 400, []),
        "W2": mk("W2", "Follow-up A", 2010, 50, ["W1"]),
        "W3": mk("W3", "Follow-up B", 2012, 40, ["W1"]),
        "W4": mk("W4", "Follow-up C", 2014, 30, ["W1"]),
        "W5": mk("W5", "Follow-up D", 2016, 20, ["W1"]),
        "W6": mk("W6", "Follow-up E", 2018, 10, ["W1"]),
        "W7": mk("W7", "Globally Popular But Off-Theme", 2003, 5000, []),
        "W8": mk("W8", "Brand New High-Impact Result", CURRENT_YEAR - 1, 60, []),
    }
    seed_ids = {"W2", "W3"}
    for wid in seed_ids:
        nodes[wid]["provenance"] = ["seed (query: test)"]
    for wid, n in nodes.items():
        n.setdefault("provenance", [f"backward from 'seed' (round 1)"])
        n["surfaced_by_queries"] = ["test"] if wid in ("W1", "W7") else []
        n["query_relevance"] = 10.0 if wid == "W1" else 0.0

    # 1. local_indegree correctness
    indeg = compute_indegree(nodes)
    ck("local_indegree: work cited by 5 others gets 5", indeg["W1"] == 5)
    ck("local_indegree: off-theme popular work gets 0 (no harvested citer)", indeg["W7"] == 0)

    coup = compute_seed_coupling(nodes, seed_ids)
    compute_key_scores(nodes, indeg, coup)

    # 2. key_score ranks high-indegree above high-global-cites-low-indegree
    ck("key_score ranks high-indegree (W1) above high-global-cites-low-indegree (W7)",
       nodes["W1"]["key_score"] > nodes["W7"]["key_score"])

    # 3. saturation stopping rule
    ck("saturation_reached true when a round adds <10% new nodes (3/40)",
       saturation_reached(3, 40) is True)
    ck("saturation_reached false when a round adds >=10% new nodes (10/40)",
       saturation_reached(10, 40) is False)
    ck("saturation_reached false on the first round (nothing existed before)",
       saturation_reached(5, 0) is False)

    # 4. tiering
    label_tiers(nodes, indeg)
    ck("highest-indegree node (W1) lands in canonical core", nodes["W1"]["tier"] == "canonical")
    recent_front = select_recent_front(nodes)
    ck("recent high-CPY low-indegree node (W8) lands in recent front",
       any(n["id"] == "W8" for n in recent_front))
    canonical_core = select_canonical_core(nodes)
    ck("canonical core selection includes W1", any(n["id"] == "W1" for n in canonical_core))

    # 5. paper-mode subtraction
    cited_dois = {nodes["W1"]["doi"]}
    mark_paper_citations(nodes, cited_dois, [])
    ck("paper-mode subtraction marks the cited DOI ALREADY-CITED", nodes["W1"]["already_cited"] is True)
    ck("paper-mode subtraction leaves an uncited DOI as MISSING", nodes["W2"]["already_cited"] is False)

    # 6. to_markdown renders without error
    run = {"nodes": nodes, "seed_ids": seed_ids, "queries": ["test theme"], "depth": "standard",
          "calls_made": 7, "call_cap": 40, "rounds_run": 1, "stop_reason": "max-rounds (1) reached"}
    report = build_report("theme", "test theme", run, None, None, "standard")
    md = None
    try:
        md = to_markdown(report)
    except Exception as e:  # pragma: no cover
        ck(f"to_markdown raised {e!r}", False)
    if md is not None:
        ck("to_markdown renders", isinstance(md, str) and "Canonical core" in md and "Coverage / audit" in md)

    # bonus: JSON round-trip of a report is stable (exercised in --format json in practice)
    ck("canonical_core items carry key_score/local_indegree/cpy/provenance/doi/abstract",
       bool(report["canonical_core"]) and all(
           k in report["canonical_core"][0] for k in
           ("key_score", "local_indegree", "cpy", "provenance", "doi", "abstract")))

    passed = all(ok for _, ok in checks)
    print("SELF-TEST PASSED" if passed else "SELF-TEST FAILED")
    return 0 if passed else 1


# --------------------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="key_citations.py",
        description="Graph-based citation snowballing: given a theme/question/sentence, find "
                    "the KEY citations via OpenAlex citation-graph expansion + local in-degree "
                    "centrality (not just keyword search). Sibling to find_gaps.py.",
    )
    p.add_argument("--self-test", action="store_true", help="Run offline self-checks and exit.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--theme", help="Free-text theme/topic to find key citations for.")
    g.add_argument("--question", help="Free-text research question to find key citations for.")
    g.add_argument("--sentence", help="A single sentence/claim to find key citations for.")
    p.add_argument("--queries", nargs="+", default=None,
                   help="Explicit angle queries (2-5, LLM-decomposed). Default: the "
                        "--theme/--question/--sentence text used as a single query.")
    p.add_argument("--paper", default=None,
                   help="Manuscript (.docx/.md/.tex/.txt) to run subtract-mode against: mark "
                        "which key citations it already has vs. is missing.")
    p.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard",
                   help="quick=5 seeds/~15 calls, standard=8 seeds/~40 calls, "
                        "deep=12 seeds/~100 calls (default: standard).")
    p.add_argument("--max-rounds", type=int, default=None,
                   help="Override the depth tier's default max expansion rounds.")
    p.add_argument("--seed-callosum", action="store_true",
                   help="Push the top canonical DOIs to callosum's /wanted list.")
    p.add_argument("--top-seed", type=int, default=5, help="How many DOIs to seed (default: 5).")
    p.add_argument("--bib", default=None,
                   help="Append BibTeX for the canonical core to this .bib file (opt-in, dedups "
                        "against existing keys via litsearch's append_bibtex).")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.add_argument("--out", default="key_citations.md", help="Output markdown path (default: key_citations.md).")
    p.add_argument("--quiet", action="store_true", help="Suppress the stderr summary.")
    args = p.parse_args(argv)

    if args.self_test:
        return _self_test()

    if not (args.theme or args.question or args.sentence):
        p.error("one of --theme / --question / --sentence is required (or --self-test)")

    if args.theme:
        mode, input_text = "theme", args.theme
    elif args.question:
        mode, input_text = "question", args.question
    else:
        mode, input_text = "sentence", args.sentence

    queries = args.queries if args.queries else [input_text]

    # Paper mode (subtraction) — read-only, reuses find_gaps.py's helpers verbatim.
    cited_dois: set = set()
    cited_titles: List[frozenset] = []
    paper_path = None
    cited_count = None
    if args.paper:
        paper_path = Path(args.paper)
        if not paper_path.is_file():
            sys.exit(f"ERROR: paper not found: {paper_path}")
        text = fg.extract_text(paper_path)
        ref_block = fg.find_references_block(text)
        cited_dois = fg.extract_dois(ref_block)
        cited_titles = fg.cited_title_sets(ref_block)
        cited_count = len(cited_dois)

    run = run_snowball(queries, args.depth, max_rounds_override=args.max_rounds, quiet=args.quiet)

    if args.paper:
        mark_paper_citations(run["nodes"], cited_dois, cited_titles)

    report = build_report(mode, input_text, run, str(paper_path) if paper_path else None,
                          cited_count, args.depth)

    # Hand-offs (opt-in, additive).
    if args.seed_callosum:
        top_dois = [n["doi"] for n in report["canonical_core"][: args.top_seed] if n.get("doi")]
        report["callosum_seed"] = fg.seed_callosum(top_dois)

    if args.bib:
        bib_entries = [n for n in report["canonical_core"] if n.get("doi")]
        appended = append_bibtex(bib_entries, Path(args.bib))
        if not args.quiet:
            log(f"appended {appended} new BibTeX entries to {args.bib}")

    if args.format == "json":
        print(json.dumps(report, indent=2, default=list))
    else:
        Path(args.out).write_text(to_markdown(report), encoding="utf-8")
        print(f"Wrote {args.out}")

    if not args.quiet:
        sys.stderr.write(
            f"\n[{len(report['canonical_core'])} canonical, {len(report['recent_front'])} recent-front, "
            f"{len(report['reviews_bridges'])} reviews/bridges from {report['harvested']} harvested "
            f"work(s); {report['calls_made']}/{report['call_cap']} calls; stop: {report['stop_reason']}]\n"
        )
        if report.get("callosum_seed"):
            ok = sum(1 for s in report["callosum_seed"] if s["ok"])
            sys.stderr.write(f"[callosum seeded: {ok}/{len(report['callosum_seed'])} DOIs]\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
