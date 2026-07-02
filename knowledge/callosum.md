# Callosum — local reference manager (MCP)

CHATLabAI is hooked into **callosum** (`~/callosum`), a local-first reference manager for
scholarly PDFs. Its thesis fits the lab's discipline exactly: an LLM summary is only
trustworthy if every citation is independently verified against the source. Callosum
extracts and chunks PDFs with precise coordinates, embeds content locally, and generates
citation-grounded summaries where every sentence is checked back against the source —
showing quotes, page numbers, and confidence levels, not verdicts.

Everything runs locally on `127.0.0.1:8080`. No data leaves the machine unless the
optional AI features are explicitly enabled (they are not, by default).

## How CHATLabAI reaches it

The callosum MCP server is registered in pi's `~/.pi/agent/mcp.json`. Pi spawns it as a
subprocess (`python -m mcp_server` from `~/callosum/.mcp-venv`, cwd `~/callosum`) over the
standard MCP stdio transport. Each tool call makes one HTTP request to the running
callosum API. **The callosum API must be running** for the tools to answer:

```bash
cd ~/callosum && .venv/bin/uvicorn app.backend.api.app:app --host 127.0.0.1 --port 8080
```

If the API is down, the MCP tools return connection errors — fall back to OpenAlex/Crossref
and tell the user to start callosum.

## The MCP tools (what you can call)

**Read tools (always available):**

- `search_library(query, limit=20)` — keyword search across metadata (title, authors, etc.).
- `get_paper(paper_id)` — full metadata for a single paper.
- `full_text_search(query, limit=20)` — verbatim text search *inside* the PDFs.
- `find_passages(query, top_k=5)` — grounded passages: verbatim quotes with page numbers,
  for citation. This is the strongest-provenance tool — use it when a claim needs a
  traceable source.
- `format_citation(paper_ids, format="bibtex")` — format papers as bibtex, ris, or csl-json.

**Write tools (opt-in, off by default):**

- `add_tag(paper_id, tag)` — tag a paper.
- `add_to_axis(paper_id, axis_id)` — add a paper to a semantic axis.
- `save_reference(identifier)` — save a reference via DOI resolution.
- `annotate(paper_id, text)` — add a note to a paper.

Writes are gated by callosum's Settings toggle and the `CALLOSUM_DISABLE_AGENT_WRITES`
kill switch. Do not enable writes unless the user asks.

## When to prefer callosum over the free APIs

The lab's standing tools (`citations`, `lit-review`) use OpenAlex/Crossref — good for
*discovery* and metadata, but they return what publishers *claim*, not what the PDF *says*.
Callosum returns quotes tied to page numbers in PDFs the user actually owns. That is
stronger provenance.

**Prefer callosum when:**
- the user asks about "my library," "the papers I have," or a specific paper they own,
- a claim needs a verbatim quote with a page number (rule 7: separate evidence from
  interpretation; rule 9: don't let the cultural material sound like decoration),
- the user wants a citation formatted from their actual library, not a guessed DOI.

**Use the free APIs when:**
- the user is discovering new literature (callosum only knows what's imported),
- checking retractions or resolving DOIs (`citations` skill, via OpenAlex/Crossref),
- the callosum API is down.

## The lab-voice rule for grounding

This is the lab's rule 4 (separate evidence from interpretation) made operational. When
you pull a passage from callosum, say what the source shows and where (the page), then say
what you infer. Do not collapse the quote into a paraphrase that sounds like your own
claim. Anjan's discipline: the reader should see the analytic steps — the quote is the
evidence, the page is the provenance, the inference is yours and marked as such.

Example, in voice: *"Chatterjee (2014) notes that artists with visual-motor deficits 'are
not spared' those deficits, 'rather their talents allow them to express visual deficits
with particular eloquence' (p. 1569). The interesting point is not that artists are
resilient, but that the deficit becomes visible through the skill."*
