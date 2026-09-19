"""The logo the connector list shows."""

from hermes_docs_mcp import icons, server


def test_a_stdio_server_inlines_the_icon(monkeypatch):
    monkeypatch.delenv("HERMES_DOCS_MCP_PUBLIC_URL", raising=False)
    icons.data_uri.cache_clear()
    listed = icons.server_icons()
    assert [i.sizes for i in listed] == [["48x48"]]
    assert listed[0].src.startswith("data:image/png;base64,")
    assert listed[0].mimeType == "image/png"


def test_a_hosted_server_offers_the_url_first(monkeypatch):
    monkeypatch.setenv("HERMES_DOCS_MCP_PUBLIC_URL", "https://example.test/")
    icons.data_uri.cache_clear()
    listed = icons.server_icons()
    assert listed[0].src == "https://example.test/icon-128.png"  # no doubled slash
    assert listed[0].sizes == ["128x128"]
    assert listed[-1].src.startswith("data:")  # inline copy stays as a fallback


def test_a_missing_asset_does_not_break_startup(monkeypatch):
    monkeypatch.setattr(icons, "ASSETS", icons.ASSETS / "gone")
    icons.data_uri.cache_clear()
    assert icons.data_uri(icons.SMALL) == ""
    monkeypatch.delenv("HERMES_DOCS_MCP_PUBLIC_URL", raising=False)
    assert icons.server_icons() == []
    icons.data_uri.cache_clear()


def test_every_advertised_asset_ships():
    for name, _ in icons.STATIC_FILES.values():
        assert (icons.ASSETS / name).is_file(), name


def test_a_connector_list_finds_the_icon_the_way_a_browser_would():
    """Not via the MCP handshake: through /favicon.ico and the landing page."""
    from starlette.testclient import TestClient

    with TestClient(server.mcp.streamable_http_app()) as client:
        favicon = client.get("/favicon.ico")
        assert favicon.status_code == 200
        assert favicon.headers["content-type"].startswith("image/")
        assert favicon.content[:4] == b"\x00\x00\x01\x00"  # ICONDIR header

        root = client.get("/")
        assert root.status_code == 200
        assert 'rel="icon"' in root.text
        assert "/mcp" in root.text  # the page tells a visitor what to connect to

        for path in ("/icon-128.png", "/icon-32.png", "/apple-touch-icon.png"):
            asset = client.get(path)
            assert asset.status_code == 200, path
            assert asset.content[:8] == b"\x89PNG\r\n\x1a\n", path


def test_the_server_advertises_its_home():
    assert server.mcp._mcp_server.website_url == "https://github.com/shi-kirill/hermes-docs-mcp"


def test_render_supplies_the_public_url_by_itself(monkeypatch):
    """A Render deploy must not need an env var spelled out by hand."""
    monkeypatch.delenv("HERMES_DOCS_MCP_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://svc.onrender.com/")
    assert icons.public_base_url() == "https://svc.onrender.com"

    monkeypatch.delenv("RENDER_EXTERNAL_URL")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "svc.onrender.com")
    assert icons.public_base_url() == "https://svc.onrender.com"

    monkeypatch.setenv("HERMES_DOCS_MCP_PUBLIC_URL", "https://docs.example.test")
    assert icons.public_base_url() == "https://docs.example.test"  # explicit wins
