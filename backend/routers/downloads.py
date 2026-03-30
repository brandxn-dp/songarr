"""
Downloads router: track active downloads, cancel, stats, and WebSocket updates.
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import DownloadJob, Song
from schemas import DownloadJobRead, DownloadQueueStats, SongRead, SongWithJob
from services.queue_manager import queue_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["downloads"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/downloads", response_model=list[SongWithJob])
async def list_downloads(db: AsyncSession = Depends(get_db)):
    """Return all songs that are not yet completed, with their latest download job."""
    stmt = (
        select(Song)
        .where(Song.status != "completed")
        .options(selectinload(Song.download_jobs))
        .order_by(Song.created_at.desc())
    )
    songs = (await db.execute(stmt)).scalars().all()

    result = []
    for song in songs:
        latest_job: Optional[DownloadJob] = None
        if song.download_jobs:
            latest_job = max(song.download_jobs, key=lambda j: j.created_at)
        result.append(
            SongWithJob(
                song=SongRead.model_validate(song),
                job=DownloadJobRead.model_validate(latest_job) if latest_job else None,
            )
        )
    return result


@router.get("/downloads/stats", response_model=DownloadQueueStats)
async def download_stats():
    """Return current queue statistics from the QueueManager."""
    stats = queue_manager.get_stats()
    return DownloadQueueStats(**stats)


@router.get("/downloads/{song_id}", response_model=SongWithJob)
async def get_download(song_id: int, db: AsyncSession = Depends(get_db)):
    """Return a single song and its most recent download job."""
    song = await db.get(Song, song_id, options=[selectinload(Song.download_jobs)])
    if song is None:
        raise HTTPException(status_code=404, detail=f"Song id={song_id} not found.")

    latest_job: Optional[DownloadJob] = None
    if song.download_jobs:
        latest_job = max(song.download_jobs, key=lambda j: j.created_at)

    return SongWithJob(
        song=SongRead.model_validate(song),
        job=DownloadJobRead.model_validate(latest_job) if latest_job else None,
    )


@router.delete("/downloads/{song_id}", status_code=204)
async def cancel_download(song_id: int, db: AsyncSession = Depends(get_db)):
    """
    Cancel and remove a download.
    Removes the Song record and all associated DownloadJob records.
    """
    song = await db.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail=f"Song id={song_id} not found.")

    await db.execute(delete(DownloadJob).where(DownloadJob.song_id == song_id))
    await db.delete(song)
    await db.commit()
    logger.info("Cancelled and removed song_id=%d", song_id)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@router.websocket("/ws/downloads")
async def ws_downloads(websocket: WebSocket):
    """
    WebSocket endpoint that streams real-time status updates for all downloads.
    Messages are JSON objects: {song_id, status, progress, error_message}
    """
    await websocket.accept()
    sub_queue = queue_manager.subscribe()
    logger.info("WebSocket client connected.")

    try:
        # Send initial stats on connect
        stats = queue_manager.get_stats()
        await websocket.send_text(json.dumps({"type": "stats", **stats}))

        while True:
            # Wait for either a status update message or a client message
            try:
                message = await asyncio.wait_for(sub_queue.get(), timeout=30.0)
                await websocket.send_text(json.dumps(message))
            except asyncio.TimeoutError:
                # Send a ping/keepalive
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        queue_manager.unsubscribe(sub_queue)
