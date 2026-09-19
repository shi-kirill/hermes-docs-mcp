import pytest

from hermes_docs_mcp.corpus import build_corpus
from hermes_docs_mcp.search import SearchIndex, snippet, tokenize

from .conftest import BASE_URL


def index(full_text, index_text) -> SearchIndex:
    return SearchIndex(build_corpus(full_text, index_text, BASE_URL))


def test_search_finds_the_right_page(full_text, index_text):
    hits = index(full_text, index_text).search("how do I add an mcp server", limit=3)
    assert hits
    assert hits[0].page.path == "user-guide/features/mcp"
    assert "hermes mcp add" in hits[0].chunk.text


def test_search_respects_section_filter(full_text, index_text):
    idx = index(full_text, index_text)
    assert all(h.page.section == "getting-started" for h in idx.search("install", section="getting-started"))
    # nav section names work too
    assert all(h.page.nav_section == "Features" for h in idx.search("mcp", section="Features"))


def test_search_can_be_scoped_to_one_page(full_text, index_text):
    hits = index(full_text, index_text).search("token", page_ref="user-guide/messaging")
    assert hits and {h.page.path for h in hits} == {"user-guide/messaging"}


def test_limit_and_page_diversity(full_text, index_text):
    idx = index(full_text, index_text)
    hits = idx.search("hermes", limit=3)
    assert len(hits) <= 3
    counts: dict[str, int] = {}
    for hit in idx.search("hermes", limit=10):
        counts[hit.page.path] = counts.get(hit.page.path, 0) + 1
    assert max(counts.values()) <= 2


def test_stopword_only_query_still_returns_something(full_text, index_text):
    assert index(full_text, index_text).search("the") is not None


def test_no_match_returns_empty(full_text, index_text):
    assert index(full_text, index_text).search("kubernetes helm chart xyzzy") == []


def test_tokenizer_keeps_dotted_and_dashed_identifiers():
    tokens = tokenize("Set `approvals.mode` via --config soul.md")
    assert "approvals.mode" in tokens
    assert "soul.md" in tokens


def test_snippet_centres_on_the_match_and_marks_truncation():
    text = "alpha " * 80 + "BOTFATHER token " + "omega " * 80
    out = snippet(text, ["botfather"], width=120)
    assert "BOTFATHER" in out
    assert out.startswith("… ") and out.endswith(" …")
    assert len(out) < 200


POSITION_DOC = """<!-- source: website/docs/x/page.md -->
# Page

## Early section

Widgetron is configured in the agent config file.

## Filler

Nothing relevant lives here.

## Late section

Widgetron is configured in the agent config file.
"""

LINKY_DOC = """<!-- source: website/docs/x/prose.md -->
# Prose

## Details

Widgetron support is enabled by editing the config file and restarting the agent.

<!-- source: website/docs/x/links.md -->
# Links

## Where to read next

- [Widgetron](https://docs.example.test/docs/x/prose)
- [Widgetron setup](https://docs.example.test/docs/x/prose)
- [Widgetron reference](https://docs.example.test/docs/x/prose)
"""


def test_earlier_chunks_win_ties(index_text):
    hits = SearchIndex(build_corpus(POSITION_DOC, index_text, BASE_URL)).search("widgetron")
    assert [h.chunk.heading for h in hits][:2] == ["Early section", "Late section"]
    assert hits[0].score > hits[1].score


def test_link_only_sections_are_demoted(index_text, monkeypatch):
    """A chunk that is almost entirely links is scored down in proportion."""
    import hermes_docs_mcp.search as search_mod

    def scores(limit: float) -> dict[str, float]:
        monkeypatch.setattr(search_mod, "LINK_DENSITY_LIMIT", limit)
        idx = SearchIndex(build_corpus(LINKY_DOC, index_text, BASE_URL))
        return {h.chunk.heading: h.score for h in idx.search("widgetron", limit=5)}

    raw = scores(1.1)  # penalty effectively disabled
    penalised = scores(0.45)
    assert penalised["Details"] == pytest.approx(raw["Details"])  # prose untouched
    assert penalised["Where to read next"] < raw["Where to read next"] * 0.75
