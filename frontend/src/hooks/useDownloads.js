import { useState, useEffect, useRef, useCallback } from 'react';
import { getDownloads } from '../api/client.js';

const BASE_RECONNECT = 3000;
const MAX_RECONNECT = 30000;

export function useDownloads() {
  const [downloads, setDownloads] = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectDelay = useRef(BASE_RECONNECT);
  const reconnectTimer = useRef(null);
  const unmounted = useRef(false);

  const applyUpdate = useCallback((update) => {
    setDownloads((prev) => {
      const idx = prev.findIndex((d) => d.song_id === update.song_id || d.id === update.song_id);
      if (idx === -1) {
        // New entry
        return [
          {
            id: update.song_id,
            song_id: update.song_id,
            status: update.status,
            progress: update.progress ?? 0,
            title: update.title ?? '',
            artist: update.artist ?? '',
            format: update.format ?? '',
            file_size: update.file_size ?? null,
          },
          ...prev,
        ];
      }
      const updated = [...prev];
      updated[idx] = {
        ...updated[idx],
        status: update.status ?? updated[idx].status,
        progress: update.progress ?? updated[idx].progress,
        title: update.title ?? updated[idx].title,
        artist: update.artist ?? updated[idx].artist,
        format: update.format ?? updated[idx].format,
      };
      return updated;
    });
  }, []);

  const connect = useCallback(() => {
    if (unmounted.current) return;

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    const url = `${protocol}://${host}/api/ws/downloads`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmounted.current) { ws.close(); return; }
      setConnected(true);
      reconnectDelay.current = BASE_RECONNECT;
    };

    ws.onmessage = (event) => {
      if (unmounted.current) return;
      try {
        const data = JSON.parse(event.data);
        if (Array.isArray(data)) {
          // Full state snapshot (SongWithJob array)
          setDownloads(
            data.map((d) => {
              const song = d.song ?? d;
              const job = d.job ?? {};
              return {
                id: song.id,
                song_id: song.id,
                status: song.status,
                progress: job.progress_percent ?? 0,
                title: song.title ?? '',
                artist: song.artist ?? '',
                format: job.file_format ?? '',
                file_size: job.file_size_bytes ?? null,
              };
            })
          );
        } else {
          applyUpdate(data);
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onerror = () => {
      // will be followed by onclose
    };

    ws.onclose = () => {
      if (unmounted.current) return;
      setConnected(false);
      wsRef.current = null;
      reconnectTimer.current = setTimeout(() => {
        if (!unmounted.current) {
          reconnectDelay.current = Math.min(reconnectDelay.current * 2, MAX_RECONNECT);
          connect();
        }
      }, reconnectDelay.current);
    };
  }, [applyUpdate]);

  // Fetch initial state
  useEffect(() => {
    unmounted.current = false;

    getDownloads()
      .then((data) => {
        if (!unmounted.current && Array.isArray(data)) {
          setDownloads(
            data.map((d) => {
              // Backend returns SongWithJob: { song: {...}, job: {...} }
              const song = d.song ?? d;
              const job = d.job ?? {};
              return {
                id: song.id,
                song_id: song.id,
                status: song.status,
                progress: job.progress_percent ?? 0,
                title: song.title ?? '',
                artist: song.artist ?? '',
                format: job.file_format ?? '',
                file_size: job.file_size_bytes ?? null,
              };
            })
          );
        }
      })
      .catch(() => {
        // silently fail — WS will provide data
      });

    connect();

    return () => {
      unmounted.current = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on intentional close
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { downloads, connected };
}
