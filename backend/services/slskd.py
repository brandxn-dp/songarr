"""
Async httpx client wrapping the slskd REST API.
"""
import asyncio
import logging
import os
from pathlib import PurePosixPath
from typing import Optional

import httpx

from schemas import SearchResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------

def _quality_score(fmt: str, bitrate: Optional[int]) -> int:
    fmt_upper = (fmt or "").upper()
    if fmt_upper in ("FLAC", "ALAC", "WAV", "AIFF"):
        return 100
    if fmt_upper in ("MP3", "OGG", "AAC", "M4A", "OPUS"):
        br = bitrate or 0
        if br >= 320:
            return 90
        if br >= 256:
            return 70
        if br >= 192:
            return 55
        if br >= 128:
            return 40
        return 20
    return 20


def _extension_to_format(ext: str) -> str:
    mapping = {
        ".mp3": "MP3",
        ".flac": "FLAC",
        ".ogg": "OGG",
        ".opus": "OPUS",
        ".m4a": "M4A",
        ".aac": "AAC",
        ".alac": "ALAC",
        ".wav": "WAV",
        ".aiff": "AIFF",
        ".wma": "WMA",
    }
    return mapping.get(ext.lower(), ext.lstrip(".").upper())


def _parse_search_response(raw_responses: list[dict]) -> list[SearchResult]:
    """
    Convert slskd search response list into SearchResult objects.
    Each element in raw_responses is a peer response object.
    """
    results: list[SearchResult] = []
    for peer in raw_responses:
        username = peer.get("username", "")
        for f in peer.get("files", []):
            filename: str = f.get("filename", "")
            if not filename:
                continue

            size: int = f.get("size", 0)
            display_name = PurePosixPath(filename.replace("\\", "/")).name

            # Determine extension / format
            ext = os.path.splitext(display_name)[1]
            fmt = _extension_to_format(ext)

            # Extract bitrate from file attributes list
            bitrate: Optional[int] = None
            for attr in f.get("attributes", []):
                # slskd attribute types: 0=bitRate, 1=length, 2=vbr, 4=sampleRate, 5=bitDepth, 6=channelCount
                if attr.get("type") == 0:
                    bitrate = attr.get("value")
                    break

            score = _quality_score(fmt, bitrate)
            size_mb = round(size / (1024 * 1024), 2) if size else 0.0

            results.append(
                SearchResult(
                    username=username,
                    filename=filename,
                    display_name=display_name,
                    file_format=fmt,
                    bitrate=bitrate,
                    file_size_bytes=size,
                    file_size_mb=size_mb,
                    quality_score=score,
                )
            )
    return results


# ---------------------------------------------------------------------------
# SlskdClient
# ---------------------------------------------------------------------------

class SlskdClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=60.0,
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, query: str, timeout: int = 30) -> list[SearchResult]:
        """
        POST /api/v0/searches to initiate a search, then poll until complete.
        Returns a list of SearchResult objects sorted by quality_score desc.
        """
        async with self._client() as client:
            # Start search
            payload = {
                "searchText": query,
                "filterResponses": False,
                "minimumResponseFileCount": 1,
            }
            resp = await client.post("/api/v0/searches", json=payload)
            resp.raise_for_status()
            search_data = resp.json()
            search_id: str = search_data.get("id", "")
            if not search_id:
                logger.warning("slskd search returned no id")
                return []

            # Poll until state == "Completed" or timeout
            deadline = asyncio.get_running_loop().time() + timeout
            poll_interval = 1.5
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(poll_interval)
                poll_resp = await client.get(f"/api/v0/searches/{search_id}")
                if poll_resp.status_code == 404:
                    break
                poll_resp.raise_for_status()
                poll_data = poll_resp.json()
                state: str = poll_data.get("state", "")
                if "Completed" in state or "Finished" in state or state == "Completed":
                    break
                # Reduce polling frequency after first few seconds
                poll_interval = min(poll_interval * 1.2, 3.0)

            # Fetch full results
            results_resp = await client.get(f"/api/v0/searches/{search_id}/responses")
            if results_resp.status_code == 404:
                return []
            results_resp.raise_for_status()
            raw: list[dict] = results_resp.json()

            parsed = _parse_search_response(raw)
            parsed.sort(key=lambda r: r.quality_score, reverse=True)
            return parsed

    # ------------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------------

    async def download(self, username: str, filename: str, size: int) -> str:
        """
        Enqueue a download from a specific peer.
        POST /api/v0/transfers/downloads/{username}
        Returns the slskd transfer id.
        """
        async with self._client() as client:
            payload = {"filename": filename, "size": size}
            resp = await client.post(
                f"/api/v0/transfers/downloads/{username}", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            # slskd returns the transfer object; id may be in 'id' field
            transfer_id: str = data.get("id", "")
            logger.info(
                "Initiated download from %s, file=%s, transfer_id=%s",
                username,
                filename,
                transfer_id,
            )
            return transfer_id

    async def get_download_status(self, username: str, transfer_id: str) -> dict:
        """
        GET /api/v0/transfers/downloads/{username}/{id}
        Returns the raw transfer dict from slskd.
        """
        async with self._client() as client:
            resp = await client.get(
                f"/api/v0/transfers/downloads/{username}/{transfer_id}"
            )
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            return resp.json()

    async def get_all_downloads(self) -> list[dict]:
        """
        GET /api/v0/transfers/downloads
        Returns list of all peer download groups.
        """
        async with self._client() as client:
            resp = await client.get("/api/v0/transfers/downloads")
            resp.raise_for_status()
            return resp.json()

    async def get_application_info(self) -> dict:
        """
        GET /api/v0/application
        Returns slskd application state including download directory.
        """
        async with self._client() as client:
            resp = await client.get("/api/v0/application")
            resp.raise_for_status()
            return resp.json()

    async def delete_search(self, search_id: str) -> None:
        """Clean up a search by ID."""
        try:
            async with self._client() as client:
                await client.delete(f"/api/v0/searches/{search_id}")
        except Exception as exc:
            logger.debug("Failed to delete search %s: %s", search_id, exc)


# ---------------------------------------------------------------------------
# Module-level helper that builds a client from DB or config settings
# ---------------------------------------------------------------------------

def get_slskd_client(slskd_url: str, api_key: str) -> SlskdClient:
    return SlskdClient(base_url=slskd_url, api_key=api_key)
