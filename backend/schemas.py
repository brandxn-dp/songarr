"""
Pydantic schemas for all API request/response bodies.
"""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Song schemas
# ---------------------------------------------------------------------------

class SongCreate(BaseModel):
    title: str
    artist: str
    album: Optional[str] = None
    album_artist: Optional[str] = None
    year: Optional[int] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    genre: Optional[str] = None
    duration_seconds: Optional[float] = None
    musicbrainz_recording_id: Optional[str] = None
    musicbrainz_release_id: Optional[str] = None
    spotify_track_id: Optional[str] = None
    spotify_playlist_id: Optional[str] = None


class SongUpdate(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    year: Optional[int] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    genre: Optional[str] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    library_path: Optional[str] = None


class SongRead(BaseModel):
    id: int
    title: str
    artist: str
    album: Optional[str] = None
    album_artist: Optional[str] = None
    year: Optional[int] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    genre: Optional[str] = None
    duration_seconds: Optional[float] = None
    musicbrainz_recording_id: Optional[str] = None
    musicbrainz_release_id: Optional[str] = None
    spotify_track_id: Optional[str] = None
    spotify_playlist_id: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    library_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# DownloadJob schemas
# ---------------------------------------------------------------------------

class DownloadJobRead(BaseModel):
    id: int
    song_id: int
    slskd_username: str
    slskd_filename: str
    file_format: str
    bitrate: Optional[int] = None
    file_size_bytes: Optional[int] = None
    local_path: Optional[str] = None
    progress_percent: float
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Library schemas
# ---------------------------------------------------------------------------

class LibraryEntryRead(BaseModel):
    id: int
    song_id: int
    file_path: str
    file_format: str
    file_size_bytes: int
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    duration_seconds: Optional[float] = None
    has_album_art: bool
    tags_verified: bool
    added_at: datetime
    song: Optional[SongRead] = None

    model_config = {"from_attributes": True}


class LibraryStats(BaseModel):
    total_songs: int
    total_size_bytes: int
    format_breakdown: dict[str, int]


class ArtistEntry(BaseModel):
    artist: str
    song_count: int


# ---------------------------------------------------------------------------
# slskd search result
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    username: str
    filename: str           # full remote path
    display_name: str       # basename only
    file_format: str        # MP3, FLAC, OGG, etc.
    bitrate: Optional[int] = None
    file_size_bytes: int
    file_size_mb: float
    quality_score: int      # computed quality metric


# ---------------------------------------------------------------------------
# Spotify schemas
# ---------------------------------------------------------------------------

class SpotifyTrackRead(BaseModel):
    spotify_id: str
    title: str
    artist: str
    artists: list[str]
    album: str
    album_artist: Optional[str] = None
    year: Optional[int] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    duration_ms: Optional[int] = None
    isrc: Optional[str] = None
    acquisition_status: Optional[str] = None   # populated when checking against DB


class SpotifyPlaylistRead(BaseModel):
    id: int
    spotify_playlist_id: str
    name: str
    description: Optional[str] = None
    track_count: int
    imported_at: datetime
    status: str

    model_config = {"from_attributes": True}


class SpotifyImportRequest(BaseModel):
    playlist_url: str


class SpotifyQueueRequest(BaseModel):
    track_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Settings schemas
# ---------------------------------------------------------------------------

class SettingsRead(BaseModel):
    settings: dict[str, str]


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


# ---------------------------------------------------------------------------
# Download / Queue schemas
# ---------------------------------------------------------------------------

class DownloadQueueStats(BaseModel):
    queue_length: int
    active_job: Optional[int] = None   # song_id of active job
    completed_today: int
    failed_today: int


class SongWithJob(BaseModel):
    song: SongRead
    job: Optional[DownloadJobRead] = None


# ---------------------------------------------------------------------------
# Manual download / auto-search requests
# ---------------------------------------------------------------------------

class ManualDownloadRequest(BaseModel):
    song_id: Optional[int] = None
    artist: str
    title: str
    album: Optional[str] = None
    year: Optional[int] = None
    username: str
    filename: str
    file_size_bytes: int


class AutoSearchRequest(BaseModel):
    artist: str
    title: str
    album: Optional[str] = None
    year: Optional[int] = None


# ---------------------------------------------------------------------------
# Tag update request (library PATCH)
# ---------------------------------------------------------------------------

class TagUpdateRequest(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    year: Optional[int] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    genre: Optional[str] = None


# ---------------------------------------------------------------------------
# WebSocket message
# ---------------------------------------------------------------------------

class WSStatusMessage(BaseModel):
    song_id: int
    status: str
    progress: Optional[float] = None
    error_message: Optional[str] = None
    extra: Optional[dict[str, Any]] = None
