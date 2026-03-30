"""
File organizer service: moves downloaded files to the library directory
using configurable folder and filename templates.
"""
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Characters illegal in file/folder names on Windows and/or POSIX
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r"\s{2,}")
_DOTS_TRAIL = re.compile(r"[. ]+$")

MAX_SEGMENT_LEN = 200


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sanitize(value: str) -> str:
    """Remove illegal filesystem characters and normalise whitespace."""
    cleaned = _ILLEGAL_CHARS.sub("", value)
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    cleaned = _DOTS_TRAIL.sub("", cleaned)
    return cleaned.strip()


def _safe(value: Optional[object], fallback: str) -> str:
    """Return a sanitised string or the fallback if value is None/empty."""
    if value is None:
        return fallback
    s = str(value).strip()
    return _sanitize(s) if s else fallback


def _truncate(s: str) -> str:
    return s[:MAX_SEGMENT_LEN]


def _render_template(template: str, song) -> str:  # song: models.Song
    """
    Substitute template variables using song metadata.
    Variables: {artist}, {album_artist}, {album}, {title},
               {year}, {track_number}, {disc_number}, {genre}
    """
    track_num = (
        f"{song.track_number:02d}" if song.track_number is not None else "00"
    )
    disc_num = (
        str(song.disc_number) if song.disc_number is not None else "1"
    )

    replacements = {
        "{artist}": _safe(song.artist, "Unknown Artist"),
        "{album_artist}": _safe(
            song.album_artist or song.artist, "Unknown Artist"
        ),
        "{album}": _safe(song.album, "Unknown Album"),
        "{title}": _safe(song.title, "Unknown Title"),
        "{year}": _safe(song.year, "Unknown Year"),
        "{track_number}": track_num,
        "{disc_number}": disc_num,
        "{genre}": _safe(song.genre, "Unknown Genre"),
    }

    result = template
    for key, val in replacements.items():
        result = result.replace(key, val)

    # Sanitise each segment individually
    parts = result.replace("\\", "/").split("/")
    parts = [_truncate(_sanitize(p)) for p in parts if p.strip()]
    return "/".join(parts)


def _unique_path(target: Path) -> Path:
    """
    Return a path that doesn't collide with an existing file.
    Appends _2, _3, … before the extension until a free slot is found.
    """
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def organize(source_path: str, song, settings: dict) -> str:  # song: models.Song
    """
    Move *source_path* to its library location derived from templates.

    Args:
        source_path: Absolute path to the downloaded file.
        song:        ORM Song instance with metadata.
        settings:   Dict of app settings (music_library_path, folder_template,
                    filename_template).

    Returns:
        Absolute path string where the file now lives.
    """
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    library_root = Path(
        settings.get("music_library_path", str(Path.home() / "Music" / "Songarr"))
    )
    folder_template = settings.get("folder_template", "{artist}/{album}")
    filename_template = settings.get("filename_template", "{track_number} - {title}")

    # Build relative folder path
    folder_rel = _render_template(folder_template, song)
    # Build filename (no extension yet)
    filename_base = _render_template(filename_template, song)

    dest_dir = library_root / folder_rel
    dest_dir.mkdir(parents=True, exist_ok=True)

    extension = source.suffix  # e.g. ".mp3"
    dest_path = _unique_path(dest_dir / f"{filename_base}{extension}")

    logger.info("Organising file: %s -> %s", source, dest_path)
    shutil.move(str(source), str(dest_path))
    return str(dest_path)
