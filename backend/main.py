"""
Songarr — self-hosted music acquisition tool.
FastAPI application entrypoint.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import init_db, AsyncSessionLocal
from routers import downloads, library, search, settings as settings_router, spotify
from services.queue_manager import queue_manager

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("songarr")


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    logger.info("Songarr starting up...")

    # 1. Create / migrate database tables
    await init_db()

    # 2. Seed default settings
    async with AsyncSessionLocal() as session:
        from routers.settings import seed_defaults
        await seed_defaults(session)

    # 3. Apply env-var overrides to DB settings (useful for Docker deployments)
    await _apply_env_overrides()

    # 4. Start background queue worker
    queue_manager.start()

    logger.info("Songarr ready.")
    yield

    # Shutdown
    logger.info("Songarr shutting down...")
    await queue_manager.stop()


async def _apply_env_overrides() -> None:
    """
    If env vars for slskd / paths are set, write them into the DB settings
    so the rest of the app always reads from DB.
    """
    from models import AppSettings
    from sqlalchemy import select

    overrides = {
        "slskd_url": os.environ.get("SLSKD_URL"),
        "slskd_api_key": os.environ.get("SLSKD_API_KEY"),
        "music_library_path": os.environ.get("MUSIC_LIBRARY_PATH"),
        "download_path": os.environ.get("DOWNLOAD_PATH"),
        "spotify_client_id": os.environ.get("SPOTIFY_CLIENT_ID"),
        "spotify_client_secret": os.environ.get("SPOTIFY_CLIENT_SECRET"),
        "acoustid_api_key": os.environ.get("ACOUSTID_API_KEY"),
    }

    async with AsyncSessionLocal() as session:
        for key, val in overrides.items():
            if not val:
                continue
            existing = (
                await session.execute(select(AppSettings).where(AppSettings.key == key))
            ).scalar_one_or_none()
            if existing:
                existing.value = val
            else:
                session.add(AppSettings(key=key, value=val))
        await session.commit()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Songarr",
    description="Self-hosted music acquisition tool powered by Soulseek, MusicBrainz, and Spotify.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow all origins (self-hosted, accessed from any local address)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(search.router, prefix="/api")
app.include_router(downloads.router, prefix="/api")
app.include_router(library.router, prefix="/api")
app.include_router(spotify.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["meta"])
async def health():
    """Simple liveness probe."""
    return {"status": "ok", "service": "songarr"}


# ---------------------------------------------------------------------------
# Serve React frontend (production build)
# ---------------------------------------------------------------------------

# Check container path first (./frontend/dist), then dev path (../frontend/dist)
_frontend_dist = Path(__file__).parent / "frontend" / "dist"
if not _frontend_dist.exists():
    _frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    # Serve static assets under /assets (Vite default output)
    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    # Catch-all: serve index.html for client-side routing
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = _frontend_dist / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"detail": "Frontend not built yet."}


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
