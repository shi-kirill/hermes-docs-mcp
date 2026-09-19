from hermes_docs_mcp.corpus import build_corpus, parse_index, parse_pages, slugify, source_to_path

from .conftest import BASE_URL


def test_pages_are_split_on_source_markers(full_text):
    pages = parse_pages(full_text, BASE_URL)
    assert [p.path for p in pages] == [
        "getting-started/installation",
        "user-guide/features/mcp",
        "user-guide/messaging",
        "user-stories",
    ]


def test_urls_match_the_docs_site(full_text):
    pages = {p.path: p for p in parse_pages(full_text, BASE_URL)}
    assert pages["getting-started/installation"].url == f"{BASE_URL}/docs/getting-started/installation"
    # index.md renders at the directory URL, with the trailing slash the site uses
    assert pages["user-guide/messaging"].url == f"{BASE_URL}/docs/user-guide/messaging/"
    assert pages["user-stories"].url == f"{BASE_URL}/docs/user-stories"


def test_duplicate_h1_is_collapsed(full_text):
    page = next(p for p in parse_pages(full_text, BASE_URL) if p.path.endswith("installation"))
    assert page.title == "Installation"
    assert page.body.count("# Installation") == 1
    assert "Get Hermes Agent running" in page.body


def test_source_to_path_handles_md_mdx_and_index():
    assert source_to_path("website/docs/user-guide/cli.md") == "user-guide/cli"
    assert source_to_path("website/docs/user-stories.mdx") == "user-stories"
    assert source_to_path("website/docs/integrations/index.md") == "integrations"


def test_chunks_carry_headings_and_anchors(full_text):
    page = next(p for p in parse_pages(full_text, BASE_URL) if p.path.endswith("installation"))
    headings = [c.heading for c in page.chunks]
    assert "Quick Install" in headings
    assert "Requirements" in headings
    quick = next(c for c in page.chunks if c.heading == "Quick Install")
    assert quick.anchor == slugify("Quick Install") == "quick-install"
    assert "install.sh" in quick.text
    # a ### heading keeps its ## parent in the breadcrumb
    req = next(c for c in page.chunks if c.heading == "Requirements")
    assert req.heading_path == "Installation > Quick Install > Requirements"


def test_index_supplies_descriptions_and_nav_sections(index_text):
    entries = parse_index(index_text)
    mcp = entries[f"{BASE_URL}/docs/user-guide/features/mcp"]
    assert mcp.nav_section == "Features"
    assert mcp.description == "Connect Hermes to MCP servers"


def test_corpus_merges_index_metadata(full_text, index_text):
    corpus = build_corpus(full_text, index_text, BASE_URL)
    page = corpus.by_path["user-guide/features/mcp"]
    assert page.description == "Connect Hermes to MCP servers"
    assert page.nav_section == "Features"
    assert corpus.sections == ["getting-started", "user-guide", "user-stories"]


def test_resolve_accepts_path_url_source_and_title(full_text, index_text):
    corpus = build_corpus(full_text, index_text, BASE_URL)
    expected = "user-guide/features/mcp"
    for ref in (
        expected,
        f"/{expected}/",
        f"{BASE_URL}/docs/{expected}",
        f"{BASE_URL}/docs/{expected}#trust-model",
        "website/docs/user-guide/features/mcp.md",
        "MCP Integration",
    ):
        assert corpus.resolve(ref) is not None, ref
        assert corpus.resolve(ref).path == expected
    assert corpus.resolve("no/such/page") is None
    assert corpus.resolve("") is None


def test_root_index_maps_to_the_docs_root():
    from hermes_docs_mcp.corpus import path_to_url

    assert source_to_path("website/docs/index.md") == ""
    assert path_to_url(BASE_URL, "", "website/docs/index.md") == f"{BASE_URL}/docs/"


def test_long_sections_are_split_but_stay_attached_to_their_heading():
    from hermes_docs_mcp.corpus import MAX_CHUNK_CHARS, chunk_page

    paragraph = "Hermes keeps a durable memory of every session it runs.\n\n"
    body = "# Long page\n\n## Memory\n\n" + paragraph * 120
    assert len(body) > MAX_CHUNK_CHARS * 2
    chunks = chunk_page("x/long", "Long page", body)
    memory_chunks = [c for c in chunks if c.heading == "Memory"]
    assert len(memory_chunks) > 1
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in memory_chunks)
    assert all(c.heading_path == "Long page > Memory" for c in memory_chunks)
    # every piece of the section survives the split
    joined = " ".join(c.text for c in memory_chunks)
    assert joined.count("durable memory") == 120


def test_breadcrumbs_use_the_same_title_as_the_page(full_text, index_text):
    """The index can rename a page; its fragments must not keep the old name."""
    corpus = build_corpus(full_text, index_text, BASE_URL)
    page = corpus.by_path["user-guide/features/mcp"]
    assert page.title == "MCP Integration"  # index wins over the page's own H1
    assert {c.crumbs[0] for c in page.chunks} == {"MCP Integration"}
    deep = next(c for c in page.chunks if c.heading == "Trust model")
    assert deep.crumbs == ("MCP Integration", "Trust model")
