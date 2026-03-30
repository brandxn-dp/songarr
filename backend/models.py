"""
SQLAlchemy ORM models for Songarr.
"""
from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Song(Base):
    """Tracks a song through the entire acquisition pipeline."""

    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    artist: Mapped[str] = mapped_column(String(512), nullable=False)
    album: Mapped[str | None] = mapped_column(String(512), nullable=True)
    album_artist: Mapped[str | None] = mapped_column(String(512), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre: Mapped[str | None] = mapped_column(String(256), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # External identifiers
    musicbrainz_recording_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    musicbrainz_release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    spotify_track_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    spotify_playlist_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Pipeline state
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    library_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    download_jobs: Mapped[list["DownloadJob"]] = relationship(
        "DownloadJob", back_populates="song", cascade="all, delete-orphan"
    )
    library_entry: Mapped["LibraryEntry | None"] = relationship(
        "LibraryEntry", back_populates="song", uselist=False, cascade="all, delete-orphan"
    )


class DownloadJob(Base):
    """Tracks an active slskd download."""

    __tablename__ = "download_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    song_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slskd_username: Mapped[str] = mapped_column(String(256), nullable=False)
    slskd_filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    song: Mapped["Song"] = relationship("Song", back_populates="download_jobs")


class LibraryEntry(Base):
    """Final organised and tagged file in the library."""

    __tablename__ = "library_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    song_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_album_art: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tags_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    added_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    song: Mapped["Song"] = relationship("Song", back_populates="library_entry")


class AppSettings(Base):
    """Key-value application settings store."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SpotifyPlaylist(Base):
    """Imported Spotify playlist record."""

    __tablename__ = "spotify_playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    spotify_playlist_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="importing", index=True
    )
