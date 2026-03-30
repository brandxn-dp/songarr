"""
Background async task runner / queue manager for the Songarr acquisition pipeline.

The QueueManager maintains an asyncio queue of song IDs and processes them
one at a time through the full pipeline:
  search -> download -> organize -> tag -> complete
"""
import asyncio
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import DownloadJob, LibraryEntry, Song
from services.organizer import organize
from services.slskd import SlskdClient
from services.tagger import tag_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

POLL_INTERVAL = 2.0          # seconds between download status polls
DOWNLOAD_TIMEOUT = 600       # max seconds to wait for a single download
STAGING_SUBDIR = "staging"   # temp dir under download_path

_SLSKD_DONE_STATES = {"Completed", "Succeeded"}
_SLSKD_FAIL_STATES = {"Cancelled", "TimedOut", "Errored", "Rejected"}


async def _get_settings(session: AsyncSession) -> dict:
    """Load all AppSettings rows into a plain dict."""
    from models import AppSettings
    rows = (await session.execute(select(AppSettings))).scalars().all()
    return {r.key: r.value for r in rows}


async def _set_song_status(
    session: AsyncSession, song_id: int, status: str, error: Optional[str] = None
) -> None:
    values: dict = {"status": status, "updated_at": datetime.utcnow()}
    if error is not None:
        values["error_message"] = error
    await session.execute(update(Song).where(Song.id == song_id).values(**values))
    await session.commit()


async def _set_job_status(
    session: AsyncSession,
    job_id: int,
    status: str,
    progress: float = 0.0,
    local_path: Optional[str] = None,
) -> None:
    values: dict = {
        "status": status,
        "progress_percent": progress,
        "updated_at": datetime.utcnow(),
    }
    if local_path is not None:
        values["local_path"] = local_path
    await session.execute(update(DownloadJob).where(DownloadJob.id == job_id).values(**values))
    await session.commit()


# ---------------------------------------------------------------------------
# QueueManager
# ---------------------------------------------------------------------------

