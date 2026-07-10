import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  TopBar, DropZone, PageTypeSelector, Toggle, StatusBadge,
  LoadingSpinner, showToast, formatFileSize
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export default function BulkScreen() {
  const [file, setFile] = useState(null);
  const [dryRun, setDryRun] = useState(false);
  const [autoDetect, setAutoDetect] = useState(true);
  const [pageType, setPageType] = useState('university');
  const [processing, setProcessing] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [progress, setProgress] = useState(null);
  const [fileCount, setFileCount] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const pollRef = useRef(null);
  const jobIdRef = useRef(null);

  // Keep jobIdRef in sync so visibilitychange handler can access it
  useEffect(() => { jobIdRef.current = jobId; }, [jobId]);

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
    setFileCount(null);
  };

  /** Fetch latest progress from backend and update state. */
  const fetchProgress = useCallback(async (id) => {
    try {
      const res = await fetch(`${API_BASE}/bulk/${id}/progress`);
      if (!res.ok) throw new Error('Progress fetch failed');
      const data = await res.json();
      setProgress(data);
      setFileCount(data.total_files || null);
      return data;
    } catch (_) {
      return null;
    }
  }, []);

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
      setFileCount(data.total_files || data.total || null);
      showToast('Bulk processing started!', 'success');

      // Start polling
      startPolling(data.job_id || data.id);
    } catch (err) {
      setError(err.message);
      setProcessing(false);
    }
  };

  const startPolling = useCallback((id) => {
    if (pollRef.current) clearInterval(pollRef.current);

    pollRef.current = setInterval(async () => {
      const data = await fetchProgress(id);
      if (!data) return;

      const done = data.status === 'completed' || data.status === 'failed' ||
                   data.status === 'completed_with_errors';
      if (done) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        setProcessing(false);
        if (data.status === 'completed') {
          showToast('Bulk processing completed!', 'success');
        } else if (data.status === 'completed_with_errors') {
          showToast('Bulk processing completed with some errors', 'warning');
        } else {
          showToast('Bulk processing encountered errors', 'warning');
        }
      }
    }, 2000);
  }, [fetchProgress]);

  /** Manual refresh — re-fetches latest scores from server. */
  const handleRefresh = useCallback(async () => {
    if (!jobIdRef.current) return;
    setRefreshing(true);
    await fetchProgress(jobIdRef.current);
    setRefreshing(false);
    showToast('Scores refreshed!', 'success');
  }, [fetchProgress]);

  // Auto-refresh when user returns to this tab after viewing/fixing JSON in another tab
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible' && jobIdRef.current) {
        const isCompleted = !pollRef.current; // polling stopped → job done
        if (isCompleted) {
          fetchProgress(jobIdRef.current);
        }
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, [fetchProgress]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const processed = progress?.processed_files || 0;
  const total = progress?.total_files || fileCount || 0;
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
  const files = progress?.results || [];

  const isJobDone = progress?.status === 'completed' ||
                    progress?.status === 'failed' ||
                    progress?.status === 'completed_with_errors';

  return (
    <div id="bulk-screen">
      <TopBar title="Bulk Upload" subtitle="Process multiple Word documents from a ZIP archive" />

      {!jobId ? (
        <div className="card" style={{ maxWidth: 680, margin: '0 auto' }}>
          <div className="card-body">
            {error && (
                <div style={{
                    background: '#FCEBEB', border: '1px solid #F09595', borderRadius: 8,
                    padding: '12px 16px', marginBottom: 16,
                    display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#A32D2D'
                }}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#A32D2D" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="15" y1="9" x2="9" y2="15"></line>
                        <line x1="9" y1="9" x2="15" y2="15"></line>
                    </svg>
                    {error}
                    <button onClick={() => setError(null)}
                        style={{ marginLeft: 'auto', background: 'none', border: 'none',
                                 cursor: 'pointer', color: '#A32D2D', fontSize: 13 }}>
                        Dismiss
                    </button>
                </div>
            )}
            <DropZone
              onFileDrop={handleFileDrop}
              accept=".zip"
              label="Drop your ZIP archive here"
              sublabel="Must contain .docx files"
              id="bulk-dropzone"
            />

            <div style={{
              marginTop: 16,
              padding: '12px 16px',
              background: '#FFFBEB',
              color: '#B45309',
              borderRadius: 'var(--radius-md)',
              fontSize: '0.875rem',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'flex-start',
              gap: '8px',
              border: '1px solid #FEF3C7'
            }}>
              <span>⚠️</span>
              <span><strong>Note:</strong> Please ensure all files within the ZIP archive are of the same page type for accurate processing.</span>
            </div>

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
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {/* Refresh button — only when job is done */}
                  {isJobDone && (
                    <button
                      id="btn-refresh-scores"
                      onClick={handleRefresh}
                      disabled={refreshing}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 5,
                        padding: '4px 10px',
                        fontSize: '0.75rem', fontWeight: 600,
                        border: '1px solid var(--color-border)',
                        borderRadius: 'var(--radius-md)',
                        background: 'var(--color-surface)',
                        color: 'var(--color-text-secondary)',
                        cursor: refreshing ? 'not-allowed' : 'pointer',
                        opacity: refreshing ? 0.6 : 1,
                        transition: 'all 0.15s',
                      }}
                      title="Re-fetch latest scores from server (useful after fixing JSON)"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                        style={{ animation: refreshing ? 'spin 0.8s linear infinite' : 'none' }}>
                        <polyline points="23 4 23 10 17 10" />
                        <polyline points="1 20 1 14 7 14" />
                        <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                      </svg>
                      {refreshing ? 'Refreshing…' : 'Refresh Scores'}
                    </button>
                  )}
                  <span style={{ fontSize: '0.875rem', fontWeight: 700, fontFamily: 'var(--font-code)', color: 'var(--color-orange)' }}>
                    {pct}%
                  </span>
                </div>
              </div>
              <div className="progress-bar">
                <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  {processed} of {total} processed
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  {progress?.status === 'completed' ? '✓ Complete'
                    : progress?.status === 'completed_with_errors' ? '⚠ Completed with errors'
                    : progress?.status === 'failed' ? '✕ Failed'
                    : '⏳ Processing…'}
                </span>
              </div>
            </div>
          </div>

          {/* Files Table */}
          <div className="card">
            <div className="card-header">
              <h3 className="card-header-title">File Results</h3>
              {isJobDone && (
                <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                  Click "Refresh Scores" after fixing JSON in another tab
                </span>
              )}
            </div>
            <div className="data-table-wrapper">
              <table className="data-table" id="bulk-results-table">
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Status</th>
                    <th>Score</th>
                    <th>ACFs Extracted</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {files.length === 0 ? (
                    <tr>
                      <td colSpan={5}>
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
                            {f.quality_score != null ? `${Math.round(f.quality_score)}%` : '—'}
                          </span>
                        </td>
                        <td>
                          {f.acf_extracted != null ? (
                            <span style={{
                              display: 'inline-flex', alignItems: 'center', gap: 4,
                              fontFamily: 'var(--font-code)', fontWeight: 600,
                              fontSize: '0.8125rem',
                            }}>
                              <span style={{
                                color: f.acf_extracted > 0 ? 'var(--color-mapped-text)' : 'var(--color-missing-text)',
                                fontWeight: 700,
                              }}>
                                {f.acf_extracted}
                              </span>
                              {f.acf_total != null && (
                                <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>
                                  / {f.acf_total}
                                </span>
                              )}
                            </span>
                          ) : (
                            <span style={{ color: 'var(--color-text-muted)', fontSize: '0.8125rem' }}>—</span>
                          )}
                        </td>
                        <td>
                          {f.upload_id && f.status !== 'processing' ? (
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => {
                                window.open(`/upload/${f.upload_id}/validation`, '_blank');
                              }}
                              id={`bulk-view-${idx}`}
                            >
                              View →
                            </button>
                          ) : f.status === 'failed' && f.error ? (
                            <button
                              className="btn btn-ghost btn-sm"
                              style={{ color: 'var(--color-missing-text)' }}
                              onClick={() => alert(`Error processing ${f.filename}:\n\n${f.error}`)}
                            >
                              View Error
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Reset Button */}
          {isJobDone && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 24 }}>
              <button
                className="btn btn-ghost"
                onClick={handleRefresh}
                disabled={refreshing}
                id="btn-bulk-refresh-bottom"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                  style={{ animation: refreshing ? 'spin 0.8s linear infinite' : 'none' }}>
                  <polyline points="23 4 23 10 17 10" />
                  <polyline points="1 20 1 14 7 14" />
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                </svg>
                Refresh Scores
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setJobId(null);
                  setProgress(null);
                  setFile(null);
                  setFileCount(null);
                  setError(null);
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
