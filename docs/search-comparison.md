# WikiMind — Search Approach Comparison

> Comparing all retrieval backends: what we built vs. what qmd adds.
> Use this to decide when and whether to upgrade from the default BM25.

---

## The 5 Approaches

| ID | Backend | Source | Status |
|---|---|---|---|
| 1 | `index_keyword` | We built it (`retrieval.py`) | Done, available |
| 2 | `bm25` | We built it (`retrieval.py`) | Done, **current default** |
| 3 | `qmd search` | qmd CLI — BM25 mode | Not integrated |
| 4 | `qmd vsearch` | qmd CLI — vector only | Not integrated |
| 5 | `qmd query` | qmd CLI — full hybrid | Not integrated |

---

## How Each One Works

### 1. `index_keyword` (ours)

Searches only the one-line summaries in `index.md`, not full page content.
Extracts words longer than 4 characters, counts overlap between query and index lines.
No ranking — just a hit count.

```
query:  "machine learning optimization"
scans:  "- [[gradient-descent]] — Method for minimizing loss functions"
overlap: {"machine","learning","optimization"} ∩ {"method","minimizing","loss","functions"} = 0
result: misses this page entirely
```

**What it searches:** index.md summary lines only  
**Ranking:** none — just overlap count  
**Algorithm:** simple set intersection

---

### 2. `bm25` (ours, current default)

Okapi BM25 over the full content of every wiki page.
Proper TF-IDF scoring with document length normalization.
Ranks results by a continuous relevance score.
Still lexical — the query and page must share tokens.

```
query:  "machine learning optimization"
action: reads every page, scores by term frequency × IDF × length normalization
finds:  pages containing "optimization", "learning", etc.
misses: page titled "gradient-descent" that never uses the words "machine learning"
```

**What it searches:** full content of all wiki pages  
**Ranking:** Okapi BM25 score (TF-IDF + length norm)  
**Algorithm:** lexical — shared tokens required

---

### 3. `qmd search` (qmd BM25 only)

qmd's own BM25 implementation over its pre-built index.
Functionally equivalent to our BM25 — same algorithm, different implementation.
Requires collection registration and `qmd embed` before first use.
Slower than our BM25 due to Node.js subprocess cold-start on every call.

**What it searches:** qmd's indexed collection (same content as our BM25)  
**Ranking:** BM25 score  
**Algorithm:** lexical — shared tokens required  
**Verdict:** no quality gain over our BM25; adds cold-start overhead with no benefit

---

### 4. `qmd vsearch` (qmd vector/semantic only)

Pure semantic search using a local GGUF embedding model (runs via node-llama-cpp, no API key).
Converts query and pages into high-dimensional vectors, finds nearest neighbors by cosine similarity.
No keyword requirement — finds pages about the same concept even with completely different words.

```
query:  "machine learning optimization"
action: embed query → [0.23, -0.11, 0.87, ...]
        cosine-score against all page embeddings
finds:  "gradient-descent", "backpropagation", "loss-minimization"
        even if those pages never say "machine learning"
misses: sometimes drops exact keyword matches that BM25 would catch
```

**What it searches:** vector space of all page embeddings  
**Ranking:** cosine similarity score  
**Algorithm:** semantic — concept proximity, not token overlap

---

### 5. `qmd query` (qmd full hybrid — BM25 + vector + LLM re-ranking)

Runs BM25 and vector search in parallel, merges the two result lists via RRF
(Reciprocal Rank Fusion), then passes the merged pool to a local GGUF LLM for re-ranking.
The LLM reads the actual query and candidate page content and re-orders by true relevance.
All steps run locally — no API key needed for any step.

```
query: "machine learning optimization"
step 1: BM25 candidates    → [gradient-descent, sgd, adam, backprop, ...]
step 2: vector candidates  → [loss-surface, convergence, optimization-theory, ...]
step 3: RRF merge          → unified ranked list of ~20 candidates
step 4: LLM re-ranking     → LLM reads each candidate and query, re-orders by relevance
result: best 10 pages, covering both keyword and semantic matches
```

**What it searches:** BM25 index + vector embedding space, merged  
**Ranking:** LLM re-ranking over RRF-merged candidates  
**Algorithm:** hybrid — catches both lexical and semantic matches

---

## Query Type Performance

Each cell rates how well the approach handles that query type:
**Best / Good / Medium / Poor / Fails**

| Query type | `index_keyword` | `bm25` (ours) | `qmd search` | `qmd vsearch` | `qmd query` |
|---|---|---|---|---|---|
| Exact keyword match: "transformer architecture" | Medium | Good | Good | Good | Best |
| Synonym: "neural net" → finds "deep learning" page | Poor | Poor | Poor | Good | Best |
| Vague / conceptual: "why did they change approach" | Fails | Poor | Poor | Medium | Good |
| Person name: "Vaswani" | Medium | Good | Good | Medium | Best |
| Concept without exact words: "how models learn" | Fails | Poor | Poor | Good | Best |
| Specific page name: "gradient-descent" | Good | Good | Good | Medium | Best |
| Cross-concept: "connection between attention and memory" | Fails | Poor | Poor | Good | Best |
| Short factual: "what year was GPT-3 released" | Medium | Good | Good | Medium | Best |
| Wiki < 50 pages (any query) | Good | Good | Good | Good | Good |
| Wiki 200+ pages (any query) | Poor | Medium | Medium | Good | Best |

---

## Speed / Latency

> These are estimated ranges based on algorithm characteristics, not measured benchmarks.
> Actual times depend on wiki size, hardware, and GGUF model size.

