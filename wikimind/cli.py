"""WikiMind CLI — LLM-powered wiki that maintains itself."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from wikimind.config import ConfigError, load_config
from wikimind.llm import LLMClient, LLMError
from wikimind.wiki import WikiStore

app = typer.Typer(
    name="wikimind",
    help="LLM-powered wiki that maintains itself.",
    add_completion=False,
)
console = Console()

# Path to the bundled templates directory
TEMPLATES_DIR = Path(__file__).parent / "templates"


# ── init ──────────────────────────────────────────────────────────────────────


_WIKIMIND_START = "<!-- wikimind:start -->"
_WIKIMIND_END = "<!-- wikimind:end -->"


def _update_claude_md(dest: Path, new_section: str, force: bool) -> str:
    """Insert or replace the WikiMind section in an existing CLAUDE.md.

    Returns a short status string: 'created' | 'merged' | 'updated' | 'skipped'.
    """
    if not dest.exists():
        dest.write_text(new_section, encoding="utf-8")
        return "created"

    existing = dest.read_text(encoding="utf-8")

    # Case 1: markers present — replace between them regardless of --force
    if _WIKIMIND_START in existing and _WIKIMIND_END in existing:
        before = existing[: existing.index(_WIKIMIND_START)]
        after = existing[existing.index(_WIKIMIND_END) + len(_WIKIMIND_END) :]
        dest.write_text(before.rstrip() + "\n\n" + new_section + after.lstrip(), encoding="utf-8")
        return "updated"

    # Case 2: old format (no markers) — only replace if --force
    if "WikiMind Knowledge Base" in existing:
        if not force:
            return "skipped"
        # Find heading and replace from there to end of file
        idx = existing.index("# WikiMind Knowledge Base")
        # Step back to catch a preceding separator line (--- or blank lines)
        prefix = existing[:idx].rstrip("\n ")
        if prefix.endswith("---"):
            prefix = prefix[: -len("---")].rstrip()
        dest.write_text(prefix + "\n\n" + new_section, encoding="utf-8")
        return "updated"

    # Case 3: CLAUDE.md exists but has no WikiMind section — always append
    dest.write_text(existing.rstrip() + "\n\n---\n\n" + new_section, encoding="utf-8")
    return "merged"


@app.command()
def init(
    template: str = typer.Option(
        "general", help="Template: general | code | research | book"
    ),
    name: str = typer.Option(None, help="Project/topic name"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace the WikiMind section in CLAUDE.md with the new template. "
             "Your own content outside the <!-- wikimind:start/end --> markers is never touched.",
    ),
):
    """Initialize WikiMind in the current directory."""
    template_dir = TEMPLATES_DIR / template
    if not template_dir.exists():
        console.print(
            f"[red]Template '{template}' not found.[/red] "
            f"Available: {', '.join(d.name for d in TEMPLATES_DIR.iterdir() if d.is_dir())}"
        )
        raise typer.Exit(1)

    root = Path.cwd()
    project_name = name or root.name
    today = datetime.now().strftime("%Y-%m-%d")

    def render(text: str) -> str:
        return text.replace("{{PROJECT_NAME}}", project_name).replace("{{DATE}}", today)

    # Read paths from existing config first, then fall back to template config
    raw_rel_str = ".wiki/raw/"
    wiki_rel_str = ".wiki/vault/"

    config_path = root / "wikimind.toml"
    source_toml = ""
    if config_path.exists():
        source_toml = config_path.read_text(encoding="utf-8")
    else:
        template_config_path = template_dir / "wikimind.toml"
        if template_config_path.exists():
            source_toml = render(template_config_path.read_text(encoding="utf-8"))

    template_categories: list[str] = []
    if source_toml:
        try:
            parsed = tomllib.loads(source_toml)
            paths_cfg = parsed.get("paths", {})
            raw_rel_str = str(paths_cfg.get("raw", raw_rel_str))
            wiki_rel_str = str(paths_cfg.get("wiki", wiki_rel_str))
        except tomllib.TOMLDecodeError:
            console.print(
                "[yellow]Warning:[/yellow] Could not parse paths from wikimind.toml; "
                "using default hidden layout (.wiki/raw + .wiki/vault)."
            )

    # Always read categories from the *template* toml (not the existing project toml)
    template_toml_path = template_dir / "wikimind.toml"
    if template_toml_path.exists():
        try:
            tpl_parsed = tomllib.loads(template_toml_path.read_text(encoding="utf-8"))
            template_categories = list(tpl_parsed.get("wiki", {}).get("categories", {}).keys())
        except tomllib.TOMLDecodeError:
            pass

    if not template_categories:
        template_categories = ["entities", "concepts", "sources", "analyses"]

    raw_rel = Path(raw_rel_str)
    wiki_rel = Path(wiki_rel_str)
    raw_path = (root / raw_rel).resolve() if not raw_rel.is_absolute() else raw_rel
    wiki_path = (root / wiki_rel).resolve() if not wiki_rel.is_absolute() else wiki_rel

    def display_path(path: Path, as_dir: bool = False) -> str:
        try:
            rel = path.relative_to(root)
            text = str(rel).replace("\\", "/")
        except ValueError:
            text = str(path).replace("\\", "/")
        if as_dir and not text.endswith("/"):
            return text + "/"
        return text

    # Create directories from template categories (additive — never removes existing)
    raw_path.mkdir(parents=True, exist_ok=True)
    for category in template_categories:
        (wiki_path / category).mkdir(parents=True, exist_ok=True)
    (wiki_path.parent / ".wikimind").mkdir(parents=True, exist_ok=True)

    # Ensure wiki/log.md exists
    log_path = wiki_path / "log.md"
    if not log_path.exists():
        log_path.write_text("# Wiki Log\n", encoding="utf-8")
        console.print(f"  [green]Created[/green]   {display_path(log_path)}")

    # Copy template files
    for src in template_dir.iterdir():
        if src.name == "CLAUDE.md":
            dest = root / "CLAUDE.md"
            new_section = render(src.read_text(encoding="utf-8"))
            status = _update_claude_md(dest, new_section, force=force)
            if status == "created":
                console.print(f"  [green]Created[/green]   CLAUDE.md")
            elif status == "merged":
                console.print(f"  [yellow]Merged[/yellow]   CLAUDE.md (appended WikiMind section)")
            elif status == "updated":
                console.print(f"  [green]Updated[/green]   CLAUDE.md (WikiMind section replaced with '{template}' template)")
            else:  # skipped
                console.print(
                    f"  [dim]Skipped[/dim]  CLAUDE.md (already has WikiMind section — use --force to replace)"
                )
            continue

        if src.name in ("index.md", "overview.md"):
            dest = wiki_path / src.name
            if dest.exists():
                console.print(
                    f"  [dim]Skipped[/dim]  {display_path(dest)} (already exists)"
                )
                continue
        elif src.name == "wikimind.toml":
            dest = root / "wikimind.toml"
            if dest.exists():
                console.print(f"  [dim]Skipped[/dim]  wikimind.toml (already exists)")
                continue

        content = render(src.read_text(encoding="utf-8"))
        dest = root / src.name if src.name not in ("index.md", "overview.md") else wiki_path / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        console.print(f"  [green]Created[/green]   {display_path(dest)}")

    # Generate .mcp.json for Claude Code integration
    mcp_path = root / ".mcp.json"
    if not mcp_path.exists():
        # Use the wikimind script in the same env as the current Python
        venv_scripts = Path(sys.executable).parent
        wikimind_script = venv_scripts / "wikimind"
        if not wikimind_script.exists():
            wikimind_script = venv_scripts / "wikimind.exe"

        mcp_config = {
            "mcpServers": {
                "wikimind": {
                    "command": str(wikimind_script)
                    if wikimind_script.exists()
                    else "wikimind",
                    "args": ["serve"],
                    "cwd": str(root),
                }
            }
        }
        mcp_path.write_text(json.dumps(mcp_config, indent=2), encoding="utf-8")
        console.print(f"  [green]Created[/green]   .mcp.json (Claude Code MCP config)")
    else:
        console.print(f"  [dim]Skipped[/dim]  .mcp.json (already exists)")

    console.print()
    console.print(
        Panel(
            f"[bold green]WikiMind initialized[/bold green] - {project_name}\n\n"
            f"  [dim]{display_path(raw_path, as_dir=True)}[/dim] -- drop your source files here\n"
            f"  [dim]{display_path(wiki_path, as_dir=True)}[/dim] -- LLM-maintained wiki (open with Obsidian)\n"
            f"  [dim]CLAUDE.md[/dim]     -- LLM instructions (the 'schema')\n"
            f"  [dim]wikimind.toml[/dim] -- tool configuration\n"
            f"  [dim].mcp.json[/dim]     -- Claude Code MCP config (auto-generated)\n\n"
            f"Mode A (Claude Code): open this folder in Claude Code - it will use the wiki automatically\n"
            f"Mode B (CLI):         wikimind ingest {display_path(raw_path, as_dir=True)}your-file.md",
            title="Done",
        )
    )


# ── ingest ────────────────────────────────────────────────────────────────────


@app.command()
def ingest(
    path: str = typer.Argument(..., help="File or directory to ingest"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show plan without writing"),
    force: bool = typer.Option(False, "--force", help="Re-ingest even if unchanged"),
):
    """Ingest a raw source file (or directory of files) into the wiki."""
    from wikimind.operations.ingest import ingest as _ingest

    cfg = _load_config_or_exit()
    store = WikiStore(cfg.wiki_path, cfg.raw_path)
    llm = _make_llm(cfg)

    from wikimind.retrieval import RetrievalError, make_retriever

    try:
        retriever = make_retriever(store, backend=cfg.wiki.retrieval_backend, wiki_config=cfg.wiki, root=cfg.root)
    except RetrievalError as e:
        console.print(f"[red]Retrieval config error:[/red] {e}")
        raise typer.Exit(1)

    source = Path(path)
    if not source.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise typer.Exit(1)

    files = list(source.rglob("*")) if source.is_dir() else [source]
    files = [f for f in files if f.is_file()]

    if not files:
        console.print(f"[yellow]No files found in:[/yellow] {path}")
        raise typer.Exit(0)

    succeeded = 0
    skipped = 0
    failed = 0

    for f in files:
        console.print(f"Ingesting [bold]{f}[/bold]...")
        try:
            result = _ingest(
                f,
                store,
                llm,
                retriever=retriever,
                dry_run=dry_run,
                force=force,
            )
            if result.summary.startswith("Skipped"):
                skipped += 1
            else:
                succeeded += 1

            if dry_run:
                console.print(f"  [dim][DRY RUN][/dim] {result.summary}")
                console.print(
                    f"  Would create [green]{result.pages_created}[/green] pages, "
                    f"update [yellow]{result.pages_updated}[/yellow]"
                )
            else:
                console.print(
                    f"  [green]✓[/green] {result.summary} "
                    f"(+{result.pages_created} pages, ~{result.pages_updated} updated)"
                )
        except LLMError as e:
            failed += 1
            console.print(f"  [red]LLM error:[/red] {e}")
        except Exception as e:
            failed += 1
            console.print(f"  [red]Error:[/red] {e}")

    console.print(
        f"\n[bold]Ingest summary:[/bold] {len(files)} file(s) processed | "
        f"[green]{succeeded} succeeded[/green], "
        f"[yellow]{skipped} skipped[/yellow], "
        f"[red]{failed} failed[/red]"
    )
    _print_cost(llm, command="ingest", cfg=cfg)

    if cfg.wiki.retrieval_backend == "qmd" and not dry_run:
        qmd_bin = cfg.wiki.qmd_bin or "qmd"
        if shutil.which(qmd_bin):
            console.print("[dim]Refreshing qmd embeddings...[/dim]")
            try:
                subprocess.run(
                    [qmd_bin, "embed"],
                    cwd=str(cfg.root),
                    timeout=120,
                    check=False,
                )
                console.print("[green]qmd embeddings refreshed.[/green]")
            except subprocess.TimeoutExpired:
                console.print("[yellow]Warning: qmd embed timed out after 120s.[/yellow]")
            except Exception as e:
                console.print(f"[yellow]Warning: qmd embed failed: {e}[/yellow]")

    if failed > 0:
        raise typer.Exit(1)


# ── query ─────────────────────────────────────────────────────────────────────


@app.command()
def query(
    question: str = typer.Argument(..., help="Question to ask the wiki"),
    save: bool = typer.Option(False, "--save", help="Save answer as wiki page"),
    top_k: int = typer.Option(10, "--top-k", help="Number of wiki pages to consider"),
):
    """Ask a question against the wiki."""
    from wikimind.operations.query import query as _query

    cfg = _load_config_or_exit()
    store = WikiStore(cfg.wiki_path, cfg.raw_path)
    llm = _make_llm(cfg)

    from wikimind.retrieval import RetrievalError, make_retriever

    try:
        retriever = make_retriever(store, backend=cfg.wiki.retrieval_backend, wiki_config=cfg.wiki, root=cfg.root)
    except RetrievalError as e:
        console.print(f"[red]Retrieval config error:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"Searching wiki for: [bold]{question}[/bold]\n")

    try:
        result = _query(
            question,
            store,
            llm,
            retriever=retriever,
            save=save,
            top_k=top_k,
        )
    except LLMError as e:
        console.print(f"[red]LLM error:[/red] {e}")
        raise typer.Exit(1)

    # Print confidence badge
    conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(
        result.confidence, "white"
    )
    console.print(
        f"[{conf_color}]Confidence: {result.confidence}[/{conf_color}]  "
        f"Citations: {len(result.citations)}"
    )
    console.print()
    console.print(result.answer)

    if result.knowledge_gaps:
        console.print("\n[dim]Knowledge gaps:[/dim]")
        for gap in result.knowledge_gaps:
            console.print(f"  [dim]• {gap}[/dim]")

    if result.saved_path:
        console.print(f"\n[green]Saved to:[/green] wiki/{result.saved_path}")

    _print_cost(llm, command="query", cfg=cfg)


# ── lint ──────────────────────────────────────────────────────────────────────


@app.command()
def lint(
    fix: bool = typer.Option(False, "--fix", help="Auto-fix issues where possible"),
    semantic: bool = typer.Option(
        False,
        "--semantic",
        help="Run one LLM semantic pass (contradictions, missing topic pages, source suggestions)",
    ),
):
    """Health-check the wiki for structural issues, with optional semantic pass."""
    from wikimind.operations.lint import fix as _fix
    from wikimind.operations.lint import lint as _lint

    cfg = _load_config_or_exit()
    store = WikiStore(cfg.wiki_path, cfg.raw_path)

    llm = None
    if semantic:
        llm = _make_llm(cfg)

    try:
        report = _lint(
            store,
            required_frontmatter=cfg.wiki.required_frontmatter,
            llm=llm,
            semantic=semantic,
        )
    except LLMError as e:
        console.print(f"[red]LLM error:[/red] {e}")
        raise typer.Exit(1)

    if not report.has_issues:
        if semantic:
            console.print(
                "[green]✓ Wiki is healthy — no structural or semantic issues found.[/green]"
            )
            if llm is not None:
                _print_cost(llm)
        else:
            console.print(
                "[green]✓ Wiki is healthy — no structural issues found.[/green]"
            )
        return

    console.print(
        f"[yellow]Found {report.issue_count()} issue(s)/finding(s):[/yellow]\n"
    )

    if report.orphan_pages:
        console.print(
            f"[bold]Orphan pages[/bold] ({len(report.orphan_pages)} — no inbound links):"
        )
        for p in report.orphan_pages:
            console.print(f"  • {p}")

    if report.broken_links:
        console.print(f"\n[bold]Broken links[/bold] ({len(report.broken_links)}):")
        for page, link in report.broken_links:
            console.print(f"  • [[{link}]] in {page}")

    if report.index_missing:
        console.print(f"\n[bold]Not in index[/bold] ({len(report.index_missing)}):")
        for p in report.index_missing:
            console.print(f"  • {p}")

    if report.stale_sources:
        console.print(
            f"\n[bold]Stale sources[/bold] ({len(report.stale_sources)} — changed since last ingest):"
        )
        for src in report.stale_sources:
            console.print(f"  • {src}")
        console.print(
            f"  [dim]Run 'wikimind ingest <file>' to re-ingest.[/dim]"
        )

    if report.missing_frontmatter:
        console.print(
            f"\n[bold]Missing frontmatter[/bold] ({len(report.missing_frontmatter)}):"
        )
        for page, fields in report.missing_frontmatter:
            console.print(f"  • {page}: missing {', '.join(fields)}")

    if report.semantic_contradictions:
        console.print(
            f"\n[bold]Semantic contradictions[/bold] ({len(report.semantic_contradictions)}):"
        )
        for pages, description in report.semantic_contradictions:
            if pages:
                console.print(
                    f"  • {description} [dim](pages: {', '.join(pages)})[/dim]"
                )
            else:
                console.print(f"  • {description}")

    if report.semantic_missing_pages:
        console.print(
            f"\n[bold]Suggested missing topic pages[/bold] ({len(report.semantic_missing_pages)}):"
        )
        for topic in report.semantic_missing_pages:
            console.print(f"  • {topic}")

    if report.semantic_suggested_sources:
        console.print(
            f"\n[bold]Suggested new sources[/bold] ({len(report.semantic_suggested_sources)}):"
        )
        for src in report.semantic_suggested_sources:
            console.print(f"  • {src}")

    if fix:
        console.print()
        fixed = _fix(report, store)
        console.print(f"[green]✓ Applied {fixed} auto-fix(es).[/green]")
        if semantic:
            console.print(
                "[dim]Note: semantic findings are report-only (no auto-fix yet).[/dim]"
            )

    if semantic and llm is not None:
        _print_cost(llm, command="lint --semantic", cfg=cfg)


# ── status ────────────────────────────────────────────────────────────────────


@app.command()
def status():
    """Show wiki statistics."""
    cfg = _load_config_or_exit()
    store = WikiStore(cfg.wiki_path, cfg.raw_path)

    table = Table(title=f"WikiMind — {cfg.project.name}", show_header=False)
    table.add_column("Key", style="dim")
    table.add_column("Value", style="bold")

    table.add_row("Wiki pages", str(store.get_page_count()))
    table.add_row("Sources ingested", str(store.get_source_count()))
    table.add_row("Unprocessed sources", str(len(store.find_unprocessed_sources())))
    table.add_row("Last updated", store.get_last_updated() or "—")
    table.add_row("Wiki path", str(cfg.wiki_path))
    table.add_row("Raw path", str(cfg.raw_path))
    table.add_row("Model", cfg.llm.model)

    console.print(table)


# ── cost ──────────────────────────────────────────────────────────────────────


@app.command()
def cost(
    last: int = typer.Option(10, "--last", help="Show last N command records"),
):
    """Show cumulative LLM token usage and per-command history."""
    cfg = _load_config_or_exit()
    store = WikiStore(cfg.wiki_path, cfg.raw_path)
    history = store.read_cost_history()

    total_in = history.get("total_input_tokens", 0)
    total_out = history.get("total_output_tokens", 0)
    total_cost = history.get("total_cost_usd", 0.0)

    if total_in == 0 and total_out == 0:
        console.print(
            "[dim]No cost history yet. Run ingest/query/lint commands to accumulate usage.[/dim]"
        )
        return

    summary_table = Table(title="LLM Cost — All Time", show_header=False)
    summary_table.add_column("Key", style="dim")
    summary_table.add_column("Value", style="bold")
    summary_table.add_row("Total input tokens", f"{total_in:,}")
    summary_table.add_row("Total output tokens", f"{total_out:,}")
    summary_table.add_row("Total tokens", f"{total_in + total_out:,}")
    summary_table.add_row("Estimated cost", f"${total_cost:.4f}")
    if cfg.llm.max_budget_usd > 0:
        pct = (total_cost / cfg.llm.max_budget_usd) * 100
        summary_table.add_row(
            "Budget used",
            f"${total_cost:.4f} / ${cfg.llm.max_budget_usd:.4f} ({pct:.1f}%)",
        )
    console.print(summary_table)

    records = history.get("records", [])
    if records:
        recent = records[-last:]
        hist_table = Table(title=f"Last {len(recent)} command(s)", show_header=True)
        hist_table.add_column("Time", style="dim")
        hist_table.add_column("Command")
        hist_table.add_column("In tokens", justify="right")
        hist_table.add_column("Out tokens", justify="right")
        hist_table.add_column("Cost", justify="right")
        for rec in recent:
            hist_table.add_row(
                rec.get("timestamp", "")[:19],
                rec.get("command", ""),
                f"{rec.get('input_tokens', 0):,}",
                f"{rec.get('output_tokens', 0):,}",
                f"${rec.get('cost_usd', 0.0):.4f}",
            )
        console.print(hist_table)


# ── watch ─────────────────────────────────────────────────────────────────────


@app.command()
def watch(
    interval: float = typer.Option(
        5.0, "--interval", help="Poll interval in seconds"
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-ingest even if file is unchanged"
    ),
):
    """Watch raw/ for new or changed files and auto-ingest them."""
    import time

    from wikimind.operations.ingest import ingest as _ingest
    from wikimind.retrieval import RetrievalError, make_retriever

    cfg = _load_config_or_exit()
    store = WikiStore(cfg.wiki_path, cfg.raw_path)

    try:
        retriever = make_retriever(store, backend=cfg.wiki.retrieval_backend, wiki_config=cfg.wiki, root=cfg.root)
    except RetrievalError as e:
        console.print(f"[red]Retrieval config error:[/red] {e}")
        raise typer.Exit(1)

    console.print(
        f"Watching [bold]{cfg.raw_path}[/bold] every {interval:.0f}s — "
        f"[dim]Ctrl+C to stop[/dim]"
    )

    try:
        while True:
            unprocessed = store.find_unprocessed_sources()
            stale = store.find_stale_sources()
            # Combine, deduplicate, preserve order (unprocessed first)
            seen: set[str] = set()
            to_process: list = []
            for f in unprocessed + stale:
                key = str(f)
                if key not in seen:
                    seen.add(key)
                    to_process.append(f)

            if to_process:
                llm = _make_llm(cfg)
                for f in to_process:
                    label = "new" if f in unprocessed else "changed"
                    console.print(f"  Auto-ingesting ([dim]{label}[/dim]): [bold]{f.name}[/bold]")
                    try:
                        result = _ingest(
                            f, store, llm, retriever=retriever, force=force
                        )
                        console.print(f"    [green]✓[/green] {result.summary}")
                    except LLMError as e:
                        console.print(f"    [red]LLM error:[/red] {e}")
                    except Exception as e:
                        console.print(f"    [red]Error:[/red] {e}")
                _print_cost(llm, command="watch", cfg=cfg)

            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Watch stopped.[/dim]")


# ── serve ─────────────────────────────────────────────────────────────────────


@app.command()
def serve(
    transport: str = typer.Option(
        "stdio",
        help="Transport: stdio (for Claude Code) | sse (HTTP server-sent events)",
    ),
):
    """Start the WikiMind MCP server for Claude Code integration.

    In Claude Code, this starts automatically via .mcp.json.
    You do NOT need ANTHROPIC_API_KEY for this mode — Claude Code is the LLM.

    Tools exposed to Claude Code:
      wiki_read_index     Read the master index
      wiki_read_page      Read a specific page
      wiki_search         Find relevant pages by keyword
      wiki_list_pages     List all wiki pages
      wiki_write_page     Create or update a wiki page
      wiki_update_index   Add/remove index entries
      wiki_append_log     Append to the wiki log
      wiki_status         Get wiki statistics
    """
    from wikimind.server import run_server

    run_server(root=Path.cwd(), transport=transport)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_config_or_exit():
    try:
        return load_config()
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1)


def _make_llm(cfg) -> LLMClient:
    try:
        return LLMClient(
            provider=cfg.llm.provider,
            model=cfg.llm.model,
            api_key=cfg.llm.api_key,
            base_url=cfg.llm.base_url,
            max_tokens=cfg.llm.max_tokens_per_call,
            max_budget_usd=cfg.llm.max_budget_usd,
        )
    except (ConfigError, LLMError) as e:
        console.print(f"[red]LLM config error:[/red] {e}")
        raise typer.Exit(1)


def _print_cost(llm: LLMClient, command: str = "", cfg=None) -> None:
    summary = llm.token_summary()
    if summary["total_tokens"] > 0:
        console.print(
            f"\n[dim]Tokens: {summary['input_tokens']:,} in + "
            f"{summary['output_tokens']:,} out = "
            f"{summary['total_tokens']:,} total "
            f"(~${summary['cost_usd']:.4f})[/dim]"
        )
        if cfg is not None and command:
            try:
                store = WikiStore(cfg.wiki_path, cfg.raw_path)
                store.record_cost(
                    command=command,
                    input_tokens=summary["input_tokens"],
                    output_tokens=summary["output_tokens"],
                    cost_usd=summary["cost_usd"],
                )
            except Exception:
                pass  # Cost recording is best-effort; never crash on it


if __name__ == "__main__":
    app()
