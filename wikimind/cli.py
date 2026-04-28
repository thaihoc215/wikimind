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
        dest.write_text(
            before.rstrip() + "\n\n" + new_section + after.lstrip(), encoding="utf-8"
        )
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
            template_categories = list(
                tpl_parsed.get("wiki", {}).get("categories", {}).keys()
            )
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
                console.print(
                    f"  [yellow]Merged[/yellow]   CLAUDE.md (appended WikiMind section)"
                )
            elif status == "updated":
                console.print(
                    f"  [green]Updated[/green]   CLAUDE.md (WikiMind section replaced with '{template}' template)"
                )
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
        dest = (
            root / src.name
            if src.name not in ("index.md", "overview.md")
            else wiki_path / src.name
        )
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

    # Update AGENTS.md and copilot-instructions.md if they exist
    # (extract WikiMind section from the rendered template)
    wikimind_section = None
    for src in template_dir.iterdir():
        if src.name == "CLAUDE.md":
            wikimind_section = render(src.read_text(encoding="utf-8"))
            break

    if wikimind_section:
        # AGENTS.md — skip if doesn't exist
        agents_md = root / "AGENTS.md"
        if agents_md.exists():
            status = _update_claude_md(agents_md, wikimind_section, force=force)
            if status == "updated":
                console.print(f"  [green]Updated[/green]   AGENTS.md (WikiMind section replaced)")
            elif status == "merged":
                console.print("  [yellow]Merged[/yellow]   AGENTS.md (WikiMind section appended)")
            elif status == "created":
                console.print("  [green]Created[/green]   AGENTS.md")
        else:
            console.print(f"  [dim]Skipped[/dim]  AGENTS.md (does not exist)")

        # .github/copilot-instructions.md — skip if doesn't exist
        github_dir = root / ".github"
        copilot_instructions = github_dir / "copilot-instructions.md" if github_dir.exists() else None
        if copilot_instructions and copilot_instructions.exists():
            status = _update_claude_md(copilot_instructions, wikimind_section, force=force)
            if status == "updated":
                console.print(f"  [green]Updated[/green]   .github/copilot-instructions.md (WikiMind section replaced)")
            elif status == "merged":
                console.print("  [yellow]Merged[/yellow]   .github/copilot-instructions.md (WikiMind section appended)")
            elif status == "created":
                console.print("  [green]Created[/green]   .github/copilot-instructions.md")
        else:
            console.print(f"  [dim]Skipped[/dim]  .github/copilot-instructions.md (does not exist)")

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


# ── generate ──────────────────────────────────────────────────────────────────


def _resolve_wikimind_exe(root: Path) -> str:
    """Resolve the wikimind executable path.

    Preference order:
    1. ``command`` recorded in .mcp.json (already resolved by ``wikimind init``)
    2. Executable in the current virtual-environment's scripts/bin directory
    3. Bare ``wikimind`` (assumes it is on PATH)
    """
    mcp_json = root / ".mcp.json"
    if mcp_json.exists():
        try:
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            cmd = data.get("mcpServers", {}).get("wikimind", {}).get("command", "")
            if cmd and isinstance(cmd, str) and Path(cmd).exists():
                return cmd
        except (json.JSONDecodeError, TypeError):
            pass

    venv_scripts = Path(sys.executable).parent
    wikimind_exe = venv_scripts / "wikimind.exe"
    wikimind_bin = venv_scripts / "wikimind"
    if wikimind_exe.exists():
        return str(wikimind_exe)
    if wikimind_bin.exists():
        return str(wikimind_bin)
    return "wikimind"


def _generate_opencode(root: Path) -> None:
    """Generate AGENTS.md and opencode.json for OpenCode integration."""
    claude_md = root / "CLAUDE.md"
    agents_md = root / "AGENTS.md"

    if not claude_md.exists():
        console.print(
            "[red]CLAUDE.md not found.[/red] Run 'wikimind init' first to create it."
        )
        raise typer.Exit(1)

    content = claude_md.read_text(encoding="utf-8")

    # Extract only the wikimind section if markers are present; otherwise use full content
    if _WIKIMIND_START in content and _WIKIMIND_END in content:
        start = content.index(_WIKIMIND_START)
        end = content.index(_WIKIMIND_END) + len(_WIKIMIND_END)
        wikimind_section = content[start:end]
    else:
        wikimind_section = content.strip()

    # Create or update AGENTS.md — always replace wikimind section (force=True)
    status = _update_claude_md(agents_md, wikimind_section, force=True)
    if status == "created":
        console.print("  [green]Created[/green]   AGENTS.md")
    elif status == "merged":
        console.print(
            "  [yellow]Merged[/yellow]    AGENTS.md (WikiMind section appended)"
        )
    elif status == "updated":
        console.print(
            "  [green]Updated[/green]   AGENTS.md (WikiMind section replaced)"
        )

    # Create or update opencode.json with the wikimind MCP entry
    _generate_opencode_json(root)


