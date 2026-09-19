"""Download and cache the two machine-readable exports the docs site publishes.

`/llms-full.txt` is the whole documentation as one markdown file; `/docs/llms.txt`
is the per-section link index with one-line page descriptions. Both are fetched
conditionally (ETag / Last-Modified), written atomically, and reused from disk,
so the server works with no network once it has run successfully one time.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import MAX_DOWNLOAD_BYTES, Config
from .errors import DocsConfigError, DocsFetchError, DocsOfflineError

FULL_TEXT_FILE = "llms-full.txt"
INDEX_FILE = "docs-llms.txt"
META_FILE = "meta.json"
USER_AGENT = "hermes-docs-mcp/0.1 (+local MCP server)"


@dataclass(frozen=True)
class CachedFile:
    name: str
    path: Path
    present: bool
    bytes: int
    etag: str | None
    last_modified: str | None


def _meta_path(cfg: Config) -> Path:
    return cfg.cache_dir / META_FILE


def read_meta(cfg: Config) -> dict[str, Any]:
    try:
        raw = _meta_path(cfg).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise DocsConfigError(f"cannot read cache metadata: {exc}") from exc
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _write_meta(cfg: Config, meta: dict[str, Any]) -> None:
    _atomic_write(_meta_path(cfg), json.dumps(meta, indent=2, sort_keys=True))


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _ensure_cache_dir(cfg: Config) -> None:
    try:
        cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DocsConfigError(f"cannot create cache dir {cfg.cache_dir}: {exc}") from exc


def cached_files(cfg: Config) -> dict[str, CachedFile]:
    meta = read_meta(cfg)
    files = meta.get("files", {})
    out: dict[str, CachedFile] = {}
    for name in (FULL_TEXT_FILE, INDEX_FILE):
        path = cfg.cache_dir / name
        entry = files.get(name, {}) if isinstance(files, dict) else {}
        present = path.is_file()
        out[name] = CachedFile(
            name=name,
            path=path,
            present=present,
            bytes=path.stat().st_size if present else 0,
            etag=entry.get("etag") if isinstance(entry, dict) else None,
            last_modified=entry.get("last_modified") if isinstance(entry, dict) else None,
        )
    return out


def cache_state(cfg: Config) -> dict[str, Any]:
    """Local cache status. Never touches the network."""
    meta = read_meta(cfg)
    files = cached_files(cfg)
    fetched_at = meta.get("fetched_at")
    age = time.time() - fetched_at if isinstance(fetched_at, int | float) else None
    complete = all(f.present for f in files.values())
    return {
        "cache_dir": str(cfg.cache_dir),
        "complete": complete,
        "fetched_at": fetched_at,
        "age_seconds": round(age) if age is not None else None,
        "stale": complete and (age is None or age > cfg.ttl_seconds),
        "ttl_seconds": cfg.ttl_seconds,
        "offline": cfg.offline,
        "files": {
            name: {"present": f.present, "bytes": f.bytes, "etag": f.etag}
            for name, f in files.items()
        },
    }


async def _download(
    client: httpx.AsyncClient, url: str, dest: Path, cached: CachedFile
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if cached.present and cached.etag:
        headers["If-None-Match"] = cached.etag
    if cached.present and cached.last_modified:
        headers["If-Modified-Since"] = cached.last_modified

    try:
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 304 and cached.present:
                return {"url": url, "changed": False, "status": 304, "bytes": cached.bytes}
            if response.status_code >= 400:
                raise DocsFetchError(
                    f"{url} returned HTTP {response.status_code}", status=response.status_code
                )
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise DocsFetchError(f"{url} exceeds the {MAX_DOWNLOAD_BYTES} byte cap")
                chunks.append(chunk)
            headers_out = response.headers
    except httpx.HTTPError as exc:
        raise DocsFetchError(f"cannot reach {url}: {exc}") from exc

    body = b"".join(chunks).decode("utf-8", errors="replace")
    if not body.strip():
        raise DocsFetchError(f"{url} returned an empty body")
    _atomic_write(dest, body)
    return {
        "url": url,
        "changed": True,
        "status": 200,
        "bytes": total,
        "etag": headers_out.get("etag"),
        "last_modified": headers_out.get("last-modified"),
    }


async def refresh(cfg: Config, *, force: bool = False) -> dict[str, Any]:
    """Re-download both exports. Returns a per-file report."""
    if cfg.offline:
        raise DocsOfflineError(
            "HERMES_DOCS_MCP_OFFLINE is set; refuse to fetch. Unset it to update the cache."
        )
    _ensure_cache_dir(cfg)
    before = cached_files(cfg)
    if force:
        before = {
            name: CachedFile(f.name, f.path, f.present, f.bytes, None, None)
            for name, f in before.items()
        }

    results: dict[str, Any] = {}
    async with httpx.AsyncClient(
        timeout=cfg.timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/plain, */*"},
    ) as client:
        for name, url in ((FULL_TEXT_FILE, cfg.full_text_url), (INDEX_FILE, cfg.index_url)):
            results[name] = await _download(client, url, cfg.cache_dir / name, before[name])

    meta = read_meta(cfg)
    files_meta = meta.get("files")
    if not isinstance(files_meta, dict):
        files_meta = {}
    for name, result in results.items():
        if result.get("changed"):
            files_meta[name] = {
                "etag": result.get("etag"),
                "last_modified": result.get("last_modified"),
                "bytes": result.get("bytes"),
            }
    meta["files"] = files_meta
    meta["fetched_at"] = time.time()
    meta["base_url"] = cfg.base_url
    _write_meta(cfg, meta)

    return {
        "refreshed": True,
        "changed": any(r.get("changed") for r in results.values()),
        "files": results,
        "cache": cache_state(cfg),
    }


async def ensure_cached(cfg: Config) -> dict[str, Any]:
    """Make sure both files exist locally, downloading only when needed.

    A stale-but-present cache is used as-is when the network fails or is
    disabled: outdated docs beat no docs.
    """
    state = cache_state(cfg)
    if state["complete"] and not state["stale"]:
        return {"refreshed": False, "cache": state}
    if cfg.offline:
        if state["complete"]:
            return {"refreshed": False, "offline": True, "cache": state}
        raise DocsOfflineError(
            f"no cached docs in {cfg.cache_dir} and HERMES_DOCS_MCP_OFFLINE is set. "
            "Run once with the network enabled, or point the cache dir at a seeded copy."
        )
    try:
        return await refresh(cfg)
    except (DocsFetchError, DocsConfigError):
        if state["complete"]:
            return {"refreshed": False, "fetch_failed": True, "cache": state}
        raise


def load_sources(cfg: Config) -> tuple[str, str]:
    files = cached_files(cfg)
    try:
        full = files[FULL_TEXT_FILE].path.read_text(encoding="utf-8")
        index = files[INDEX_FILE].path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DocsConfigError(f"cannot read cached docs: {exc}") from exc
    return full, index
