"""Retrieval abstraction boundary for selecting wiki context pages."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import warnings
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from wikimind.wiki import WikiStore

if TYPE_CHECKING:
    from wikimind.config import WikiConfig


class RetrievalError(ValueError):
    """Raised when retrieval backend configuration is invalid."""


class Retriever(Protocol):
    """Interface for context retrieval backends."""

    def retrieve(self, query: str, top_k: int) -> dict[str, str]:
        """Return relevant wiki pages keyed by relative path."""


class KeywordIndexRetriever:
    """Current MVP retriever: keyword overlap against index.md entries."""

    name = "index_keyword"

    def __init__(self, store: WikiStore):
        self.store = store

    def retrieve(self, query: str, top_k: int) -> dict[str, str]:
        return self.store.find_relevant_pages(query, top_k=top_k)


class BM25Retriever:
    """Okapi BM25 lexical retriever over wiki markdown pages."""

    name = "bm25"

    def __init__(self, store: WikiStore, k1: float = 1.5, b: float = 0.75):
        self.store = store
        self.k1 = k1
        self.b = b

    def retrieve(self, query: str, top_k: int) -> dict[str, str]:
        if top_k <= 0:
            return {}

        query_terms = _tokenize(query)
        if not query_terms:
            return {}

        corpus = self._build_corpus()
        if not corpus:
            return {}

        n_docs = len(corpus)
        avg_doc_len = sum(doc_len for _, _, doc_len, _ in corpus) / n_docs
        doc_freq = self._compute_document_frequencies(corpus)

        scored: list[tuple[float, str, str]] = []
        query_unique = set(query_terms)
        for rel_path, tf, doc_len, content in corpus:
            score = 0.0
            for term in query_unique:
                term_tf = tf.get(term, 0)
                if term_tf <= 0:
                    continue
                df = doc_freq.get(term, 0)
                if df <= 0:
                    continue

                idf = math.log(1.0 + ((n_docs - df + 0.5) / (df + 0.5)))
                norm = self.k1 * (1.0 - self.b + self.b * (doc_len / avg_doc_len))
                score += idf * ((term_tf * (self.k1 + 1.0)) / (term_tf + norm))

            if score > 0:
                scored.append((score, rel_path, content))

        scored.sort(key=lambda item: (-item[0], item[1]))
        top = scored[:top_k]
        return {rel_path: content for _, rel_path, content in top}

    def _build_corpus(self) -> list[tuple[str, Counter[str], int, str]]:
        corpus: list[tuple[str, Counter[str], int, str]] = []
        for page in self.store.all_pages():
            rel_path = str(page.relative_to(self.store.wiki_path)).replace("\\", "/")
            if rel_path in {"index.md", "log.md"}:
                continue

            content = page.read_text(encoding="utf-8", errors="replace")
            # Include path tokens to support explicit path/page-name queries.
            indexed_text = f"{rel_path}\n{content}"
            terms = _tokenize(indexed_text)
            if not terms:
                continue

            tf = Counter(terms)
            corpus.append((rel_path, tf, len(terms), content))

        return corpus

    @staticmethod
    def _compute_document_frequencies(
        corpus: list[tuple[str, Counter[str], int, str]],
    ) -> Counter[str]:
        df: Counter[str] = Counter()
        for _, tf, _, _ in corpus:
            for term in tf.keys():
                df[term] += 1
        return df


class QmdRetriever:
    """Retriever that delegates to the qmd CLI for hybrid/semantic search.

    Supports three search modes:
      - "search"  : BM25 lexical search (qmd's own BM25 implementation)
      - "vsearch" : Vector/semantic search via local GGUF embedding model (default)
      - "query"   : Full hybrid: BM25 + vector + local LLM re-ranking

    Falls back gracefully to empty results if qmd times out or exits with error.
    Use make_retriever() for automatic BM25 fallback when qmd is not installed.
    """

    name = "qmd"
    VALID_MODES = {"search", "vsearch", "query"}

    def __init__(
        self,
        store: WikiStore,
        mode: str = "vsearch",
        qmd_bin: str = "qmd",
        root: Path | None = None,
    ):
        if mode not in self.VALID_MODES:
            raise RetrievalError(
                f"Invalid qmd_mode: {mode!r}. "
                f"Valid modes: {', '.join(sorted(self.VALID_MODES))}"
            )
        self.store = store
        self.mode = mode
        self.qmd_bin = qmd_bin
        self.root = root or store.wiki_path.parent
        self._cmd_prefix: list[str] | None = None  # lazily resolved

    def _build_cmd_prefix(self) -> list[str]:
        """Resolve the command prefix needed to run qmd.

        On Windows, npm-installed packages create .CMD wrappers that invoke
        the real script via /bin/sh — which only works inside Git Bash, not
        from a Python subprocess via cmd.exe. We detect this and run the
        underlying shell script directly through Git's sh.exe instead.
        """
        resolved = shutil.which(self.qmd_bin)
        if (
            sys.platform == "win32"
            and resolved
            and resolved.upper().endswith(".CMD")
        ):
            sh_exe = self._find_git_sh(resolved)
            script = Path(resolved).parent / "node_modules" / "@tobilu" / "qmd" / "bin" / "qmd"
            if sh_exe and script.exists():
                return [sh_exe, str(script)]
        return [resolved or self.qmd_bin]

    @staticmethod
    def _find_git_sh(cmd_path: str) -> str | None:
        """Find sh.exe from the Git for Windows installation."""
        git = shutil.which("git")
        if not git:
            return None
        for parent in Path(git).resolve().parents:
            sh = parent / "usr" / "bin" / "sh.exe"
            if sh.exists():
                return str(sh)
        return None

    def retrieve(self, query: str, top_k: int) -> dict[str, str]:
        if top_k <= 0 or not query.strip():
            return {}

        if self._cmd_prefix is None:
            self._cmd_prefix = self._build_cmd_prefix()

        try:
            result = subprocess.run(
                self._cmd_prefix + [self.mode, query, "--json"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=60,
                cwd=str(self.root),
            )
        except FileNotFoundError:
            warnings.warn(
                f"qmd binary not found at {self.qmd_bin!r}. Returning empty results.",
                stacklevel=2,
            )
            return {}
        except subprocess.TimeoutExpired:
            warnings.warn("qmd search timed out after 60s.", stacklevel=2)
            return {}

        if result.returncode != 0:
            return {}

        try:
            items = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}

        pages: dict[str, str] = {}
        for item in items[:top_k]:
            # qmd --json returns "file" (qmd://collection/rel_path) not "path"
            file_uri = item.get("file", "") or item.get("path", "")
            if not file_uri:
                continue

            rel_path = self._parse_file_uri(file_uri)
            if not rel_path:
                continue

            # Read full content from disk — qmd "snippet" is a diff excerpt, not full text
            full_path = self.store.wiki_path / rel_path
            if not full_path.exists():
                continue
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            pages[rel_path] = content

        return pages

    def _parse_file_uri(self, file_uri: str) -> str:
        """Strip qmd://collection/ prefix to get wiki-relative path.

        qmd returns URIs like 'qmd://wiki/analyses/foo.md'.
        We strip everything up to and including the second slash after 'qmd://'
        to get the wiki-relative path 'analyses/foo.md'.
        """
        if file_uri.startswith("qmd://"):
            without_scheme = file_uri[6:]  # drop "qmd://"
            slash = without_scheme.find("/")
            if slash >= 0:
                return without_scheme[slash + 1:]
        return file_uri


_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def make_retriever(
    store: WikiStore,
    backend: str = "index_keyword",
    wiki_config: WikiConfig | None = None,
    root: Path | None = None,
) -> Retriever:
    normalized = (backend or "").strip().lower()
    if normalized in {"index_keyword", "keyword", "index"}:
        return KeywordIndexRetriever(store)
    if normalized in {"bm25"}:
        return BM25Retriever(store)
    if normalized in {"qmd"}:
        qmd_bin = (wiki_config.qmd_bin if wiki_config else None) or "qmd"
        qmd_mode = (wiki_config.qmd_mode if wiki_config else None) or "vsearch"
        if not shutil.which(qmd_bin):
            warnings.warn(
                f"qmd binary {qmd_bin!r} not found on PATH. "
                "Falling back to BM25 retriever.",
                stacklevel=2,
            )
            return BM25Retriever(store)
        return QmdRetriever(store, mode=qmd_mode, qmd_bin=qmd_bin, root=root)

    raise RetrievalError(
        "Unsupported retrieval backend: "
        f"{backend!r}. Supported backends: index_keyword, bm25, qmd"
    )
