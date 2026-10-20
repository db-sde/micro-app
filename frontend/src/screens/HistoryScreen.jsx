import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  TopBar, SearchBar, StatusBadge, DataTable, Modal,
  SkeletonTable, showToast, relativeDate,
  IconButton, DownloadIcon, TrashIcon, downloadUploadJson,
} from '../components/Components';
import { CatalogBackfill } from '../components/CatalogSync';
import { describeSync, ACTIVE_SYNC_STATES } from '../components/catalogApi.mjs';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';
const PAGE_SIZE = 20;
const POLL_MS = 10000;

export function ChatbotStatus({ sync, uploadId }) {
  const view = describeSync(sync);
  const tip = [view.detail, sync?.last_error && sync.last_error !== view.detail ? sync.last_error : '']
    .filter(Boolean).join('\n');
  return (
    <Link to={`/upload/${uploadId}/validation`} title={tip} style={{ textDecoration: 'none' }}>
      <span className={`badge badge--${view.tone}`}><span className="badge-dot" />{view.label}</span>
    </Link>
  );
}

export default function HistoryScreen() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const requestId = useRef(0);

  // Debounce typing so every keystroke doesn't hit the backend.
  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => { setPage(1); }, [query, filter]);

  const fetchPage = useCallback(async (quiet = false) => {
    const id = ++requestId.current;
    if (!quiet) setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((page - 1) * PAGE_SIZE) });
      if (query) params.set('q', query);
      if (filter !== 'all') params.set('page_type', filter);
      const res = await fetch(`${API_BASE}/history?${params}`);
      if (!res.ok) throw new Error('Could not load upload history');
      const data = await res.json();
      if (id !== requestId.current) return; // a newer request already answered
      setRows(data.uploads || []);
      setTotal(data.total ?? (data.uploads || []).length);
    } catch (err) {
      if (!quiet) showToast(err.message, 'error');
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [page, query, filter]);

  useEffect(() => { fetchPage(); }, [fetchPage]);

  // Refresh quietly only while a visible row is still being sent to the
  // chatbot. The old screen re-downloaded the whole history every 5 seconds.
  const anyActive = rows.some((r) => ACTIVE_SYNC_STATES.includes(r.catalog_sync?.status));
  useEffect(() => {
    if (!anyActive) return undefined;
    const timer = setInterval(() => { if (!document.hidden) fetchPage(true); }, POLL_MS);
    return () => clearInterval(timer);
  }, [anyActive, fetchPage]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);

  const handleDownload = async (item) => {
    try {
      await downloadUploadJson(API_BASE, item);
      showToast('File downloaded', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const res = await fetch(`${API_BASE}/history/${deleteTarget.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete failed');
      showToast('Upload deleted', 'success');
      setDeleteTarget(null);
      fetchPage(true);
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setDeleting(false);
    }
  };

  const filterOptions = [
    { value: 'all', label: 'All Types' },
    { value: 'university', label: 'University' },
    { value: 'course', label: 'Course' },
    { value: 'specialization', label: 'Specialization' },
    { value: 'blog', label: 'Blog' },
  ];

  const columns = [
    {
      key: 'filename', label: 'Filename', className: 'cell-wrap',
      render: (val, row) => (
        <Link className="row-link" to={`/upload/${row.id}/validation`}>{(val || '—').replace(/\.docx$/i, '')}</Link>
      ),
    },
    {
      key: 'page_type', label: 'Page Type',
      render: (val) => <span style={{ textTransform: 'capitalize' }}>{val || '—'}</span>,
    },
    {
      key: 'status', label: 'Status',
      render: (val) => <StatusBadge status={val || 'draft'} />,
    },
    {
      key: 'catalog_sync', label: 'Chatbot', sortable: false,
      render: (val, row) => <ChatbotStatus sync={val} uploadId={row.id} />,
    },
    {
      key: 'score', label: 'Score',
      render: (val) => (
        <span style={{ fontFamily: 'var(--font-code)', fontWeight: 600 }}>
          {val != null ? `${Math.round(val)}%` : '—'}
        </span>
      ),
    },
    {
      key: 'created_at', label: 'Date',
      render: (val) => (
        <span title={val || ''} style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>
          {relativeDate(val)}
        </span>
      ),
    },
    {
      key: 'actions', label: '', sortable: false, className: 'cell-actions',
      render: (_, row) => (
        <div className="table-actions">
          <IconButton label="Download JSON" onClick={() => handleDownload(row)} id={`hist-download-${row.id}`}><DownloadIcon /></IconButton>
          <IconButton label="Delete upload" danger onClick={() => setDeleteTarget(row)} id={`hist-delete-${row.id}`}><TrashIcon /></IconButton>
        </div>
      ),
    },
  ];

  const filtered = query || filter !== 'all';

  return (
    <div id="history-screen">
      <TopBar title="Upload History" subtitle={loading && total === 0 ? 'Loading…' : `${total} upload${total === 1 ? '' : 's'}${filtered ? ' match' : ''}`} />

      <CatalogBackfill />

      <SearchBar
        searchValue={search}
        onSearchChange={setSearch}
        filterValue={filter}
        onFilterChange={setFilter}
        filterOptions={filterOptions}
      />

      {loading && rows.length === 0 ? (
        <SkeletonTable rows={8} cols={7} />
      ) : (
        <div style={{ opacity: loading ? 0.6 : 1, transition: 'opacity 150ms' }} aria-busy={loading}>
          <DataTable
            columns={columns}
            data={rows}
            emptyMessage={filtered ? 'No uploads match your search.' : 'No uploads yet. Start by uploading a .docx file.'}
            id="history-table"
            pagination={total > PAGE_SIZE ? {
              page,
              totalPages,
              total,
              from,
              to,
              onPrev: () => setPage((p) => Math.max(1, p - 1)),
              onNext: () => setPage((p) => Math.min(totalPages, p + 1)),
            } : undefined}
          />
        </div>
      )}

      <Modal isOpen={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete upload">
        <div style={{ marginBottom: 24 }}>
          <p style={{ marginBottom: 8, color: 'var(--color-text-primary)', fontWeight: 500 }}>
            Delete this upload from the app?
          </p>
          <p style={{ fontSize: '0.875rem' }}>
            <strong>{deleteTarget?.filename}</strong> will be permanently removed. This cannot be undone.
          </p>
          {(deleteTarget?.status === 'published' || deleteTarget?.status === 'draft_published') && (
            <div className="notice notice--warning" style={{ marginTop: 12 }}>
              This upload was published to WordPress. Deleting it here only removes it from this app — the WordPress post stays as it is.
            </div>
          )}
        </div>
        <div className="modal-footer" style={{ padding: 0, borderTop: 'none' }}>
          <button className="btn btn-secondary" onClick={() => setDeleteTarget(null)} id="btn-cancel-delete">Cancel</button>
          <button className="btn btn-danger" onClick={confirmDelete} disabled={deleting} id="btn-confirm-delete">
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </Modal>
    </div>
  );
}
