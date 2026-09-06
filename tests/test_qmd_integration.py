"""Opt-in contract tests against a real qmd install.

Every other qmd test in this suite mocks ``subprocess.run`` and asserts on argv,
which means they pass no matter which qmd version is installed — or whether it is
installed at all. That is how seven upstream releases of CLI drift went unnoticed.

These tests run the real binary (no models, no collection, no network) and fail
loudly if qmd stops accepting an argument wikimind actually sends.

Skipped automatically when qmd is not on PATH.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from wikimind.retrieval import QmdRetriever, build_qmd_cmd
from wikimind.wiki import WikiStore

pytestmark = pytest.mark.skipif(
    shutil.which("qmd") is None,
    reason="qmd not installed; install with `npm install -g @tobilu/qmd`",
)


@pytest.fixture(scope="module")
def qmd_help() -> str:
    """Top-level `qmd --help` text, lowercased."""
    cmd = build_qmd_cmd("qmd")
    assert cmd is not None, "qmd resolved on PATH but build_qmd_cmd() returned None"
    result = subprocess.run(
        cmd + ["--help"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = f"{result.stdout}{result.stderr}"
    assert output.strip(), "qmd --help produced no output"
    return output.lower()


def test_build_qmd_cmd_produces_a_runnable_invocation() -> None:
    """The (Windows-aware) launcher prefix we build can actually execute qmd."""
    cmd = build_qmd_cmd("qmd")
    assert cmd is not None

    result = subprocess.run(
        cmd + ["--version"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"qmd --version failed: {result.stderr[:300]}"
    assert "qmd" in f"{result.stdout}{result.stderr}".lower()


@pytest.mark.parametrize(
    "subcommand",
    ["search", "vsearch", "query", "collection", "update", "embed"],
)
def test_required_subcommand_still_exists(qmd_help: str, subcommand: str) -> None:
    """wikimind invokes each of these; none may disappear silently."""
    assert subcommand in qmd_help


@pytest.mark.parametrize(
    "flag",
    [
        "--index",       # per-project named index
        "--format",      # supersedes the legacy --json alias
        "--collection",  # -c scoping in QmdRetriever
        "--no-rerank",   # optional query-mode tuning
    ],
)
def test_required_flag_still_documented(qmd_help: str, flag: str) -> None:
    assert flag in qmd_help


def test_format_json_is_accepted(tmp_path) -> None:
    """`--format json` must parse as an argument, not just appear in help.

    Uses a throwaway named index so no real collection is touched. An empty index
    yields no results, which is fine — we only care that qmd did not reject the
    flag as unknown.
    """
    cmd = build_qmd_cmd("qmd")
    assert cmd is not None

    result = subprocess.run(
        cmd + ["--index", "wikimind-contract-test", "search", "anything", "--format", "json"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=120,
        check=False,
    )
    combined = f"{result.stdout}{result.stderr}".lower()
    assert "unknown option" not in combined
    assert "unknown argument" not in combined
    assert "--format" not in combined or "unknown" not in combined


def test_retriever_resolves_real_qmd_results_end_to_end(tmp_path) -> None:
    """Real qmd indexes a real vault and QmdRetriever resolves real files.

    This is the test that catches result-shape drift. It uses `search` (BM25) so
    no embedding model is needed — the point is the qmd:// URI round-trip, not
    ranking quality. qmd 2.8.3 began appending "?index=<name>" to the `file`
    field; before that was handled, this returned an empty dict.
    """
    wiki_dir = tmp_path / "vault"
    raw_dir = tmp_path / "raw"
    (wiki_dir / "notes").mkdir(parents=True)
    raw_dir.mkdir()
    page = wiki_dir / "notes" / "kestrel.md"
    page.write_text(
        "\n".join(
            ["---", "title: Kestrel", "---", "", "The zarquonicity of falconry.", ""]
        ),
        encoding="utf-8",
    )

    cmd = build_qmd_cmd("qmd")
    assert cmd is not None
    index_name = "wikimind-e2e-test"

    def run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd + ["--index", index_name] + args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(tmp_path),
            timeout=timeout,
            check=False,
        )

    try:
        added = run(["collection", "add", str(wiki_dir), "--name", index_name])
        assert added.returncode == 0, f"collection add failed: {added.stderr[:300]}"

        updated = run(["update"])
        assert updated.returncode == 0, f"update failed: {updated.stderr[:300]}"

        store = WikiStore(wiki_dir, raw_dir)
        retriever = QmdRetriever(
            store,
            mode="search",
            qmd_bin="qmd",
            root=tmp_path,
            index_name=index_name,
            collection_name=index_name,
        )
        pages = retriever.retrieve("zarquonicity", top_k=5)

        assert pages, "qmd returned no resolvable pages — result URI shape may have changed"
        assert "notes/kestrel.md" in pages
        assert "zarquonicity" in pages["notes/kestrel.md"]
    finally:
        run(["collection", "remove", index_name], timeout=60)
