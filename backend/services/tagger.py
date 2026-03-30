"""
Audio tagging service using mutagen + musicbrainzngs + pyacoustid.

Pipeline:
  1. Fingerprint with fpcalc (via acoustid library which shells out to fpcalc)
  2. Query AcoustID API -> MusicBrainz recording ID
  3. Fetch MusicBrainz metadata (title, artist, album, track#, year, etc.)
  4. Fetch album art from Cover Art Archive
  5. Write all tags + embedded art using mutagen
  6. Fall back to existing song metadata if fingerprinting fails
"""
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import acoustid
import httpx
import musicbrainzngs
import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    ID3,
    ID3NoHeaderError,
    TALB,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    TYER,
    TCON,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis

logger = logging.getLogger(__name__)

# Set musicbrainzngs user agent once at module level
musicbrainzngs.set_useragent("Songarr", "1.0", "self-hosted")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TagResult:
    success: bool
    matched_via: Optional[str] = None   # "acoustid", "existing_tags", "manual"
    musicbrainz_recording_id: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    year: Optional[int] = None
    track_number: Optional[int] = None
    has_album_art: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# MusicBrainz helpers
# ---------------------------------------------------------------------------

def _fetch_mb_recording(recording_id: str) -> Optional[dict]:
    """Fetch a MusicBrainz recording including release details."""
    try:
        result = musicbrainzngs.get_recording_by_id(
            recording_id,
            includes=["artists", "releases", "release-groups"],
        )
        return result.get("recording")
    except musicbrainzngs.WebServiceError as exc:
        logger.warning("MusicBrainz fetch failed for %s: %s", recording_id, exc)
        return None


def _extract_mb_metadata(recording: dict) -> dict:
    """Extract useful fields from a MusicBrainz recording dict."""
    meta: dict = {}

    meta["title"] = recording.get("title", "")

    # Primary artist
    ac_list = recording.get("artist-credit", [])
    artist_parts = []
    for ac in ac_list:
        if isinstance(ac, dict) and "artist" in ac:
            artist_parts.append(ac["artist"].get("name", ""))
    meta["artist"] = " & ".join(filter(None, artist_parts))

    # Release / album info - use first release
    releases = recording.get("release-list", [])
    if releases:
        rel = releases[0]
        meta["album"] = rel.get("title", "")
        date_str = rel.get("date", "")
        if date_str:
            try:
                meta["year"] = int(date_str[:4])
            except ValueError:
                pass
        # Track number within the release
        medium_list = rel.get("medium-list", [])
        if medium_list:
            medium = medium_list[0]
            track_list = medium.get("track-list", [])
            if track_list:
                pos = track_list[0].get("number")
                if pos:
                    try:
                        meta["track_number"] = int(pos)
                    except ValueError:
                        pass
        meta["release_id"] = rel.get("id", "")

    return meta


# ---------------------------------------------------------------------------
# Cover Art Archive
# ---------------------------------------------------------------------------

async def _fetch_cover_art(release_id: str) -> Optional[bytes]:
    """Fetch front cover art from the Cover Art Archive."""
    url = f"https://coverartarchive.org/release/{release_id}/front-500"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.content
    except Exception as exc:
        logger.debug("Cover art fetch failed for release %s: %s", release_id, exc)
    return None


# ---------------------------------------------------------------------------
# Fingerprinting via acoustid
# ---------------------------------------------------------------------------

def _fingerprint_file(file_path: str) -> Optional[tuple[int, str]]:
    """
    Run fpcalc to get (duration, fingerprint).
    Returns None if fpcalc is not installed or fails.
    """
    try:
        duration, fp = acoustid.fingerprint_file(file_path)
        return int(duration), fp
    except acoustid.FingerprintGenerationError as exc:
        logger.debug("Fingerprint generation failed: %s", exc)
        return None
    except Exception as exc:
        logger.debug("Unexpected fingerprint error: %s", exc)
        return None


async def _lookup_acoustid(api_key: str, duration: int, fingerprint: str) -> Optional[str]:
    """
    Query AcoustID and return the best MusicBrainz recording ID.
    Runs in thread pool executor to avoid blocking event loop.
    """
    if not api_key:
        return None

    def _do_lookup():
        try:
            results = acoustid.lookup(api_key, fingerprint, duration, meta="recordings")
            best_score = 0.0
            best_id = None
            for result in results:
                score = result.get("score", 0.0)
                if score > best_score:
                    for recording in result.get("recordings", []):
                        rec_id = recording.get("id")
                        if rec_id:
                            best_score = score
                            best_id = rec_id
                            break
            return best_id
        except acoustid.WebServiceError as exc:
            logger.warning("AcoustID lookup failed: %s", exc)
            return None

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do_lookup)


# ---------------------------------------------------------------------------
# Mutagen tag writers
# ---------------------------------------------------------------------------