def _generate_opencode_json(root: Path) -> None:
    """Create or update opencode.json with the wikimind MCP server entry."""
    opencode_json = root / "opencode.json"
    exe = _resolve_wikimind_exe(root)

    wikimind_entry: dict = {
        "type": "local",
        "command": [exe, "serve"],
        "enabled": True,
    }

    if opencode_json.exists():
        try:
            existing = json.loads(opencode_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            console.print(
                "[yellow]Warning:[/yellow] opencode.json is not valid JSON — overwriting."
            )
            existing = {}

        mcp = existing.get("mcp", {})
        action = "Updated" if "wikimind" in mcp else "Added"
        mcp["wikimind"] = wikimind_entry
        existing["mcp"] = mcp
        # Ensure $schema is present without disturbing the rest of the object
        if "$schema" not in existing:
            existing = {"$schema": "https://opencode.ai/config.json", **existing}
        opencode_json.write_text(json.dumps(existing, indent=4), encoding="utf-8")
        console.print(
            f"  [green]{action}[/green]    opencode.json (wikimind MCP entry)"
        )
    else:
        config = {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                "wikimind": wikimind_entry,
            },
        }
        opencode_json.write_text(json.dumps(config, indent=4), encoding="utf-8")
        console.print("  [green]Created[/green]   opencode.json")


def _generate_vscode(root: Path) -> None:
    """Generate or update .vscode/mcp.json and .github/copilot-instructions.md for VSCode Copilot."""
    vscode_dir = root / ".vscode"
    mcp_path = vscode_dir / "mcp.json"

    command = _resolve_wikimind_exe(root)
    wikimind_server = {
        "command": command,
        "args": ["serve"],
        "cwd": str(root),
    }

    vscode_dir.mkdir(exist_ok=True)

    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            console.print(
                "[yellow]Warning:[/yellow] .vscode/mcp.json is not valid JSON — overwriting."
            )
            existing = {}
        servers = existing.get("servers", {})
        action = "Updated" if "wikimind" in servers else "Added"
        servers["wikimind"] = wikimind_server
        existing["servers"] = servers
        mcp_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        console.print(
            f"  [green]{action}[/green]    .vscode/mcp.json (wikimind server entry)"
        )
    else:
        config = {"servers": {"wikimind": wikimind_server}}
        mcp_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        console.print("  [green]Created[/green]   .vscode/mcp.json")

    _generate_copilot_instructions(root)


def _generate_copilot_instructions(root: Path) -> None:
    """Generate or update .github/copilot-instructions.md for GitHub Copilot."""
    github_dir = root / ".github"
    copilot_instructions_path = github_dir / "copilot-instructions.md"
    claude_md_path = root / "CLAUDE.md"

    wiki_section = _get_wikimind_section_from_claude(claude_md_path)

    if copilot_instructions_path.exists():
        existing = copilot_instructions_path.read_text(encoding="utf-8")
        if "<!-- wikimind:start -->" in existing and "<!-- wikimind:end -->" in existing:
            console.print("  [dim]Skipped[/dim]   .github/copilot-instructions.md (wiki section already present)")
            return

        if wiki_section in existing:
            console.print("  [dim]Skipped[/dim]   .github/copilot-instructions.md (wiki content already merged)")
            return

        copilot_instructions_path.write_text(existing.rstrip() + "\n\n---\n\n" + wiki_section, encoding="utf-8")
        console.print("  [green]Updated[/green]  .github/copilot-instructions.md (wiki section appended)")
    else:
        github_dir.mkdir(exist_ok=True)
        if claude_md_path.exists():
            shutil.copy2(claude_md_path, copilot_instructions_path)
            console.print("  [green]Copied[/green]    CLAUDE.md -> .github/copilot-instructions.md")
        else:
            copilot_instructions_path.write_text(wiki_section, encoding="utf-8")
            console.print("  [green]Created[/green]   .github/copilot-instructions.md")


def _get_wikimind_section_from_claude(claude_md_path: Path) -> str:
    """Extract the WikiMind section from CLAUDE.md."""
    if not claude_md_path.exists():
        return _default_wikimind_section()

    existing = claude_md_path.read_text(encoding="utf-8")
    if _WIKIMIND_START in existing and _WIKIMIND_END in existing:
        start_idx = existing.index(_WIKIMIND_START)
        end_idx = existing.index(_WIKIMIND_END) + len(_WIKIMIND_END)
        return existing[start_idx:end_idx]

    if "# WikiMind Knowledge Base" in existing:
        return _default_wikimind_section()

    return _default_wikimind_section()


