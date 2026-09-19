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


def test_the_icon_file_ships_and_is_served():
    assert (icons.ASSETS / icons.LARGE).is_file()
    paths = {getattr(r, "path", None) for r in server.mcp.streamable_http_app().router.routes}
    assert icons.ICON_ROUTE in paths


def test_the_server_advertises_its_home():
    assert server.mcp._mcp_server.website_url == "https://github.com/shi-kirill/hermes-docs-mcp"
