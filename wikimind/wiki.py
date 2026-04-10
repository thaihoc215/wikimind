"""WikiStore — all wiki file operations. No database, just filesystem."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path


class WikiStore:
    """All wiki file operations. No database — just filesystem."""

    def __init__(self, wiki_path: Path, raw_path: Path):
        self.wiki_path = wiki_path
        self.raw_path = raw_path
        self.meta_path = wiki_path.parent / ".wikimind"

    # ── Read ──────────────────────────────────────────────────────────────

    def _resolve_wiki_relative_path(self, relative_path: str) -> Path:
        """Resolve a wiki-relative path and prevent path traversal."""
        if not relative_path or not relative_path.strip():
            raise ValueError("Path must be a non-empty path relative to wiki/.")

        raw = Path(relative_path)
        if raw.is_absolute():
            raise ValueError(f"Path must be relative to wiki/: {relative_path}")

        wiki_root = self.wiki_path.resolve()
        full_path = (self.wiki_path / raw).resolve()

        try:
            full_path.relative_to(wiki_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes wiki root: {relative_path}") from exc

        return full_path

    def read_index(self) -> str:
        index_path = self.wiki_path / "index.md"
        if not index_path.exists():
            return "# Index\n"
        return index_path.read_text(encoding="utf-8")

    def read_page(self, relative_path: str) -> str:
        return self._resolve_wiki_relative_path(relative_path).read_text(
            encoding="utf-8"
        )

    def read_source(self, source_path: Path) -> str:
        return source_path.read_text(encoding="utf-8")

    def page_exists(self, relative_path: str) -> bool:
        try:
            return self._resolve_wiki_relative_path(relative_path).exists()
        except ValueError:
            return False

    def normalize_wikilink_target(self, target: str) -> str:
        """Normalize a wikilink target (strip alias, anchor, .md, separators)."""
        cleaned = target.strip()
        if not cleaned:
            return ""

        cleaned = cleaned.split("|", 1)[0].strip()
        cleaned = cleaned.split("#", 1)[0].strip()
        cleaned = cleaned.replace("\\", "/")
        if cleaned.startswith(("http://", "https://")):
            return ""
        if cleaned.endswith(".md"):
            cleaned = cleaned[:-3]
        while cleaned.startswith("./"):
            cleaned = cleaned[2:]

        return cleaned.strip("/")

    def build_link_registry(self) -> dict[str, str]:
        """Build registry for resolving wikilinks to canonical relative file paths."""
        registry: dict[str, str] = {}
        stems: dict[str, list[str]] = {}

        for page in self.all_pages():
            rel = str(page.relative_to(self.wiki_path)).replace("\\", "/")
            rel_no_ext = rel[:-3] if rel.endswith(".md") else rel
            registry[rel_no_ext] = rel
            stems.setdefault(page.stem, []).append(rel)

        # Bare-stem links are only valid when unique; avoids collisions.
        for stem, paths in stems.items():
            if len(paths) == 1:
                registry.setdefault(stem, paths[0])

        return registry

    def resolve_wikilink(
        self,
        target: str,
        *,
        registry: dict[str, str] | None = None,
    ) -> str | None:
        """Resolve wikilink target to canonical relative page path (e.g. entities/x.md)."""
        key = self.normalize_wikilink_target(target)
        if not key:
            return None

        link_registry = registry if registry is not None else self.build_link_registry()
        return link_registry.get(key)

    def find_relevant_pages(self, text: str, top_k: int = 5) -> dict[str, str]:
        """Find wiki pages relevant to given text via index keyword matching."""
        index = self.read_index()
        index_lines = index.strip().split("\n")

        # Extract keywords: words > 4 chars, lowercase
        words = set(w.lower() for w in re.findall(r"\b\w{4,}\b", text))

        # Score each index entry by keyword overlap
        scored: list[tuple[int, str]] = []
        for line in index_lines:
            if not line.strip().startswith("- [["):
                continue
            match = re.search(r"\[\[(.+?)\]\]", line)
            if not match:
                continue
            link_target = self.normalize_wikilink_target(match.group(1))
            if not link_target:
                continue

            line_words = set(w.lower() for w in re.findall(r"\b\w{4,}\b", line))
            target_words = set(
                w.lower()
                for w in re.findall(r"\b\w{4,}\b", link_target.replace("/", " "))
            )
            score = len(words & (line_words | target_words))
            if score > 0:
                scored.append((score, link_target))

        scored.sort(reverse=True)
        top_targets: list[str] = []
        seen: set[str] = set()
        for _, target in scored:
            if target in seen:
                continue
            seen.add(target)
            top_targets.append(target)
            if len(top_targets) >= top_k:
                break

        link_registry = self.build_link_registry()
        result: dict[str, str] = {}
        for target in top_targets:
            rel = self.resolve_wikilink(target, registry=link_registry)
            if not rel:
                continue
            path = self.wiki_path / rel
            if path.exists() and path.is_file():
                result[rel] = path.read_text(encoding="utf-8")

        return result

    # ── Write ─────────────────────────────────────────────────────────────

    def write_page(self, relative_path: str, content: str) -> None:
        """Write a wiki page. Creates parent directories if needed."""
        full_path = self._resolve_wiki_relative_path(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def update_index(
        self, entries_to_add: list[str], entries_to_remove: list[str]
    ) -> None:
        """Add/remove entries from index.md."""
        index_path = self.wiki_path / "index.md"
        text = (
            index_path.read_text(encoding="utf-8")
            if index_path.exists()
            else "# Index\n"
        )
        lines = text.split("\n")

        # Remove entries (exact line match after stripping)
        if entries_to_remove:
            remove_set = {e.strip() for e in entries_to_remove}
            lines = [l for l in lines if l.strip() not in remove_set]

        # Add new entries (avoid duplicates)
        existing = {l.strip() for l in lines}
        for entry in entries_to_add:
            if entry.strip() not in existing:
                lines.append(entry)
                existing.add(entry.strip())

        index_path.write_text("\n".join(lines), encoding="utf-8")

    def append_log(self, entry: str) -> None:
        """Append an entry to log.md."""
        log_path = self.wiki_path / "log.md"
        current = (
            log_path.read_text(encoding="utf-8")
            if log_path.exists()
            else "# Wiki Log\n"
        )
        log_path.write_text(current + "\n" + entry + "\n", encoding="utf-8")

    # ── Dedup ─────────────────────────────────────────────────────────────

    def _source_key(self, source_path: Path) -> str:
        """Normalize source path key for stable dedup tracking."""
        resolved = source_path.resolve()
        return os.path.normcase(os.path.normpath(str(resolved)))

    def _source_lookup_keys(self, source_path: Path) -> set[str]:
        """Return compatible keys for old/new sources.json formats."""
        keys = {
            self._source_key(source_path),
            str(source_path),
            source_path.as_posix(),
        }

        project_root = self.wiki_path.parent.resolve()
        resolved = source_path.resolve()
        try:
            rel = resolved.relative_to(project_root)
            keys.add(str(rel))
            keys.add(rel.as_posix())
        except ValueError:
            pass

        return keys

    def _get_source_record(self, sources: dict, source_path: Path) -> dict | None:
        for key in self._source_lookup_keys(source_path):
            record = sources.get(key)
            if record is not None:
                return record
        return None

    def is_already_ingested(self, source_path: Path) -> bool:
        sources = self._load_sources_json()
        try:
            content = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = source_path.read_bytes().decode("latin-1")
        current_hash = hashlib.sha256(content.encode()).hexdigest()
        stored = self._get_source_record(sources, source_path)
        return stored is not None and stored.get("hash") == current_hash

    def mark_ingested(self, source_path: Path) -> None:
        sources = self._load_sources_json()
        try:
            content = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = source_path.read_bytes().decode("latin-1")
        sources[self._source_key(source_path)] = {
            "hash": hashlib.sha256(content.encode()).hexdigest(),
            "ingested_at": datetime.now().isoformat(),
        }
        self._save_sources_json(sources)

    def _load_sources_json(self) -> dict:
        path = self.meta_path / "sources.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def _save_sources_json(self, data: dict) -> None:
        self.meta_path.mkdir(exist_ok=True)
        (self.meta_path / "sources.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    # ── Lint helpers ───────────────────────────────────────────────────────

    def all_pages(self) -> list[Path]:
        if not self.wiki_path.exists():
            return []
        return list(self.wiki_path.rglob("*.md"))

    def get_page_count(self) -> int:
        return len(self.all_pages())

    def get_source_count(self) -> int:
        return len(self._load_sources_json())

    def find_unprocessed_sources(self) -> list[Path]:
        sources = self._load_sources_json()
        unprocessed = []
        if not self.raw_path.exists():
            return []
        for raw_file in self.raw_path.rglob("*"):
            if (
                raw_file.is_file()
                and self._get_source_record(sources, raw_file) is None
            ):
                unprocessed.append(raw_file)
        return unprocessed

    def find_stale_sources(self) -> list[Path]:
        """Raw files that have changed content since they were last ingested."""
        sources = self._load_sources_json()
        stale = []
        if not self.raw_path.exists():
            return []
        for raw_file in self.raw_path.rglob("*"):
            if not raw_file.is_file():
                continue
            record = self._get_source_record(sources, raw_file)
            if record is None:
                continue  # Not ingested yet — unprocessed, not stale
            try:
                content = raw_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = raw_file.read_bytes().decode("latin-1")
            current_hash = hashlib.sha256(content.encode()).hexdigest()
            if current_hash != record.get("hash"):
                stale.append(raw_file)
        return stale

    def parse_all_wikilinks(self) -> dict[str, list[str]]:
        """Build link graph by page path with normalized wikilink targets."""
        graph: dict[str, list[str]] = {}
        for page in self.all_pages():
            content = page.read_text(encoding="utf-8")
            raw_links = re.findall(r"\[\[(.+?)\]\]", content)
            links = [
                normalized
                for normalized in (
                    self.normalize_wikilink_target(link) for link in raw_links
                )
                if normalized
            ]
            rel = str(page.relative_to(self.wiki_path)).replace("\\", "/")
            graph[rel] = links
        return graph

    def get_last_updated(self) -> str | None:
        """Return ISO timestamp of the most recently modified wiki page."""
        pages = self.all_pages()
        if not pages:
            return None
        latest = max(pages, key=lambda p: p.stat().st_mtime)
        return datetime.fromtimestamp(latest.stat().st_mtime).isoformat(
            timespec="seconds"
        )

    # ── Context assembly ───────────────────────────────────────────────────

    def build_ingest_context(
        self,
        source_content: str,
        relevant_pages: dict[str, str],
        max_chars: int = 150_000,
    ) -> str:
        """Assemble LLM context for ingest, truncating if needed."""
        index = self.read_index()
        parts = [
            f"## Source to ingest\n\n{source_content}",
            f"## Current wiki index\n\n{index}",
        ]
        remaining = max_chars - sum(len(p) for p in parts)
        for path, content in relevant_pages.items():
            chunk = f"## Existing page: {path}\n\n{content}"
            if len(chunk) > remaining:
                break
            parts.append(chunk)
            remaining -= len(chunk)

        return "\n\n---\n\n".join(parts)

    # ── Cost tracking ──────────────────────────────────────────────────────

    def record_cost(
        self,
        command: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Append a cost record to .wikimind/cost.json."""
        path = self.meta_path / "cost.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {
                "records": [],
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
            }
        data["records"].append(
            {
                "command": command,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6),
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
        )
        data["total_input_tokens"] = data.get("total_input_tokens", 0) + input_tokens
        data["total_output_tokens"] = (
            data.get("total_output_tokens", 0) + output_tokens
        )
        data["total_cost_usd"] = round(
            data.get("total_cost_usd", 0.0) + cost_usd, 6
        )
        self.meta_path.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def read_cost_history(self) -> dict:
        """Read cumulative cost history from .wikimind/cost.json."""
        path = self.meta_path / "cost.json"
        if not path.exists():
            return {
                "records": [],
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
            }
        return json.loads(path.read_text(encoding="utf-8"))

    def build_query_context(
        self,
        question: str,
        relevant_pages: dict[str, str],
        max_chars: int = 150_000,
    ) -> str:
        """Assemble LLM context for query, truncating if needed."""
        parts = [f"## Question\n\n{question}"]
        remaining = max_chars - len(parts[0])
        for path, content in relevant_pages.items():
            chunk = f"## Wiki page: {path}\n\n{content}"
            if len(chunk) > remaining:
                break
            parts.append(chunk)
            remaining -= len(chunk)

        return "\n\n---\n\n".join(parts)