| Approach | Estimated latency | Bottleneck |
|---|---|---|
| `index_keyword` | < 5ms | Read one file + set intersection |
| `bm25` (ours) | 20–200ms | Read all pages + BM25 scoring in Python |
| `qmd search` | 200–800ms | **Node.js process startup** + BM25 |
| `qmd vsearch` | 500ms–3s | Node.js startup + GGUF embedding inference |
| `qmd query` | 1s–10s | Node.js startup + GGUF embeddings + GGUF LLM re-ranking |

### The subprocess cold-start problem

Every call to `QmdRetriever.retrieve()` spawns a **new Node.js process** via `subprocess.run()`.
The process exits after printing results. This means:

- Node.js startup cost: ~200–500ms, paid on **every single search call**
- GGUF model load cost: additional 500ms–5s depending on model size, also paid every call
- Our BM25 pays none of this — pure Python, no subprocess, no model load

**Does it matter for WikiMind?**

The retrieval result feeds into an LLM call that takes 5–30 seconds. So 1–3 seconds of qmd
overhead is a 10–20% increase in total operation time — noticeable but not blocking.

For `wikimind watch` polling every 5 seconds and auto-ingesting, it matters more.

**The persistent process alternative:**

If qmd ran as its MCP server (`qmd mcp`, a long-running process), model stays loaded in memory
and each search call is just inference — the cold-start cost disappears. But registering the
qmd MCP server alongside wikimind creates two overlapping search tools (`wiki_search` +
`qmd_search`) and Claude Code would unpredictably pick between them. The tradeoff is real
and there is no clean resolution with the current architecture.

---

## Result Quality by Wiki Size

| Wiki size | `index_keyword` | `bm25` (ours) | `qmd query` |
|---|---|---|---|
| < 30 pages | Adequate | Good | Overkill — same results, much slower |
| 30–100 pages | Starts missing | Good | Marginally better |
| 100–200 pages | Poor | Medium — lexical gaps appear | Clearly better |
| 200–500 pages | Unusable | Degrading | Good |
| 500+ pages | Unusable | Poor | Good |

---

## Why `qmd search` Is Not Worth Integrating

`qmd search` runs BM25 — the same algorithm our `BM25Retriever` already implements.

| | `bm25` (ours) | `qmd search` |
|---|---|---|
| Algorithm | Okapi BM25 | Okapi BM25 |
| Search quality | Same | Same |
| Latency | 20–200ms | 200–800ms (subprocess overhead) |
| Dependencies | None | Node.js + npm package |
| Extra setup | None | `qmd collection add` + `qmd embed` |

**Conclusion:** `qmd search` adds cold-start overhead, requires external install, and produces
identical results to what we already have. Skip it entirely. The only qmd modes worth
considering are `vsearch` (semantic) and `query` (full hybrid).

---

## Full Decision Matrix

| | `index_keyword` | `bm25` (ours) | `qmd vsearch` | `qmd query` |
|---|---|---|---|---|
| **Search quality** | Low | Medium | Medium–High | High |
| **Semantic search** | No | No | Yes | Yes |
| **LLM re-ranking** | No | No | No | Yes (local GGUF) |
| **Latency (estimated)** | < 5ms | 20–200ms | 500ms–3s | 1s–10s |
| **Subprocess cold-start** | No | No | Yes | Yes |
| **Works offline** | Yes | Yes | Yes | Yes |
| **API key required** | None | None | None | None |
| **Extra install** | None | None | Node.js + npm | Node.js + npm |
| **One-time vault setup** | None | None | `qmd collection add` + `qmd embed` | same |
| **Post-ingest step** | None | None | `qmd embed` | `qmd embed` |
| **GGUF model download** | No | No | Yes (auto, first run) | Yes (auto, first run) |
| **WikiMind code to add** | Done | Done | ~60 lines | ~60 lines (same class) |
| **Good from page count** | 0–50 | 0–200 | Any | Any |

---

## Practical Recommendation

```
Wiki size        retrieval_backend         Notes
─────────────────────────────────────────────────────────────────────
0–50 pages    →  index_keyword             Fast, zero deps, good enough
50–200 pages  →  bm25                      Current default, solid
200+ pages    →  qmd query                 If user accepts Node.js install
              →  embedding (Option B)      If using OpenAI or Ollama provider
```

The inflection point where qmd becomes worth the setup cost is around **200 pages** — where
BM25 starts returning results that miss the actually-relevant page because it uses different
words than the query.

For users on the default Anthropic provider: qmd is the better upgrade path because Anthropic
has no public embeddings API, making the native embedding retriever (Option B) unavailable
without switching providers.

For users on OpenAI or Ollama: the native embedding retriever (Option B in GAP-10) is simpler —
no extra install, single config, same semantic capability.

---

## Implementation Notes (for when the time comes)

The key insight: `qmd search` (BM25 only) should never be used as a WikiMind backend.
Only these two qmd commands are worth wiring up:

```python
# Option: vector only (faster, no re-ranking)
subprocess.run(["qmd", "vsearch", query, "--json"])

# Option: full hybrid (slower, best quality) — recommended
subprocess.run(["qmd", "query", query, "--json"])
```

Both slot into `QmdRetriever.retrieve()` — the only difference is the subcommand name.
The class itself is identical for both; expose the choice via config:

```toml
[wiki]
retrieval_backend = "qmd"
qmd_mode = "query"    # "query" (full hybrid, default) or "vsearch" (vector only)
```

One-time vault setup the user runs after installing qmd:

```bash
npm install -g @tobilu/qmd

# register the wiki vault as a qmd collection
qmd collection add .wiki/vault/ --name wiki

# pre-compute embeddings (re-run after each batch ingest)
qmd embed
```

Post-ingest automation: when `retrieval_backend = "qmd"`, `wikimind ingest` should call
`subprocess.run(["qmd", "embed"])` after writing pages so the index stays current.
