import React, { useState, useEffect, useCallback } from 'react';
import { getSettings, updateSettings, testSlskd, testSpotify, getSpotifyAuthStatus, getSpotifyAuthUrl, exchangeSpotifyCode, disconnectSpotify } from '../api/client.js';

const TEMPLATE_VARS = [
  '{artist}', '{album_artist}', '{album}', '{title}',
  '{year}', '{track_number}', '{disc_number}', '{genre}',
];

const EXAMPLE_VALUES = {
  '{artist}': 'Radiohead',
  '{album_artist}': 'Radiohead',
  '{album}': 'OK Computer',
  '{title}': 'Karma Police',
  '{year}': '1997',
  '{track_number}': '03',
  '{disc_number}': '1',
  '{genre}': 'Alternative Rock',
};

function applyTemplate(template, values) {
  if (!template) return '';
  return Object.entries(values).reduce((acc, [k, v]) => acc.split(k).join(v), template);
}

function PasswordInput({ value, onChange, placeholder, id }) {
  const [show, setShow] = useState(false);
  return (
    <div className="input-group">
      <input
        id={id}
        type={show ? 'text' : 'password'}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        style={{ borderRadius: 'var(--radius) 0 0 var(--radius)' }}
      />
      <span className="input-addon" onClick={() => setShow((s) => !s)} title={show ? 'Hide' : 'Show'}>
        {show ? '○' : '●'}
      </span>
    </div>
  );
}

