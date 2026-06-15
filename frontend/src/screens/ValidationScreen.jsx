import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useLocation, Link } from 'react-router-dom';
import {
  TopBar, StepIndicator, StatusBadge, ConfidenceBar,
  QualityScoreBadge, LoadingSpinner, showToast
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

/* ─── ACF field type reference (for the formatting guide) ─── */
const FIELD_TYPE_GUIDE = [
  {
    type: 'text / textarea / html / stat',
    format: 'Plain string',
    example: '"2 Years"  or  "A+"  or  "<p>About text…</p>"',
  },
  {
    type: 'faqs  (json_array)',
    format: 'Array of objects',
    example: '[{"question": "What is the fee?", "answer": "₹50,000 per semester"}]',
  },
  {
    type: 'highlights  (json_array)',
    format: 'Array of objects',
    example: '[{"highlight_title": "100% Online", "highlight_description": "Learn from anywhere"}]',
  },
  {
    type: 'programs_table  (json_array)',
    format: 'Array of objects',
    example: '[{"program_name": "MBA", "program_fee": "₹1,20,000", "program_eligibility": "Graduation"}]',
  },
  {
    type: 'fee_plans  (json_array)',
    format: 'Array of objects',
    example: '[{"plan_name": "Semester", "plan_amount": "₹30,000", "plan_total": "₹60,000"}]',
  },
  {
    type: 'job_profiles  (json_array)',
    format: 'Array of objects',
    example: '[{"job_title": "Marketing Manager", "avg_salary": "₹8 LPA"}]',
  },
  {
    type: 'faculty_members  (json_array)',
    format: 'Array of objects',
    example: '[{"member_name": "Dr. John", "member_program": "MBA", "member_designation": "Professor", "member_qualification": "PhD"}]',
  },
  {
    type: 'reviews  (json_array)',
    format: 'Array of objects',
    example: '[{"review_text": "Great learning experience!", "reviewer_label": "MBA Student 2023"}]',
  },
  {
    type: 'accreditations  (json_array)',
    format: 'Array of objects',
    example: '[{"body_name": "NAAC", "body_descriptor": "A+ Grade", "body_detail": "2023-2028"}]',
  },
  {
    type: 'facts  (json_array)',
    format: 'Array of objects',
    example: '[{"fact_title": "Established", "fact_description": "2005"}]',
  },
  {
    type: 'other_specs  (json_array)',
    format: 'Array of objects',
    example: '[{"other_spec_name": "Marketing MBA", "other_spec_fee": "₹1,10,000"}]',
  },
  {
    type: 'hero_image / linked_university / linked_course',
    format: 'WordPress Post ID or media ID (string)',
    example: '"4521"  — set manually in WordPress',
  },
];



/**
 * Merges validation.field_report with field_mappings from the backend response.
 */
function buildFieldRows(uploadData) {
  if (!uploadData) return [];

  const fieldReport = uploadData.validation?.field_report || [];
  const fieldMappings = uploadData.field_mappings || [];

  const mappingByKey = {};
  for (const m of fieldMappings) {
    mappingByKey[m.field_key] = m;
  }

  return fieldReport.map((fr) => {
    const mapping = mappingByKey[fr.field_key] || {};
    const value = uploadData.payload?.[fr.field_key];
    let charCount = 0;
    let preview = '—';
    const isSkipped = ['hero_image', 'linked_university', 'linked_course'].includes(fr.field_key);

    if (isSkipped) {
      preview = 'Set manually in WordPress';
    } else if (typeof value === 'string') {
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
      status: isSkipped ? 'skipped' : (fr.status || mapping.status || 'missing'),
      heading_in_doc: mapping.heading_in_doc || '—',
      source: isSkipped ? 'manual' : (mapping.source || '—'),
      confidence: isSkipped ? 0 : (mapping.confidence || 0),
      preview,
      charCount,
    };
  });
}

/* ═══════════════════════════════════════
   TINY JSON SYNTAX HIGHLIGHTER
   ═══════════════════════════════════════ */
function JsonSyntaxHighlight({ json }) {
  const tokens = [];
  const regex = /("(?:[^"\\]|\\.)*")\s*:|("(?:[^"\\]|\\.)*")|(true|false|null)|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([{}[\],:])/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(json)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ type: 'plain', text: json.slice(lastIndex, match.index) });
    }
    if (match[1]) tokens.push({ type: 'key', text: match[0] });
    else if (match[2]) tokens.push({ type: 'string', text: match[0] });
    else if (match[3]) tokens.push({ type: 'keyword', text: match[0] });
    else if (match[4]) tokens.push({ type: 'number', text: match[0] });
    else tokens.push({ type: 'punct', text: match[0] });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < json.length) {
    tokens.push({ type: 'plain', text: json.slice(lastIndex) });
  }

  const colors = {
    key: '#7C3AED',
    string: '#059669',
    keyword: '#D97706',
    number: '#2563EB',
    punct: '#64748B',
    plain: 'var(--color-text-primary)',
  };

  return (
    <>
      {tokens.map((t, i) => (
        <span key={i} style={{ color: colors[t.type] }}>{t.text}</span>
      ))}
    </>
  );
}

