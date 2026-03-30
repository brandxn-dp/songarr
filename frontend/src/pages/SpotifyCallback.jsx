import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { exchangeSpotifyCode } from '../api/client';

export default function SpotifyCallback() {
  const navigate = useNavigate();
  const [status, setStatus] = useState('exchanging'); // exchanging | success | error
  const [error, setError] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const err = params.get('error');

    if (err) {
      setStatus('error');
      setError(`Spotify denied access: ${err}`);
      return;
    }
    if (!code) {
      setStatus('error');
      setError('No authorization code found in URL.');
      return;
    }

    exchangeSpotifyCode(code, 'http://localhost:8000/spotify-callback')
      .then(() => {
        setStatus('success');
        setTimeout(() => navigate('/settings?spotify_connected=1'), 1500);
      })
      .catch((e) => {
        setStatus('error');
        setError(e.message || 'Token exchange failed.');
      });
  }, []);

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', flexDirection: 'column', gap: '1rem', background: 'var(--bg-primary, #0f0f0f)', color: 'var(--text-primary, #e0e0e0)' }}>
      {status === 'exchanging' && <><div className="spinner" /><p>Connecting Spotify account…</p></>}
      {status === 'success' && <><span style={{ color: 'var(--accent, #4ade80)', fontSize: '2rem' }}>✓</span><p>Connected! Redirecting…</p></>}
      {status === 'error' && <><span style={{ color: '#ef4444', fontSize: '2rem' }}>✕</span><p>{error}</p><a href="/settings" style={{ color: 'var(--accent)' }}>← Back to Settings</a></>}
    </div>
  );
}
