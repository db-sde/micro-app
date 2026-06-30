import React, { useState, useRef, useCallback, useEffect } from 'react';
import { NavLink } from 'react-router-dom';

/* ═══════════════════════════════════════════════════════════════
   SHARED COMPONENTS — DegreeBaba Content Publisher
   ═══════════════════════════════════════════════════════════════ */

/* ─── Utility: Human-readable file size ─── */
export function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/* ─── Utility: Relative date ─── */
export function relativeDate(dateString) {
  if (!dateString) return '—';
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/* ═══════════════════════════════════════
   SIDEBAR
   ═══════════════════════════════════════ */
export function Sidebar() {
  return (
    <aside className="sidebar" id="sidebar" role="navigation" aria-label="Main navigation">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        </div>
        <div className="sidebar-brand-text">
          <span className="sidebar-brand-name">Content Publisher</span>
          <span className="sidebar-brand-sub">Parsing Suite</span>
        </div>
      </div>

      <div className="sidebar-section-label">Main</div>
      <nav className="sidebar-nav">
        <NavLink to="/" end className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`} id="nav-dashboard">
          <span className="sidebar-nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
          </span>
          <span>Dashboard</span>
        </NavLink>

        <NavLink to="/upload" className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`} id="nav-upload">
          <span className="sidebar-nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </span>
          <span>New Upload</span>
        </NavLink>

        <NavLink to="/bulk" className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`} id="nav-bulk">
          <span className="sidebar-nav-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
              <line x1="3" y1="9" x2="21" y2="9"/>
              <line x1="9" y1="21" x2="9" y2="9"/>
            </svg>
          </span>
          <span className="sidebar-nav-label">Bulk Process</span>
        </NavLink>

        <NavLink to="/blog-summarizer" className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`} id="nav-blog">
          <span className="sidebar-nav-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
          </span>
          <span className="sidebar-nav-label">Blog Summarizer</span>
        </NavLink>

        <NavLink to="/history" className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`} id="nav-history">
          <span className="sidebar-nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          </span>
          <span>History</span>
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        <span className="sidebar-footer-logo">
          Powered by <span>DegreeBaba</span>
        </span>
      </div>
    </aside>
  );
}

/* ═══════════════════════════════════════
   TOP BAR
   ═══════════════════════════════════════ */
export function TopBar({ title, subtitle, children }) {
  return (
    <div className="topbar" id="topbar">
      <div className="topbar-left">
        <h1 className="topbar-title">{title}</h1>
        {subtitle && <p className="topbar-subtitle">{subtitle}</p>}
      </div>
      {children && <div className="topbar-actions">{children}</div>}
    </div>
  );
}

/* ═══════════════════════════════════════
   STAT CARD
   ═══════════════════════════════════════ */
export function StatCard({ icon, label, value, trend, color = 'orange' }) {
  return (
    <div className={`stat-card stat-card--${color}`} id={`stat-${label?.toLowerCase().replace(/\s+/g, '-')}`}>
      <div className="stat-card-icon" aria-hidden="true">{icon}</div>
      <div className="stat-card-value">{value}</div>
      <div className="stat-card-label">{label}</div>
      {trend && (
        <div className={`stat-card-trend stat-card-trend--${trend.direction}`}>
          {trend.direction === 'up' ? '↑' : '↓'} {trend.value}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   STATUS BADGE
   ═══════════════════════════════════════ */
export function StatusBadge({ status }) {
  if (!status) return null;
  const normalized = status.toLowerCase().replace(/\s+/g, '');

  const statusBadgeMap = {
    'complete':   { status: 'published', label: 'Complete'   },
    'processed':  { status: 'published', label: 'Processed'  },
    'published':  { status: 'published', label: 'Published'  },
    'draft':      { status: 'draft',     label: 'Draft'      },
    'validated':  { status: 'mapped',    label: 'Validated'  },
    'processing': { status: 'processing',label: 'Processing' },
    'pending':    { status: 'draft',     label: 'Pending'    },
    'failed':     { status: 'failed',    label: 'Failed'     },
    'issues':     { status: 'issues',    label: 'Issues'     },
    'error':      { status: 'failed',    label: 'Error'      },
  };

  const badgeInfo = statusBadgeMap[normalized] || { status: normalized, label: status.charAt(0).toUpperCase() + status.slice(1) };

  return (
    <span className={`badge badge--${badgeInfo.status}`} id={`badge-${normalized}`}>
      <span className="badge-dot" />
      {badgeInfo.label}
    </span>
  );
}

/* ═══════════════════════════════════════
   CONFIDENCE BAR
   ═══════════════════════════════════════ */
export function ConfidenceBar({ value = 0, showLabel = true }) {
  const pct = Math.round(Math.max(0, Math.min(100, value * 100)));
  const level = pct >= 80 ? 'high' : pct >= 60 ? 'mid' : 'low';
  return (
    <div className="confidence-bar" role="progressbar" aria-valuenow={pct} aria-valuemin="0" aria-valuemax="100">
      <div className="confidence-bar-track">
        <div
          className={`confidence-bar-fill confidence-bar-fill--${level}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className={`confidence-bar-label text-${level === 'high' ? 'success' : level === 'mid' ? 'warning' : 'error'}`}>
          {pct}%
        </span>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   DROP ZONE
   ═══════════════════════════════════════ */
export function DropZone({ onFileDrop, accept, label, sublabel, multiple = false, id = 'dropzone' }) {
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState(null);
  const inputRef = useRef(null);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragIn = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragOut = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      const f = multiple ? Array.from(files) : files[0];
      setFile(multiple ? f[0] : f);
      onFileDrop && onFileDrop(f);
    }
  }, [onFileDrop, multiple]);

  const handleChange = useCallback((e) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      const f = multiple ? Array.from(files) : files[0];
      setFile(multiple ? f[0] : f);
      onFileDrop && onFileDrop(f);
    }
  }, [onFileDrop, multiple]);

  const removeFile = useCallback((e) => {
    e.stopPropagation();
    setFile(null);
    if (inputRef.current) inputRef.current.value = '';
    onFileDrop && onFileDrop(null);
  }, [onFileDrop]);

  const classes = [
    'dropzone',
    dragOver && 'dropzone--active',
    file && 'dropzone--has-file'
  ].filter(Boolean).join(' ');

  return (
    <div
      className={classes}
      id={id}
      onDragEnter={handleDragIn}
      onDragOver={handleDrag}
      onDragLeave={handleDragOut}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      aria-label={label || 'Upload file'}
      tabIndex={0}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={handleChange}
        onClick={(e) => e.stopPropagation()}
        style={{ display: 'none' }}
        tabIndex={-1}
      />
      <div className="dropzone-icon" aria-hidden="true">
        {file ? '✓' : (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        )}
      </div>
      <div className="dropzone-label">{file ? 'File selected' : (label || 'Drop your file here')}</div>
      <div className="dropzone-sublabel">{file ? '' : (sublabel || 'or click to browse')}</div>
      {file && (
        <div className="dropzone-file-info">
          <span className="dropzone-file-name">{file.name}</span>
          <span className="dropzone-file-size">{formatFileSize(file.size)}</span>
          <button className="dropzone-file-remove" onClick={removeFile} aria-label="Remove file" type="button">×</button>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   DATA TABLE
   ═══════════════════════════════════════ */
export function DataTable({ columns = [], data = [], emptyMessage = 'No data found', pagination, id = 'data-table' }) {
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState('asc');

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  let sortedData = [...data];
  if (sortKey) {
    sortedData.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
      }
      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      return sortDir === 'asc' ? aStr.localeCompare(bStr) : bStr.localeCompare(aStr);
    });
  }

  if (data.length === 0) {
    return (
      <div className="card" id={id}>
        <EmptyState icon="📋" title="Nothing here yet" message={emptyMessage} />
      </div>
    );
  }

  return (
    <div className="card" id={id} style={{ animationDelay: '0.1s' }}>
      <div className="data-table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => col.sortable !== false && handleSort(col.key)}
                  className={sortKey === col.key ? 'sorted' : ''}
                  style={col.width ? { width: col.width } : undefined}
                >
                  {col.label}
                  {col.sortable !== false && (
                    <span className="sort-icon">
                      {sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedData.map((row, rowIdx) => (
              <tr key={row.id || rowIdx} className={row._highlight ? 'row-highlight' : ''}>
                {columns.map((col) => (
                  <td key={col.key}>
                    {col.render ? col.render(row[col.key], row, rowIdx) : (row[col.key] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pagination && (
        <div className="table-pagination">
          <span>
            Showing {pagination.from}–{pagination.to} of {pagination.total}
          </span>
          <div className="table-pagination-buttons">
            <button
              className="btn btn-secondary btn-sm"
              disabled={pagination.page <= 1}
              onClick={pagination.onPrev}
              id="pagination-prev"
            >
              ← Prev
            </button>
            <button
              className="btn btn-secondary btn-sm"
              disabled={pagination.page >= pagination.totalPages}
              onClick={pagination.onNext}
              id="pagination-next"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   PAGE TYPE SELECTOR
   ═══════════════════════════════════════ */
export function PageTypeSelector({ value, onChange, disabled = false }) {
  const types = [
    { key: 'university', icon: '🏛️', label: 'University' },
    { key: 'course', icon: '📚', label: 'Course' },
    { key: 'specialization', icon: '🎯', label: 'Specialization' },
  ];

  return (
    <div className="page-type-selector" id="page-type-selector" role="radiogroup" aria-label="Select page type">
      {types.map((t) => (
        <div
          key={t.key}
          className={[
            'page-type-card',
            value === t.key && 'page-type-card--selected',
            disabled && 'page-type-card--disabled'
          ].filter(Boolean).join(' ')}
          onClick={() => !disabled && onChange(t.key)}
          role="radio"
          aria-checked={value === t.key}
          tabIndex={disabled ? -1 : 0}
          id={`page-type-${t.key}`}
        >
          <div className="page-type-card-icon" aria-hidden="true">{t.icon}</div>
          <div className="page-type-card-label">{t.label}</div>
        </div>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════
   SEARCH BAR
   ═══════════════════════════════════════ */
export function SearchBar({ searchValue, onSearchChange, filterValue, onFilterChange, filterOptions = [] }) {
  return (
    <div className="search-bar" id="search-bar">
      <div className="search-input-wrap">
        <span className="search-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </span>
        <input
          className="input"
          type="text"
          placeholder="Search files…"
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          id="search-input"
          aria-label="Search"
        />
      </div>
      {filterOptions.length > 0 && (
        <select
          className="select"
          value={filterValue}
          onChange={(e) => onFilterChange(e.target.value)}
          id="filter-select"
          aria-label="Filter by page type"
        >
          {filterOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   QUALITY SCORE BADGE
   ═══════════════════════════════════════ */
export function QualityScoreBadge({ score }) {
  const s = Math.round(score || 0);
  const level = s >= 80 ? 'high' : s >= 60 ? 'mid' : 'low';
  return (
    <div className={`quality-score quality-score--${level}`} id="quality-score" aria-label={`Quality score: ${s}`}>
      <span className="quality-score-value">{s}</span>
    </div>
  );
}

/* ═══════════════════════════════════════
   LOADING SPINNER
   ═══════════════════════════════════════ */
export function LoadingSpinner({ message }) {
  return (
    <div className="spinner-wrap" id="loading-spinner" role="status" aria-live="polite">
      <div className="spinner" />
      {message && <div className="spinner-text">{message}</div>}
    </div>
  );
}

/* ═══════════════════════════════════════
   EMPTY STATE
   ═══════════════════════════════════════ */
export function EmptyState({ icon = '📭', title = 'Nothing here', message, actionLabel, onAction }) {
  return (
    <div className="empty-state" id="empty-state">
      <div className="empty-state-icon" aria-hidden="true">{icon}</div>
      <div className="empty-state-title">{title}</div>
      {message && <div className="empty-state-message">{message}</div>}
      {actionLabel && onAction && (
        <button className="btn btn-primary" onClick={onAction} id="empty-state-action">
          {actionLabel}
        </button>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   MODAL
   ═══════════════════════════════════════ */
export function Modal({ isOpen, onClose, title, children }) {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  useEffect(() => {
    const handleEsc = (e) => { if (e.key === 'Escape') onClose(); };
    if (isOpen) window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose} id="modal-overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">{title}</h3>
          <button className="modal-close" onClick={onClose} aria-label="Close modal" id="modal-close">×</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════
   STEP INDICATOR
   ═══════════════════════════════════════ */
export function StepIndicator({ currentStep }) {
  const steps = [
    { num: 1, label: 'Upload' },
    { num: 2, label: 'Validation' },
  ];

  return (
    <div className="step-indicator" id="step-indicator" role="navigation" aria-label="Upload progress">
      {steps.map((step, idx) => (
        <React.Fragment key={step.num}>
          <div
            className={[
              'step-item',
              currentStep === step.num && 'step-item--active',
              currentStep > step.num && 'step-item--completed',
            ].filter(Boolean).join(' ')}
          >
            <div className="step-circle">
              {currentStep > step.num ? '✓' : step.num}
            </div>
            <span className="step-label">{step.label}</span>
          </div>
          {idx < steps.length - 1 && (
            <div className={`step-connector ${currentStep > step.num ? 'step-connector--completed' : ''}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════
   TOAST SYSTEM
   ═══════════════════════════════════════ */
let toastId = 0;
const toastListeners = new Set();
let toasts = [];

function notifyToastListeners() {
  toastListeners.forEach((fn) => fn([...toasts]));
}

export function showToast(message, type = 'info', duration = 4000) {
  const id = ++toastId;
  toasts = [...toasts, { id, message, type }];
  notifyToastListeners();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    notifyToastListeners();
  }, duration);
}

export function ToastContainer() {
  const [items, setItems] = useState([]);

  useEffect(() => {
    toastListeners.add(setItems);
    return () => toastListeners.delete(setItems);
  }, []);

  const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };

  const dismiss = (id) => {
    toasts = toasts.filter((t) => t.id !== id);
    notifyToastListeners();
  };

  if (items.length === 0) return null;

  return (
    <div className="toast-container" id="toast-container" role="alert" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast toast--${t.type}`}>
          <span className="toast-icon">{icons[t.type] || 'ℹ'}</span>
          <span className="toast-message">{t.message}</span>
          <button className="toast-close" onClick={() => dismiss(t.id)} aria-label="Dismiss">×</button>
        </div>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════
   TOGGLE SWITCH
   ═══════════════════════════════════════ */
export function Toggle({ checked, onChange, label, id = 'toggle' }) {
  return (
    <label className="toggle-wrap" htmlFor={id}>
      <div className="toggle">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          id={id}
        />
        <span className="toggle-slider" />
      </div>
      {label && <span className="toggle-label">{label}</span>}
    </label>
  );
}

/* ═══════════════════════════════════════
   SKELETON LOADER
   ═══════════════════════════════════════ */
export function SkeletonTable({ rows = 5, cols = 5 }) {
  return (
    <div className="card">
      <div className="data-table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              {Array.from({ length: cols }).map((_, i) => (
                <th key={i}><div className="skeleton skeleton-text" style={{ width: `${60 + Math.random() * 40}%`, height: 12 }} /></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }).map((_, r) => (
              <tr key={r}>
                {Array.from({ length: cols }).map((_, c) => (
                  <td key={c}><div className="skeleton skeleton-text" style={{ width: `${40 + Math.random() * 50}%`, height: 14 }} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SkeletonStats({ count = 4 }) {
  return (
    <div className="stat-grid">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton skeleton-card" />
      ))}
    </div>
  );
}
