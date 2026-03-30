import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  importSpotifyPlaylist,
  getPlaylists,
  getPlaylistTracks,
  queuePlaylistTracks,
} from '../api/client.js';
import StatusBadge from '../components/StatusBadge.jsx';

function formatDuration(ms) {
  if (!ms) return '—';
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function SpotifyImport({ addToast }) {
  const [url, setUrl] = useState('');
  const [urlError, setUrlError] = useState('');
  const [fetching, setFetching] = useState(false);

  const [currentPlaylist, setCurrentPlaylist] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [tracksLoading, setTracksLoading] = useState(false);
  const [tracksError, setTracksError] = useState(null);

  const [selectedIds, setSelectedIds] = useState(new Set());
  const [queuing, setQueuing] = useState(false);
  const [queued, setQueued] = useState(false);

  const [playlists, setPlaylists] = useState([]);
  const [playlistsLoading, setPlaylistsLoading] = useState(true);
  const [activePlaylistId, setActivePlaylistId] = useState(null);

  const pollTimer = useRef(null);

  const loadPlaylists = useCallback(async () => {
    setPlaylistsLoading(true);
    try {
      const data = await getPlaylists();
      setPlaylists(Array.isArray(data) ? data : data?.playlists ?? []);
    } catch {
      // silently fail
    } finally {
      setPlaylistsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPlaylists();
    return () => { if (pollTimer.current) clearInterval(pollTimer.current); };
  }, [loadPlaylists]);

  const loadPlaylistTracks = useCallback(async (playlistId) => {
    setTracksLoading(true);
    setTracksError(null);
    try {
      const data = await getPlaylistTracks(playlistId);
      const t = Array.isArray(data) ? data : data?.tracks ?? [];
      setTracks(t);
      setSelectedIds(new Set(t.filter((tr) => !tr.status || tr.status === 'pending').map((tr) => tr.id || tr.track_id)));
    } catch (e) {
      setTracksError(e.message);
    } finally {
      setTracksLoading(false);
    }
  }, []);

  const handleFetch = async (e) => {
    e.preventDefault();
    if (!url.trim()) { setUrlError('Enter a Spotify playlist URL or ID'); return; }
    setUrlError('');
    setFetching(true);
    setQueued(false);
    setCurrentPlaylist(null);
    setTracks([]);

    try {
      const data = await importSpotifyPlaylist(url.trim());
      const playlist = data?.playlist ?? data;
      setCurrentPlaylist(playlist);
      setActivePlaylistId(playlist.id || playlist.playlist_id);
      await loadPlaylistTracks(playlist.id || playlist.playlist_id);
      await loadPlaylists();
    } catch (err) {
      if (err.message.includes('credentials') || err.message.includes('Spotify') || err.message.includes('401')) {
        setUrlError('Spotify credentials not configured. Please check Settings.');
      } else {
        setUrlError(err.message);
      }
    } finally {
      setFetching(false);
    }
  };

  const handleSidebarSelect = async (pl) => {
    const plId = pl.id || pl.playlist_id;
    setActivePlaylistId(plId);
    setCurrentPlaylist(pl);
    setQueued(false);
    if (pollTimer.current) clearInterval(pollTimer.current);
    await loadPlaylistTracks(plId);
  };

  const toggleTrack = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedIds.size === tracks.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(tracks.map((t) => t.id || t.track_id)));
    }
  };

  const handleQueue = async () => {
    if (!selectedIds.size) { addToast('info', 'No tracks selected', null); return; }
    setQueuing(true);
    try {
      await queuePlaylistTracks(activePlaylistId, [...selectedIds]);
      setQueued(true);
      addToast('success', 'Queued', `${selectedIds.size} tracks added to download queue`);
      // Start polling for track status updates
      pollTimer.current = setInterval(async () => {
        try {
          const data = await getPlaylistTracks(activePlaylistId);
          const t = Array.isArray(data) ? data : data?.tracks ?? [];
          setTracks(t);
          const allDone = t.every((tr) =>
            ['completed', 'failed', 'cancelled'].includes((tr.status || '').toLowerCase())
          );
          if (allDone) clearInterval(pollTimer.current);
        } catch {
          clearInterval(pollTimer.current);
        }
      }, 3000);
    } catch (err) {
      addToast('error', 'Queue failed', err.message);
    } finally {
      setQueuing(false);
    }
  };

  const hasSpotifyError =
    !fetching && urlError && (urlError.includes('credentials') || urlError.includes('Settings'));

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Spotify Import</h1>
          <div className="page-subtitle">Import playlists from Spotify and queue tracks for download</div>
        </div>
      </div>

      <div className="spotify-layout">
        {/* Main panel */}
        <div>
          {/* Step 1: Input */}
          <div className="card" style={{ marginBottom: 14 }}>
            <div className="section-title">Import Playlist</div>
            <form onSubmit={handleFetch}>
              <div className="form-group">
                <label>Spotify Playlist URL or ID</label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    type="text"
                    value={url}
                    onChange={(e) => { setUrl(e.target.value); setUrlError(''); }}
                    placeholder="https://open.spotify.com/playlist/… or playlist ID"
                    style={{ flex: 1 }}
                  />
                  <button type="submit" className="btn btn-primary" disabled={fetching} style={{ flexShrink: 0 }}>
                    {fetching
                      ? <><span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> Fetching…</>
                      : '⊕ Fetch Playlist'}
                  </button>
                </div>
                {urlError && !hasSpotifyError && <div className="form-error">{urlError}</div>}
              </div>
            </form>

            {hasSpotifyError && (
              <div className="warning-block">
                <span>⚠</span>
                <span>
                  Spotify credentials are not configured.{' '}
                  <a href="/settings">Go to Settings</a> to add your Client ID and Secret.
                </span>
              </div>
            )}
          </div>

          {/* Step 2: Playlist review */}
          {tracksLoading && (
            <div className="loading-state">
              <div className="spinner" />
              Loading tracks…
            </div>
          )}

          {tracksError && (
            <div className="error-state">
              <div className="error-icon">⚠</div>
              <strong>Failed to load tracks</strong>
              <p>{tracksError}</p>
            </div>
          )}

          {!tracksLoading && !tracksError && currentPlaylist && (
            <>
              {/* Playlist header */}
              <div className="playlist-header-card">
                {currentPlaylist.cover_url ? (
                  <img
                    src={currentPlaylist.cover_url}
                    alt="Playlist cover"
                    className="playlist-cover"
                  />
                ) : (
                  <div className="playlist-cover-placeholder">♫</div>
                )}
                <div className="playlist-info">
                  <h2>{currentPlaylist.name || currentPlaylist.playlist_name || 'Playlist'}</h2>
                  {currentPlaylist.description && <p>{currentPlaylist.description}</p>}
                  <div className="playlist-meta">
                    {currentPlaylist.owner && <span>{currentPlaylist.owner} · </span>}
                    <span>{tracks.length} tracks</span>
                    {currentPlaylist.followers != null && <span> · {currentPlaylist.followers?.toLocaleString()} followers</span>}
                  </div>
                </div>
              </div>

              {/* Track list controls */}
              <div className="track-select-controls">
                <input
                  type="checkbox"
                  id="select-all-tracks"
                  checked={selectedIds.size === tracks.length && tracks.length > 0}
                  onChange={toggleAll}
                />
                <label htmlFor="select-all-tracks" style={{ fontSize: 12, cursor: 'pointer', userSelect: 'none' }}>
                  {selectedIds.size === tracks.length ? 'Deselect All' : 'Select All'}
                </label>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>
                  {selectedIds.size} selected
                </span>
                {!queued && (
                  <button
                    className="btn btn-primary btn-sm"
                    style={{ marginLeft: 'auto' }}
                    onClick={handleQueue}
                    disabled={queuing || selectedIds.size === 0}
                  >
                    {queuing
                      ? <><span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} /> Queueing…</>
                      : `↓ Queue Selected (${selectedIds.size})`}
                  </button>
                )}
              </div>

              {/* Tracks table */}
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 36 }}>#</th>
                      <th style={{ width: 36 }}></th>
                      <th>Title</th>
                      <th>Artist</th>
                      <th>Album</th>
                      <th style={{ width: 60 }}>Year</th>
                      <th style={{ width: 70 }}>Duration</th>
                      <th style={{ width: 100 }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tracks.map((track, idx) => {
                      const id = track.id || track.track_id;
                      const isSelected = selectedIds.has(id);
                      const hasStatus = track.status && track.status !== 'pending';
                      return (
                        <tr key={id || idx} style={{ opacity: hasStatus && track.status === 'completed' ? 0.7 : 1 }}>
                          <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{idx + 1}</td>
                          <td onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleTrack(id)}
                              disabled={track.status === 'completed'}
                            />
                          </td>
                          <td style={{ fontWeight: 500 }}>{track.title || track.name || '—'}</td>
                          <td style={{ color: 'var(--text-secondary)' }}>
                            {Array.isArray(track.artists)
                              ? track.artists.map((a) => (typeof a === 'string' ? a : a.name)).join(', ')
                              : track.artist || '—'}
                          </td>
                          <td style={{ color: 'var(--text-secondary)' }}>
                            {typeof track.album === 'object' ? track.album?.name : track.album || '—'}
                          </td>
                          <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                            {track.release_year || track.year || (typeof track.album === 'object' ? track.album?.release_date?.substring(0, 4) : null) || '—'}
                          </td>
                          <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                            {formatDuration(track.duration_ms || track.duration)}
                          </td>
                          <td>
                            {track.status && track.status !== 'pending' ? (
                              <StatusBadge status={track.status} />
                            ) : (
                              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {queued && (
                <div className="info-block" style={{ marginTop: 12 }}>
                  <span>⊙</span>
                  <span>
                    {selectedIds.size} tracks queued. Track statuses update automatically every 3 seconds.
                  </span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Sidebar — Imported playlists */}
        <div>
          <div className="imported-playlists-sidebar">
            <div className="sidebar-header">Imported Playlists</div>
            {playlistsLoading && (
              <div className="loading-state" style={{ padding: 16 }}>
                <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
              </div>
            )}
            {!playlistsLoading && playlists.length === 0 && (
              <div className="empty-state" style={{ padding: 16 }}>
                <span style={{ fontSize: 12 }}>No imports yet</span>
              </div>
            )}
            {!playlistsLoading && playlists.map((pl) => {
              const plId = pl.id || pl.playlist_id;
              return (
                <div
                  key={plId}
                  className={`playlist-sidebar-item${activePlaylistId === plId ? ' active' : ''}`}
                  onClick={() => handleSidebarSelect(pl)}
                >
                  <div className="playlist-sidebar-name">
                    {pl.name || pl.playlist_name || 'Playlist'}
                  </div>
                  <div className="playlist-sidebar-meta">
                    {pl.track_count ?? pl.total_tracks ?? '?'} tracks
                    {pl.imported_at && (
                      <span> · {new Date(pl.imported_at).toLocaleDateString()}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