class QueueManager:
    """Singleton-style background task runner for the acquisition pipeline."""

    def __init__(self):
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._active_song_id: Optional[int] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._subscribers: list[asyncio.Queue] = []

        # Daily counters (reset at midnight automatically via check)
        self._today: date = date.today()
        self._completed_today: int = 0
        self._failed_today: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the background worker coroutine."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("QueueManager worker started.")

    async def stop(self):
        """Gracefully stop the worker."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("QueueManager worker stopped.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, song_id: int) -> None:
        """Add a song_id to the processing queue."""
        await self._queue.put(song_id)
        logger.info("Enqueued song_id=%d (queue size now %d)", song_id, self._queue.qsize())

    def get_stats(self) -> dict:
        """Return current queue statistics."""
        self._reset_daily_counters()
        return {
            "queue_length": self._queue.qsize(),
            "active_job": self._active_song_id,
            "completed_today": self._completed_today,
            "failed_today": self._failed_today,
        }

    # ------------------------------------------------------------------
    # WebSocket subscriber management
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Register a new WebSocket subscriber and return its queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def _broadcast(self, message: dict) -> None:
        """Send a status update to all subscribed WebSocket clients."""
        dead: list[asyncio.Queue] = []
        for sub in self._subscribers:
            try:
                sub.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(sub)
        for d in dead:
            self._subscribers.remove(d)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reset_daily_counters(self):
        today = date.today()
        if today != self._today:
            self._today = today
            self._completed_today = 0
            self._failed_today = 0

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    async def _worker(self):
        """Main worker loop — processes one song at a time."""
        logger.info("QueueManager worker loop running.")
        while True:
            try:
                song_id = await self._queue.get()
                self._active_song_id = song_id
                try:
                    await self._process_song(song_id)
                except Exception as exc:
                    logger.exception("Unhandled error processing song_id=%d: %s", song_id, exc)
                    async with AsyncSessionLocal() as session:
                        await _set_song_status(
                            session, song_id, "failed", error=str(exc)
                        )
                    self._failed_today += 1
                    await self._broadcast(
                        {"song_id": song_id, "status": "failed", "progress": None}
                    )
                finally:
                    self._active_song_id = None
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Worker loop error: %s", exc)
                await asyncio.sleep(1)

    async def _process_song(self, song_id: int) -> None:
        """Full acquisition pipeline for one song."""
        async with AsyncSessionLocal() as session:
            song = await session.get(Song, song_id)
            if song is None:
                logger.warning("song_id=%d not found in DB, skipping.", song_id)
                return
            settings = await _get_settings(session)

        # ----------------------------------------------------------------
        # 1. Search slskd
        # ----------------------------------------------------------------
        await self._broadcast({"song_id": song_id, "status": "searching", "progress": 0})
        async with AsyncSessionLocal() as session:
            await _set_song_status(session, song_id, "searching")

        slskd_url = settings.get("slskd_url", "http://localhost:5030")
        slskd_key = settings.get("slskd_api_key", "")
        client = SlskdClient(base_url=slskd_url, api_key=slskd_key)

        query = f"{song.artist} {song.title}"
        logger.info("Searching slskd for: %s", query)

        try:
            results = await client.search(query)
        except Exception as exc:
            logger.error("slskd search error for song_id=%d: %s", song_id, exc)
            results = []

        # Filter by preferred format / min bitrate
        preferred_fmt = settings.get("preferred_format", "FLAC").upper()
        try:
            min_bitrate = int(settings.get("min_bitrate", "128"))
        except ValueError:
            min_bitrate = 128

        def _acceptable(r):
            if r.file_format.upper() == preferred_fmt:
                return True
            if r.bitrate and r.bitrate >= min_bitrate:
                return True
            if r.quality_score >= 40:
                return True
            return False

        filtered = [r for r in results if _acceptable(r)]
        if not filtered:
            filtered = results  # no results match filter, use all

        if not filtered:
            async with AsyncSessionLocal() as session:
                await _set_song_status(session, song_id, "failed", error="No results found on Soulseek")
            self._failed_today += 1
            await self._broadcast({"song_id": song_id, "status": "failed", "progress": None})
            return

        best = filtered[0]  # already sorted by quality_score desc

        # ----------------------------------------------------------------
        # 2. Create DownloadJob and start download
        # ----------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            job = DownloadJob(
                song_id=song_id,
                slskd_username=best.username,
                slskd_filename=best.filename,
                file_format=best.file_format,
                bitrate=best.bitrate,
                file_size_bytes=best.file_size_bytes,
                status="queued",
                progress_percent=0.0,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        logger.info(
            "Initiating download from %s: %s (song_id=%d)",
            best.username, best.filename, song_id,
        )

        try:
            transfer_id = await client.download(
                username=best.username,
                filename=best.filename,
                size=best.file_size_bytes,
            )
        except Exception as exc:
            logger.error("Download initiation failed for song_id=%d: %s", song_id, exc)
            async with AsyncSessionLocal() as session:
                await _set_song_status(session, song_id, "failed", error=f"Download start failed: {exc}")
                await _set_job_status(session, job_id, "failed")
            self._failed_today += 1
            await self._broadcast({"song_id": song_id, "status": "failed", "progress": None})
            return

        async with AsyncSessionLocal() as session:
            await _set_song_status(session, song_id, "downloading")
            await _set_job_status(session, job_id, "downloading")

        await self._broadcast({"song_id": song_id, "status": "downloading", "progress": 0})

        # ----------------------------------------------------------------
        # 3. Poll download status
        # ----------------------------------------------------------------
        start_time = asyncio.get_running_loop().time()
        local_path: Optional[str] = None
        download_ok = False

        while True:
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed > DOWNLOAD_TIMEOUT:
                logger.warning("Download timed out for song_id=%d", song_id)
                break

            await asyncio.sleep(POLL_INTERVAL)

            try:
                status_data = await client.get_download_status(
                    username=best.username, transfer_id=transfer_id
                )
            except Exception as exc:
                logger.debug("Status poll error for song_id=%d: %s", song_id, exc)
                continue

            if not status_data:
                continue

            state: str = status_data.get("state", "")
            bytes_transferred: int = status_data.get("bytesTransferred", 0)
            file_size: int = status_data.get("size", best.file_size_bytes or 1)
            progress = min(100.0, (bytes_transferred / max(file_size, 1)) * 100)

            async with AsyncSessionLocal() as session:
                await _set_job_status(session, job_id, "downloading", progress=progress)

            await self._broadcast(
                {"song_id": song_id, "status": "downloading", "progress": progress}
            )

            if state in _SLSKD_DONE_STATES or "Completed" in state:
                local_path = status_data.get("localFilename") or status_data.get("filename")
                download_ok = True
                logger.info("Download completed for song_id=%d: %s", song_id, local_path)
                break

            if state in _SLSKD_FAIL_STATES or any(s in state for s in _SLSKD_FAIL_STATES):
                logger.warning("Download failed (state=%s) for song_id=%d", state, song_id)
                break

        if not download_ok:
            async with AsyncSessionLocal() as session:
                await _set_song_status(session, song_id, "failed", error="Download did not complete")
                await _set_job_status(session, job_id, "failed")
            self._failed_today += 1
            await self._broadcast({"song_id": song_id, "status": "failed", "progress": None})
            return

        # Resolve local_path from slskd if not directly provided
        if not local_path:
            # Try to reconstruct from download path
            download_base = settings.get("download_path", str(Path.home() / "Music" / "Songarr" / "downloads"))
            filename_base = Path(best.filename.replace("\\", "/")).name
            candidate = Path(download_base) / filename_base
            if candidate.exists():
                local_path = str(candidate)
            else:
                # Search recursively
                for root, _, files in os.walk(download_base):
                    for f in files:
                        if f == filename_base:
                            local_path = os.path.join(root, f)
                            break
                    if local_path:
                        break

        if not local_path or not Path(local_path).exists():
            async with AsyncSessionLocal() as session:
                await _set_song_status(
                    session, song_id, "failed",
                    error=f"Cannot locate downloaded file: {local_path}"
                )
                await _set_job_status(session, job_id, "failed")
            self._failed_today += 1
            await self._broadcast({"song_id": song_id, "status": "failed", "progress": None})
            return

        async with AsyncSessionLocal() as session:
            await _set_job_status(session, job_id, "completed", progress=100.0, local_path=local_path)

        # ----------------------------------------------------------------
        # 4. Organize
        # ----------------------------------------------------------------
        await self._broadcast({"song_id": song_id, "status": "organizing", "progress": 100})
        async with AsyncSessionLocal() as session:
            await _set_song_status(session, song_id, "organizing")
            song = await session.get(Song, song_id)
            settings = await _get_settings(session)

        organized_path: Optional[str] = None
        auto_organize = settings.get("auto_organize", "true").lower() == "true"
        if auto_organize:
            try:
                organized_path = organize(local_path, song, settings)
                logger.info("Organized to: %s", organized_path)
            except Exception as exc:
                logger.error("Organize failed for song_id=%d: %s", song_id, exc)
                organized_path = local_path  # keep in place
        else:
            organized_path = local_path

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Song)
                .where(Song.id == song_id)
                .values(library_path=organized_path, updated_at=datetime.utcnow())
            )
            await session.commit()

        # ----------------------------------------------------------------
        # 5. Tag
        # ----------------------------------------------------------------
        await self._broadcast({"song_id": song_id, "status": "tagging", "progress": 100})
        async with AsyncSessionLocal() as session:
            await _set_song_status(session, song_id, "tagging")
            song = await session.get(Song, song_id)
            settings = await _get_settings(session)

        auto_tag = settings.get("auto_tag", "true").lower() == "true"
        tag_result = None
        if auto_tag:
            try:
                tag_result = await tag_file(organized_path, song, settings)
                logger.info(
                    "Tagging song_id=%d: success=%s, via=%s",
                    song_id, tag_result.success, tag_result.matched_via
                )
            except Exception as exc:
                logger.error("Tagging failed for song_id=%d: %s", song_id, exc)

        # ----------------------------------------------------------------
        # 6. Create LibraryEntry + mark completed
        # ----------------------------------------------------------------
        final_path = Path(organized_path)
        file_size = final_path.stat().st_size if final_path.exists() else 0
        ext = final_path.suffix.lstrip(".").upper() or best.file_format

        # Attempt to read audio properties via mutagen
        duration_secs: Optional[float] = None
        sample_rate: Optional[int] = None
        channels: Optional[int] = None
        try:
            import mutagen as mg
            af = mg.File(str(final_path))
            if af and af.info:
                duration_secs = getattr(af.info, "length", None)
                sample_rate = getattr(af.info, "sample_rate", None)
                channels = getattr(af.info, "channels", None)
        except Exception:
            pass

        has_art = tag_result.has_album_art if tag_result else False
        tags_verified = (tag_result is not None and tag_result.success)

        async with AsyncSessionLocal() as session:
            # Update song with possibly-improved metadata from tagging
            song_updates: dict = {"status": "completed", "updated_at": datetime.utcnow()}
            if tag_result and tag_result.success:
                if tag_result.musicbrainz_recording_id:
                    song_updates["musicbrainz_recording_id"] = tag_result.musicbrainz_recording_id
                if tag_result.title:
                    song_updates["title"] = tag_result.title
                if tag_result.artist:
                    song_updates["artist"] = tag_result.artist
                if tag_result.album:
                    song_updates["album"] = tag_result.album
                if tag_result.year:
                    song_updates["year"] = tag_result.year
                if tag_result.track_number:
                    song_updates["track_number"] = tag_result.track_number

            await session.execute(
                update(Song).where(Song.id == song_id).values(**song_updates)
            )

            entry = LibraryEntry(
                song_id=song_id,
                file_path=str(final_path),
                file_format=ext,
                file_size_bytes=file_size,
                bitrate=best.bitrate,
                sample_rate=sample_rate,
                channels=channels,
                duration_seconds=duration_secs,
                has_album_art=has_art,
                tags_verified=tags_verified,
            )
            session.add(entry)
            await session.commit()

        self._completed_today += 1
        await self._broadcast({"song_id": song_id, "status": "completed", "progress": 100})
        logger.info("Song id=%d acquisition complete: %s", song_id, final_path)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

queue_manager = QueueManager()
