"""BM25 ranking over documentation chunks.

Pure Python on purpose: ~230 pages is small enough that an in-process index
builds in well under a second, and the server stays dependency-light (mcp +
httpx) so it installs the same way on a laptop and on a VPS.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .corpus import Chunk, Corpus, Page

TOKEN = re.compile(r"[a-z0-9][a-z0-9_.+/-]*")
MD_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
K1 = 1.5
B = 0.75
TITLE_BOOST = 1.35
HEADING_BOOST = 1.25
PHRASE_BOOST = 1.5
# Docs pages put the essentials first, so a chunk near the top of its page wins
# ties against a deep troubleshooting subsection.
POSITION_BOOST = 0.12
# "Where to read next" sections are nothing but links: they match many terms and
# answer nothing. Penalty grows with density — 45% links costs nothing, all links
# costs LINK_DENSITY_PENALTY.
LINK_DENSITY_LIMIT = 0.45
LINK_DENSITY_PENALTY = 0.5
SNIPPET_CHARS = 360
MAX_PER_PAGE = 2
STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how", "i", "in", "is", "it", "its", "of", "on", "or", "that", "the", "to", "use", "using", "what", "when", "where", "which", "with", "you", "your"]
)


def tokenize(text: str) -> list[str]:
    return [t.strip("._-/+") for t in TOKEN.findall(text.lower()) if t.strip("._-/+")]


@dataclass
class Hit:
    page: Page
    chunk: Chunk
    score: float
    snippet: str


class SearchIndex:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self._chunks: list[Chunk] = []
        self._tokens: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._rel_pos: list[float] = []
        self._link_density: list[float] = []
        df: Counter[str] = Counter()
        for page in corpus.pages:
            last = max(len(page.chunks) - 1, 1)
            for position, chunk in enumerate(page.chunks):
                counts = Counter(tokenize(chunk.text))
                self._chunks.append(chunk)
                self._tokens.append(counts)
                self._lengths.append(sum(counts.values()) or 1)
                self._rel_pos.append(position / last)
                linked = sum(len(m.group(0)) for m in MD_LINK.finditer(chunk.text))
                self._link_density.append(linked / max(len(chunk.text), 1))
                df.update(counts.keys())
        self._df = df
        self._n = max(len(self._chunks), 1)
        self._avgdl = (sum(self._lengths) / self._n) if self._lengths else 1.0
        self._page_tokens = {
            p.path: set(tokenize(f"{p.title} {p.path} {p.description}")) for p in corpus.pages
        }

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        section: str | None = None,
        page_ref: str | None = None,
    ) -> list[Hit]:
        terms = [t for t in tokenize(query) if t not in STOPWORDS] or tokenize(query)
        if not terms:
            return []
        phrase = query.strip().lower()
        wanted_page = self.corpus.resolve(page_ref) if page_ref else None
        section_key = section.strip().lower() if section else None

        scored: list[Hit] = []
        for i, chunk in enumerate(self._chunks):
            page = self.corpus.by_path.get(chunk.page_path)
            if page is None:
                continue
            if wanted_page is not None and page.path != wanted_page.path:
                continue
            if section_key and section_key not in {
                page.section.lower(),
                page.nav_section.lower(),
            }:
                continue
            counts = self._tokens[i]
            length = self._lengths[i]
            score = 0.0
            matched = 0
            for term in terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                matched += 1
                denom = tf + K1 * (1 - B + B * length / self._avgdl)
                score += self._idf(term) * (tf * (K1 + 1)) / denom
            if not score:
                continue
            heading_tokens = set(tokenize(chunk.heading_path))
            title_tokens = self._page_tokens.get(page.path, set())
            if any(t in heading_tokens for t in terms):
                score *= HEADING_BOOST
            if any(t in title_tokens for t in terms):
                score *= TITLE_BOOST
            if len(terms) > 1 and phrase in chunk.text.lower():
                score *= PHRASE_BOOST
            score *= 1 + 0.15 * (matched - 1)  # favour chunks covering more terms
            score *= 1 + POSITION_BOOST * (1 - self._rel_pos[i])
            density = self._link_density[i]
            if density > LINK_DENSITY_LIMIT:
                excess = (density - LINK_DENSITY_LIMIT) / (1 - LINK_DENSITY_LIMIT)
                score *= 1 - (1 - LINK_DENSITY_PENALTY) * min(excess, 1.0)
            scored.append(
                Hit(page=page, chunk=chunk, score=score, snippet=snippet(chunk.text, terms))
            )

        scored.sort(key=lambda h: h.score, reverse=True)
        return _diversify(scored, limit)


def _diversify(hits: list[Hit], limit: int) -> list[Hit]:
    """Keep at most MAX_PER_PAGE chunks per page until the limit needs filling."""
    primary: list[Hit] = []
    overflow: list[Hit] = []
    per_page: Counter[str] = Counter()
    for hit in hits:
        if per_page[hit.page.path] < MAX_PER_PAGE:
            per_page[hit.page.path] += 1
            primary.append(hit)
        else:
            overflow.append(hit)
        if len(primary) >= limit:
            break
    return (primary + overflow)[:limit]


def snippet(text: str, terms: list[str], width: int = SNIPPET_CHARS) -> str:
    lowered = text.lower()
    best = -1
    for term in sorted(terms, key=len, reverse=True):
        pos = lowered.find(term)
        if pos >= 0:
            best = pos
            break
    if best < 0:
        best = 0
    start = max(0, best - width // 3)
    end = min(len(text), start + width)
    if start > 0:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < start + 40 else start
    cut = text[start:end].strip()
    cut = re.sub(r"\s*\n\s*", " ", cut)
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(text) else ""
    return f"{prefix}{cut}{suffix}"
