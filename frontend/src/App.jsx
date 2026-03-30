import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Navbar from './components/Navbar.jsx';
import Toast from './components/Toast.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Search from './pages/Search.jsx';
import Library from './pages/Library.jsx';
import SpotifyImport from './pages/SpotifyImport.jsx';
import Settings from './pages/Settings.jsx';
import SpotifyCallback from './pages/SpotifyCallback.jsx';
import { useDownloads } from './hooks/useDownloads.js';
import { useToast } from './hooks/useToast.js';

export default function App() {
  // Single shared WebSocket connection for the whole app
  const { downloads, connected } = useDownloads();
  const { toasts, addToast, removeToast } = useToast();

  return (
    <div className="app-layout">
      <Navbar connected={connected} />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard addToast={addToast} downloads={downloads} connected={connected} />} />
          <Route path="/search" element={<Search addToast={addToast} downloads={downloads} />} />
          <Route path="/library" element={<Library addToast={addToast} />} />
          <Route path="/spotify" element={<SpotifyImport addToast={addToast} />} />
          <Route path="/settings" element={<Settings addToast={addToast} />} />
          <Route path="/spotify-callback" element={<SpotifyCallback />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Toast toasts={toasts} removeToast={removeToast} />
    </div>
  );
}