def _write_mp3_tags(
    file_path: str,
    meta: dict,
    cover_data: Optional[bytes],
) -> bool:
    try:
        try:
            audio = ID3(file_path)
        except ID3NoHeaderError:
            audio = ID3()

        if meta.get("title"):
            audio.setall("TIT2", [TIT2(encoding=3, text=meta["title"])])
        if meta.get("artist"):
            audio.setall("TPE1", [TPE1(encoding=3, text=meta["artist"])])
        if meta.get("album_artist") or meta.get("artist"):
            audio.setall(
                "TPE2",
                [TPE2(encoding=3, text=meta.get("album_artist") or meta.get("artist", ""))],
            )
        if meta.get("album"):
            audio.setall("TALB", [TALB(encoding=3, text=meta["album"])])
        if meta.get("year"):
            audio.setall("TYER", [TYER(encoding=3, text=str(meta["year"]))])
        if meta.get("track_number"):
            total = meta.get("track_total", "")
            track_str = (
                f"{meta['track_number']}/{total}" if total else str(meta["track_number"])
            )
            audio.setall("TRCK", [TRCK(encoding=3, text=track_str)])
        if meta.get("disc_number"):
            audio.setall("TPOS", [TPOS(encoding=3, text=str(meta["disc_number"]))])
        if meta.get("genre"):
            audio.setall("TCON", [TCON(encoding=3, text=meta["genre"])])

        if cover_data:
            audio.setall(
                "APIC",
                [
                    APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,
                        desc="Cover",
                        data=cover_data,
                    )
                ],
            )

        audio.save(file_path)
        return True
    except Exception as exc:
        logger.error("MP3 tag write failed: %s", exc)
        return False


def _write_flac_tags(
    file_path: str,
    meta: dict,
    cover_data: Optional[bytes],
) -> bool:
    try:
        audio = FLAC(file_path)

        if meta.get("title"):
            audio["title"] = [meta["title"]]
        if meta.get("artist"):
            audio["artist"] = [meta["artist"]]
        if meta.get("album_artist") or meta.get("artist"):
            audio["albumartist"] = [meta.get("album_artist") or meta.get("artist", "")]
        if meta.get("album"):
            audio["album"] = [meta["album"]]
        if meta.get("year"):
            audio["date"] = [str(meta["year"])]
        if meta.get("track_number"):
            audio["tracknumber"] = [str(meta["track_number"])]
        if meta.get("disc_number"):
            audio["discnumber"] = [str(meta["disc_number"])]
        if meta.get("genre"):
            audio["genre"] = [meta["genre"]]

        if cover_data:
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            pic.data = cover_data
            audio.clear_pictures()
            audio.add_picture(pic)

        audio.save()
        return True
    except Exception as exc:
        logger.error("FLAC tag write failed: %s", exc)
        return False


def _write_vorbis_tags(
    file_path: str,
    meta: dict,
    cover_data: Optional[bytes],
) -> bool:
    """Write Vorbis comment tags for OGG files."""
    try:
        audio = OggVorbis(file_path)

        if meta.get("title"):
            audio["title"] = [meta["title"]]
        if meta.get("artist"):
            audio["artist"] = [meta["artist"]]
        if meta.get("album_artist") or meta.get("artist"):
            audio["albumartist"] = [meta.get("album_artist") or meta.get("artist", "")]
        if meta.get("album"):
            audio["album"] = [meta["album"]]
        if meta.get("year"):
            audio["date"] = [str(meta["year"])]
        if meta.get("track_number"):
            audio["tracknumber"] = [str(meta["track_number"])]
        if meta.get("disc_number"):
            audio["discnumber"] = [str(meta["disc_number"])]
        if meta.get("genre"):
            audio["genre"] = [meta["genre"]]

        audio.save()
        return True
    except Exception as exc:
        logger.error("OGG Vorbis tag write failed: %s", exc)
        return False


