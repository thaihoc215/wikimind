# WikiMind Cheat Sheet

Quick operator guide for day-to-day use.

## Modes

- Mode A (Claude Code + MCP): no `ANTHROPIC_API_KEY` needed.
- Mode B (CLI): configure `anthropic`, `openai`, or `ollama` in `wikimind.toml`.

## 1) Setup

```bash
pip install -e .
# optional
pip install -e ".[pdf]"
```

Initialize in your project folder:

```bash
wikimind init --name "My Research"
```

Creates: `.wiki/raw/`, `.wiki/vault/`, `CLAUDE.md`, `wikimind.toml`, `.mcp.json`.
Default paths: `.wiki/raw/`, `.wiki/vault/`, and `.wiki/.wikimind/`.

## Generate client configs

```bash
wikimind generate --tool opencode   # creates AGENTS.md + opencode.json (OpenCode)
wikimind generate --tool vscode     # creates .vscode/mcp.json (Copilot)
```

Reads `.mcp.json` to resolve the correct executable path automatically.

## Packaging Wheel

```bash
# macOS/Linux/Git Bash
bash scripts/build-wheel.sh

# PowerShell
powershell -ExecutionPolicy Bypass -File scripts/build-wheel.ps1
```

Installs from generated wheel:

```bash
pipx install dist/wikimind-0.1.0-py3-none-any.whl
# or: pip install dist/wikimind-0.1.0-py3-none-any.whl
```

## 2) Ingest Sources

```bash
wikimind ingest .wiki/raw/article.md
wikimind ingest .wiki/raw/ --dry-run
wikimind ingest .wiki/raw/ --force
```

- Batch ingest prints summary: succeeded / skipped / failed.
- If any file fails, command exits non-zero.

## 3) Query the Wiki

```bash
wikimind query "What are the key arguments?"
wikimind query "Compare methodologies" --save
wikimind query "How does X relate to Y?" --save --top-k 15
```

- `--save` writes answer to `.wiki/vault/analyses/` and updates index/log.
- Output includes confidence, citations, and knowledge gaps.

## 4) Lint Wiki Health

```bash
wikimind lint
wikimind lint --fix
wikimind lint --semantic
```

- Structural lint: orphans, broken links, index desync, missing frontmatter.
- `--fix`: applies structural auto-fixes.
- `--semantic`: one LLM call; report-only findings (no auto-fix yet).

## 5) Inspect State

```bash
wikimind status
wikimind cost
```

- `status`: pages, ingested sources, unprocessed sources, last updated.
- `cost`: token/cost usage for current session.

## 6) MCP Server (usually automatic)

```bash
wikimind serve
wikimind serve --transport sse
```

- Claude Code starts this from `.mcp.json` in stdio mode.
- Exposed tools: `wiki_read_index`, `wiki_read_page`, `wiki_search`,
  `wiki_list_pages`, `wiki_write_page`, `wiki_update_index`,
  `wiki_append_log`, `wiki_status`.

## Config Snippet

```toml
[llm]
provider = "anthropic"  # anthropic | openai | ollama
model = "claude-sonnet-4-20250514"
api_key_env = "ANTHROPIC_API_KEY"  # OPENAI_API_KEY for openai; optional for ollama
# base_url = ""                    # optional override

[wiki]
required_frontmatter = ["title", "type", "tags", "created", "updated"]
retrieval_backend = "bm25"          # bm25 | index_keyword
```

- `anthropic` and `openai` need API keys via `api_key_env`.
- `ollama` works locally without API key by default.
- `bm25` is the default and recommended backend.

## Recommended Daily Loop

1. `wikimind ingest .wiki/raw/...`
2. `wikimind query "..." --save`
3. `wikimind lint --fix`
4. `wikimind lint --semantic`
5. `wikimind status`
