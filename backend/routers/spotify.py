"""
Spotify router: playlist import, browsing, and queuing tracks for download.
"""
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
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


async def _get_spotify_with_oauth(db: AsyncSession) -> SpotifyService:
    """
    Build a SpotifyService using OAuth access token if available and valid,
    refreshing if needed, falling back to Client Credentials otherwise.
    """
    settings = await _load_settings(db)
    client_id = settings.get("spotify_client_id", "")
    client_secret = settings.get("spotify_client_secret", "")

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=422,
            detail="Spotify credentials not configured.",
        )

    access_token = settings.get("spotify_access_token", "")
    expires_at = int(settings.get("spotify_token_expires", "0") or "0")
    refresh_tok = settings.get("spotify_refresh_token", "")
    redirect_uri = ""  # not needed for refresh, but required by SpotifyOAuth constructor

    # Determine a redirect_uri placeholder (not used for refresh, just needed for init)
    # We use a dummy value since refresh doesn't need it to match Spotify's redirect
    redirect_uri = "http://localhost:8000/api/spotify/callback"

    # Check if token is valid (with 60s buffer)
    if access_token and expires_at > (time.time() - 60):
        logger.debug("Using stored OAuth access token for Spotify.")
        return SpotifyService(client_id=client_id, client_secret=client_secret, access_token=access_token)

    # Token expired but we have a refresh token
    if refresh_tok:
        logger.info("OAuth access token expired; refreshing.")
        try:
            token_info = SpotifyService.refresh_token(client_id, client_secret, redirect_uri, refresh_tok)
        except Exception as exc:
            logger.warning("Failed to refresh Spotify token: %s; falling back to Client Credentials.", exc)
            return SpotifyService(client_id=client_id, client_secret=client_secret)

        new_access_token = token_info.get("access_token", "")
        new_refresh_token = token_info.get("refresh_token", refresh_tok)
        new_expires_at = token_info.get("expires_at", 0)

        # Persist refreshed tokens
        async def _upsert(key, val):
            existing = (await db.execute(select(AppSettings).where(AppSettings.key == key))).scalar_one_or_none()
            if existing:
                existing.value = str(val)
            else:
                db.add(AppSettings(key=key, value=str(val)))

        await _upsert("spotify_access_token", new_access_token)
        await _upsert("spotify_refresh_token", new_refresh_token)
        await _upsert("spotify_token_expires", str(new_expires_at))
        await db.commit()

        if new_access_token:
            return SpotifyService(client_id=client_id, client_secret=client_secret, access_token=new_access_token)

    # No OAuth tokens available — fall back to Client Credentials (public playlists only)
    logger.debug("No OAuth tokens; using Client Credentials for Spotify.")
    return SpotifyService(client_id=client_id, client_secret=client_secret)


def _raise_spotify_error(exc: Exception) -> None:
    """Raise a user-friendly HTTPException for common Spotify errors."""
    msg = str(exc)
    if "Forbidden" in msg or "403" in msg:
        raise HTTPException(
            status_code=502,
            detail=(
                "This playlist is private. Connect your Spotify account in Settings "
                "to access private playlists."
            ),
        )
    if "Not found" in msg or "404" in msg:
        raise HTTPException(
            status_code=502,
            detail=(
                "This playlist could not be found. Note: Spotify editorial playlists "
                "(Discover Weekly, Daily Mix, Radio) cannot be accessed via the API."
            ),
        )
    raise HTTPException(status_code=502, detail=f"Spotify error: {exc}")


# ---------------------------------------------------------------------------
# OAuth Routes
# ---------------------------------------------------------------------------

@router.get("/spotify/auth")
async def spotify_auth(request: Request, db: AsyncSession = Depends(get_db)):
    """Return Spotify OAuth URL for the user to visit."""
    settings = await _load_settings(db)
    client_id = settings.get("spotify_client_id", "")
    client_secret = settings.get("spotify_client_secret", "")
    if not client_id or not client_secret:
        raise HTTPException(422, "Spotify credentials not configured")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/spotify/callback"
    auth_url = SpotifyService.get_auth_url(client_id, client_secret, redirect_uri)
    return {"auth_url": auth_url, "redirect_uri": redirect_uri}


@router.get("/spotify/callback")
async def spotify_callback(code: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Spotify OAuth callback, store token, redirect to frontend."""
    settings = await _load_settings(db)
    client_id = settings.get("spotify_client_id", "")
    client_secret = settings.get("spotify_client_secret", "")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/spotify/callback"

    try:
        token_info = SpotifyService.exchange_code(client_id, client_secret, redirect_uri, code)
    except Exception as exc:
        raise HTTPException(502, f"Token exchange failed: {exc}")

    # Store tokens in settings
    async def _upsert(key, val):
        existing = (await db.execute(select(AppSettings).where(AppSettings.key == key))).scalar_one_or_none()
        if existing:
            existing.value = str(val)
        else:
            db.add(AppSettings(key=key, value=str(val)))

    await _upsert("spotify_access_token", token_info.get("access_token", ""))
    await _upsert("spotify_refresh_token", token_info.get("refresh_token", ""))
    await _upsert("spotify_token_expires", str(token_info.get("expires_at", 0)))
    await db.commit()
    logger.info("Spotify OAuth token stored successfully")

    # Redirect to settings page
    return RedirectResponse(url="/settings?spotify_connected=1")


@router.delete("/spotify/auth", response_model=dict)
async def spotify_disconnect(db: AsyncSession = Depends(get_db)):
    """Remove stored OAuth tokens."""
    for key in ("spotify_access_token", "spotify_refresh_token", "spotify_token_expires"):
        row = (await db.execute(select(AppSettings).where(AppSettings.key == key))).scalar_one_or_none()
        if row:
            await db.delete(row)
    await db.commit()
    return {"disconnected": True}


@router.get("/spotify/auth/status")
async def spotify_auth_status(db: AsyncSession = Depends(get_db)):
    """Check if OAuth token is present and valid."""
    settings = await _load_settings(db)
    access_token = settings.get("spotify_access_token", "")
    expires_at = int(settings.get("spotify_token_expires", "0") or "0")
    connected = bool(access_token) and expires_at > int(time.time())
    return {"connected": connected, "expires_at": expires_at}


# ---------------------------------------------------------------------------
# Playlist Routes
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
    sp = await _get_spotify_with_oauth(db)

    try:
        data = sp.get_playlist(body.playlist_url)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Spotify import error: %s", exc)
        _raise_spotify_error(exc)

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

    sp = await _get_spotify_with_oauth(db)

    try:
        data = sp.get_playlist(pl.spotify_playlist_id)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_spotify_error(exc)

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

    sp = await _get_spotify_with_oauth(db)

    try:
        data = sp.get_playlist(pl.spotify_playlist_id)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_spotify_error(exc)

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
