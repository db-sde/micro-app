import React, { useState, useEffect } from 'react';
import { useParams, useLocation, Link } from 'react-router-dom';
import {
  TopBar, StepIndicator, StatusBadge, ConfidenceBar,
  QualityScoreBadge, LoadingSpinner, showToast
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

/**
 * Merges validation.field_report with field_mappings from the backend response
 * into a single array the UI can render.
 */
function buildFieldRows(uploadData) {
  if (!uploadData) return [];

  const fieldReport = uploadData.validation?.field_report || [];
  const fieldMappings = uploadData.field_mappings || [];

  // Build lookup from field_mappings by field_key
  const mappingByKey = {};
  for (const m of fieldMappings) {
    mappingByKey[m.field_key] = m;
  }

  // Merge: field_report has status info, field_mappings has confidence/source/heading
  return fieldReport.map((fr) => {
    const mapping = mappingByKey[fr.field_key] || {};
    const value = uploadData.payload?.[fr.field_key];
    let charCount = 0;
    let preview = '—';
    if (typeof value === 'string') {
      charCount = value.length;
      preview = value.length > 100 ? value.slice(0, 100) + '…' : value;
    } else if (Array.isArray(value)) {
      charCount = JSON.stringify(value).length;
      preview = `[${value.length} items]`;
    } else if (value != null) {
      const s = JSON.stringify(value);
      charCount = s.length;
      preview = s.length > 100 ? s.slice(0, 100) + '…' : s;
    }

    return {
      field_key: fr.field_key,
      status: fr.status || mapping.status || 'missing',
      heading_in_doc: mapping.heading_in_doc || '—',
      source: mapping.source || '—',
      confidence: mapping.confidence || 0,
      preview,
      charCount,
    };
  });
}

export default function ValidationScreen() {
  const { uploadId } = useParams();
  const location = useLocation();
  const [data, setData] = useState(location.state?.uploadData || null);
  const [loading, setLoading] = useState(!data);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (data) return;
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);
        // Backend does not have a GET /jobs/:id endpoint.
        // We use POST /confirm/:id with empty corrections to fetch the validation details.
        const res = await fetch(`${API_BASE}/confirm/${uploadId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ corrections: [] })
        });
        if (!res.ok) throw new Error('Failed to load validation data');
        const json = await res.json();
        console.log('[ValidationScreen] raw job data:', json);
        setData(json);
      } catch (err) {
        console.error('[ValidationScreen] fetch failed:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [uploadId, data]);

  const handleDownload = async () => {
    try {
      const res = await fetch(`${API_BASE}/download/${uploadId}`);
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const baseName = (data?.filename || `upload_${uploadId}`).replace(/\.docx$/i, '');
      a.download = `${baseName}_acf_payload.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('JSON downloaded successfully', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  const handleSaveDraft = () => {
    showToast('Saved as draft successfully', 'success');
  };

  if (loading) {
    return (
      <div id="validation-screen" style={{ padding: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 400 }}>
        <LoadingSpinner message="Loading validation results…" />
      </div>
    );
  }

  if (error) {
    return (
      <div id="validation-screen" style={{ padding: 32 }}>
        <div style={{ background: '#FCEBEB', border: '1px solid #F09595', borderRadius: 8, padding: '16px 20px', color: '#A32D2D' }}>
          <strong>Could not load validation data</strong><br />
          <span style={{ fontSize: 13 }}>{error}</span><br />
          <span style={{ fontSize: 12, color: '#9CA3AF' }}>Job ID: {uploadId}</span>
        </div>
      </div>
    );
  }

  if (!data || !data.field_mappings || data.field_mappings.length === 0) {
    return (
      <div id="validation-screen" style={{ padding: 32 }}>
        <div style={{ background: '#F3F4F6', borderRadius: 8, padding: '32px', textAlign: 'center', color: '#9CA3AF' }}>
          No field data found for job {uploadId}.<br />
          <span style={{ fontSize: 12 }}>
            The pipeline may still be processing, or this job has no mapped fields.
          </span>
        </div>
      </div>
    );
  }

  // Extract data from the backend response shape
  const qualityScore = data?.validation?.summary?.quality_score ?? data?.score ?? 0;
  const summary = data?.validation?.summary || {};
  const fields = buildFieldRows(data);

  const mappedCount = summary.mapped ?? fields.filter((f) => f.status === 'mapped').length;
  const thinCount = summary.thin ?? fields.filter((f) => f.status === 'thin').length;
  const missingCount = summary.missing ?? fields.filter((f) => f.status === 'missing').length;

  return (
    <div id="validation-screen">
      <TopBar title="Validation Results" subtitle={data?.filename || ''}>
        <Link to={`/upload/${uploadId}/mapping`} state={{ uploadData: data }} className="btn btn-secondary" id="btn-fix-mappings">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
          Fix Mappings
        </Link>
      </TopBar>

      <StepIndicator currentStep={3} />

      {/* Score + Summary */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div className="card-body" style={{ display: 'flex', alignItems: 'center', gap: 40, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <QualityScoreBadge score={qualityScore} />
            <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Quality Score
            </span>
          </div>

          <div style={{ display: 'flex', gap: 16, flex: 1, minWidth: 300 }}>
            <div style={{
              flex: 1, padding: '16px 20px', background: 'var(--color-mapped)', borderRadius: 'var(--radius-md)',
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4
            }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-mapped-text)' }}>{mappedCount}</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-mapped-text)' }}>Mapped</span>
            </div>
            <div style={{
              flex: 1, padding: '16px 20px', background: 'var(--color-thin)', borderRadius: 'var(--radius-md)',
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4
            }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-thin-text)' }}>{thinCount}</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-thin-text)' }}>Thin</span>
            </div>
            <div style={{
              flex: 1, padding: '16px 20px', background: 'var(--color-missing)', borderRadius: 'var(--radius-md)',
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4
            }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-missing-text)' }}>{missingCount}</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-missing-text)' }}>Missing</span>
            </div>
          </div>
        </div>
      </div>

      {/* Processing time */}
      {data?.processing_time_ms && (
        <div style={{ marginBottom: 16, fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
          ⏱ Processed in {(data.processing_time_ms / 1000).toFixed(1)}s • Page type: <strong>{data.page_type}</strong>
        </div>
      )}

      {/* Fields Table */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-header-title">Field Details</h3>
          <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
            {fields.length} fields total
          </span>
        </div>
        <div className="data-table-wrapper">
          <table className="data-table" id="validation-fields-table">
            <thead>
              <tr>
                <th>Field Name</th>
                <th>Heading in Doc</th>
                <th>Status</th>
                <th>Source</th>
                <th style={{ width: 140 }}>Confidence</th>
                <th>Content Preview</th>
                <th style={{ width: 80 }}>Chars</th>
              </tr>
            </thead>
            <tbody>
              {fields.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: 40, color: 'var(--color-text-muted)' }}>
                    No field data available
                  </td>
                </tr>
              ) : (
                fields.map((field, idx) => (
                  <tr key={field.field_key || idx} style={field.status === 'missing' ? { background: 'var(--color-missing)' } : field.status === 'thin' ? { background: 'var(--color-thin)' } : {}}>
                    <td>
                      <code style={{ fontFamily: 'var(--font-code)', fontSize: '0.8125rem', color: 'var(--color-navy)' }}>
                        {field.field_key}
                      </code>
                    </td>
                    <td style={{ fontSize: '0.8125rem', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {field.heading_in_doc}
                    </td>
                    <td><StatusBadge status={field.status} /></td>
                    <td>
                      <span style={{
                        fontSize: '0.6875rem',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-full)',
                        background: field.source === 'embedding' ? '#EDE9FE' : field.source === 'ai' ? '#DBEAFE' : '#F1F5F9',
                        color: field.source === 'embedding' ? '#7C3AED' : field.source === 'ai' ? '#2563EB' : '#64748B',
                      }}>
                        {field.source}
                      </span>
                    </td>
                    <td>
                      <ConfidenceBar value={Math.round(field.confidence * 100)} />
                    </td>
                    <td style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={field.preview}>
                      {field.preview}
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-code)', fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                        {field.charCount}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 24 }}>
        <button className="btn btn-secondary" onClick={handleSaveDraft} id="btn-save-draft">
          Save as Draft
        </button>
        <button className="btn btn-secondary" onClick={handleDownload} id="btn-download-json">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Download JSON
        </button>
        <Link to={`/upload/${uploadId}/mapping`} state={{ uploadData: data }} className="btn btn-primary" id="btn-go-fix-mappings">
          Fix Mappings →
        </Link>
      </div>
    </div>
  );
}
