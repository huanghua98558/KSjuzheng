# -*- coding: utf-8 -*-
"""Unified drama library — the core of Level 4 (drama acquisition).

Business logic reverse-engineered from KS184 UI log
  ``[高转化提取] 「XXX」从全局匹配到记录``
  ``[高转化提取] ✓ 「XXX」匹配成功 -> https://...``

Meaning:
  1. MCN pushes a list of "sanctioned" drama names via /api/collect-pool.
  2. Local download_cache stores past video downloads keyed by drama_url.
  3. A drama is PUBLISHABLE when it has BOTH a name (from collect-pool)
     AND a resolved URL (from download_cache).
  4. Names without matching URLs need a download step first.

This module:
  - pulls collect-pool → names table
  - joins with download_cache → resolved names
  - upserts result into drama_links (keyed by drama_url)
  - exposes helpers to pick the next drama to publish, filter by account,
    and report which names still need URL resolution.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from core.mcn_client import MCN_BASE, MCNClient

log = logging.getLogger(__name__)


@dataclass
class DramaEntry:
    drama_name: str
    drama_url: str | None
    collect_pool_id: int | None = None
    source: str = "collect_pool"
    created_at: str | None = None


class DramaLibrary:
    """Drama acquisition / de-dup / publishable-query layer."""

    def __init__(self, db_manager, mcn_client: MCNClient | None = None):
        self.db = db_manager
        self.mcn = mcn_client or MCNClient()
        self._token: str | None = None

    # ------------------------------------------------------------------
    # Low-level: MCN collect-pool
    # ------------------------------------------------------------------

    def _fetch_collect_pool(self) -> list[dict[str, Any]]:
        """GET /api/collect-pool — returns raw list of 17+ items."""
        if self._token is None:
            self._token = self.mcn.login()
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        r = requests.get(f"{MCN_BASE}/api/collect-pool", headers=headers, timeout=10)
        j = r.json()
        if not j.get("success"):
            log.error("[DramaLibrary] collect-pool failed: %s", j)
            return []
        return j.get("data") or []

    @staticmethod
    def _is_url(s: str) -> bool:
        return isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))

    @staticmethod
    def _extract_drama_name_from_url(url: str) -> str:
        """Best-effort: pull the ``/f/{SHORTID}`` segment as a placeholder name.

        collect-pool sometimes stores a bare kuaishou.com/f/... URL as ``name``.
        Without side channels we can't recover the real drama title from such
        entries — flag them with a synthetic name for tracking.
        """
        import re
        m = re.search(r"/f/([A-Za-z0-9\-]+)", url)
        if m:
            return f"[URL_ONLY]{m.group(1)}"
        return f"[URL_ONLY]{url[-32:]}"

    # ------------------------------------------------------------------
    # Join with local download_cache
    # ------------------------------------------------------------------

    def _load_download_cache_map(self) -> dict[str, list[dict[str, Any]]]:
        """Return drama_name → list of download_cache rows.

        ``download_cache.file_path`` encodes the drama name in the path:
           ``...\short_drama_videos\{acct}\{drama_name}\cover.jpg``

        We parse that out as the canonical name. The drama_url column is the
        actual kuaishou.com URL for that drama.
        """
        rows = self.db.conn.execute(
            """SELECT drama_url, drama_url_hash, cache_type, file_path,
                      file_size, use_count, created_time
               FROM download_cache"""
        ).fetchall()
        cache_by_name: dict[str, list[dict]] = {}
        for r in rows:
            url, url_hash, ctype, fp, fsize, ucnt, cts = r
            # Parse drama name from path: ..\short_drama_videos\{acct}\{drama_name}\...
            parts = (fp or "").replace("/", "\\").split("\\")
            drama_name = None
            for i, p in enumerate(parts):
                if p == "short_drama_videos" and i + 2 < len(parts):
                    drama_name = parts[i + 2]
                    break
            if not drama_name:
                continue
            cache_by_name.setdefault(drama_name, []).append({
                "drama_url": url,
                "drama_url_hash": url_hash,
                "cache_type": ctype,
                "file_path": fp,
                "file_size": fsize,
                "use_count": ucnt,
                "created_time": cts,
            })
        return cache_by_name

    # ------------------------------------------------------------------
    # Main sync
    # ------------------------------------------------------------------

    def sync(self, link_mode: str = "firefly") -> dict[str, Any]:
        """Pull collect-pool + merge download_cache + upsert drama_links.

        Returns stats dict:
          {
            collect_pool_rows:   17,
            download_cache_rows: 18,
            matched:             N,   # have both name+url
            missing_urls:        M,   # name only (need download)
            upserted:            K,   # rows inserted/updated in drama_links
            name_only:           [...list of drama_names missing a URL...],
          }
        """
        pool = self._fetch_collect_pool()
        cache_map = self._load_download_cache_map()

        entries: list[DramaEntry] = []
        missing_names: list[str] = []

        for item in pool:
            raw_name = item.get("name") or ""
            pool_id = item.get("id")
            created_at = item.get("created_at")

            # Case 1: ``name`` is actually a URL — record as URL-only.
            if self._is_url(raw_name):
                entries.append(DramaEntry(
                    drama_name=self._extract_drama_name_from_url(raw_name),
                    drama_url=raw_name,
                    collect_pool_id=pool_id,
                    created_at=created_at,
                ))
                continue

            # Case 2: ``name`` is a drama title — look up local cache for URL.
            drama_name = raw_name.strip()
            hits = cache_map.get(drama_name)
            if hits:
                # Prefer 'video' cache over 'cover' if both exist
                best = None
                for h in hits:
                    if h["cache_type"] == "video":
                        best = h; break
                best = best or hits[0]
                entries.append(DramaEntry(
                    drama_name=drama_name,
                    drama_url=best["drama_url"],
                    collect_pool_id=pool_id,
                    created_at=created_at,
                ))
            else:
                missing_names.append(drama_name)
                # Still register a stub entry so tracking works; use synthetic URL.
                # UNIQUE constraint is (drama_url, link_mode) so stub URL must be
                # unique-ish. We use a stable hash-like placeholder.
                entries.append(DramaEntry(
                    drama_name=drama_name,
                    drama_url=None,  # stub later — or skip insert
                    collect_pool_id=pool_id,
                    created_at=created_at,
                ))

        # Upsert only entries with real URLs (drama_url NOT NULL constraint).
        upserted = 0
        now = datetime.utcnow().isoformat()
        for e in entries:
            if not e.drama_url:
                continue
            try:
                self.db.conn.execute(
                    """INSERT INTO drama_links
                         (drama_name, drama_url, source_file, link_mode,
                          status, remark, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                       ON CONFLICT(drama_url, link_mode) DO UPDATE SET
                         drama_name = excluded.drama_name,
                         updated_at = excluded.updated_at,
                         remark = excluded.remark""",
                    (
                        e.drama_name, e.drama_url,
                        f"collect-pool:{e.collect_pool_id}",
                        link_mode,
                        f"pool_id={e.collect_pool_id}",
                        now, now,
                    ),
                )
                upserted += 1
            except Exception as exc:
                log.error("[DramaLibrary] upsert failed for %s: %s", e.drama_name, exc)
        self.db.conn.commit()

        stats = {
            "collect_pool_rows": len(pool),
            "download_cache_rows": sum(len(v) for v in cache_map.values()),
            "download_cache_unique_names": len(cache_map),
            "matched": sum(1 for e in entries if e.drama_url),
            "missing_urls": len(missing_names),
            "upserted": upserted,
            "name_only": missing_names,
        }
        log.info("[DramaLibrary] sync complete: %s",
                 {k: v for k, v in stats.items() if k != "name_only"})
        return stats

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list_publishable(self, link_mode: str = "firefly",
                         limit: int = 20) -> list[dict[str, Any]]:
        """Return pending dramas (have name+url) ready to publish.

        Excludes dramas that already have status='completed' or 'used'.
        """
        rows = self.db.conn.execute(
            """SELECT id, drama_name, drama_url, source_file, status,
                      use_count, created_at
               FROM drama_links
               WHERE link_mode = ? AND status = 'pending'
                 AND drama_url IS NOT NULL AND drama_url != ''
               ORDER BY use_count ASC, id DESC
               LIMIT ?""",
            (link_mode, limit),
        ).fetchall()
        cols = ["id", "drama_name", "drama_url", "source_file", "status",
                "use_count", "created_at"]
        return [dict(zip(cols, r)) for r in rows]

    def list_unresolved(self) -> list[dict[str, Any]]:
        """Return drama names from collect-pool that have no URL yet.

        These need a download step (via VideoDownloader) before they can
        enter the publish pipeline.
        """
        pool = self._fetch_collect_pool()
        cache_map = self._load_download_cache_map()
        unresolved = []
        for item in pool:
            raw_name = item.get("name") or ""
            if self._is_url(raw_name):
                continue
            name = raw_name.strip()
            if name not in cache_map:
                unresolved.append({
                    "drama_name": name,
                    "collect_pool_id": item.get("id"),
                    "created_at": item.get("created_at"),
                })
        return unresolved
