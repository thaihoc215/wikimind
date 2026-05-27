"""Tests for retrieval backend abstraction."""

import json
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wikimind.config import WikiConfig
from wikimind.retrieval import BM25Retriever, QmdRetriever, RetrievalError, build_qmd_cmd, make_retriever, run_qmd_refresh
from wikimind.wiki import WikiStore


def test_make_retriever_default_backend(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/openai.md", "# OpenAI")
    tmp_wiki.update_index(
        entries_to_add=["- [[openai]] — AI lab"],
        entries_to_remove=[],
    )

    retriever = make_retriever(tmp_wiki, backend="index_keyword")
    pages = retriever.retrieve("openai", top_k=5)
    assert "entities/openai.md" in pages


def test_make_retriever_rejects_unknown_backend(tmp_wiki: WikiStore):
    with pytest.raises(RetrievalError):
        make_retriever(tmp_wiki, backend="vector")


def test_make_retriever_bm25_backend(tmp_wiki: WikiStore):
    tmp_wiki.write_page(
        "entities/openai.md",
        "# OpenAI\n\nOpenAI works on large language models and RLHF.",
    )
    tmp_wiki.write_page(
        "entities/anthropic.md",
        "# Anthropic\n\nAnthropic focuses on constitutional AI.",
    )

    retriever = make_retriever(tmp_wiki, backend="bm25")
    assert isinstance(retriever, BM25Retriever)

    pages = retriever.retrieve("rlhf openai", top_k=2)
    assert pages
    first_path = next(iter(pages.keys()))
    assert first_path == "entities/openai.md"


def test_bm25_retriever_ignores_empty_query(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/openai.md", "# OpenAI")
    retriever = BM25Retriever(tmp_wiki)
    assert retriever.retrieve("   ", top_k=5) == {}


# ── QmdRetriever tests ────────────────────────────────────────────────────────


def test_qmd_retriever_fallback_to_bm25(tmp_wiki: WikiStore):
    """When qmd binary is not found, make_retriever falls back to BM25 with a warning."""
    config = WikiConfig(retrieval_backend="qmd", qmd_mode="vsearch", qmd_bin="qmd")
    with patch("wikimind.retrieval.shutil.which", return_value=None):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            retriever = make_retriever(tmp_wiki, backend="qmd", wiki_config=config)
            assert isinstance(retriever, BM25Retriever)
            assert len(w) == 1
            assert "falling back" in str(w[0].message).lower()


def test_make_retriever_qmd_backend(tmp_wiki: WikiStore):
    """Factory creates QmdRetriever when qmd binary is available."""
    config = WikiConfig(retrieval_backend="qmd", qmd_mode="vsearch", qmd_bin="qmd")
    with patch("wikimind.retrieval.shutil.which", return_value="/usr/local/bin/qmd"):
        retriever = make_retriever(
            tmp_wiki,
            backend="qmd",
            wiki_config=config,
            index_name="ph-bsl",
            collection_name="ph-bsl",
        )
        assert isinstance(retriever, QmdRetriever)
        assert retriever.mode == "vsearch"
        assert retriever.index_name == "ph-bsl"
        assert retriever.collection_name == "ph-bsl"


def test_build_qmd_cmd_uses_git_sh_for_windows_cmd_wrapper(tmp_path: Path):
    qmd_cmd = tmp_path / "node" / "bin" / "qmd.CMD"
    qmd_script = qmd_cmd.parent / "node_modules" / "@tobilu" / "qmd" / "bin" / "qmd"
    git_exe = tmp_path / "Git" / "cmd" / "git.exe"
    sh_exe = tmp_path / "Git" / "usr" / "bin" / "sh.exe"
    qmd_script.parent.mkdir(parents=True)
    git_exe.parent.mkdir(parents=True)
    sh_exe.parent.mkdir(parents=True)
    qmd_cmd.write_text("", encoding="utf-8")
    qmd_script.write_text("", encoding="utf-8")
    git_exe.write_text("", encoding="utf-8")
    sh_exe.write_text("", encoding="utf-8")

    def which(name: str):
        if name == "qmd":
            return str(qmd_cmd)
        if name == "git":
            return str(git_exe)
        return None

    with patch("wikimind.retrieval.sys.platform", "win32"), \
         patch("wikimind.retrieval.shutil.which", side_effect=which):
        assert build_qmd_cmd("qmd") == [str(sh_exe), str(qmd_script)]


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_build_qmd_cmd_uses_resolved_binary_on_unix_platforms(tmp_path: Path, platform: str):
    qmd_bin = tmp_path / "bin" / "qmd"
    qmd_bin.parent.mkdir(parents=True)
    qmd_bin.write_text("", encoding="utf-8")

    with patch("wikimind.retrieval.sys.platform", platform), \
         patch("wikimind.retrieval.shutil.which", return_value=str(qmd_bin)):
        assert build_qmd_cmd("qmd") == [str(qmd_bin)]


def test_build_qmd_cmd_returns_none_when_qmd_is_missing():
    with patch("wikimind.retrieval.shutil.which", return_value=None):
        assert build_qmd_cmd("qmd") is None


def test_build_qmd_cmd_falls_back_to_cmd_for_windows_wrapper_without_sh(tmp_path: Path):
    qmd_cmd = tmp_path / "node" / "bin" / "qmd.CMD"
    qmd_cmd.parent.mkdir(parents=True)
    qmd_cmd.write_text("", encoding="utf-8")

    def which(name: str):
        if name == "qmd":
            return str(qmd_cmd)
        return None

    with patch("wikimind.retrieval.sys.platform", "win32"), \
         patch("wikimind.retrieval.shutil.which", side_effect=which):
        assert build_qmd_cmd("qmd") == ["cmd", "/c", str(qmd_cmd)]


def test_run_qmd_refresh_updates_before_embedding(tmp_path: Path):
    update_result = MagicMock(returncode=0)
    embed_result = MagicMock(returncode=0)

    with patch(
        "wikimind.retrieval.subprocess.run",
        side_effect=[update_result, embed_result],
    ) as mock_run:
        assert run_qmd_refresh(["qmd"], tmp_path) == (update_result, embed_result)

    assert mock_run.call_args_list[0].args[0] == ["qmd", "update"]
    assert mock_run.call_args_list[1].args[0] == ["qmd", "embed"]


def test_run_qmd_refresh_uses_named_index(tmp_path: Path):
    update_result = MagicMock(returncode=0)
    embed_result = MagicMock(returncode=0)

    with patch(
        "wikimind.retrieval.subprocess.run",
        side_effect=[update_result, embed_result],
    ) as mock_run:
        assert run_qmd_refresh(["qmd"], tmp_path, index_name="ph-bsl") == (update_result, embed_result)

    assert mock_run.call_args_list[0].args[0] == ["qmd", "--index", "ph-bsl", "update"]
    assert mock_run.call_args_list[1].args[0] == ["qmd", "--index", "ph-bsl", "embed"]


def test_run_qmd_refresh_adds_missing_collection_to_named_index(tmp_path: Path):
    show_result = MagicMock(returncode=1)
    add_result = MagicMock(returncode=0)
    update_result = MagicMock(returncode=0)
    embed_result = MagicMock(returncode=0)

    with patch(
        "wikimind.retrieval.subprocess.run",
        side_effect=[show_result, add_result, update_result, embed_result],
    ) as mock_run:
        assert run_qmd_refresh(
            ["qmd"],
            tmp_path,
            index_name="ph-bsl",
            collection_name="ph-bsl",
            collection_path=".wiki/vault/",
        ) == (update_result, embed_result)

    assert mock_run.call_args_list[0].args[0] == ["qmd", "--index", "ph-bsl", "collection", "show", "ph-bsl"]
    assert mock_run.call_args_list[1].args[0] == ["qmd", "--index", "ph-bsl", "collection", "add", ".wiki/vault/", "--name", "ph-bsl"]
    assert mock_run.call_args_list[2].args[0] == ["qmd", "--index", "ph-bsl", "update"]
    assert mock_run.call_args_list[3].args[0] == ["qmd", "--index", "ph-bsl", "embed"]


def test_run_qmd_refresh_skips_embed_when_update_fails(tmp_path: Path):
    update_result = MagicMock(returncode=1)

    with patch("wikimind.retrieval.subprocess.run", return_value=update_result) as mock_run:
        assert run_qmd_refresh(["qmd"], tmp_path) == (update_result, None)

    mock_run.assert_called_once()
    assert mock_run.call_args.args[0] == ["qmd", "update"]


@pytest.mark.parametrize("mode", ["search", "vsearch", "query"])
def test_qmd_retriever_modes(tmp_wiki: WikiStore, mode: str):
    """Each qmd mode uses the correct subcommand and parses results."""
    # retrieve() reads the page from disk after qmd returns its path, so create it.
    (tmp_wiki.wiki_path / "entities").mkdir(exist_ok=True)
    (tmp_wiki.wiki_path / "entities" / "openai.md").write_text("# OpenAI", encoding="utf-8")

    retriever = QmdRetriever(tmp_wiki, mode=mode, qmd_bin="qmd")
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps([
        {"path": "entities/openai.md", "content": "# OpenAI", "score": 0.95}
    ])

    # Stub _build_cmd_prefix so the test is platform-agnostic (avoids real
    # shutil.which resolving cmd /c or sh.exe wrappers on Windows/MINGW64).
    with patch.object(QmdRetriever, "_build_cmd_prefix", return_value=["qmd"]), \
         patch("wikimind.retrieval.subprocess.run", return_value=mock_result) as mock_run:
        pages = retriever.retrieve("openai", top_k=5)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "qmd"
        assert cmd[1] == mode
        assert cmd[2] == "openai"
        assert "--json" in cmd
        assert "entities/openai.md" in pages


def test_qmd_retriever_scopes_search_to_collection(tmp_wiki: WikiStore):
    """qmd searches should be constrained to the current project collection."""
    (tmp_wiki.wiki_path / "entities").mkdir(exist_ok=True)
    (tmp_wiki.wiki_path / "entities" / "openai.md").write_text("# OpenAI", encoding="utf-8")

    retriever = QmdRetriever(tmp_wiki, mode="vsearch", qmd_bin="qmd", collection_name="ph-bsl")
    mock_result = MagicMock(returncode=0)
    mock_result.stdout = json.dumps([
        {"path": "entities/openai.md", "content": "# OpenAI", "score": 0.95}
    ])

    with patch.object(QmdRetriever, "_build_cmd_prefix", return_value=["qmd"]), \
         patch("wikimind.retrieval.subprocess.run", return_value=mock_result) as mock_run:
        pages = retriever.retrieve("openai", top_k=5)

    cmd = mock_run.call_args.args[0]
    assert cmd == ["qmd", "vsearch", "openai", "--json", "-c", "ph-bsl"]
    assert "entities/openai.md" in pages


def test_qmd_retriever_scopes_search_to_index_and_collection(tmp_wiki: WikiStore):
    """qmd search should use the project index and collection."""
    (tmp_wiki.wiki_path / "entities").mkdir(exist_ok=True)
    (tmp_wiki.wiki_path / "entities" / "openai.md").write_text("# OpenAI", encoding="utf-8")

    retriever = QmdRetriever(
        tmp_wiki,
        mode="vsearch",
        qmd_bin="qmd",
        index_name="ph-bsl",
        collection_name="ph-bsl",
    )
    mock_result = MagicMock(returncode=0)
    mock_result.stdout = json.dumps([
        {"path": "entities/openai.md", "content": "# OpenAI", "score": 0.95}
    ])

    with patch.object(QmdRetriever, "_build_cmd_prefix", return_value=["qmd"]), \
         patch("wikimind.retrieval.subprocess.run", return_value=mock_result) as mock_run:
        pages = retriever.retrieve("openai", top_k=5)

    cmd = mock_run.call_args.args[0]
    assert cmd == ["qmd", "--index", "ph-bsl", "vsearch", "openai", "--json", "-c", "ph-bsl"]
    assert "entities/openai.md" in pages


def test_qmd_retriever_invalid_mode(tmp_wiki: WikiStore):
    """QmdRetriever rejects invalid modes at construction time."""
    with pytest.raises(RetrievalError, match="Invalid qmd_mode"):
        QmdRetriever(tmp_wiki, mode="invalid")


def test_qmd_retriever_empty_query(tmp_wiki: WikiStore):
    """QmdRetriever returns empty dict for blank queries and top_k=0."""
    retriever = QmdRetriever(tmp_wiki, mode="vsearch")
    assert retriever.retrieve("   ", top_k=5) == {}
    assert retriever.retrieve("hello", top_k=0) == {}


def test_qmd_retriever_subprocess_failure(tmp_wiki: WikiStore):
    """QmdRetriever returns empty dict when subprocess exits with non-zero code."""
    retriever = QmdRetriever(tmp_wiki, mode="vsearch")
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch("wikimind.retrieval.subprocess.run", return_value=mock_result):
        assert retriever.retrieve("test query", top_k=5) == {}


def test_qmd_retriever_top_k_respected(tmp_wiki: WikiStore):
    """QmdRetriever limits results to top_k even when subprocess returns more."""
    # retrieve() reads pages from disk — create all 5 so none are skipped.
    (tmp_wiki.wiki_path / "entities").mkdir(exist_ok=True)
    for i in range(5):
        (tmp_wiki.wiki_path / "entities" / f"page{i}.md").write_text(f"# Page {i}", encoding="utf-8")

    retriever = QmdRetriever(tmp_wiki, mode="vsearch")
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps([
        {"path": f"entities/page{i}.md", "content": f"# Page {i}", "score": 1.0 - i * 0.1}
        for i in range(5)
    ])

    with patch.object(QmdRetriever, "_build_cmd_prefix", return_value=["qmd"]), \
         patch("wikimind.retrieval.subprocess.run", return_value=mock_result):
        pages = retriever.retrieve("test", top_k=2)
        assert len(pages) == 2
