import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { getDownloadStats, getLibrary, getLibraryStats, cancelDownload } from '../api/client.js';
import StatusBadge from '../components/StatusBadge.jsx';

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (isNaN(d)) return dateStr;
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return d.toLocaleDateString();
}

function FormatBadge({ format }) {
  if (!format) return null;
  const f = format.toUpperCase();
  let cls = 'badge badge-other';
  if (f === 'FLAC') cls = 'badge badge-flac';
  else if (f === 'MP3' || f === 'AAC' || f === 'OGG') cls = 'badge badge-mp3';
  return <span className={cls}>{f}</span>;
}

export default function Dashboard({ addToast, downloads = [], connected = false }) {
  const [stats, setStats] = useState(null);
  const [libStats, setLibStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = useCallback(async () => {
    try {
      const [dlStats, ls, lib] = await Promise.all([
        getDownloadStats().catch(() => null),
        getLibraryStats().catch(() => null),
        getLibrary({ limit: 10, sort: 'added_at', order: 'desc' }).catch(() => ({ items: [], total: 0 })),
      ]);
      setStats(dlStats);
      setLibStats(ls);
      setRecent(lib.items || lib || []);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  const handleCancel = async (songId) => {
    try {
      await cancelDownload(songId);
      addToast('info', 'Download cancelled', null);
    } catch (e) {
      addToast('error', 'Cancel failed', e.message);
    }
  };

  const activeDownloads = downloads.filter((d) =>
    ['downloading', 'queued', 'tagging', 'processing'].includes((d.status || '').toLowerCase())
  );
  const queuedCount = downloads.filter((d) => d.status?.toLowerCase() === 'queued').length;
  const downloadingCount = downloads.filter((d) => d.status?.toLowerCase() === 'downloading').length;

  if (loading) {
    return (
      <div className="loading-state">
        <div className="spinner" />
        Loading dashboard…
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-state">
        <div className="error-icon">⚠</div>
        <strong>Failed to load dashboard</strong>
        <p>{error}</p>
        <button className="btn btn-primary btn-sm" onClick={loadData}>Retry</button>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <div className="page-subtitle">Overview of downloads and library activity</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className={`conn-dot ${connected ? 'connected' : 'disconnected'}`} />
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {connected ? 'Live updates' : 'Reconnecting…'}
          </span>
        </div>
      </div>

      {/* Stats Row */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-card-label">Library Songs</div>
          <div className="stat-card-value">{(libStats?.total_songs ?? 0).toLocaleString()}</div>
          <div className="stat-card-sub">{libStats?.total_artists ?? 0} artists</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Active Downloads</div>
          <div className="stat-card-value" style={{ color: downloadingCount > 0 ? 'var(--status-downloading)' : undefined }}>
            {downloadingCount}
          </div>
          <div className="stat-card-sub">in progress</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Queued</div>
          <div className="stat-card-value">{queuedCount}</div>
          <div className="stat-card-sub">waiting</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Storage Used</div>
          <div className="stat-card-value" style={{ fontSize: 16 }}>
            {formatBytes(libStats?.storage_bytes)}
          </div>
          <div className="stat-card-sub">
            {libStats?.format_breakdown
              ? Object.entries(libStats.format_breakdown)
                  .map(([fmt, count]) => `${fmt}: ${count}`)
                  .join(' · ')
              : 'library'}
          </div>
        </div>
      </div>

      {/* Main grid */}
      <div className="dashboard-grid">
        {/* Download Queue */}
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="section-header" style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', marginBottom: 0 }}>
            <h2>Download Queue</h2>
            <Link to="/search" className="btn btn-ghost btn-sm">+ Add</Link>
          </div>

          {downloads.length === 0 ? (
            <div className="empty-state">
              <span style={{ fontSize: 20 }}>⬇</span>
              <span>No downloads yet</span>
              <Link to="/search" style={{ fontSize: 11 }}>Start a search</Link>
            </div>
          ) : (
            <div className="table-wrapper" style={{ border: 'none', borderRadius: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>Song</th>
                    <th>Status</th>
                    <th>Format</th>
                    <th style={{ width: 120 }}>Progress</th>
                    <th style={{ width: 60 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {downloads.map((dl) => {
                    const isDownloading = dl.status?.toLowerCase() === 'downloading';
                    return (
                      <tr key={dl.song_id || dl.id}>
                        <td>
                          <div style={{ fontSize: 12, fontWeight: 500 }}>
                            {dl.artist && dl.title
                              ? `${dl.artist} — ${dl.title}`
                              : dl.title || dl.artist || dl.filename || `Song ${dl.song_id}`}
                          </div>
                        </td>
                        <td>
                          <StatusBadge status={dl.status} />
                        </td>
                        <td>
                          {dl.format ? <FormatBadge format={dl.format} /> : <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>}
                        </td>
                        <td>
                          {isDownloading ? (
                            <div>
                              <div className="progress-bar">
                                <div
                                  className="progress-fill"
                                  style={{ width: `${dl.progress ?? 0}%` }}
                                />
                              </div>
                              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                                {(dl.progress ?? 0).toFixed(0)}%
                              </div>
                            </div>
                          ) : (
                            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>—</span>
                          )}
                        </td>
                        <td>
                          {['queued', 'downloading'].includes(dl.status?.toLowerCase()) && (
                            <button
                              className="btn btn-danger btn-xs"
                              onClick={() => handleCancel(dl.song_id || dl.id)}
                              title="Cancel download"
                            >
                              ✕
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Recent Additions */}
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="section-header" style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', marginBottom: 0 }}>
            <h2>Recent Additions</h2>
            <Link to="/library" className="btn btn-ghost btn-sm">View All</Link>
          </div>

          {recent.length === 0 ? (
            <div className="empty-state">
              <span style={{ fontSize: 20 }}>♫</span>
              <span>Library is empty</span>
            </div>
          ) : (
            <div style={{ padding: '4px 16px' }}>
              {recent.slice(0, 10).map((item) => (
                <div key={item.id} className="recent-item">
                  <div className="recent-item-info">
                    <div className="recent-item-title">{item.title || item.filename || 'Unknown'}</div>
                    <div className="recent-item-artist">{item.artist || item.artist_name || '—'}</div>
                  </div>
                  <FormatBadge format={item.format} />
                  <div className="recent-item-date">{formatDate(item.added_at || item.created_at)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
