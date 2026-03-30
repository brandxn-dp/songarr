import React, { useState, useCallback, useMemo } from 'react';
import { searchSoulseek, downloadResult } from '../api/client.js';
import StatusBadge from '../components/StatusBadge.jsx';

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getQualityColor(score) {
  if (score >= 80) return 'var(--status-completed)';
  if (score >= 50) return 'var(--accent)';
  if (score >= 30) return 'var(--status-downloading)';
  return 'var(--status-failed)';
}

function FormatBadge({ format }) {
  if (!format) return null;
  const f = format.toUpperCase();
  let cls = 'badge badge-other';
  if (f === 'FLAC') cls = 'badge badge-flac';
  else if (['MP3', 'AAC', 'OGG', 'OPUS'].includes(f)) cls = 'badge badge-mp3';
  return <span className={cls}>{f}</span>;
}

function DownloadForm({ result, onSubmit, onCancel }) {
  const guessArtist = result.artist || '';
  const guessTitle = result.title || result.display_name?.replace(/\.\w+$/, '') || '';

  const [form, setForm] = useState({
    artist: guessArtist,
    title: guessTitle,
    album: result.album || '',
    year: result.year || '',
  });
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  const validate = () => {
    const e = {};
    if (!form.artist.trim()) e.artist = 'Artist is required';
    if (!form.title.trim()) e.title = 'Title is required';
    return e;
  };

  const handleChange = (field) => (e) => {
    setForm((f) => ({ ...f, [field]: e.target.value }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const e2 = validate();
    if (Object.keys(e2).length) { setErrors(e2); return; }
    setSubmitting(true);
    try {
      await onSubmit({ ...result, ...form });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="result-expand" onSubmit={handleSubmit}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
        Confirm Metadata
      </div>
      <div className="search-download-form">
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Artist *</label>
          <input type="text" value={form.artist} onChange={handleChange('artist')} placeholder="Artist name" />
          {errors.artist && <div className="form-error">{errors.artist}</div>}
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Title *</label>
          <input type="text" value={form.title} onChange={handleChange('title')} placeholder="Song title" />
          {errors.title && <div className="form-error">{errors.title}</div>}
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Album</label>
          <input type="text" value={form.album} onChange={handleChange('album')} placeholder="Album name" />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Year</label>
          <input type="number" value={form.year} onChange={handleChange('year')} placeholder="e.g. 2024" min="1900" max="2099" />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'flex-end' }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn btn-primary btn-sm" disabled={submitting}>
          {submitting ? <><span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} /> Queueing…</> : 'Queue Download'}
        </button>
      </div>
    </form>
  );
}

export default function Search({ addToast, downloads = [] }) {
  const [useRaw, setUseRaw] = useState(false);
  const [artist, setArtist] = useState('');
  const [title, setTitle] = useState('');
  const [rawQuery, setRawQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [expandedIdx, setExpandedIdx] = useState(null);
  const [sortKey, setSortKey] = useState('quality_score');
  const [formErrors, setFormErrors] = useState({});
  const [queuedIds, setQueuedIds] = useState(new Set());

  const validateSearch = () => {
    const e = {};
    if (useRaw) {
      if (!rawQuery.trim()) e.rawQuery = 'Enter a search query';
    } else {
      if (!artist.trim() && !title.trim()) e.artist = 'Enter at least an artist or title';
    }
    return e;
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    const errs = validateSearch();
    if (Object.keys(errs).length) { setFormErrors(errs); return; }
    setFormErrors({});
    setSearching(true);
    setSearchError(null);
    setResults([]);
    setExpandedIdx(null);

    try {
      const data = await searchSoulseek(
        useRaw ? '' : artist,
        useRaw ? '' : title,
        useRaw ? rawQuery : ''
      );
      setResults(Array.isArray(data) ? data : data.results || []);
    } catch (err) {
      setSearchError(err.message);
    } finally {
      setSearching(false);
    }
  };

  const handleDownload = useCallback(async (result, metadata) => {
    try {
      await downloadResult({
        username: result.username,
        filename: result.filename,
        size: result.size,
        display_name: result.display_name,
        format: result.format,
        bitrate: result.bitrate,
        quality_score: result.quality_score,
        artist: metadata.artist,
        title: metadata.title,
        album: metadata.album,
        year: metadata.year,
      });
      setQueuedIds((prev) => new Set([...prev, result.filename]));
      setExpandedIdx(null);
      addToast('success', 'Queued', `${metadata.artist} — ${metadata.title}`);
    } catch (err) {
      addToast('error', 'Download failed', err.message);
      throw err;
    }
  }, [addToast]);

  const sortedResults = useMemo(() => {
    if (!results.length) return [];
    const sorted = [...results];
    sorted.sort((a, b) => {
      if (sortKey === 'quality_score') return (b.quality_score ?? 0) - (a.quality_score ?? 0);
      if (sortKey === 'size') return (b.size ?? 0) - (a.size ?? 0);
      if (sortKey === 'format') return (a.format ?? '').localeCompare(b.format ?? '');
      return 0;
    });
    return sorted;
  }, [results, sortKey]);

  const recentQueue = downloads.slice(0, 5);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Search</h1>
          <div className="page-subtitle">Find and download music via Soulseek / slskd</div>
        </div>
      </div>

      <div className="search-layout">
        {/* Left panel */}
        <div>
          {/* Search form */}
          <div className="search-form-card">
            <form onSubmit={handleSearch}>
              {!useRaw ? (
                <div className="form-row" style={{ marginBottom: 10 }}>
                  <div className="form-group">
                    <label>Artist</label>
                    <input
                      type="text"
                      value={artist}
                      onChange={(e) => { setArtist(e.target.value); setFormErrors({}); }}
                      placeholder="e.g. Radiohead"
                    />
                  </div>
                  <div className="form-group">
                    <label>Title</label>
                    <input
                      type="text"
                      value={title}
                      onChange={(e) => { setTitle(e.target.value); setFormErrors({}); }}
                      placeholder="e.g. Creep"
                    />
                  </div>
                </div>
              ) : (
                <div className="form-group" style={{ marginBottom: 10 }}>
                  <label>Raw Query</label>
                  <input
                    type="text"
                    value={rawQuery}
                    onChange={(e) => { setRawQuery(e.target.value); setFormErrors({}); }}
                    placeholder="e.g. Radiohead Creep FLAC"
                    autoFocus
                  />
                  {formErrors.rawQuery && <div className="form-error">{formErrors.rawQuery}</div>}
                </div>
              )}

              {formErrors.artist && <div className="form-error" style={{ marginBottom: 8 }}>{formErrors.artist}</div>}

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                <button type="submit" className="btn btn-primary" disabled={searching}>
                  {searching ? (
                    <><span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> Searching…</>
                  ) : (
                    '⊙ Search Soulseek'
                  )}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => { setUseRaw(!useRaw); setFormErrors({}); }}
                >
                  {useRaw ? 'Use artist/title fields' : 'Use raw query'}
                </button>
              </div>
            </form>
          </div>

          {/* Results */}
          {searchError && (
            <div className="error-state" style={{ padding: 20 }}>
              <div className="error-icon">⚠</div>
              <strong>Search failed</strong>
              <p>{searchError}</p>
            </div>
          )}

          {!searching && !searchError && results.length > 0 && (
            <div>
              <div className="search-controls">
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  {results.length} result{results.length !== 1 ? 's' : ''}
                </div>
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Sort:</span>
                  <select
                    className="sort-select"
                    value={sortKey}
                    onChange={(e) => setSortKey(e.target.value)}
                  >
                    <option value="quality_score">Quality Score</option>
                    <option value="size">File Size</option>
                    <option value="format">Format</option>
                  </select>
                </div>
              </div>

              <div className="search-results-list">
                {sortedResults.map((result, idx) => {
                  const isExpanded = expandedIdx === idx;
                  const alreadyQueued = queuedIds.has(result.filename);
                  const score = result.quality_score ?? 0;

                  return (
                    <div
                      key={`${result.username}-${result.filename}-${idx}`}
                      style={{
                        background: 'var(--bg-card)',
                        border: `1px solid ${isExpanded ? 'var(--border-accent)' : 'var(--border)'}`,
                        borderRadius: 'var(--radius)',
                        overflow: 'hidden',
                        transition: 'border-color var(--transition)',
                      }}
                    >
                      <div
                        className="search-result-row"
                        style={{ cursor: 'default' }}
                      >
                        <div className="search-result-name" title={result.filename}>
                          {result.display_name || result.filename}
                        </div>
                        <FormatBadge format={result.format} />
                        <div className="search-result-meta">
                          {result.bitrate ? `${result.bitrate} kbps` : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                        </div>
                        <div className="search-result-meta">{formatBytes(result.size)}</div>
                        <div>
                          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>{score}/100</div>
                          <div className="quality-bar-wrapper">
                            <div className="quality-bar">
                              <div
                                className="quality-fill"
                                style={{ width: `${score}%`, background: getQualityColor(score) }}
                              />
                            </div>
                          </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                            {result.username}
                          </span>
                          {alreadyQueued ? (
                            <span className="badge badge-queued">Queued</span>
                          ) : (
                            <button
                              className="btn btn-primary btn-xs"
                              onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                            >
                              {isExpanded ? 'Cancel' : '↓ Download'}
                            </button>
                          )}
                        </div>
                      </div>

                      {isExpanded && (
                        <DownloadForm
                          result={result}
                          onSubmit={(metadata) => handleDownload(result, metadata)}
                          onCancel={() => setExpandedIdx(null)}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {!searching && !searchError && results.length === 0 && (
            <div className="empty-state" style={{ marginTop: 20 }}>
              <span style={{ fontSize: 24 }}>⊙</span>
              <span>Enter a query and search</span>
            </div>
          )}
        </div>

        {/* Right panel — Quick Queue */}
        <div>
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
              <div className="section-title" style={{ marginBottom: 0 }}>Recent Queue</div>
            </div>
            {recentQueue.length === 0 ? (
              <div className="empty-state" style={{ padding: '20px 14px' }}>
                <span style={{ fontSize: 18 }}>⬇</span>
                <span style={{ fontSize: 11 }}>Nothing queued yet</span>
              </div>
            ) : (
              <div style={{ padding: '4px 14px' }}>
                {recentQueue.map((dl) => (
                  <div key={dl.song_id || dl.id} className="quick-queue-item">
                    <div className="quick-queue-title">
                      {dl.title || dl.filename || `Song ${dl.song_id}`}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                      <div className="quick-queue-sub">{dl.artist || '—'}</div>
                      <StatusBadge status={dl.status} />
                    </div>
                    {dl.status?.toLowerCase() === 'downloading' && (
                      <div className="progress-bar" style={{ marginTop: 2 }}>
                        <div className="progress-fill" style={{ width: `${dl.progress ?? 0}%` }} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
