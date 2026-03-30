"""
Spotify router: playlist import, browsing, and queuing tracks for download.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AppSettings, Song, SpotifyPlaylist
from schemas import (
    SpotifyImportRequest,
    SpotifyPlaylistRead,
    SpotifyQueueRequest,
    SpotifyTrackRead,
)
from services.queue_manager import queue_manager
from services.spotify_client import SpotifyService, get_spotify_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["spotify"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_settings(session: AsyncSession) -> dict:
    rows = (await session.execute(select(AppSettings))).scalars().all()
    return {r.key: r.value for r in rows}


def _get_spotify(settings: dict) -> SpotifyService:
    try:
        return get_spotify_service(settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Spotify credentials not configured: {exc}",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/spotify/import", response_model=dict, status_code=201)
async def import_playlist(
    body: SpotifyImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch a Spotify playlist and persist it.
    Returns the playlist record plus the full track list.
    Does NOT automatically queue tracks for download.
    """
    settings = await _load_settings(db)
    sp = _get_spotify(settings)

    try:
        data = sp.get_playlist(body.playlist_url)
    except Exception as exc:
        logger.error("Spotify import error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Spotify error: {exc}")

    # Upsert playlist record
    existing = (
        await db.execute(
            select(SpotifyPlaylist).where(
                SpotifyPlaylist.spotify_playlist_id == data.playlist_id
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.name = data.name
        existing.description = data.description
        existing.track_count = data.track_count
        existing.status = "queued"
        playlist_record = existing
    else:
        playlist_record = SpotifyPlaylist(
            spotify_playlist_id=data.playlist_id,
            name=data.name,
            description=data.description,
            track_count=data.track_count,
            status="queued",
        )
        db.add(playlist_record)

    await db.commit()
    await db.refresh(playlist_record)

    # Build track list with acquisition status
    tracks_out = []
    for t in data.tracks:
        # Check if already in DB
        existing_song = (
            await db.execute(
                select(Song).where(Song.spotify_track_id == t.spotify_id)
            )
        ).scalar_one_or_none()

        tracks_out.append(
            SpotifyTrackRead(
                spotify_id=t.spotify_id,
                title=t.title,
                artist=t.artist,
                artists=t.artists,
                album=t.album,
                album_artist=t.album_artist,
                year=t.year,
                track_number=t.track_number,
                disc_number=t.disc_number,
                duration_ms=t.duration_ms,
                isrc=t.isrc,
                acquisition_status=existing_song.status if existing_song else None,
            )
        )

    return {
        "playlist": SpotifyPlaylistRead.model_validate(playlist_record),
        "tracks": [t.model_dump() for t in tracks_out],
    }


@router.get("/spotify/playlists", response_model=list[SpotifyPlaylistRead])
async def list_playlists(db: AsyncSession = Depends(get_db)):
    """Return all imported Spotify playlists."""
    rows = (
        await db.execute(select(SpotifyPlaylist).order_by(SpotifyPlaylist.imported_at.desc()))
    ).scalars().all()
    return [SpotifyPlaylistRead.model_validate(r) for r in rows]


@router.get("/spotify/playlists/{playlist_db_id}/tracks", response_model=list[SpotifyTrackRead])
async def get_playlist_tracks(
    playlist_db_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Return tracks for an imported playlist with their current acquisition status.
    Re-fetches track data from Spotify.
    """
    pl = await db.get(SpotifyPlaylist, playlist_db_id)
    if pl is None:
        raise HTTPException(status_code=404, detail=f"Playlist id={playlist_db_id} not found.")

    settings = await _load_settings(db)
    sp = _get_spotify(settings)

    try:
        data = sp.get_playlist(pl.spotify_playlist_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Spotify error: {exc}")

    tracks_out = []
    for t in data.tracks:
        existing_song = (
            await db.execute(
                select(Song).where(Song.spotify_track_id == t.spotify_id)
            )
        ).scalar_one_or_none()

        tracks_out.append(
            SpotifyTrackRead(
                spotify_id=t.spotify_id,
                title=t.title,
                artist=t.artist,
                artists=t.artists,
                album=t.album,
                album_artist=t.album_artist,
                year=t.year,
                track_number=t.track_number,
                disc_number=t.disc_number,
                duration_ms=t.duration_ms,
                isrc=t.isrc,
                acquisition_status=existing_song.status if existing_song else None,
            )
        )
    return tracks_out


@router.post("/spotify/playlists/{playlist_db_id}/queue", response_model=dict, status_code=202)
async def queue_playlist_tracks(
    playlist_db_id: int,
    body: SpotifyQueueRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Queue playlist tracks for download.
    Pass specific spotify track IDs in body.track_ids, or leave empty to queue all.
    Returns {queued: int}.
    """
    pl = await db.get(SpotifyPlaylist, playlist_db_id)
    if pl is None:
        raise HTTPException(status_code=404, detail=f"Playlist id={playlist_db_id} not found.")

    settings = await _load_settings(db)
    sp = _get_spotify(settings)

    try:
        data = sp.get_playlist(pl.spotify_playlist_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Spotify error: {exc}")

    # Filter tracks if specific IDs were requested
    target_ids = set(body.track_ids)
    tracks_to_queue = (
        [t for t in data.tracks if t.spotify_id in target_ids]
        if target_ids
        else data.tracks
    )

    queued_count = 0
    for t in tracks_to_queue:
        # Skip if already in DB with a non-failed status
        existing = (
            await db.execute(
                select(Song).where(Song.spotify_track_id == t.spotify_id)
            )
        ).scalar_one_or_none()

        if existing and existing.status not in ("failed",):
            continue

        if existing and existing.status == "failed":
            # Reset and re-queue
            existing.status = "queued"
            existing.error_message = None
            await db.commit()
            await queue_manager.enqueue(existing.id)
            queued_count += 1
            continue

        song = Song(
            title=t.title,
            artist=t.artist,
            album=t.album,
            album_artist=t.album_artist,
            year=t.year,
            track_number=t.track_number,
            disc_number=t.disc_number,
            spotify_track_id=t.spotify_id,
            spotify_playlist_id=pl.spotify_playlist_id,
            status="queued",
        )
        db.add(song)
        await db.commit()
        await db.refresh(song)
        await queue_manager.enqueue(song.id)
        queued_count += 1

    # Update playlist status
    if queued_count > 0:
        pl.status = "in_progress"
        await db.commit()

    logger.info(
        "Queued %d tracks from playlist id=%d (%s)",
        queued_count, playlist_db_id, pl.name,
    )
    return {"queued": queued_count, "playlist_id": playlist_db_id}
