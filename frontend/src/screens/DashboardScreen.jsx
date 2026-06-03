import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  TopBar, StatCard, StatusBadge, DataTable,
  SkeletonStats, SkeletonTable, showToast, relativeDate
} from '../components/Components';

const API_BASE = '/api';

export default function DashboardScreen() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchHistory = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/history`);
      if (!res.ok) throw new Error('Failed to fetch history');
      const data = await res.json();
      setHistory(Array.isArray(data) ? data : data.uploads || []);
    } catch (err) {
      showToast(err.message || 'Failed to load dashboard data', 'error');
      setHistory([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchHistory(); }, []);

  const publishedCount = history.filter((h) => h.status === 'published' || h.status === 'passed').length;
  const draftsCount = history.filter((h) => h.status === 'draft').length;
  const issuesCount = history.filter((h) => h.status === 'issues' || h.status === 'failed').length;

  const lastUploadDate = history.length > 0
    ? relativeDate(history.reduce((latest, h) => {
        const d = new Date(h.created_at || h.date || 0);
        return d > latest ? d : latest;
      }, new Date(0)).toISOString())
    : 'Never';

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
      showToast('File downloaded successfully', 'success');
    } catch (err) {
      showToast(err.message || 'Download failed', 'error');
    }
  };

  const handleDelete = async (item) => {
    if (!window.confirm(`Delete "${item.filename}"? This cannot be undone.`)) return;
    try {
      const res = await fetch(`${API_BASE}/history/${item.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete failed');
      setHistory((prev) => prev.filter((h) => h.id !== item.id));
      showToast('Upload deleted', 'success');
    } catch (err) {
      showToast(err.message || 'Delete failed', 'error');
    }
  };

  const columns = [
    { key: 'filename', label: 'Filename', render: (val) => <span style={{ fontWeight: 600 }}>{val || '—'}</span> },
    { key: 'page_type', label: 'Page Type', render: (val) => (
      <span style={{ textTransform: 'capitalize' }}>{val || '—'}</span>
    )},
    { key: 'status', label: 'Status', render: (val) => <StatusBadge status={val || 'draft'} /> },
    { key: 'score', label: 'Score', render: (val) => (
      <span style={{ fontFamily: 'var(--font-code)', fontWeight: 600 }}>
        {val != null ? `${Math.round(val)}%` : '—'}
      </span>
    )},
    { key: 'created_at', label: 'Date', render: (val, row) => (
      <span title={val || row.date || ''}>
        {relativeDate(val || row.date)}
      </span>
    )},
    {
      key: 'actions', label: 'Actions', sortable: false, render: (_, row) => (
        <div className="table-actions">
          <button className="btn btn-ghost btn-sm" onClick={() => handleDownload(row)} id={`download-${row.id}`} title="Download JSON">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(row)} id={`delete-${row.id}`} title="Delete" style={{ color: 'var(--color-error)' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        </div>
      ),
    },
  ];

  const recentUploads = [...history]
    .sort((a, b) => new Date(b.created_at || b.date || 0) - new Date(a.created_at || a.date || 0))
    .slice(0, 10);

  return (
    <div id="dashboard-screen">
      <TopBar title="Dashboard" subtitle="Overview of your content publishing pipeline">
        <Link to="/upload" className="btn btn-primary" id="btn-new-upload">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New Upload
        </Link>
      </TopBar>

      {loading ? (
        <>
          <SkeletonStats count={4} />
          <SkeletonTable rows={5} cols={6} />
        </>
      ) : (
        <>
          <div className="stat-grid">
            <StatCard
              icon="📄"
              label="Pages Published"
              value={publishedCount}
              color="green"
            />
            <StatCard
              icon="📝"
              label="Drafts Pending"
              value={draftsCount}
              color="yellow"
            />
            <StatCard
              icon="⚠️"
              label="Files with Issues"
              value={issuesCount}
              color="red"
            />
            <StatCard
              icon="🕐"
              label="Last Upload"
              value={lastUploadDate}
              color="blue"
            />
          </div>

          <div className="card-header" style={{
            background: 'var(--color-surface)',
            borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0',
            border: '1px solid var(--color-border-light)',
            borderBottom: 'none',
            marginTop: 4
          }}>
            <h3 className="card-header-title">Recent Uploads</h3>
            <Link to="/history" className="btn btn-ghost btn-sm" id="btn-view-all">
              View All →
            </Link>
          </div>
          <DataTable
            columns={columns}
            data={recentUploads}
            emptyMessage="No uploads yet. Start by uploading a .docx file."
            id="recent-uploads-table"
          />
        </>
      )}
    </div>
  );
}