def _default_wikimind_section() -> str:
    """Return the default WikiMind section for Copilot instructions."""
    return f"""<!-- wikimind:start -->
# WikiMind Knowledge Base

This project uses a persistent wiki in `.wiki/vault/` maintained by LLMs.

## Structure

- `.wiki/vault/index.md` — Master catalog of all wiki pages. **READ THIS FIRST.**
- `.wiki/vault/log.md` — Chronological record of all wiki changes.
- `.wiki/vault/overview.md` — High-level codebase overview.
- `.wiki/vault/modules/` — Source files, classes, functions, components.
- `.wiki/vault/apis/` — Endpoints, interfaces, contracts, schemas.
- `.wiki/vault/patterns/` — Design patterns, architectural decisions, conventions.
- `.wiki/vault/decisions/` — Architecture Decision Records (ADRs).
- `.wiki/vault/sources/` — One summary page per raw source in `.wiki/raw/`.
- `.wiki/vault/analyses/` — Saved query answers, comparisons, syntheses.
- `.wiki/raw/` — Raw source documents. **Immutable — never modify these.**

## When working on this project

Follow this default order (wiki-first):

1. **Before deep-diving into source files or broad code search**, use `wiki_search` first.
2. **If relevant wiki pages exist**, read them with `wiki_read_page` and answer from wiki context.
3. **Only read raw/source files when needed** (wiki is missing details, outdated, or exact code is required).
4. **After answering questions or making discoveries**, save durable outputs with
   `wikimind query --save "your question"` (or write an analysis page via MCP tools).
5. **When answering**, cite wiki pages with [[wikilinks]] whenever possible.
6. **After significant code/source changes**, update affected wiki pages (`wiki_write_page`),
   update index if needed (`wiki_update_index`), and append log (`wiki_append_log`).
   Log entry must be a single bullet line: `- [YYYY-MM-DD] action | one-line summary`
7. **After ingesting new sources**, run `wikimind lint` (and `wikimind lint --semantic` when needed).
8. If paths are customized in `wikimind.toml`, always follow configured paths.
9. Never modify raw source documents in `.wiki/raw/`; treat them as immutable.

## Wiki page format

Every wiki page must have YAML frontmatter:

```yaml
---
title: Page Title
type: module | api | pattern | decision | source | analysis | overview
tags: [tag1, tag2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [sources/source-name]
---
```

Use [[wikilinks]] to cross-reference between pages. When new information
contradicts existing content, note the contradiction explicitly rather than
silently overwriting.

## CLI commands

```bash
wikimind ingest .wiki/raw/file.md    # Process a source into wiki pages
wikimind query "question"            # Ask the wiki a question
wikimind query --save "question"     # Ask and save the answer as a wiki page
wikimind lint                        # Health-check the wiki
wikimind lint --fix                  # Auto-fix wiki issues
wikimind lint --semantic             # Semantic check (contradictions, gaps, source ideas)
```
<!-- wikimind:end -->"""


@app.command()
def generate(
    tool: str = typer.Option(
        ...,
        "--tool",
        help="Tool to generate config for: opencode | vscode",
    ),
):
    """Generate tool-specific configuration files for WikiMind integration.

    \b
    --tool opencode   Create/update AGENTS.md + opencode.json (MCP config for OpenCode)
    --tool vscode     Create/update .vscode/mcp.json for VSCode Copilot MCP
    """
    root = Path.cwd()

    if tool == "opencode":
        _generate_opencode(root)
    elif tool == "vscode":
        _generate_vscode(root)
    else:
        console.print(f"[red]Unknown tool:[/red] '{tool}'. Available: opencode, vscode")
        raise typer.Exit(1)


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
        retriever = make_retriever(
            store,
            backend=cfg.wiki.retrieval_backend,
            wiki_config=cfg.wiki,
            root=cfg.root,
        )
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
                console.print(
                    "[yellow]Warning: qmd embed timed out after 120s.[/yellow]"
                )
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
        retriever = make_retriever(
            store,
            backend=cfg.wiki.retrieval_backend,
            wiki_config=cfg.wiki,
            root=cfg.root,
        )
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
        console.print(f"  [dim]Run 'wikimind ingest <file>' to re-ingest.[/dim]")

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
    interval: float = typer.Option(5.0, "--interval", help="Poll interval in seconds"),
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
        retriever = make_retriever(
            store,
            backend=cfg.wiki.retrieval_backend,
            wiki_config=cfg.wiki,
            root=cfg.root,
        )
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
                    console.print(
                        f"  Auto-ingesting ([dim]{label}[/dim]): [bold]{f.name}[/bold]"
                    )
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
