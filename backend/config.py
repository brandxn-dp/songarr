"""
Application-wide configuration loaded from environment variables / .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # slskd connection
    SLSKD_URL: str = os.environ.get("SLSKD_URL", "http://localhost:5030")
    SLSKD_API_KEY: str = os.environ.get("SLSKD_API_KEY", "")

    # File system paths
    MUSIC_LIBRARY_PATH: str = os.environ.get(
        "MUSIC_LIBRARY_PATH",
        str(Path.home() / "Music" / "Songarr"),
    )
    DOWNLOAD_PATH: str = os.environ.get(
        "DOWNLOAD_PATH",
        str(Path.home() / "Music" / "Songarr" / "downloads"),
    )

    # Database
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./songarr.db",
    )

    # Naming templates
    FOLDER_TEMPLATE: str = os.environ.get("FOLDER_TEMPLATE", "{artist}/{album}")
    FILENAME_TEMPLATE: str = os.environ.get(
        "FILENAME_TEMPLATE", "{track_number} - {title}"
    )

    # Spotify
    SPOTIFY_CLIENT_ID: str = os.environ.get("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET: str = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

    # AcoustID
    ACOUSTID_API_KEY: str = os.environ.get("ACOUSTID_API_KEY", "")


settings = Settings()
