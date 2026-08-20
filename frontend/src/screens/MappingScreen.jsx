import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import {
  TopBar, ConfidenceBar, LoadingSpinner, showToast
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export default function MappingScreen() {
  const { uploadId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState(location.state?.uploadData || null);
  const [loading, setLoading] = useState(!data);
  const [saving, setSaving] = useState(false);
  const [mappings, setMappings] = useState([]);
  // Fetched from the backend (acf/fields.py is the source of truth) rather
  // than hardcoded here, so this never drifts out of sync with the real
  // schema again. Keyed by page_type; populated lazily as needed.
  const [schemaByType, setSchemaByType] = useState({});

  useEffect(() => {
    if (data) {
      initMappings(data);
      return;
    }
    const fetchData = async () => {
      try {
        setLoading(true);
        // /upload/{id}, not /download/{id} — the latter is just the bare
        // payload file for download and has no field_mappings, which this
        // screen needs. Only hit when navigated to directly (e.g. a
        // refresh) without router state carrying the data already.
        const res = await fetch(`${API_BASE}/upload/${uploadId}`);
        if (!res.ok) throw new Error('Failed to load data');
        const json = await res.json();
        setData(json);
        initMappings(json);
      } catch (err) {
        showToast(err.message, 'error');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [uploadId]);

  useEffect(() => {
    const pt = data?.page_type;
    if (!pt || schemaByType[pt]) return;
    fetch(`${API_BASE}/schema/${pt}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('Failed to load field schema'))))
      .then((json) => setSchemaByType((prev) => ({ ...prev, [pt]: json.fields || [] })))
      .catch((err) => showToast(err.message, 'error'));
  }, [data?.page_type, schemaByType]);

  const initMappings = (d) => {
    // Build mappings from backend field_mappings array
    const fieldMappings = d?.field_mappings || [];
    const rows = fieldMappings.map((fm) => ({
      heading_in_doc: fm.heading_in_doc || '',
      field_key: fm.field_key || '',
      confidence: fm.confidence || 0,
      source: fm.source || '—',
    }));
    setMappings(rows);
  };

  const pageType = data?.page_type || 'university';
  const acfOptions = schemaByType[pageType] || [];

  const handleFieldChange = (index, newField) => {
    setMappings((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], field_key: newField };
      return updated;
    });
  };

  const handleConfirm = async () => {
    setSaving(true);
    try {
      // Backend expects { corrections: [{field_key, heading_in_doc}] }
      const corrections = mappings
        .filter((m) => m.field_key && m.heading_in_doc)
        .map((m) => ({
          field_key: m.field_key,
          heading_in_doc: m.heading_in_doc,
        }));

      const res = await fetch(`${API_BASE}/confirm/${uploadId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ corrections }),
      });

      if (!res.ok) throw new Error('Failed to confirm mappings');
      const updatedData = await res.json();
      showToast('Mappings confirmed successfully!', 'success');
      navigate(`/upload/${uploadId}/validation`, { state: { uploadData: { ...data, ...updatedData } } });
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div id="mapping-screen">
        <TopBar title="Fix Field Mappings" />
        <LoadingSpinner message="Loading field mappings…" />
      </div>
    );
  }

  // Images aren't correctable here — they're managed on the Images step,
  // and their field type is excluded from the schema dropdown entirely.
  const editableMappings = mappings.filter((m) => m.heading_in_doc !== '[image upload]');

  return (
    <div id="mapping-screen">
      <TopBar title="Fix Field Mappings" subtitle="Review and correct AI-suggested field mappings">
        <Link to={`/upload/${uploadId}/validation`} state={{ uploadData: data }} className="btn btn-ghost" id="btn-back-validation">
          ← Back to Validation
        </Link>
      </TopBar>

      <div className="card">
        <div className="card-header">
          <h3 className="card-header-title">Field Mapping Editor</h3>
          <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
            {editableMappings.length} headings mapped
          </span>
        </div>

        {/* Column Headers */}
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr 120px',
          gap: 16, padding: '12px 24px',
          background: '#F8FAFC', borderBottom: '1px solid var(--color-border)'
        }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary)' }}>
            Heading in Word Doc
          </div>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary)' }}>
            Mapped ACF Field
          </div>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary)' }}>
            Confidence
          </div>
        </div>

        {/* Mapping Rows — index stays aligned with the underlying `mappings`
            state array (needed by handleFieldChange), image rows just
            render nothing rather than being filtered out of the array. */}
        {mappings.map((m, idx) => {
          if (m.heading_in_doc === '[image upload]') return null;
          const isLow = m.confidence < 0.72;

          return (
            <div
              key={`${m.heading_in_doc}-${idx}`}
              style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr 120px',
                gap: 16, padding: '14px 24px', alignItems: 'center',
                borderBottom: '1px solid var(--color-border)',
                background: isLow ? 'var(--color-thin)' : 'transparent',
                transition: 'background 0.2s ease',
              }}
              id={`mapping-row-${idx}`}
            >
              <div style={{
                fontSize: '0.875rem', fontWeight: 500,
                color: 'var(--color-text-primary)',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }} title={m.heading_in_doc}>
                {m.heading_in_doc || '(empty heading)'}
              </div>

              <select
                className="select"
                value={m.field_key}
                onChange={(e) => handleFieldChange(idx, e.target.value)}
                style={{ width: '100%' }}
                aria-label={`ACF field for "${m.heading_in_doc}"`}
              >
                <option value="">— Select field —</option>
                {acfOptions.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>

              <ConfidenceBar value={Math.round(m.confidence * 100)} />
            </div>
          );
        })}

        {editableMappings.length === 0 && (
          <div style={{ padding: 48, textAlign: 'center', color: 'var(--color-text-muted)' }}>
            No headings found in the document.
          </div>
        )}

        <div className="card-footer">
          <Link to={`/upload/${uploadId}/validation`} state={{ uploadData: data }} className="btn btn-secondary" id="btn-cancel-mapping">
            Cancel
          </Link>
          <button
            className="btn btn-primary"
            onClick={handleConfirm}
            disabled={saving}
            id="btn-confirm-mappings"
          >
            {saving ? (
              <>
                <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                Saving…
              </>
            ) : (
              'Confirm Mappings'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
