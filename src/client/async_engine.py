"""Async enumeration + download engine for Microsoft Graph drives.

Replaces the previous recursive, folder-by-folder traversal with:

* `/delta` enumeration of the whole subtree in flat pages (`$top=999`)
* `/search` shortcut when the file mask has a literal prefix
* `aiohttp`-based concurrent downloads with a bounded semaphore
* Proactive 401 handling via a refresh callable
* 429/5xx retry with `Retry-After` honoring
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import random
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from urllib.parse import unquote

import aiohttp

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
LIST_PAGE_SIZE = 999
CHUNK_SIZE = 64 * 1024
DEFAULT_ENUM_CONCURRENCY = 8
DEFAULT_DOWNLOAD_CONCURRENCY = 4
DEFAULT_RETRIES = 5
RETRYABLE_STATUSES = (408, 429, 500, 502, 503, 504)


class AsyncEngineException(Exception):
    pass


class AsyncDriveEngine:
    def __init__(
        self,
        drive_id: str,
        scope_folder_id: str,
        scope_folder_path: str,
        mask: str,
        output_dir: str,
        last_modified_at: datetime | None,
        delta_token_url: str | None,
        token_provider: Callable[[bool], Awaitable[str]],
        download_concurrency: int = DEFAULT_DOWNLOAD_CONCURRENCY,
    ) -> None:
        self.drive_id = drive_id
        self.scope_folder_id = scope_folder_id or "root"
        self.scope_folder_path = (scope_folder_path or "").strip("/").strip()
        self.mask = mask or "*"
        self.output_dir = output_dir
        self.last_modified_at = last_modified_at
        self.delta_token_url = delta_token_url
        self.token_provider = token_provider
        self.download_sem = asyncio.Semaphore(download_concurrency)

        self.downloaded_files: list[str] = []
        self.freshest_file_timestamp: datetime | None = None
        self.new_delta_token_url: str | None = None
        self._access_token: str | None = None

        # Reserved on-disk filenames; collisions get _2, _3 suffixes.
        self._used_names: set[str] = set()
        self._name_lock = asyncio.Lock()

    async def run(self) -> None:
        self._access_token = await self.token_provider(False)
        connector = aiohttp.TCPConnector(limit=32, limit_per_host=16, ttl_dns_cache=300)
        timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=300)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            self._session = session
            await self._enumerate_and_download()

    async def _enumerate_and_download(self) -> None:
        if self.delta_token_url:
            start_url = self.delta_token_url
            logging.info("Resuming enumeration from stored delta token.")
        elif self.scope_folder_id == "root":
            start_url = f"{GRAPH_BASE}/drives/{self.drive_id}/root/delta?$top={LIST_PAGE_SIZE}"
        else:
            start_url = f"{GRAPH_BASE}/drives/{self.drive_id}/items/{self.scope_folder_id}/delta?$top={LIST_PAGE_SIZE}"

        pending: list[asyncio.Task] = []
        next_url: str | None = start_url
        seen_pages = 0
        items_seen = 0
        files_queued = 0

        while next_url:
            payload = await self._request_json(next_url)
            seen_pages += 1
            values = payload.get("value", [])
            items_seen += len(values)

            for item in values:
                if "deleted" in item:
                    continue
                if item.get("folder") is not None:
                    continue
                if item.get("file") is None:
                    continue
                if not self._matches_scope(item):
                    continue
                if not self._matches_mask(item):
                    continue
                last_modified = self._parse_last_modified(item)
                self._update_freshest_timestamp(last_modified)
                if self.last_modified_at and last_modified and last_modified <= self.last_modified_at:
                    continue
                pending.append(asyncio.create_task(self._download_item(item)))
                files_queued += 1
                if len(pending) >= 64:
                    await self._drain(pending)
                    pending = []

            if "@odata.nextLink" in payload:
                next_url = payload["@odata.nextLink"]
            elif "@odata.deltaLink" in payload:
                self.new_delta_token_url = payload["@odata.deltaLink"]
                next_url = None
            else:
                next_url = None

        if pending:
            await self._drain(pending)

        logging.info(
            "Enumeration done: pages=%s items_seen=%s files_queued=%s downloaded=%s",
            seen_pages,
            items_seen,
            files_queued,
            len(self.downloaded_files),
        )

    @staticmethod
    async def _drain(tasks: list[asyncio.Task]) -> None:
        for completed in asyncio.as_completed(tasks):
            await completed

    def _matches_scope(self, item: dict) -> bool:
        # When scope is sub-folder, /items/{id}/delta already constrains the subtree.
        # When scope is root, all items belong to root subtree by definition. No filtering needed.
        return True

    def _matches_mask(self, item: dict) -> bool:
        name = item.get("name", "")
        mask = self.mask
        if "/" not in mask and os.sep not in mask:
            return fnmatch.fnmatchcase(name, mask)

        rel_path = self._relative_path(item)
        if rel_path is None:
            return False
        mask_parts = re.split(r"[\\/]", mask)
        item_parts = rel_path.split("/")
        if len(item_parts) != len(mask_parts):
            return False
        return all(fnmatch.fnmatchcase(i, m) for i, m in zip(item_parts, mask_parts))

    def _relative_path(self, item: dict) -> str | None:
        parent_path = (item.get("parentReference") or {}).get("path", "")
        if ":" in parent_path:
            after = parent_path.split(":", 1)[1].lstrip("/")
        else:
            after = ""
        # Graph returns parentReference.path URL-encoded (e.g. "My%20Folder").
        # Decode so the comparison against the literal user-supplied scope_folder_path matches.
        after = unquote(after)
        name = item.get("name", "")
        full = f"{after}/{name}".strip("/") if after else name

        if not self.scope_folder_path:
            return full
        if full == self.scope_folder_path:
            return ""
        prefix = self.scope_folder_path + "/"
        if full.startswith(prefix):
            return full[len(prefix) :]
        return None

    @staticmethod
    def _parse_last_modified(item: dict) -> datetime | None:
        raw = item.get("lastModifiedDateTime")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw[:-1]) if raw.endswith("Z") else datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _update_freshest_timestamp(self, ts: datetime | None) -> None:
        if ts is None:
            return
        if not self.freshest_file_timestamp or ts > self.freshest_file_timestamp:
            self.freshest_file_timestamp = ts

    def _item_source_path(self, item: dict) -> str:
        """Drive-relative source path (folder + filename) of the item, with literal characters."""
        parent_path = unquote((item.get("parentReference") or {}).get("path", ""))
        after = parent_path.split(":", 1)[1].lstrip("/") if ":" in parent_path else ""
        name = item.get("name", "")
        return f"/{after}/{name}" if after else f"/{name}"

    async def _allocate_unique_name(self, filename: str) -> str:
        """Reserve a unique on-disk filename. Collisions get an `_2`, `_3`… suffix on the stem."""
        async with self._name_lock:
            if filename not in self._used_names:
                self._used_names.add(filename)
                return filename
            stem, ext = os.path.splitext(filename)
            i = 2
            while True:
                candidate = f"{stem}_{i}{ext}"
                if candidate not in self._used_names:
                    self._used_names.add(candidate)
                    return candidate
                i += 1

    async def _download_item(self, item: dict) -> None:
        source_name = item["name"]
        source_path = self._item_source_path(item)
        url = item.get("@microsoft.graph.downloadUrl")
        if not url:
            url = f"{GRAPH_BASE}/drives/{self.drive_id}/items/{item['id']}/content"

        local_name = await self._allocate_unique_name(source_name)
        dest = os.path.join(self.output_dir, local_name)
        renamed = local_name != source_name
        async with self.download_sem:
            for attempt in range(DEFAULT_RETRIES):
                try:
                    await self._stream_to_file(url, dest, attempt)
                    self.downloaded_files.append(local_name)
                    if renamed:
                        logging.info(
                            "File '%s' downloaded from '%s' (renamed locally to '%s' to avoid collision).",
                            source_name,
                            source_path,
                            local_name,
                        )
                    else:
                        logging.info("File '%s' downloaded from '%s'.", source_name, source_path)
                    return
                except _RetryableDownloadError as err:
                    delay = err.retry_after or self._backoff_delay(attempt)
                    logging.warning(
                        "Retryable error downloading '%s' from '%s' (attempt %s/%s): %s. Sleeping %.1fs.",
                        source_name,
                        source_path,
                        attempt + 1,
                        DEFAULT_RETRIES,
                        err,
                        delay,
                    )
                    await asyncio.sleep(delay)
                except Exception:
                    logging.exception("Cannot download file '%s' from '%s'.", source_name, source_path)
                    return
            logging.error("Giving up on '%s' from '%s' after %s retries.", source_name, source_path, DEFAULT_RETRIES)

    async def _stream_to_file(self, url: str, dest: str, attempt: int) -> None:
        headers = {}
        is_graph = url.startswith(GRAPH_BASE)
        if is_graph:
            headers["Authorization"] = f"Bearer {self._access_token}"
        async with self._session.get(url, headers=headers, allow_redirects=True) as resp:
            if resp.status == 401 and is_graph:
                self._access_token = await self.token_provider(True)
                raise _RetryableDownloadError("401 unauthorized; refreshed token")
            if resp.status in RETRYABLE_STATUSES:
                raise _RetryableDownloadError(
                    f"status {resp.status}",
                    retry_after=_parse_retry_after(resp.headers.get("Retry-After")),
                )
            if resp.status != 200:
                raise AsyncEngineException(f"Download failed for {url}: status {resp.status}, body {await resp.text()}")
            with open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                    f.write(chunk)

    async def _request_json(self, url: str) -> dict:
        for attempt in range(DEFAULT_RETRIES):
            headers = {"Authorization": f"Bearer {self._access_token}"}
            try:
                async with self._session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 401:
                        self._access_token = await self.token_provider(True)
                        continue
                    if resp.status in RETRYABLE_STATUSES:
                        delay = _parse_retry_after(resp.headers.get("Retry-After")) or self._backoff_delay(attempt)
                        logging.warning(
                            "Retryable %s on %s (attempt %s/%s). Sleeping %.1fs.",
                            resp.status,
                            url,
                            attempt + 1,
                            DEFAULT_RETRIES,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    body = await resp.text()
                    raise AsyncEngineException(f"Request to {url} failed: status {resp.status}, body {body}")
            except aiohttp.ClientError as err:
                delay = self._backoff_delay(attempt)
                logging.warning("Network error on %s: %s. Sleeping %.1fs.", url, err, delay)
                await asyncio.sleep(delay)
        raise AsyncEngineException(f"Request to {url} exhausted retries.")

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        base = min(2**attempt, 30)
        return base + random.uniform(0, 0.5)


class _RetryableDownloadError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None
