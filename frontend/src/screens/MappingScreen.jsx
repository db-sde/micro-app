import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import {
  TopBar, ConfidenceBar, LoadingSpinner, showToast
} from '../components/Components';

const API_BASE = '/api';

/* ACF fields per page type — must match backend schemas exactly */
const ACF_FIELDS = {
  university: [
    'university_name', 'about_content', 'key_highlights', 'accreditations',
    'stat_students', 'stat_alumni', 'stat_hiring_partners', 'stat_years',
    'stat_programs', 'admission_process', 'emi_details', 'courses_table',
    'faculty_table', 'placement_content', 'faqs', 'reviews', 'pros_content',
  ],
  course: [
    'course_name', 'course_about', 'course_accreditations', 'eligibility',
    'course_facts', 'admission_process', 'specializations', 'specialization_fees',
    'fee_structure', 'syllabus', 'placement_partners', 'job_roles',
    'faqs', 'duration', 'total_fee', 'emi_amount',
  ],
  specialization: [
    'spec_name', 'spec_about', 'spec_facts', 'eligibility',
    'spec_fee_table', 'admission_process', 'emi_details', 'syllabus',
    'exam_pattern', 'placement', 'faqs', 'reviews',
    'spec_total_fee', 'spec_emi',
  ],
};

export default function MappingScreen() {
  const { uploadId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState(location.state?.uploadData || null);
  const [loading, setLoading] = useState(!data);
  const [saving, setSaving] = useState(false);
  const [mappings, setMappings] = useState([]);

  useEffect(() => {
    if (data) {
      initMappings(data);
      return;
    }
    const fetchData = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/download/${uploadId}`);
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
  const acfOptions = ACF_FIELDS[pageType] || ACF_FIELDS.university;

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
            {mappings.length} headings mapped
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

        {/* Mapping Rows */}
        {mappings.map((m, idx) => {
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

        {mappings.length === 0 && (
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
