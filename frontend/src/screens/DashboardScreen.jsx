import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  TopBar, StatCard, StatusBadge, DataTable, Modal,
  SkeletonStats, SkeletonTable, showToast, relativeDate,
  IconButton, DownloadIcon, TrashIcon, downloadUploadJson,
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export default function DashboardScreen() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      // Counts come from one grouped query on the server. This screen used to
      // download 500 full history rows (several seconds, and it froze the
      // backend for everyone meanwhile) just to count them here.
      const [statsRes, recentRes] = await Promise.all([
        fetch(`${API_BASE}/stats`),
        fetch(`${API_BASE}/history?limit=5`),
      ]);
      if (!statsRes.ok || !recentRes.ok) throw new Error('Could not load the dashboard');
      const statsData = await statsRes.json();
      const recentData = await recentRes.json();
      const by = statsData.by_status || {};
      setStats({
        live: by.published || 0,
        wpDrafts: by.draft_published || 0,
        notPublished: (by.processed || 0) + (by.confirmed || 0),
        total: statsData.total || 0,
        lastTime: statsData.last_upload_at,
      });
      setRecent(recentData.uploads || []);
    } catch (err) {
      showToast(err.message || 'Dashboard failed to load', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDashboardData(); }, []);

  const handleDownload = async (item) => {
    try {
      await downloadUploadJson(API_BASE, item);
      showToast('File downloaded', 'success');
    } catch (err) {
      showToast(err.message || 'Download failed', 'error');
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
      fetchDashboardData();
    } catch (err) {
      showToast(err.message || 'Delete failed', 'error');
    } finally {
      setDeleting(false);
    }
  };

  const columns = [
    {
      key: 'filename', label: 'Filename', className: 'cell-wrap',
      render: (val, row) => (
        <Link className="row-link" to={`/upload/${row.id}/validation`}>{(val || '—').replace(/\.docx$/i, '')}</Link>
      ),
    },
    { key: 'page_type', label: 'Page Type', render: (val) => <span style={{ textTransform: 'capitalize' }}>{val || '—'}</span> },
    { key: 'status', label: 'Status', render: (val) => <StatusBadge status={val || 'draft'} /> },
    {
      key: 'score', label: 'Score', render: (val) => (
        <span style={{ fontFamily: 'var(--font-code)', fontWeight: 600 }}>{val != null ? `${Math.round(val)}%` : '—'}</span>
      ),
    },
    { key: 'created_at', label: 'Date', render: (val) => <span title={val || ''} style={{ whiteSpace: 'nowrap' }}>{relativeDate(val)}</span> },
    {
      key: 'actions', label: '', sortable: false, className: 'cell-actions', render: (_, row) => (
        <div className="table-actions">
          <IconButton label="Download JSON" onClick={() => handleDownload(row)} id={`download-${row.id}`}><DownloadIcon /></IconButton>
          <IconButton label="Delete upload" danger onClick={() => setDeleteTarget(row)} id={`delete-${row.id}`}><TrashIcon /></IconButton>
        </div>
      ),
    },
  ];

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
            <StatCard icon="🌐" label="Live on WordPress" value={stats?.live ?? 0} color="green" />
            <StatCard icon="📝" label="WordPress drafts" value={stats?.wpDrafts ?? 0} color="yellow" />
            <StatCard icon="📄" label="Parsed, not published" value={stats?.notPublished ?? 0} color="blue" />
            <StatCard icon="🕐" label="Last upload" value={stats?.lastTime ? relativeDate(stats.lastTime) : 'Never'} color="red" />
          </div>

          <div className="card-header" style={{
            background: 'var(--color-surface)',
            borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0',
            border: '1px solid var(--color-border-light)',
            borderBottom: 'none',
            marginTop: 4,
          }}>
            <h3 className="card-header-title">Recent uploads</h3>
            <Link to="/history" className="btn btn-ghost btn-sm" id="btn-view-all">
              View all {stats?.total ? `(${stats.total})` : ''} →
            </Link>
          </div>
          <DataTable
            columns={columns}
            data={recent}
            emptyMessage="No uploads yet. Start by uploading a .docx file."
            id="recent-uploads-table"
          />
        </>
      )}

      <Modal isOpen={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete upload">
        <p style={{ marginBottom: 8, color: 'var(--color-text-primary)', fontWeight: 500 }}>Delete this upload from the app?</p>
        <p style={{ fontSize: '0.875rem', marginBottom: 16 }}>
          <strong>{deleteTarget?.filename}</strong> will be permanently removed. The WordPress post, if any, is not affected.
        </p>
        <div className="modal-footer" style={{ padding: 0, borderTop: 'none' }}>
          <button className="btn btn-secondary" onClick={() => setDeleteTarget(null)}>Cancel</button>
          <button className="btn btn-danger" onClick={confirmDelete} disabled={deleting}>{deleting ? 'Deleting…' : 'Delete'}</button>
        </div>
      </Modal>
    </div>
  );
}