export default function Settings({ addToast }) {
  const [form, setForm] = useState({
    slskd_url: '',
    slskd_api_key: '',
    spotify_client_id: '',
    spotify_client_secret: '',
    library_path: '',
    download_path: '',
    folder_template: '{artist}/{album}',
    filename_template: '{track_number} - {title}',
    preferred_format: 'FLAC',
    min_bitrate: '',
    acoustid_api_key: '',
    auto_tag: true,
    auto_organize: true,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const [slskdTest, setSlskdTest] = useState(null); // null | 'testing' | 'ok' | 'fail'
  const [slskdTestMsg, setSlskdTestMsg] = useState('');
  const [spotifyTest, setSpotifyTest] = useState(null);
  const [spotifyTestMsg, setSpotifyTestMsg] = useState('');
  const [spotifyConnected, setSpotifyConnected] = useState(false);

  const [showSpotifyOAuth, setShowSpotifyOAuth] = useState(false);
  const [oauthStep, setOauthStep] = useState(1); // 1 = open link, 2 = paste URL
  const [oauthAuthUrl, setOauthAuthUrl] = useState('');
  const [pastedUrl, setPastedUrl] = useState('');
  const [oauthLoading, setOauthLoading] = useState(false);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getSettings();
      // Backend returns { settings: { key: value, ... } }
      setForm((prev) => ({ ...prev, ...(data.settings ?? data) }));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSpotifyStatus = useCallback(async () => {
    try {
      const status = await getSpotifyAuthStatus();
      setSpotifyConnected(status?.connected ?? false);
    } catch {
      setSpotifyConnected(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
    loadSpotifyStatus();

    // Check for ?spotify_connected=1 in URL after OAuth redirect
    const params = new URLSearchParams(window.location.search);
    if (params.get('spotify_connected') === '1') {
      addToast('success', 'Spotify connected', 'Your Spotify account has been connected successfully.');
      // Clean up URL
      const url = new URL(window.location.href);
      url.searchParams.delete('spotify_connected');
      window.history.replaceState({}, '', url.toString());
    }
  }, [loadSettings, loadSpotifyStatus, addToast]);

  const handleConnectSpotify = async () => {
    try {
      const data = await getSpotifyAuthUrl();
      setOauthAuthUrl(data.auth_url);
      setOauthStep(1);
      setShowSpotifyOAuth(true);
    } catch (e) {
      addToast('error', 'Failed to get auth URL', e.message);
    }
  };

  const handlePasteSubmit = async () => {
    setOauthLoading(true);
    try {
      // Extract code from pasted URL
      let code = pastedUrl.trim();
      try {
        const u = new URL(code);
        code = u.searchParams.get('code') || code;
      } catch {}

      await exchangeSpotifyCode(code, 'http://127.0.0.1:8000/spotify-callback');
      addToast('success', 'Spotify connected successfully!');
      setShowSpotifyOAuth(false);
      setPastedUrl('');
      loadSpotifyStatus();
    } catch (e) {
      addToast('error', 'Failed to connect Spotify', e.message);
    } finally {
      setOauthLoading(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnectSpotify();
      setSpotifyConnected(false);
      addToast('success', 'Spotify disconnected', 'Your Spotify account has been disconnected.');
    } catch (err) {
      addToast('error', 'Failed to disconnect', err.message);
    }
  };

  const set = (field) => (e) => {
    const val = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: val }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await updateSettings(form);
      addToast('success', 'Settings saved', 'Configuration updated successfully');
    } catch (err) {
      addToast('error', 'Failed to save settings', err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleTestSlskd = async () => {
    setSlskdTest('testing');
    setSlskdTestMsg('');
    try {
      const res = await testSlskd();
      setSlskdTest('ok');
      setSlskdTestMsg(res?.message || 'Connected successfully');
    } catch (err) {
      setSlskdTest('fail');
      setSlskdTestMsg(err.message);
    }
  };

  const handleTestSpotify = async () => {
    setSpotifyTest('testing');
    setSpotifyTestMsg('');
    try {
      const res = await testSpotify();
      setSpotifyTest('ok');
      setSpotifyTestMsg(res?.message || 'Credentials valid');
    } catch (err) {
      setSpotifyTest('fail');
      setSpotifyTestMsg(err.message);
    }
  };

  const folderPreview = applyTemplate(form.folder_template, EXAMPLE_VALUES);
  const filenamePreview = applyTemplate(form.filename_template, EXAMPLE_VALUES);
  const fullPathPreview = [form.library_path, folderPreview, filenamePreview]
    .filter(Boolean)
    .join('/');

  if (loading) {
    return (
      <div className="loading-state">
        <div className="spinner" />
        Loading settings…
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-state">
        <div className="error-icon">⚠</div>
        <strong>Failed to load settings</strong>
        <p>{error}</p>
        <button className="btn btn-primary btn-sm" onClick={loadSettings}>Retry</button>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <div className="page-subtitle">Configure Songarr, slskd, Spotify, and library options</div>
        </div>
      </div>

      <form className="settings-layout" onSubmit={handleSave}>
        {/* Soulseek / slskd */}
        <div className="settings-section">
          <div className="settings-section-title">
            <span>⊙</span> Soulseek / slskd
          </div>

          <div className="form-group">
            <label>slskd URL</label>
            <input
              type="text"
              value={form.slskd_url}
              onChange={set('slskd_url')}
              placeholder="http://localhost:5030"
            />
            <div className="form-hint">Base URL of your slskd instance</div>
          </div>

          <div className="form-group">
            <label>slskd API Key</label>
            <PasswordInput
              value={form.slskd_api_key}
              onChange={set('slskd_api_key')}
              placeholder="Enter API key"
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={handleTestSlskd}
              disabled={slskdTest === 'testing'}
            >
              {slskdTest === 'testing' ? (
                <><span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} /> Testing…</>
              ) : 'Test Connection'}
            </button>
            {slskdTest === 'ok' && (
              <span className="test-result success">✓ {slskdTestMsg}</span>
            )}
            {slskdTest === 'fail' && (
              <span className="test-result error">✕ {slskdTestMsg}</span>
            )}
          </div>
        </div>

        {/* Spotify */}
        <div className="settings-section">
          <div className="settings-section-title">
            <span>⊕</span> Spotify
          </div>

          <div className="form-group">
            <label>Client ID</label>
            <input
              type="text"
              value={form.spotify_client_id}
              onChange={set('spotify_client_id')}
              placeholder="Spotify Developer Client ID"
            />
          </div>

          <div className="form-group">
            <label>Client Secret</label>
            <PasswordInput
              value={form.spotify_client_secret}
              onChange={set('spotify_client_secret')}
              placeholder="Spotify Developer Client Secret"
            />
            <div className="form-hint">
              Get credentials at{' '}
              <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noopener noreferrer">
                developer.spotify.com
              </a>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={handleTestSpotify}
              disabled={spotifyTest === 'testing'}
            >
              {spotifyTest === 'testing' ? (
                <><span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} /> Testing…</>
              ) : 'Test Credentials'}
            </button>
            {spotifyTest === 'ok' && (
              <span className="test-result success">✓ {spotifyTestMsg}</span>
            )}
            {spotifyTest === 'fail' && (
              <span className="test-result error">✕ {spotifyTestMsg}</span>
            )}
          </div>

          <div className="spotify-connect-panel" style={{ marginTop: 16 }}>
            <div className="form-group">
              <label>ACCOUNT CONNECTION</label>
              {!showSpotifyOAuth && (
                spotifyConnected ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <span className="badge badge-success" style={{ color: 'var(--success, #1db954)', fontWeight: 600 }}>● Spotify Connected</span>
                    <button className="btn btn-danger btn-sm" type="button" onClick={handleDisconnect}>Disconnect</button>
                  </div>
                ) : (
                  <button className="btn btn-primary" type="button" onClick={handleConnectSpotify}>
                    Connect Spotify Account
                  </button>
                )
              )}

              {showSpotifyOAuth && (
                <div className="card" style={{ marginTop: '1rem', border: '1px solid var(--border)' }}>
                  <div className="card-header">CONNECT SPOTIFY ACCOUNT</div>
                  <div className="card-body">
                    <div style={{ marginBottom: '1rem' }}>
                      <strong>Step 1:</strong>{' '}
                      <a href={oauthAuthUrl} target="_blank" rel="noreferrer" className="btn btn-primary btn-sm"
                         onClick={() => setOauthStep(2)}>
                        Open Spotify Authorization ↗
                      </a>
                      <p style={{ marginTop: '0.5rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                        Authorize in the new tab. Make sure <code>http://127.0.0.1:8000/spotify-callback</code> is added as a Redirect URI in your{' '}
                        <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noreferrer">Spotify app settings</a>.
                      </p>
                    </div>

                    {oauthStep >= 2 && (
                      <div>
                        <strong>Step 2:</strong> After authorizing, your browser will redirect to <code>127.0.0.1:8000</code>.
                        <ul style={{ margin: '0.5rem 0', paddingLeft: '1.2rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                          <li>If Songarr opened automatically — you&apos;re done! Check the connection status above.</li>
                          <li>If you see a &quot;connection refused&quot; error, <strong>copy the full URL from the address bar</strong> and paste it below:</li>
                        </ul>
                        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                          <input
                            className="form-control"
                            placeholder="http://127.0.0.1:8000/spotify-callback?code=AQD..."
                            value={pastedUrl}
                            onChange={e => setPastedUrl(e.target.value)}
                            style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}
                          />
                          <button className="btn btn-primary" type="button" onClick={handlePasteSubmit} disabled={!pastedUrl || oauthLoading}>
                            {oauthLoading ? '…' : 'Connect'}
                          </button>
                        </div>
                      </div>
                    )}

                    <button className="btn btn-ghost btn-sm" type="button" style={{ marginTop: '1rem' }}
                            onClick={() => setShowSpotifyOAuth(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Library */}
        <div className="settings-section">
          <div className="settings-section-title">
            <span>♫</span> Library
          </div>

          <div className="form-group">
            <label>Music Library Path</label>
            <input
              type="text"
              value={form.library_path}
              onChange={set('library_path')}
              placeholder="/music"
            />
            <div className="form-hint">Root directory where organized music is stored</div>
          </div>

          <div className="form-group">
            <label>Download Path</label>
            <input
              type="text"
              value={form.download_path}
              onChange={set('download_path')}
              placeholder="/downloads"
            />
            <div className="form-hint">Temporary directory for files during download</div>
          </div>

          <div className="form-group">
            <label>Folder Template</label>
            <input
              type="text"
              value={form.folder_template}
              onChange={set('folder_template')}
              placeholder="{artist}/{album}"
            />
          </div>

          <div className="form-group">
            <label>Filename Template</label>
            <input
              type="text"
              value={form.filename_template}
              onChange={set('filename_template')}
              placeholder="{track_number} - {title}"
            />
          </div>

          <div className="form-group">
            <label style={{ marginBottom: 4 }}>Available Variables</label>
            <div className="template-vars">
              {TEMPLATE_VARS.map((v) => (
                <span key={v} className="template-var">{v}</span>
              ))}
            </div>
          </div>

          {(form.folder_template || form.filename_template) && (
            <div className="form-group">
              <label>Path Preview</label>
              <div className="template-preview">
                {fullPathPreview || <span style={{ color: 'var(--text-muted)' }}>—</span>}
              </div>
            </div>
          )}
        </div>

        {/* Quality */}
        <div className="settings-section">
          <div className="settings-section-title">
            <span>◉</span> Quality
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Preferred Format</label>
              <select value={form.preferred_format} onChange={set('preferred_format')}>
                <option value="FLAC">FLAC</option>
                <option value="MP3">MP3</option>
                <option value="Any">Any</option>
              </select>
            </div>

            <div className="form-group">
              <label>Minimum Bitrate (kbps)</label>
              <input
                type="number"
                value={form.min_bitrate}
                onChange={set('min_bitrate')}
                placeholder="e.g. 320"
                min="0"
                max="9999"
              />
              <div className="form-hint">0 = no minimum</div>
            </div>
          </div>
        </div>

        {/* Tagging */}
        <div className="settings-section">
          <div className="settings-section-title">
            <span>⊘</span> Tagging
          </div>

          <div className="form-group" style={{ marginBottom: 14 }}>
            <label>AcoustID API Key</label>
            <input
              type="text"
              value={form.acoustid_api_key}
              onChange={set('acoustid_api_key')}
              placeholder="AcoustID application API key"
            />
            <div className="form-hint">
              Get a free key at{' '}
              <a href="https://acoustid.org/my-applications" target="_blank" rel="noopener noreferrer">
                acoustid.org
              </a>
            </div>
          </div>

          <div className="toggle-row">
            <div>
              <div className="toggle-label">Auto-tag</div>
              <div className="toggle-desc">Automatically identify and tag downloaded files using AcoustID</div>
            </div>
            <input type="checkbox" checked={!!form.auto_tag} onChange={set('auto_tag')} />
          </div>

          <div className="toggle-row">
            <div>
              <div className="toggle-label">Auto-organize</div>
              <div className="toggle-desc">Move tagged files into the library folder structure automatically</div>
            </div>
            <input type="checkbox" checked={!!form.auto_organize} onChange={set('auto_organize')} />
          </div>
        </div>

        {/* Save */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button type="button" className="btn btn-ghost" onClick={loadSettings}>
            Revert
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving
              ? <><span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> Saving…</>
              : '✓ Save Settings'}
          </button>
        </div>
      </form>
    </div>
  );
}
