"""
Settings router: read/write application settings and test external connections.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AppSettings
from schemas import SettingsRead, SettingsUpdate

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])

# ---------------------------------------------------------------------------
# Default settings seeded on first boot
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, str] = {
    "slskd_url": "http://localhost:5030",
    "slskd_api_key": "",
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "acoustid_api_key": "",
    "music_library_path": "",
    "download_path": "",
    "folder_template": "{artist}/{album}",
    "filename_template": "{track_number} - {title}",
    "preferred_format": "FLAC",
    "min_bitrate": "128",
    "auto_tag": "true",
    "auto_organize": "true",
}


async def seed_defaults(session: AsyncSession) -> None:
    """Insert default settings rows that do not already exist."""
    existing = {
        r.key
        for r in (await session.execute(select(AppSettings.key))).all()
    }
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            session.add(AppSettings(key=key, value=value))
    await session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_all(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(AppSettings))).scalars().all()
    return {r.key: r.value for r in rows}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=SettingsRead)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Return all current settings."""
    return SettingsRead(settings=await _load_all(db))


@router.patch("/settings", response_model=SettingsRead)
async def update_settings(
    body: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update one or more settings key-value pairs.
    Unknown keys are created; existing keys are updated.
    """
    if not body.settings:
        raise HTTPException(status_code=400, detail="No settings provided.")

    for key, value in body.settings.items():
        existing = (
            await db.execute(select(AppSettings).where(AppSettings.key == key))
        ).scalar_one_or_none()

        if existing:
            existing.value = value
            existing.updated_at = datetime.utcnow()
        else:
            db.add(AppSettings(key=key, value=value))

    await db.commit()
    logger.info("Updated settings: %s", list(body.settings.keys()))
    return SettingsRead(settings=await _load_all(db))


@router.post("/settings/test/slskd", response_model=dict)
async def test_slskd(db: AsyncSession = Depends(get_db)):
    """Test the slskd connection using stored settings."""
    settings = await _load_all(db)
    slskd_url = settings.get("slskd_url", "http://localhost:5030")
    api_key = settings.get("slskd_api_key", "")

    from services.slskd import SlskdClient
    client = SlskdClient(base_url=slskd_url, api_key=api_key)

    try:
        info = await client.get_application_info()
        version = info.get("version", "unknown")
        return {"status": "ok", "message": f"Connected to slskd v{version}", "version": version}
    except Exception as exc:
        logger.warning("slskd connection test failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Cannot connect to slskd at {slskd_url}: {exc}",
        )


@router.post("/settings/test/spotify", response_model=dict)
async def test_spotify(db: AsyncSession = Depends(get_db)):
    """Test Spotify API credentials using stored settings."""
    settings = await _load_all(db)

    client_id = settings.get("spotify_client_id", "")
    client_secret = settings.get("spotify_client_secret", "")

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=422,
            detail="Spotify client_id and client_secret are not configured.",
        )

    from services.spotify_client import SpotifyService
    try:
        sp = SpotifyService(client_id=client_id, client_secret=client_secret)
        ok = sp.test_connection()
        if ok:
            return {"status": "ok", "message": "Spotify credentials are valid."}
        raise HTTPException(status_code=502, detail="Spotify credential test failed.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify test failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Spotify error: {exc}")
