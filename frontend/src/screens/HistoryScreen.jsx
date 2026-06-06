import React, { useState, useEffect, useMemo } from 'react';
import {
  TopBar, SearchBar, StatusBadge, DataTable, Modal,
  LoadingSpinner, SkeletonTable, showToast, relativeDate
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';
const PAGE_SIZE = 20;

export default function HistoryScreen() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const fetchHistory = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/history`);
      if (!res.ok) throw new Error('Failed to load history');
      const data = await res.json();
      setHistory(Array.isArray(data) ? data : data.uploads || []);
    } catch (err) {
      showToast(err.message, 'error');
      setHistory([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchHistory(); }, []);

  const filtered = useMemo(() => {
    let items = [...history];

    // Filter by page type
    if (filter !== 'all') {
      items = items.filter((h) => (h.page_type || '').toLowerCase() === filter);
    }

    // Search
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter((h) =>
        (h.filename || '').toLowerCase().includes(q) ||
        (h.page_type || '').toLowerCase().includes(q)
      );
    }

    // Sort newest first
    items.sort((a, b) => new Date(b.created_at || b.date || 0) - new Date(a.created_at || a.date || 0));

    return items;
  }, [history, filter, search]);

  // Reset page when filters change
  useEffect(() => { setPage(1); }, [search, filter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageStart = (page - 1) * PAGE_SIZE;
  const pageEnd = Math.min(pageStart + PAGE_SIZE, filtered.length);
  const pageData = filtered.slice(pageStart, pageEnd);

  const handleDownload = async (item) => {
    try {
      const res = await fetch(`${API_BASE}/download/${item.id}`);
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${item.filename || item.id}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
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
      setHistory((prev) => prev.filter((h) => h.id !== deleteTarget.id));
      showToast('Upload deleted successfully', 'success');
      setDeleteTarget(null);
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
  ];

  const columns = [
    {
      key: 'filename', label: 'Filename',
      render: (val) => <span style={{ fontWeight: 600 }}>{val || '—'}</span>
    },
    {
      key: 'page_type', label: 'Page Type',
      render: (val) => <span style={{ textTransform: 'capitalize' }}>{val || '—'}</span>
    },
    {
      key: 'status', label: 'Status',
      render: (val) => <StatusBadge status={val || 'draft'} />
    },
    {
      key: 'score', label: 'Score',
      render: (val) => (
        <span style={{ fontFamily: 'var(--font-code)', fontWeight: 600 }}>
          {val != null ? `${Math.round(val)}%` : '—'}
        </span>
      )
    },
    {
      key: 'created_at', label: 'Date',
      render: (val, row) => (
        <span title={val || row.date || ''} style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)' }}>
          {relativeDate(val || row.date)}
        </span>
      )
    },
    {
      key: 'download', label: 'Download', sortable: false,
      render: (_, row) => (
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => handleDownload(row)}
          id={`hist-download-${row.id}`}
          title="Download JSON"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
        </button>
      ),
    },
    {
      key: 'delete', label: '', sortable: false, width: '48px',
      render: (_, row) => (
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => setDeleteTarget(row)}
          id={`hist-delete-${row.id}`}
          title="Delete"
          style={{ color: 'var(--color-error)' }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>
      ),
    },
  ];

  return (
    <div id="history-screen">
      <TopBar title="Upload History" subtitle={`${filtered.length} uploads found`} />

      <SearchBar
        searchValue={search}
        onSearchChange={setSearch}
        filterValue={filter}
        onFilterChange={setFilter}
        filterOptions={filterOptions}
      />

      {loading ? (
        <SkeletonTable rows={8} cols={7} />
      ) : (
        <DataTable
          columns={columns}
          data={pageData}
          emptyMessage={search || filter !== 'all' ? 'No uploads match your search.' : 'No uploads yet. Start by uploading a .docx file.'}
          id="history-table"
          pagination={filtered.length > PAGE_SIZE ? {
            page,
            totalPages,
            total: filtered.length,
            from: pageStart + 1,
            to: pageEnd,
            onPrev: () => setPage((p) => Math.max(1, p - 1)),
            onNext: () => setPage((p) => Math.min(totalPages, p + 1)),
          } : undefined}
        />
      )}

      {/* Delete Confirmation Modal */}
      <Modal
        isOpen={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Upload"
      >
        <div style={{ marginBottom: 24 }}>
          <p style={{ marginBottom: 8, color: 'var(--color-text-primary)', fontWeight: 500 }}>
            Are you sure you want to delete this upload?
          </p>
          <p style={{ fontSize: '0.875rem' }}>
            <strong>{deleteTarget?.filename}</strong> will be permanently removed. This action cannot be undone.
          </p>
        </div>
        <div className="modal-footer" style={{ padding: 0, borderTop: 'none' }}>
          <button className="btn btn-secondary" onClick={() => setDeleteTarget(null)} id="btn-cancel-delete">
            Cancel
          </button>
          <button className="btn btn-danger" onClick={confirmDelete} disabled={deleting} id="btn-confirm-delete">
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </Modal>
    </div>
  );
}
