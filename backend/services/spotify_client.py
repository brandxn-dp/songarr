"""
Spotipy-based Spotify client for playlist and track data retrieval.
Credentials are fetched fresh from the DB settings on each call.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes returned by this service
# ---------------------------------------------------------------------------

@dataclass
class SpotifyTrackData:
    spotify_id: str
    title: str
    artist: str                          # primary artist display string
    artists: list[str] = field(default_factory=list)
    album: str = ""
    album_artist: Optional[str] = None
    year: Optional[int] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    duration_ms: Optional[int] = None
    isrc: Optional[str] = None


@dataclass
class SpotifyPlaylistData:
    playlist_id: str
    name: str
    description: Optional[str]
    track_count: int
    tracks: list[SpotifyTrackData] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_playlist_id(playlist_url_or_id: str) -> str:
    """Extract the bare Spotify playlist ID from a URL or raw ID."""
    # Handle URL form: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
    match = re.search(r"playlist[/:]([A-Za-z0-9]+)", playlist_url_or_id)
    if match:
        return match.group(1)
    # Assume it's already a raw ID
    return playlist_url_or_id.strip()


def _parse_track(item: dict) -> Optional[SpotifyTrackData]:
    """Parse a single Spotify track object (as returned inside playlist items)."""
    track = item.get("track")
    if not track or track.get("is_local"):
        return None

    track_id = track.get("id", "")
    if not track_id:
        return None

    name: str = track.get("name", "")
    artists_raw: list[dict] = track.get("artists", [])
    artist_names = [a.get("name", "") for a in artists_raw if a.get("name")]
    artist_display = ", ".join(artist_names)

    album_obj: dict = track.get("album", {})
    album_name: str = album_obj.get("name", "")
    album_artists_raw: list[dict] = album_obj.get("artists", [])
    album_artist_names = [a.get("name", "") for a in album_artists_raw if a.get("name")]
    album_artist = album_artist_names[0] if album_artist_names else None

    # Release year
    release_date: str = album_obj.get("release_date", "")
    year: Optional[int] = None
    if release_date:
        try:
            year = int(release_date[:4])
        except (ValueError, IndexError):
            pass

    track_number: Optional[int] = track.get("track_number")
    disc_number: Optional[int] = track.get("disc_number")
    duration_ms: Optional[int] = track.get("duration_ms")

    # ISRC from external_ids
    external_ids: dict = track.get("external_ids", {})
    isrc: Optional[str] = external_ids.get("isrc")

    return SpotifyTrackData(
        spotify_id=track_id,
        title=name,
        artist=artist_display,
        artists=artist_names,
        album=album_name,
        album_artist=album_artist,
        year=year,
        track_number=track_number,
        disc_number=disc_number,
        duration_ms=duration_ms,
        isrc=isrc,
    )


# ---------------------------------------------------------------------------
# SpotifyService
# ---------------------------------------------------------------------------

class SpotifyService:
    """
    Wraps spotipy with credentials sourced from the DB settings dict.
    Construct a new instance per request (or per operation) so credentials
    are always fresh.
    """

    def __init__(self, client_id: str, client_secret: str):
        if not client_id or not client_secret:
            raise ValueError(
                "Spotify client_id and client_secret must be configured in settings."
            )
        self._sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret,
            )
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_playlist(self, playlist_id_or_url: str) -> SpotifyPlaylistData:
        """
        Fetch playlist metadata and all tracks, handling Spotify's pagination.
        Returns a SpotifyPlaylistData object.
        """
        playlist_id = _extract_playlist_id(playlist_id_or_url)
        logger.info("Fetching Spotify playlist: %s", playlist_id)

        pl = self._sp.playlist(playlist_id, fields="id,name,description,tracks.total")
        pl_name: str = pl.get("name", "")
        pl_desc: Optional[str] = pl.get("description") or None
        total: int = pl.get("tracks", {}).get("total", 0)

        tracks: list[SpotifyTrackData] = []
        offset = 0
        limit = 100

        while True:
            page = self._sp.playlist_items(
                playlist_id,
                offset=offset,
                limit=limit,
                fields="items(track(id,name,artists,album,track_number,disc_number,duration_ms,external_ids,is_local)),next",
            )
            items: list[dict] = page.get("items", [])
            for item in items:
                parsed = _parse_track(item)
                if parsed:
                    tracks.append(parsed)
            if page.get("next") is None:
                break
            offset += limit

        logger.info(
            "Fetched playlist '%s' with %d/%d tracks.", pl_name, len(tracks), total
        )
        return SpotifyPlaylistData(
            playlist_id=playlist_id,
            name=pl_name,
            description=pl_desc,
            track_count=len(tracks),
            tracks=tracks,
        )

    def get_track(self, track_id: str) -> SpotifyTrackData:
        """Fetch a single track by Spotify ID."""
        raw = self._sp.track(track_id)
        # Wrap in the same format as playlist items use
        parsed = _parse_track({"track": raw})
        if parsed is None:
            raise ValueError(f"Could not parse track {track_id}")
        return parsed

    def test_connection(self) -> bool:
        """Verify credentials work by fetching a well-known track."""
        try:
            # Fetch a known track (Bohemian Rhapsody)
            self._sp.track("7tFiyTwD0nx5a1eklYtX2J")
            return True
        except Exception as exc:
            logger.warning("Spotify connection test failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_spotify_service(settings_dict: dict) -> SpotifyService:
    """Build a SpotifyService from the app settings dict."""
    client_id = settings_dict.get("spotify_client_id", "")
    client_secret = settings_dict.get("spotify_client_secret", "")
    return SpotifyService(client_id=client_id, client_secret=client_secret)
