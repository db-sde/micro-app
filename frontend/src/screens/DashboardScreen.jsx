import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  TopBar, StatCard, StatusBadge, DataTable,
  SkeletonStats, SkeletonTable, showToast, relativeDate
} from '../components/Components';

const API_BASE = '/api';

export default function DashboardScreen() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      // Fetch recent uploads (fetching enough to derive aggregate stats too)
      const res = await fetch(`${API_BASE}/history?limit=500`);
      if (!res.ok) throw new Error('Failed to fetch history');
      const data = await res.json();
      const items = data.uploads || [];

      setRecent(items.slice(0, 5));

      const pubCount = items.filter((i) => ['complete', 'processed', 'published'].includes(i.status)).length;
      const drfCount = items.filter((i) => ['draft', 'validated', 'pending'].includes(i.status)).length;
      const issCount = items.filter((i) => ['failed', 'issues', 'error'].includes(i.status)).length;
      const last = items.length > 0 ? items[0] : null;

      setStats({
          published: pubCount,
          drafts: drfCount,
          issues: issCount,
          lastFile: last?.filename || '—',
          lastTime: last?.created_at || last?.date || null,
      });
    } catch (err) {
      showToast(err.message || 'Dashboard fetch failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDashboardData(); }, []);

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
      setRecent((prev) => prev.filter((h) => h.id !== item.id));
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

  const recentUploads = recent;

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
              value={stats?.published || 0}
              color="green"
            />
            <StatCard
              icon="📝"
              label="Drafts Pending"
              value={stats?.drafts || 0}
              color="yellow"
            />
            <StatCard
              icon="⚠️"
              label="Files with Issues"
              value={stats?.issues || 0}
              color="red"
            />
            <StatCard
              icon="🕐"
              label="Last Upload"
              value={stats?.lastTime ? relativeDate(stats.lastTime) : 'Never'}
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
