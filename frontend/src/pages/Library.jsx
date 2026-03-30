import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { getLibrary, getLibraryStats, getArtists, deleteLibraryEntry, updateTags } from '../api/client.js';

const PAGE_SIZE = 50;

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDuration(seconds) {
  if (!seconds) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (isNaN(d)) return dateStr;
  return d.toLocaleDateString();
}

function FormatBadge({ format }) {
  if (!format) return null;
  const f = format.toUpperCase();
  let cls = 'badge badge-other';
  if (f === 'FLAC') cls = 'badge badge-flac';
  else if (['MP3', 'AAC', 'OGG', 'OPUS'].includes(f)) cls = 'badge badge-mp3';
  return <span className={cls}>{f}</span>;
}

function EditTagsModal({ entry, onClose, onSaved, addToast }) {
  const [form, setForm] = useState({
    title: entry.title || '',
    artist: entry.artist || '',
    album: entry.album || '',
    album_artist: entry.album_artist || '',
    year: entry.year || '',
    track_number: entry.track_number || '',
    genre: entry.genre || '',
  });
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});

  const handleChange = (field) => (e) => {
    setForm((f) => ({ ...f, [field]: e.target.value }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const validate = () => {
    const e = {};
    if (!form.title.trim()) e.title = 'Title is required';
    if (!form.artist.trim()) e.artist = 'Artist is required';
    return e;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) { setErrors(errs); return; }
    setSaving(true);
    try {
      await updateTags(entry.id, form);
      addToast('success', 'Tags updated', `${form.artist} — ${form.title}`);
      onSaved({ ...entry, ...form });
    } catch (err) {
      addToast('error', 'Failed to update tags', err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Edit Tags — {entry.filename || entry.title}</div>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-row">
              <div className="form-group">
                <label>Title *</label>
                <input type="text" value={form.title} onChange={handleChange('title')} />
                {errors.title && <div className="form-error">{errors.title}</div>}
              </div>
              <div className="form-group">
                <label>Artist *</label>
                <input type="text" value={form.artist} onChange={handleChange('artist')} />
                {errors.artist && <div className="form-error">{errors.artist}</div>}
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Album</label>
                <input type="text" value={form.album} onChange={handleChange('album')} />
              </div>
              <div className="form-group">
                <label>Album Artist</label>
                <input type="text" value={form.album_artist} onChange={handleChange('album_artist')} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Year</label>
                <input type="number" value={form.year} onChange={handleChange('year')} min="1900" max="2099" />
              </div>
              <div className="form-group">
                <label>Track #</label>
                <input type="number" value={form.track_number} onChange={handleChange('track_number')} min="1" />
              </div>
              <div className="form-group">
                <label>Genre</label>
                <input type="text" value={form.genre} onChange={handleChange('genre')} />
              </div>
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
              {saving ? <><span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} /> Saving…</> : 'Save Tags'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function Library({ addToast }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [artists, setArtists] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [filterArtist, setFilterArtist] = useState('');
  const [filterAlbum, setFilterAlbum] = useState('');
  const [filterFormat, setFilterFormat] = useState('');
  const [sortField, setSortField] = useState('added_at');
  const [sortOrder, setSortOrder] = useState('desc');
  const [page, setPage] = useState(1);

  const [selectedArtist, setSelectedArtist] = useState(null);
  const [expandedRow, setExpandedRow] = useState(null);
  const [editingEntry, setEditingEntry] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        sort: sortField,
        order: sortOrder,
      };
      if (selectedArtist) params.artist = selectedArtist;
      else if (filterArtist) params.artist = filterArtist;
      if (filterAlbum) params.album = filterAlbum;
      if (filterFormat) params.format = filterFormat;

      const [libRes, statsRes, artistsRes] = await Promise.all([
        getLibrary(params),
        getLibraryStats().catch(() => null),
        getArtists().catch(() => []),
      ]);

      const libItems = Array.isArray(libRes) ? libRes : libRes?.items ?? [];
      const libTotal = Array.isArray(libRes) ? libRes.length : libRes?.total ?? 0;

      setItems(libItems);
      setTotal(libTotal);
      setStats(statsRes);
      setArtists(Array.isArray(artistsRes) ? artistsRes : artistsRes?.artists ?? []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [page, sortField, sortOrder, filterArtist, filterAlbum, filterFormat, selectedArtist]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSort = (field) => {
    if (sortField === field) setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    else { setSortField(field); setSortOrder('asc'); }
    setPage(1);
  };

  const handleDelete = async (entry) => {
    if (!window.confirm(`Delete "${entry.title}"? This will remove it from the library.`)) return;
    try {
      await deleteLibraryEntry(entry.id, false);
      setItems((prev) => prev.filter((i) => i.id !== entry.id));
      setTotal((t) => t - 1);
      addToast('success', 'Deleted', entry.title);
    } catch (err) {
      addToast('error', 'Delete failed', err.message);
    }
  };

  const handleTagsSaved = (updated) => {
    setItems((prev) => prev.map((i) => (i.id === updated.id ? { ...i, ...updated } : i)));
    setEditingEntry(null);
  };

  const sortIcon = (field) => {
    if (sortField !== field) return ' ↕';
    return sortOrder === 'asc' ? ' ↑' : ' ↓';
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const formatBreakdown = useMemo(() => {
    if (!stats?.format_breakdown) return null;
    return Object.entries(stats.format_breakdown);
  }, [stats]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Library</h1>
          <div className="page-subtitle">{total.toLocaleString()} songs</div>
        </div>
      </div>

      <div className="library-layout">
        {/* Artist Sidebar */}
        <div className="artist-sidebar">
          <div className="artist-sidebar-header">Artists</div>
          <div className="artist-list">
            <div
              className={`artist-item${selectedArtist === null ? ' active' : ''}`}
              onClick={() => { setSelectedArtist(null); setPage(1); }}
            >
              <span className="artist-item-name">All Artists</span>
              <span className="artist-item-count">{total}</span>
            </div>
            {artists.map((a) => {
              const name = typeof a === 'string' ? a : a.name || a.artist;
              const count = typeof a === 'string' ? null : a.count || a.song_count;
              return (
                <div
                  key={name}
                  className={`artist-item${selectedArtist === name ? ' active' : ''}`}
                  onClick={() => { setSelectedArtist(name); setPage(1); }}
                >
                  <span className="artist-item-name" title={name}>{name}</span>
                  {count != null && <span className="artist-item-count">{count}</span>}
                </div>
              );
            })}
          </div>
        </div>

        {/* Main Content */}
        <div>
          {/* Filters */}
          <div className="library-filters">
            <input
              type="text"
              placeholder="Search artist…"
              value={filterArtist}
              onChange={(e) => { setFilterArtist(e.target.value); setPage(1); setSelectedArtist(null); }}
              style={{ maxWidth: 180 }}
            />
            <input
              type="text"
              placeholder="Search album…"
              value={filterAlbum}
              onChange={(e) => { setFilterAlbum(e.target.value); setPage(1); }}
              style={{ maxWidth: 180 }}
            />
            <select
              value={filterFormat}
              onChange={(e) => { setFilterFormat(e.target.value); setPage(1); }}
              style={{ width: 'auto', minWidth: 90 }}
            >
              <option value="">All Formats</option>
              <option value="FLAC">FLAC</option>
              <option value="MP3">MP3</option>
              <option value="AAC">AAC</option>
              <option value="OGG">OGG</option>
            </select>
            {(filterArtist || filterAlbum || filterFormat || selectedArtist) && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setFilterArtist('');
                  setFilterAlbum('');
                  setFilterFormat('');
                  setSelectedArtist(null);
                  setPage(1);
                }}
              >
                ✕ Clear
              </button>
            )}
          </div>

          {loading && (
            <div className="loading-state">
              <div className="spinner" />
              Loading library…
            </div>
          )}

          {error && (
            <div className="error-state">
              <div className="error-icon">⚠</div>
              <strong>Failed to load library</strong>
              <p>{error}</p>
              <button className="btn btn-primary btn-sm" onClick={loadData}>Retry</button>
            </div>
          )}

          {!loading && !error && items.length === 0 && (
            <div className="empty-state">
              <span style={{ fontSize: 24 }}>♫</span>
              <span>No songs found</span>
              {(filterArtist || filterAlbum || filterFormat || selectedArtist) && (
                <span style={{ fontSize: 11 }}>Try clearing the filters</span>
              )}
            </div>
          )}

          {!loading && !error && items.length > 0 && (
            <>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 40 }}>#</th>
                      <th className={sortField === 'title' ? 'sorted' : ''} onClick={() => handleSort('title')}>
                        Title{sortIcon('title')}
                      </th>
                      <th className={sortField === 'artist' ? 'sorted' : ''} onClick={() => handleSort('artist')}>
                        Artist{sortIcon('artist')}
                      </th>
                      <th className={sortField === 'album' ? 'sorted' : ''} onClick={() => handleSort('album')}>
                        Album{sortIcon('album')}
                      </th>
                      <th className={sortField === 'year' ? 'sorted' : ''} onClick={() => handleSort('year')} style={{ width: 60 }}>
                        Year{sortIcon('year')}
                      </th>
                      <th style={{ width: 70 }}>Format</th>
                      <th style={{ width: 80 }}>Bitrate</th>
                      <th style={{ width: 70 }}>Duration</th>
                      <th className={sortField === 'added_at' ? 'sorted' : ''} onClick={() => handleSort('added_at')} style={{ width: 90 }}>
                        Added{sortIcon('added_at')}
                      </th>
                      <th style={{ width: 80 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, rowIdx) => {
                      const rowNum = (page - 1) * PAGE_SIZE + rowIdx + 1;
                      const isExpanded = expandedRow === item.id;
                      return (
                        <React.Fragment key={item.id}>
                          <tr
                            className={isExpanded ? 'expanded' : ''}
                            style={{ cursor: 'pointer' }}
                            onClick={() => setExpandedRow(isExpanded ? null : item.id)}
                          >
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{rowNum}</td>
                            <td style={{ fontWeight: 500, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {item.title || '—'}
                            </td>
                            <td style={{ color: 'var(--text-secondary)', maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {item.artist || '—'}
                            </td>
                            <td style={{ color: 'var(--text-secondary)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {item.album || '—'}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{item.year || '—'}</td>
                            <td><FormatBadge format={item.format} /></td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                              {item.bitrate ? `${item.bitrate}` : '—'}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                              {formatDuration(item.duration)}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontSize: 11 }}>{formatDate(item.added_at || item.created_at)}</td>
                            <td onClick={(e) => e.stopPropagation()}>
                              <div className="td-actions">
                                <button
                                  className="btn btn-ghost btn-xs"
                                  onClick={() => setEditingEntry(item)}
                                  title="Edit tags"
                                >
                                  ✎
                                </button>
                                <button
                                  className="btn btn-danger btn-xs"
                                  onClick={() => handleDelete(item)}
                                  title="Delete"
                                >
                                  ✕
                                </button>
                              </div>
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr className="expanded-row">
                              <td colSpan={10}>
                                <div className="expanded-details">
                                  <div className="expanded-detail-row">
                                    <span className="expanded-detail-label">File path</span>
                                    <span className="expanded-detail-value">{item.file_path || item.path || '—'}</span>
                                  </div>
                                  <div className="expanded-detail-row">
                                    <span className="expanded-detail-label">File size</span>
                                    <span className="expanded-detail-value">{formatBytes(item.file_size)}</span>
                                  </div>
                                  <div className="expanded-detail-row">
                                    <span className="expanded-detail-label">MusicBrainz ID</span>
                                    <span className="expanded-detail-value">
                                      {item.musicbrainz_id || item.mb_recording_id || '—'}
                                    </span>
                                  </div>
                                  <div className="expanded-detail-row">
                                    <span className="expanded-detail-label">Tags status</span>
                                    <span className="expanded-detail-value">
                                      {item.tags_verified ? (
                                        <span className="verified-badge">✓ Verified</span>
                                      ) : (
                                        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Unverified</span>
                                      )}
                                    </span>
                                  </div>
                                  {item.album_art_url && (
                                    <div className="expanded-detail-row" style={{ gridColumn: '1 / -1' }}>
                                      <span className="expanded-detail-label">Album art</span>
                                      <img
                                        src={item.album_art_url}
                                        alt="Album art"
                                        style={{ width: 48, height: 48, objectFit: 'cover', borderRadius: 3, border: '1px solid var(--border)' }}
                                      />
                                    </div>
                                  )}
                                  <div className="expanded-detail-row">
                                    <span className="expanded-detail-label">Genre</span>
                                    <span className="expanded-detail-value">{item.genre || '—'}</span>
                                  </div>
                                  <div className="expanded-detail-row">
                                    <span className="expanded-detail-label">Track #</span>
                                    <span className="expanded-detail-value">{item.track_number || '—'}</span>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="pagination">
                  <button className="page-btn" disabled={page === 1} onClick={() => setPage(1)}>«</button>
                  <button className="page-btn" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>‹</button>
                  {Array.from({ length: Math.min(7, totalPages) }, (_, i) => {
                    let p;
                    if (totalPages <= 7) p = i + 1;
                    else if (page <= 4) p = i + 1;
                    else if (page >= totalPages - 3) p = totalPages - 6 + i;
                    else p = page - 3 + i;
                    return (
                      <button
                        key={p}
                        className={`page-btn${p === page ? ' active' : ''}`}
                        onClick={() => setPage(p)}
                      >
                        {p}
                      </button>
                    );
                  })}
                  <button className="page-btn" disabled={page === totalPages} onClick={() => setPage((p) => p + 1)}>›</button>
                  <button className="page-btn" disabled={page === totalPages} onClick={() => setPage(totalPages)}>»</button>
                  <span className="page-info">
                    {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total.toLocaleString()}
                  </span>
                </div>
              )}
            </>
          )}

          {/* Stats Bar */}
          {stats && (
            <div className="library-stats-bar">
              <span><span>{stats.total_songs?.toLocaleString() ?? 0}</span> songs</span>
              <span><span>{stats.total_artists ?? 0}</span> artists</span>
              <span><span>{stats.total_albums ?? 0}</span> albums</span>
              <span><span>{formatBytes(stats.storage_bytes)}</span> storage</span>
              {formatBreakdown && formatBreakdown.length > 0 && (
                <div className="format-breakdown">
                  {formatBreakdown.map(([fmt, count]) => {
                    const pct = stats.total_songs
                      ? Math.round((count / stats.total_songs) * 100)
                      : 0;
                    return (
                      <span key={fmt} className="format-pct">
                        <span className="label">{fmt}</span>
                        <span className="value">{pct}%</span>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {editingEntry && (
        <EditTagsModal
          entry={editingEntry}
          onClose={() => setEditingEntry(null)}
          onSaved={handleTagsSaved}
          addToast={addToast}
        />
      )}
    </div>
  );
}
