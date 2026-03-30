import React from 'react';
import { NavLink } from 'react-router-dom';

const NAV_ITEMS = [
  { to: '/', icon: '⊞', label: 'Dashboard', end: true },
  { to: '/search', icon: '⊙', label: 'Search' },
  { to: '/library', icon: '♫', label: 'Library' },
  { to: '/spotify', icon: '⊕', label: 'Spotify Import' },
  { to: '/settings', icon: '⚙', label: 'Settings' },
];

export default function Navbar({ connected }) {
  return (
    <nav className="navbar">
      <div className="navbar-logo">
        <div className="navbar-logo-name">SONGARR</div>
        <div className="navbar-logo-sub">Music Acquisition</div>
      </div>

      <ul className="navbar-nav">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            >
              <span className="nav-item-icon">{item.icon}</span>
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="navbar-footer">
        <span className="navbar-version">v1.0.0</span>
        <div className="navbar-conn">
          <span className={`conn-dot ${connected ? 'connected' : 'disconnected'}`} />
          {connected ? 'Live' : 'Offline'}
        </div>
      </div>
    </nav>
  );
}
