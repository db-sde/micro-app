import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  TopBar, DropZone, PageTypeSelector, Toggle, StatusBadge,
  LoadingSpinner, showToast, formatFileSize
} from '../components/Components';

const API_BASE = '/api';

export default function BulkScreen() {
  const [file, setFile] = useState(null);
  const [dryRun, setDryRun] = useState(false);
  const [autoDetect, setAutoDetect] = useState(true);
  const [pageType, setPageType] = useState('university');
  const [processing, setProcessing] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [progress, setProgress] = useState(null);
  const [fileCount, setFileCount] = useState(null);
  const pollRef = useRef(null);

  const handleFileDrop = (f) => {
    if (!f) {
      setFile(null);
      setFileCount(null);
      return;
    }
    if (f.name && !f.name.toLowerCase().endsWith('.zip')) {
      showToast('Only .zip files are supported for bulk upload', 'error');
      setFile(null);
      return;
    }
    setFile(f);
    // Estimate file count (we can't peek into zip client-side, show after upload)
    setFileCount(null);
  };

  const handleStart = async () => {
    if (!file) return;
    setProcessing(true);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('dry_run', dryRun.toString());
      if (!autoDetect) {
        formData.append('page_type', pageType);
      }

      const res = await fetch(`${API_BASE}/bulk`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || errData.message || 'Bulk upload failed');
      }

      const data = await res.json();
      setJobId(data.job_id || data.id);
      setFileCount(data.file_count || data.total || null);
      showToast('Bulk processing started!', 'success');

      // Start polling
      startPolling(data.job_id || data.id);
    } catch (err) {
      showToast(err.message, 'error');
      setProcessing(false);
    }
  };

  const startPolling = useCallback((id) => {
    if (pollRef.current) clearInterval(pollRef.current);

    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/bulk/${id}/progress`);
        if (!res.ok) throw new Error('Progress fetch failed');
        const data = await res.json();
        setProgress(data);
        setFileCount(data.total || null);

        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setProcessing(false);
          if (data.status === 'completed') {
            showToast('Bulk processing completed!', 'success');
          } else {
            showToast('Bulk processing encountered errors', 'warning');
          }
        }
      } catch (err) {
        // Silently handle poll errors
      }
    }, 2000);
  }, []);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const processed = progress?.processed || 0;
  const total = progress?.total || fileCount || 0;
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
  const files = progress?.files || [];

  return (
    <div id="bulk-screen">
      <TopBar title="Bulk Upload" subtitle="Process multiple Word documents from a ZIP archive" />

      {!jobId ? (
        <div className="card" style={{ maxWidth: 680, margin: '0 auto' }}>
          <div className="card-body">
            <DropZone
              onFileDrop={handleFileDrop}
              accept=".zip"
              label="Drop your ZIP archive here"
              sublabel="Must contain .docx files"
              id="bulk-dropzone"
            />

            {fileCount && (
              <div style={{
                marginTop: 16, padding: '12px 16px',
                background: 'var(--color-info-light)', color: 'var(--color-info)',
                borderRadius: 'var(--radius-md)', fontSize: '0.875rem', fontWeight: 600
              }}>
                📁 {fileCount} .docx files found
              </div>
            )}

            <div style={{ marginTop: 28, borderTop: '1px solid var(--color-border-light)', paddingTop: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>
              <Toggle
                checked={dryRun}
                onChange={setDryRun}
                label="Dry Run (validate only, don't publish)"
                id="toggle-dry-run"
              />

              <Toggle
                checked={autoDetect}
                onChange={setAutoDetect}
                label="Auto-detect page type"
                id="toggle-bulk-auto-detect"
              />

              {!autoDetect && (
                <div style={{ animation: 'fadeIn 0.3s ease' }}>
                  <label className="input-label" style={{ marginBottom: 12, display: 'block' }}>
                    Page Type for All Files
                  </label>
                  <PageTypeSelector value={pageType} onChange={setPageType} />
                </div>
              )}
            </div>
          </div>

          <div className="card-footer">
            <button
              className="btn btn-primary btn-lg"
              onClick={handleStart}
              disabled={!file || processing}
              id="btn-start-processing"
            >
              {processing ? (
                <>
                  <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                  Starting…
                </>
              ) : (
                <>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  Start Processing
                </>
              )}
            </button>
          </div>
        </div>
      ) : (
        /* ─── Progress View ─── */
        <div>
          {/* Progress Bar */}
          <div className="card" style={{ marginBottom: 20 }}>
            <div className="card-body">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                  Processing {total} files
                </span>
                <span style={{ fontSize: '0.875rem', fontWeight: 700, fontFamily: 'var(--font-code)', color: 'var(--color-orange)' }}>
                  {pct}%
                </span>
              </div>
              <div className="progress-bar">
                <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  {processed} of {total} processed
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  {progress?.status === 'completed' ? '✓ Complete' : progress?.status === 'failed' ? '✕ Failed' : '⏳ Processing…'}
                </span>
              </div>
            </div>
          </div>

          {/* Files Table */}
          <div className="card">
            <div className="card-header">
              <h3 className="card-header-title">File Results</h3>
            </div>
            <div className="data-table-wrapper">
              <table className="data-table" id="bulk-results-table">
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Status</th>
                    <th>Score</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {files.length === 0 ? (
                    <tr>
                      <td colSpan={4}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: 32, color: 'var(--color-text-muted)' }}>
                          <div className="spinner" style={{ width: 20, height: 20, borderWidth: 2 }} />
                          Waiting for results…
                        </div>
                      </td>
                    </tr>
                  ) : (
                    files.map((f, idx) => (
                      <tr key={f.filename || idx}>
                        <td style={{ fontWeight: 600 }}>{f.filename || `File ${idx + 1}`}</td>
                        <td>
                          {f.status === 'processing' ? (
                            <span className="badge badge--processing">
                              <div className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} />
                              Processing
                            </span>
                          ) : (
                            <StatusBadge status={f.status} />
                          )}
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-code)', fontWeight: 600 }}>
                            {f.score != null ? `${Math.round(f.score)}%` : '—'}
                          </span>
                        </td>
                        <td>
                          {f.upload_id && f.status !== 'processing' && (
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => {
                                window.open(`/upload/${f.upload_id}/validation`, '_blank');
                              }}
                              id={`bulk-view-${idx}`}
                            >
                              View →
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Reset Button */}
          {(progress?.status === 'completed' || progress?.status === 'failed') && (
            <div style={{ display: 'flex', justifyContent: 'center', marginTop: 24 }}>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setJobId(null);
                  setProgress(null);
                  setFile(null);
                  setFileCount(null);
                  setProcessing(false);
                }}
                id="btn-bulk-reset"
              >
                Start New Batch
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