/* ═══════════════════════════════════════
   JSON EDITOR SLIDE-OVER PANEL
   ═══════════════════════════════════════ */
function JsonEditorModal({ isOpen, onClose, uploadId, initialPayload, initialPageType, onSaved }) {
  const [tab, setTab] = useState('view');
  const [editText, setEditText] = useState('');
  const [jsonError, setJsonError] = useState('');
  const [guideOpen, setGuideOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const prettyJson = initialPayload ? JSON.stringify(initialPayload, null, 2) : '{}';

  // Sync state when modal opens
  useEffect(() => {
    if (isOpen) {
      setEditText(prettyJson);
      setJsonError('');
      setTab('view');
      setGuideOpen(false);
    }
  }, [isOpen, prettyJson]);

  // Escape key
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    if (isOpen) window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = isOpen ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  const handleEditChange = (e) => {
    const val = e.target.value;
    setEditText(val);
    try {
      JSON.parse(val);
      setJsonError('');
    } catch (err) {
      setJsonError(err.message);
    }
  };

  const handleCopy = useCallback(() => {
    const text = tab === 'edit' ? editText : prettyJson;
    navigator.clipboard.writeText(text).then(() => {
      showToast('Copied to clipboard!', 'success');
    });
  }, [tab, editText, prettyJson]);

  const handleSave = async () => {
    let parsed;
    try {
      parsed = JSON.parse(editText);
    } catch (err) {
      setJsonError(err.message);
      showToast('Fix JSON errors before saving', 'error');
      return;
    }

    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/payload/${uploadId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload: parsed }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Save failed (${res.status})`);
      }

      const updated = await res.json();
      showToast('Payload saved & re-validated!', 'success');
      onSaved(updated);
      onClose();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      id="json-editor-modal-overlay"
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(14, 31, 61, 0.55)',
        backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'stretch', justifyContent: 'flex-end',
        animation: 'fadeIn 0.18s ease',
      }}
    >
      {/* Slide-in panel */}
      <div
        id="json-editor-panel"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(780px, 100vw)',
          height: '100vh',
          background: 'var(--color-surface)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-8px 0 40px rgba(14,31,61,0.18)',
          animation: 'slideInRight 0.22s cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '20px 24px',
          borderBottom: '1px solid var(--color-border)',
          flexShrink: 0,
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.0625rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
              View / Edit JSON Payload
            </h3>
            <p style={{ margin: '2px 0 0', fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
              Edit extracted content · Save &amp; re-validate
            </p>
          </div>
          <button
            id="json-modal-close"
            onClick={onClose}
            aria-label="Close panel"
            style={{
              background: 'none', border: 'none', fontSize: '1.375rem',
              color: 'var(--color-text-muted)', cursor: 'pointer',
              width: 36, height: 36, borderRadius: 'var(--radius-md)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'background 0.15s',
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--color-border-light)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
          >
            ×
          </button>
        </div>

        {/* Tab bar */}
        <div style={{
          display: 'flex',
          borderBottom: '1px solid var(--color-border)',
          flexShrink: 0,
          alignItems: 'center',
        }}>
          {[
            { key: 'view', label: '👁  View' },
            { key: 'edit', label: '✏️  Edit' },
          ].map((t) => (
            <button
              key={t.key}
              id={`json-tab-${t.key}`}
              onClick={() => setTab(t.key)}
              style={{
                padding: '12px 22px',
                border: 'none',
                borderBottom: tab === t.key ? '2px solid var(--color-orange)' : '2px solid transparent',
                marginBottom: '-1px',
                background: 'none',
                color: tab === t.key ? 'var(--color-orange)' : 'var(--color-text-muted)',
                fontWeight: tab === t.key ? 700 : 500,
                fontSize: '0.875rem',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              {t.label}
            </button>
          ))}
          {/* Copy button floated right */}
          <button
            id="json-copy-btn"
            onClick={handleCopy}
            style={{
              marginLeft: 'auto',
              marginRight: 16,
              padding: '6px 14px',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              background: 'var(--color-surface)',
              color: 'var(--color-text-secondary)',
              fontSize: '0.8125rem',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-orange)'; e.currentTarget.style.color = 'var(--color-orange)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border)'; e.currentTarget.style.color = 'var(--color-text-secondary)'; }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            Copy
          </button>
        </div>

        {/* JSON error banner (edit mode only) */}
        {tab === 'edit' && jsonError && (
          <div id="json-error-banner" style={{
            padding: '8px 24px',
            background: '#FEE2E2',
            color: '#DC2626',
            fontSize: '0.8125rem',
            fontWeight: 500,
            borderBottom: '1px solid #FCA5A5',
            flexShrink: 0,
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span>⚠</span>
            <span>Invalid JSON — {jsonError}</span>
          </div>
        )}

        {/* Content area */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {tab === 'view' ? (
            <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>
              <pre id="json-view-pre" style={{
                fontFamily: 'var(--font-code)',
                fontSize: '0.8125rem',
                lineHeight: 1.75,
                background: '#F8FAFC',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-md)',
                padding: '16px 20px',
                margin: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}>
                <JsonSyntaxHighlight json={prettyJson} />
              </pre>
            </div>
          ) : (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              <textarea
                id="json-edit-textarea"
                value={editText}
                onChange={handleEditChange}
                spellCheck={false}
                style={{
                  flex: 1,
                  resize: 'none',
                  border: 'none',
                  outline: 'none',
                  fontFamily: 'var(--font-code)',
                  fontSize: '0.8125rem',
                  lineHeight: 1.75,
                  padding: '20px 24px',
                  color: 'var(--color-text-primary)',
                  background: jsonError ? '#FFF5F5' : '#FAFBFD',
                  transition: 'background 0.2s',
                }}
              />
            </div>
          )}
        </div>

        {/* Formatting Guide (collapsible) */}
        <div style={{ borderTop: '1px solid var(--color-border)', flexShrink: 0 }}>
          <button
            id="json-guide-toggle"
            onClick={() => setGuideOpen((o) => !o)}
            style={{
              width: '100%',
              padding: '11px 24px',
              background: '#F8FAFC',
              border: 'none',
              textAlign: 'left',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              cursor: 'pointer',
              fontSize: '0.8125rem',
              fontWeight: 700,
              color: 'var(--color-text-secondary)',
            }}
          >
            <span>📖  Field Formatting Guide</span>
            <span style={{
              transition: 'transform 0.2s',
              display: 'inline-block',
              transform: guideOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            }}>▾</span>
          </button>

          {guideOpen && (
            <div id="json-guide-content" style={{
              maxHeight: 260, overflowY: 'auto',
              padding: '0 24px 12px',
              background: '#F8FAFC',
            }}>
              {FIELD_TYPE_GUIDE.map((row, i) => (
                <div key={i} style={{
                  padding: '9px 0',
                  borderBottom: i < FIELD_TYPE_GUIDE.length - 1 ? '1px solid var(--color-border-light)' : 'none',
                }}>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{
                      minWidth: 190,
                      fontSize: '0.75rem', fontWeight: 700,
                      color: 'var(--color-navy)',
                      fontFamily: 'var(--font-code)',
                    }}>
                      {row.type}
                    </div>
                    <div style={{ flex: 1, minWidth: 220 }}>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginBottom: 3 }}>{row.format}</div>
                      <code style={{
                        fontSize: '0.72rem',
                        fontFamily: 'var(--font-code)',
                        color: '#059669',
                        background: '#ECFDF5',
                        padding: '2px 7px',
                        borderRadius: 4,
                        display: 'block',
                        wordBreak: 'break-all',
                      }}>
                        {row.example}
                      </code>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div style={{
          display: 'flex', gap: 12, padding: '16px 24px',
          borderTop: '1px solid var(--color-border)',
          flexShrink: 0,
          justifyContent: 'flex-end',
          background: 'var(--color-surface)',
        }}>
          <button className="btn btn-secondary" onClick={onClose} id="json-modal-cancel">
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving || !!jsonError}
            id="json-modal-save"
          >
            {saving ? (
              <>
                <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                Saving…
              </>
            ) : (
              <>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                  <polyline points="17 21 17 13 7 13 7 21" />
                  <polyline points="7 3 7 8 15 8" />
                </svg>
                Save &amp; Re-validate
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════
   MAIN VALIDATION SCREEN
   ═══════════════════════════════════════ */
export default function ValidationScreen() {
  const { uploadId } = useParams();
  const location = useLocation();
  const [data, setData] = useState(location.state?.uploadData || null);
  const [loading, setLoading] = useState(!data);
  const [error, setError] = useState(null);
  const [jsonModalOpen, setJsonModalOpen] = useState(false);

  useEffect(() => {
    if (data) return;
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);
        const res = await fetch(`${API_BASE}/confirm/${uploadId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ corrections: [] }),
        });
        if (!res.ok) throw new Error('Failed to load validation data');
        const json = await res.json();
        setData(json);
      } catch (err) {
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

  // Merge updated server response back into local state
  const handleJsonSaved = (updatedData) => {
    setData((prev) => ({ ...prev, ...updatedData }));
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

      <StepIndicator currentStep={2} />

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
            <div style={{ flex: 1, padding: '16px 20px', background: 'var(--color-mapped)', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-mapped-text)' }}>{mappedCount}</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-mapped-text)' }}>Mapped</span>
            </div>
            <div style={{ flex: 1, padding: '16px 20px', background: 'var(--color-thin)', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-thin-text)' }}>{thinCount}</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-thin-text)' }}>Thin</span>
            </div>
            <div style={{ flex: 1, padding: '16px 20px', background: 'var(--color-missing)', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-missing-text)' }}>{missingCount}</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-missing-text)' }}>Missing</span>
            </div>
          </div>
        </div>
      </div>

      {/* Processing time + page type */}
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
                  <tr
                    key={field.field_key || idx}
                    style={
                      field.status === 'missing' ? { background: 'var(--color-missing)' }
                      : field.status === 'thin' ? { background: 'var(--color-thin)' }
                      : {}
                    }
                  >
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
                        fontSize: '0.6875rem', fontWeight: 600, textTransform: 'uppercase',
                        letterSpacing: '0.05em', padding: '2px 8px',
                        borderRadius: 'var(--radius-full)',
                        background: field.source === 'embedding' ? '#EDE9FE' : field.source === 'ai' ? '#DBEAFE' : '#F1F5F9',
                        color: field.source === 'embedding' ? '#7C3AED' : field.source === 'ai' ? '#2563EB' : '#64748B',
                      }}>
                        {field.source}
                      </span>
                    </td>
                    <td><ConfidenceBar value={Math.round(field.confidence * 100)} /></td>
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

      {/* Action buttons */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 24 }}>
        <button className="btn btn-secondary" onClick={handleSaveDraft} id="btn-save-draft">
          Save as Draft
        </button>

        {/* View / Edit JSON */}
        <button
          className="btn btn-secondary"
          onClick={() => setJsonModalOpen(true)}
          id="btn-view-edit-json"
          style={{ display: 'flex', alignItems: 'center', gap: 7 }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="16 18 22 12 16 6" />
            <polyline points="8 6 2 12 8 18" />
          </svg>
          View / Edit JSON
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

      {/* JSON Editor Slide-over Modal */}
      <JsonEditorModal
        isOpen={jsonModalOpen}
        onClose={() => setJsonModalOpen(false)}
        uploadId={uploadId}
        initialPayload={data?.payload || {}}
        initialPageType={data?.page_type || 'university'}
        onSaved={handleJsonSaved}
      />
    </div>
  );
}
