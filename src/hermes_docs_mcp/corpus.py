"""Turn the two downloaded text files into pages and searchable chunks.

`llms-full.txt` is a concatenation where every page starts with a
`<!-- source: website/docs/<path>.md -->` marker; `docs/llms.txt` is a markdown
link list grouped by `## Section`, which supplies the nav section name and the
one-line description for each page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PAGE_MARKER = re.compile(r"^<!--\s*source:\s*(?P<path>\S+?)\s*-->\s*$", re.MULTILINE)
HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$", re.MULTILINE)
INDEX_SECTION = re.compile(r"^##\s+(?P<name>.+?)\s*$", re.MULTILINE)
INDEX_ENTRY = re.compile(
    r"^-\s+\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)\s*(?::\s*(?P<description>.*))?$",
    re.MULTILINE,
)
DOCS_PREFIX = "website/docs/"
# Chunks are what the ranker scores and what a search hit quotes; keep them near
# one screenful so a snippet stays readable and a term's context survives.
MAX_CHUNK_CHARS = 2400


@dataclass(frozen=True)
class IndexEntry:
    title: str
    url: str
    description: str
    nav_section: str


@dataclass(frozen=True)
class Chunk:
    page_path: str
    heading: str
    heading_path: str
    anchor: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Page:
    path: str
    source: str
    title: str
    section: str
    url: str
    body: str
    description: str = ""
    nav_section: str = ""
    chunks: tuple[Chunk, ...] = field(default_factory=tuple)

    @property
    def headings(self) -> list[str]:
        seen: list[str] = []
        for match in HEADING.finditer(self.body):
            if len(match.group("hashes")) >= 2:
                text = match.group("text").strip()
                if text and text not in seen:
                    seen.append(text)
        return seen


def slugify(text: str) -> str:
    slug = re.sub(r"`|\*|_", "", text).strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    return re.sub(r"[\s-]+", "-", slug).strip("-")


def source_to_path(source: str) -> str:
    """`website/docs/user-guide/features/mcp.md` -> `user-guide/features/mcp`."""
    path = source.strip()
    if path.startswith(DOCS_PREFIX):
        path = path[len(DOCS_PREFIX) :]
    for suffix in (".mdx", ".md"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    if path.endswith("/index"):
        path = path[: -len("/index")]
    elif path == "index":
        path = ""
    return path.strip("/")


def path_to_url(base_url: str, path: str, source: str) -> str:
    base = f"{base_url.rstrip('/')}/docs"
    if not path:
        return f"{base}/"
    stem = source.rsplit("/", 1)[-1]
    trailing = "/" if stem in {"index.md", "index.mdx"} else ""
    return f"{base}/{path}{trailing}"


def _strip_duplicate_title(body: str) -> tuple[str, str]:
    """The export prepends the page title, so most pages open with two identical H1s."""
    lines = body.splitlines()
    title = ""
    kept: list[str] = []
    seen_title = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            text = stripped[2:].strip()
            if not seen_title:
                title = text
                seen_title = True
                kept.append(line)
                continue
            if text == title and not "".join(kept[1:]).strip():
                continue  # exact repeat with nothing in between
        kept.append(line)
    return title, "\n".join(kept).strip()


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts: list[str] = []
    buffer: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        piece = para + "\n\n"
        if size + len(piece) > MAX_CHUNK_CHARS and buffer:
            parts.append("".join(buffer).strip())
            buffer, size = [], 0
        buffer.append(piece)
        size += len(piece)
    if buffer:
        parts.append("".join(buffer).strip())
    return [p for p in parts if p]


def chunk_page(path: str, title: str, body: str) -> tuple[Chunk, ...]:
    """Split a page at its `##`/`###` headings, keeping each heading with its text."""
    boundaries = [m for m in HEADING.finditer(body) if 2 <= len(m.group("hashes")) <= 3]
    spans: list[tuple[str, int, int, int]] = []  # heading, level, start, end
    if not boundaries or boundaries[0].start() > 0:
        end = boundaries[0].start() if boundaries else len(body)
        spans.append(("", 1, 0, end))
    for i, match in enumerate(boundaries):
        end = boundaries[i + 1].start() if i + 1 < len(boundaries) else len(body)
        spans.append((match.group("text").strip(), len(match.group("hashes")), match.start(), end))

    chunks: list[Chunk] = []
    parent = ""
    for heading, level, start, end in spans:
        if level == 2:
            parent = heading
        crumbs = [title] if title else []
        if parent and parent != heading:
            crumbs.append(parent)
        if heading:
            crumbs.append(heading)
        heading_path = " > ".join(crumbs)
        raw = body[start:end].strip()
        if not raw:
            continue
        offset = start
        for piece in _split_long(raw):
            found = body.find(piece[:80], offset, end) if piece[:80] else -1
            piece_start = found if found >= 0 else offset
            chunks.append(
                Chunk(
                    page_path=path,
                    heading=heading,
                    heading_path=heading_path or title,
                    anchor=slugify(heading) if heading else "",
                    text=piece,
                    start=piece_start,
                    end=piece_start + len(piece),
                )
            )
            offset = piece_start + len(piece)
    return tuple(chunks)


def parse_index(text: str) -> dict[str, IndexEntry]:
    """Map canonical URL -> nav section, title and one-line description."""
    entries: dict[str, IndexEntry] = {}
    sections: list[tuple[int, str]] = [
        (m.start(), m.group("name").strip()) for m in INDEX_SECTION.finditer(text)
    ]
    for match in INDEX_ENTRY.finditer(text):
        nav = ""
        for pos, name in sections:
            if pos < match.start():
                nav = name
            else:
                break
        url = match.group("url").strip()
        entries[url.rstrip("/")] = IndexEntry(
            title=match.group("title").strip(),
            url=url,
            description=(match.group("description") or "").strip(),
            nav_section=nav,
        )
    return entries


def parse_pages(full_text: str, base_url: str) -> list[Page]:
    markers = list(PAGE_MARKER.finditer(full_text))
    pages: list[Page] = []
    for i, match in enumerate(markers):
        source = match.group("path")
        body_start = match.end()
        body_end = markers[i + 1].start() if i + 1 < len(markers) else len(full_text)
        raw = full_text[body_start:body_end].strip()
        raw = raw.rstrip("-").rstrip()  # trailing `---` separator between pages
        path = source_to_path(source)
        title, body = _strip_duplicate_title(raw)
        if not title:
            title = path.rsplit("/", 1)[-1].replace("-", " ").title() or "Documentation"
        pages.append(
            Page(
                path=path,
                source=source,
                title=title,
                section=path.split("/")[0] if "/" in path else (path or "root"),
                url=path_to_url(base_url, path, source),
                body=body,
                chunks=chunk_page(path, title, body),
            )
        )
    return pages


class Corpus:
    """Parsed docs: pages by path, their chunks, and reference resolution."""

    def __init__(self, pages: list[Page], base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.pages = pages
        self.by_path = {p.path: p for p in pages}
        self._by_url = {p.url.rstrip("/"): p for p in pages}
        self._by_title = {p.title.lower(): p for p in pages}
        self.chunks = [c for p in pages for c in p.chunks]

    @property
    def sections(self) -> list[str]:
        out: list[str] = []
        for page in self.pages:
            if page.section not in out:
                out.append(page.section)
        return out

    def nav_sections(self) -> list[str]:
        out: list[str] = []
        for page in self.pages:
            if page.nav_section and page.nav_section not in out:
                out.append(page.nav_section)
        return out

    def resolve(self, ref: str) -> Page | None:
        """Accept a doc path, a full URL, a source filename or an exact title."""
        needle = ref.strip()
        if not needle:
            return None
        candidates = [needle, needle.strip("/")]
        if needle.startswith("http"):
            candidates.append(needle.rstrip("/"))
            tail = needle.split("/docs/", 1)[-1] if "/docs/" in needle else needle
            candidates.append(tail.split("#")[0].strip("/"))
        for candidate in candidates:
            hit = self._by_url.get(candidate.rstrip("/")) or self.by_path.get(candidate.strip("/"))
            if hit:
                return hit
        stripped = source_to_path(needle.split("#")[0])
        if stripped in self.by_path:
            return self.by_path[stripped]
        lowered = needle.lower()
        if lowered in self._by_title:
            return self._by_title[lowered]
        tail_matches = [p for p in self.pages if p.path.rsplit("/", 1)[-1] == stripped]
        return tail_matches[0] if len(tail_matches) == 1 else None


def build_corpus(full_text: str, index_text: str, base_url: str) -> Corpus:
    pages = parse_pages(full_text, base_url)
    index = parse_index(index_text)
    enriched: list[Page] = []
    for page in pages:
        entry = index.get(page.url.rstrip("/"))
        enriched.append(
            Page(
                path=page.path,
                source=page.source,
                title=entry.title if entry and entry.title else page.title,
                section=page.section,
                url=page.url,
                body=page.body,
                description=entry.description if entry else "",
                nav_section=entry.nav_section if entry else "",
                chunks=page.chunks,
            )
        )
    return Corpus(enriched, base_url)