def _write_m4a_tags(
    file_path: str,
    meta: dict,
    cover_data: Optional[bytes],
) -> bool:
    try:
        audio = MP4(file_path)

        if meta.get("title"):
            audio["\xa9nam"] = [meta["title"]]
        if meta.get("artist"):
            audio["\xa9ART"] = [meta["artist"]]
        if meta.get("album_artist") or meta.get("artist"):
            audio["aART"] = [meta.get("album_artist") or meta.get("artist", "")]
        if meta.get("album"):
            audio["\xa9alb"] = [meta["album"]]
        if meta.get("year"):
            audio["\xa9day"] = [str(meta["year"])]
        if meta.get("track_number"):
            total = meta.get("track_total") or 0
            audio["trkn"] = [(meta["track_number"], total)]
        if meta.get("disc_number"):
            audio["disk"] = [(meta["disc_number"], 0)]
        if meta.get("genre"):
            audio["\xa9gen"] = [meta["genre"]]

        if cover_data:
            audio["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]

        audio.save()
        return True
    except Exception as exc:
        logger.error("M4A tag write failed: %s", exc)
        return False


def _write_tags(file_path: str, meta: dict, cover_data: Optional[bytes]) -> bool:
    """Dispatch to the correct tagger based on file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".mp3":
        return _write_mp3_tags(file_path, meta, cover_data)
    if ext == ".flac":
        return _write_flac_tags(file_path, meta, cover_data)
    if ext in (".ogg", ".opus"):
        return _write_vorbis_tags(file_path, meta, cover_data)
    if ext in (".m4a", ".aac", ".alac"):
        return _write_m4a_tags(file_path, meta, cover_data)

    # Generic fallback via mutagen.File()
    try:
        audio = mutagen.File(file_path, easy=True)
        if audio is None:
            logger.warning("mutagen could not identify file: %s", file_path)
            return False
        for key, val in {
            "title": meta.get("title"),
            "artist": meta.get("artist"),
            "album": meta.get("album"),
            "date": str(meta["year"]) if meta.get("year") else None,
            "tracknumber": str(meta["track_number"]) if meta.get("track_number") else None,
        }.items():
            if val:
                audio[key] = [val]
        audio.save()
        return True
    except Exception as exc:
        logger.error("Generic tag write failed for %s: %s", file_path, exc)
        return False


# ---------------------------------------------------------------------------
# Check for existing embedded art
# ---------------------------------------------------------------------------

def _has_album_art(file_path: str) -> bool:
    try:
        audio = mutagen.File(file_path)
        if audio is None:
            return False
        # ID3
        if hasattr(audio, "tags") and audio.tags:
            if any(k.startswith("APIC") for k in audio.tags.keys()):
                return True
        # FLAC
        if hasattr(audio, "pictures"):
            return bool(audio.pictures)
        # MP4
        if hasattr(audio, "tags") and audio.tags and "covr" in audio.tags:
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def tag_file(file_path: str, song, settings: dict) -> TagResult:
    """
    Tag an audio file using AcoustID fingerprinting + MusicBrainz,
    falling back to song metadata when fingerprinting is unavailable.

    Args:
        file_path:  Absolute path to the audio file.
        song:       ORM Song instance.
        settings:   Dict of app settings (acoustid_api_key, etc.)

    Returns:
        TagResult dataclass.
    """
    acoustid_key = settings.get("acoustid_api_key", "")

    # ------------------------------------------------------------------
    # Step 1: Try AcoustID fingerprinting
    # ------------------------------------------------------------------
    mb_recording_id: Optional[str] = None
    matched_via: Optional[str] = None
    meta: dict = {}

    loop = asyncio.get_running_loop()
    fp_result = await loop.run_in_executor(None, _fingerprint_file, file_path)

    if fp_result is not None:
        duration, fingerprint = fp_result
        mb_recording_id = await _lookup_acoustid(acoustid_key, duration, fingerprint)

    # ------------------------------------------------------------------
    # Step 2: Fetch MusicBrainz metadata
    # ------------------------------------------------------------------
    release_id: Optional[str] = None

    if mb_recording_id:
        recording = await loop.run_in_executor(None, _fetch_mb_recording, mb_recording_id)
        if recording:
            meta = _extract_mb_metadata(recording)
            release_id = meta.pop("release_id", None)
            matched_via = "acoustid"

    # ------------------------------------------------------------------
    # Step 3: Fall back to existing song metadata if needed
    # ------------------------------------------------------------------
    if not meta:
        meta = {
            "title": song.title,
            "artist": song.artist,
            "album": song.album,
            "album_artist": song.album_artist,
            "year": song.year,
            "track_number": song.track_number,
            "disc_number": song.disc_number,
            "genre": song.genre,
        }
        if song.musicbrainz_recording_id:
            mb_recording_id = song.musicbrainz_recording_id
            matched_via = "existing_tags"
        else:
            matched_via = "existing_tags"

    # ------------------------------------------------------------------
    # Step 4: Fetch cover art
    # ------------------------------------------------------------------
    cover_data: Optional[bytes] = None
    if release_id:
        cover_data = await _fetch_cover_art(release_id)
    elif song.musicbrainz_release_id:
        cover_data = await _fetch_cover_art(song.musicbrainz_release_id)

    # ------------------------------------------------------------------
    # Step 5: Write tags
    # ------------------------------------------------------------------
    write_ok = await loop.run_in_executor(
        None, _write_tags, file_path, meta, cover_data
    )

    if not write_ok:
        return TagResult(
            success=False,
            matched_via=matched_via,
            musicbrainz_recording_id=mb_recording_id,
            error="Failed to write tags to file.",
        )

    has_art = cover_data is not None or await loop.run_in_executor(
        None, _has_album_art, file_path
    )

    return TagResult(
        success=True,
        matched_via=matched_via,
        musicbrainz_recording_id=mb_recording_id,
        title=meta.get("title"),
        artist=meta.get("artist"),
        album=meta.get("album"),
        year=meta.get("year"),
        track_number=meta.get("track_number"),
        has_album_art=has_art,
    )
