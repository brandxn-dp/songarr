"""
Library router: browse, filter, and manage the organised music library.
"""
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import LibraryEntry, Song
from schemas import (
    ArtistEntry,
    LibraryEntryRead,
    LibraryStats,
    SongRead,
    TagUpdateRequest,
)
from services.tagger import _write_tags

logger = logging.getLogger(__name__)
router = APIRouter(tags=["library"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sort_column(sort_by: str):
    """Return the ORM column to sort by."""
    mapping = {
        "added_at": LibraryEntry.added_at,
        "file_size": LibraryEntry.file_size_bytes,
        "format": LibraryEntry.file_format,
        "bitrate": LibraryEntry.bitrate,
        "duration": LibraryEntry.duration_seconds,
        "artist": Song.artist,
        "album": Song.album,
        "title": Song.title,
        "year": Song.year,
    }
    return mapping.get(sort_by, LibraryEntry.added_at)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/library", response_model=dict)
async def list_library(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    artist: Optional[str] = Query(None),
    album: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    sort_by: str = Query("added_at"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db),
):
    """
    Paginated library browser with optional filtering and sorting.
    Returns {items: [...], total: int, page: int, page_size: int, total_pages: int}
    """
    stmt = (
        select(LibraryEntry)
        .join(LibraryEntry.song)
        .options(selectinload(LibraryEntry.song))
    )

    if artist:
        stmt = stmt.where(Song.artist.ilike(f"%{artist}%"))
    if album:
        stmt = stmt.where(Song.album.ilike(f"%{album}%"))
    if format:
        stmt = stmt.where(LibraryEntry.file_format.ilike(format))

    col = _sort_column(sort_by)
    stmt = stmt.order_by(desc(col) if sort_order == "desc" else asc(col))

    # Count total without pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    entries = (await db.execute(stmt)).scalars().all()

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": [LibraryEntryRead.model_validate(e) for e in entries],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/library/artists", response_model=list[ArtistEntry])
async def list_artists(db: AsyncSession = Depends(get_db)):
    """Return distinct artists with their song counts."""
    stmt = (
        select(Song.artist, func.count(LibraryEntry.id).label("song_count"))
        .join(LibraryEntry, LibraryEntry.song_id == Song.id)
        .group_by(Song.artist)
        .order_by(Song.artist)
    )
    rows = (await db.execute(stmt)).all()
    return [ArtistEntry(artist=row.artist, song_count=row.song_count) for row in rows]


@router.get("/library/stats", response_model=LibraryStats)
async def library_stats(db: AsyncSession = Depends(get_db)):
    """Return aggregate library statistics."""
    total_songs: int = (
        await db.execute(select(func.count(LibraryEntry.id)))
    ).scalar_one()

    total_size: int = (
        await db.execute(select(func.coalesce(func.sum(LibraryEntry.file_size_bytes), 0)))
    ).scalar_one()

    fmt_rows = (
        await db.execute(
            select(LibraryEntry.file_format, func.count(LibraryEntry.id))
            .group_by(LibraryEntry.file_format)
        )
    ).all()
    format_breakdown = {row[0]: row[1] for row in fmt_rows}

    return LibraryStats(
        total_songs=total_songs,
        total_size_bytes=total_size,
        format_breakdown=format_breakdown,
    )


@router.get("/library/{entry_id}", response_model=LibraryEntryRead)
async def get_library_entry(entry_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(
        LibraryEntry, entry_id, options=[selectinload(LibraryEntry.song)]
    )
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Library entry id={entry_id} not found.")
    return LibraryEntryRead.model_validate(entry)


@router.delete("/library/{entry_id}", status_code=204)
async def remove_library_entry(
    entry_id: int,
    delete_file: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Remove a library entry. Optionally delete the actual file from disk."""
    entry = await db.get(LibraryEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Library entry id={entry_id} not found.")

    if delete_file:
        file_path = Path(entry.file_path)
        if file_path.exists():
            try:
                file_path.unlink()
                logger.info("Deleted file: %s", file_path)
            except OSError as exc:
                logger.warning("Could not delete file %s: %s", file_path, exc)

    await db.delete(entry)
    await db.commit()


@router.patch("/library/{entry_id}/tags", response_model=LibraryEntryRead)
async def update_tags(
    entry_id: int,
    body: TagUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually update metadata for a library entry and rewrite the file's tags.
    """
    entry = await db.get(
        LibraryEntry, entry_id, options=[selectinload(LibraryEntry.song)]
    )
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Library entry id={entry_id} not found.")

    song = entry.song
    file_path = entry.file_path

    if not Path(file_path).exists():
        raise HTTPException(
            status_code=422,
            detail=f"File not found on disk: {file_path}",
        )

    # Build updated metadata dict from request + existing song
    updates = body.model_dump(exclude_none=True)
    meta = {
        "title": updates.get("title", song.title),
        "artist": updates.get("artist", song.artist),
        "album": updates.get("album", song.album),
        "album_artist": updates.get("album_artist", song.album_artist),
        "year": updates.get("year", song.year),
        "track_number": updates.get("track_number", song.track_number),
        "disc_number": updates.get("disc_number", song.disc_number),
        "genre": updates.get("genre", song.genre),
    }

    # Write tags synchronously (mutagen is not async)
    import asyncio
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, _write_tags, file_path, meta, None)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to write tags to file.")

    # Update Song record
    for field, val in updates.items():
        if hasattr(song, field):
            setattr(song, field, val)

    entry.tags_verified = True
    db.add(song)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return LibraryEntryRead.model_validate(entry)
