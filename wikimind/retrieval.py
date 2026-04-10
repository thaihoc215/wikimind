"""Retrieval abstraction boundary for selecting wiki context pages."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

from wikimind.wiki import WikiStore


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


_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def make_retriever(store: WikiStore, backend: str = "index_keyword") -> Retriever:
    normalized = (backend or "").strip().lower()
    if normalized in {"index_keyword", "keyword", "index"}:
        return KeywordIndexRetriever(store)
    if normalized in {"bm25"}:
        return BM25Retriever(store)

    raise RetrievalError(
        "Unsupported retrieval backend: "
        f"{backend!r}. Supported backends: index_keyword, bm25"
    )
