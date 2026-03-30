"""
Search router: manual search, manual download initiation, and auto-search.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AppSettings, DownloadJob, Song
from schemas import AutoSearchRequest, ManualDownloadRequest, SearchResult, SongRead
from services.queue_manager import queue_manager
from services.slskd import SlskdClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_settings(session: AsyncSession) -> dict:
    rows = (await session.execute(select(AppSettings))).scalars().all()
    return {r.key: r.value for r in rows}


def _get_slskd(settings: dict) -> SlskdClient:
    return SlskdClient(
        base_url=settings.get("slskd_url", "http://localhost:5030"),
        api_key=settings.get("slskd_api_key", ""),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/search", response_model=list[SearchResult])
async def search_soulseek(
    artist: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    raw_query: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Search Soulseek via slskd for songs.
    Pass `artist` + `title`, or a freeform `raw_query`.
    """
    if raw_query:
        query = raw_query
    elif artist and title:
        query = f"{artist} {title}"
    elif artist:
        query = artist
    elif title:
        query = title
    else:
        raise HTTPException(status_code=400, detail="Provide artist, title, or raw_query.")

    settings = await _load_settings(db)
    client = _get_slskd(settings)
    try:
        results = await client.search(query)
    except Exception as exc:
        logger.error("slskd search error: %s", exc)
        raise HTTPException(status_code=502, detail=f"slskd search failed: {exc}")

    return results


@router.post("/search/download", response_model=SongRead, status_code=201)
async def manual_download(
    body: ManualDownloadRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate a download for a specific search result.
    Optionally link to an existing Song by song_id; otherwise create a new one.
    """
    settings = await _load_settings(db)

    # Resolve or create Song
    if body.song_id:
        song = await db.get(Song, body.song_id)
        if song is None:
            raise HTTPException(status_code=404, detail=f"Song id={body.song_id} not found.")
    else:
        song = Song(
            title=body.title,
            artist=body.artist,
            album=body.album,
            year=body.year,
            status="queued",
        )
        db.add(song)
        await db.commit()
        await db.refresh(song)

    # Determine file format from filename extension
    import os
    ext = os.path.splitext(body.filename)[1].lstrip(".").upper() or "UNKNOWN"

    job = DownloadJob(
        song_id=song.id,
        slskd_username=body.username,
        slskd_filename=body.filename,
        file_format=ext,
        file_size_bytes=body.file_size_bytes,
        status="queued",
        progress_percent=0.0,
    )
    db.add(job)
    await db.commit()

    await queue_manager.enqueue(song.id)
    logger.info("Manual download queued: song_id=%d, file=%s", song.id, body.filename)

    await db.refresh(song)
    return SongRead.model_validate(song)


@router.post("/search/auto", response_model=SongRead, status_code=201)
async def auto_search_and_queue(
    body: AutoSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Search slskd, auto-pick the best result, create a Song record and enqueue.
    """
    settings = await _load_settings(db)
    client = _get_slskd(settings)

    query = f"{body.artist} {body.title}"
    try:
        results = await client.search(query)
    except Exception as exc:
        logger.error("slskd auto-search error: %s", exc)
        raise HTTPException(status_code=502, detail=f"slskd search failed: {exc}")

    if not results:
        raise HTTPException(status_code=404, detail="No results found on Soulseek for this query.")

    best = results[0]

    song = Song(
        title=body.title,
        artist=body.artist,
        album=body.album,
        year=body.year,
        status="queued",
    )
    db.add(song)
    await db.commit()
    await db.refresh(song)

    job = DownloadJob(
        song_id=song.id,
        slskd_username=best.username,
        slskd_filename=best.filename,
        file_format=best.file_format,
        bitrate=best.bitrate,
        file_size_bytes=best.file_size_bytes,
        status="queued",
        progress_percent=0.0,
    )
    db.add(job)
    await db.commit()

    await queue_manager.enqueue(song.id)
    logger.info(
        "Auto-queued song_id=%d: %s - %s (format=%s, quality=%d)",
        song.id, body.artist, body.title, best.file_format, best.quality_score,
    )

    await db.refresh(song)
    return SongRead.model_validate(song)
