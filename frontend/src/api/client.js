const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body.detail || body.message || body.error || message;
    } catch {
      // ignore parse error
    }
    throw new Error(message);
  }

  // Handle 204 No Content
  if (res.status === 204) return null;

  return res.json();
}

// ---- Search ----

export async function searchSoulseek(artist, title, rawQuery) {
  const params = new URLSearchParams();
  if (rawQuery) {
    params.set('q', rawQuery);
  } else {
    if (artist) params.set('artist', artist);
    if (title) params.set('title', title);
  }
  return request(`/search?${params.toString()}`);
}

export async function downloadResult(data) {
  return request('/search/download', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function autoDownload(artist, title, album, year) {
  return request('/search/auto', {
    method: 'POST',
    body: JSON.stringify({ artist, title, album, year }),
  });
}

// ---- Downloads ----

export async function getDownloads() {
  return request('/downloads');
}

export async function getDownloadStats() {
  return request('/downloads/stats');
}

export async function cancelDownload(songId) {
  return request(`/downloads/${songId}`, { method: 'DELETE' });
}

// ---- Library ----

export async function getLibrary(params = {}) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.set(k, v);
  });
  const q = qs.toString();
  return request(`/library${q ? `?${q}` : ''}`);
}

export async function getLibraryStats() {
  return request('/library/stats');
}

export async function getArtists() {
  return request('/library/artists');
}

export async function deleteLibraryEntry(id, deleteFile = false) {
  return request(`/library/${id}?delete_file=${deleteFile}`, { method: 'DELETE' });
}

export async function updateTags(id, tags) {
  return request(`/library/${id}/tags`, {
    method: 'PATCH',
    body: JSON.stringify(tags),
  });
}

// ---- Spotify ----

export async function importSpotifyPlaylist(url) {
  return request('/spotify/playlists/import', {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}

export async function getPlaylists() {
  return request('/spotify/playlists');
}

export async function getPlaylistTracks(id) {
  return request(`/spotify/playlists/${id}/tracks`);
}

export async function queuePlaylistTracks(playlistId, trackIds) {
  return request(`/spotify/playlists/${playlistId}/queue`, {
    method: 'POST',
    body: JSON.stringify({ track_ids: trackIds }),
  });
}

// ---- Settings ----

export async function getSettings() {
  return request('/settings');
}

export async function updateSettings(data) {
  return request('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function testSlskd() {
  return request('/settings/test/slskd', { method: 'POST' });
}

export async function testSpotify() {
  return request('/settings/test/spotify', { method: 'POST' });
}
