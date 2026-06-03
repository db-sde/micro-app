import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  TopBar, StepIndicator, DropZone, PageTypeSelector,
  Toggle, LoadingSpinner, showToast
} from '../components/Components';

const API_BASE = '/api';

export default function UploadScreen() {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [autoDetect, setAutoDetect] = useState(true);
  const [pageType, setPageType] = useState('university');
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState('');

  const handleFileDrop = (f) => {
    setError('');
    if (!f) {
      setFile(null);
      return;
    }
    if (f.name && !f.name.toLowerCase().endsWith('.docx')) {
      setError('Only .docx files are supported. Please select a Word document.');
      setFile(null);
      showToast('Invalid file type — only .docx files accepted', 'error');
      return;
    }
    setFile(f);
  };

  const handleParse = async () => {
    if (!file) return;
    setProcessing(true);
    setError('');

    try {
      const formData = new FormData();
      formData.append('file', file);
      if (!autoDetect) {
        formData.append('page_type', pageType);
      }

      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || errData.message || `Upload failed (${res.status})`);
      }

      const data = await res.json();
      const uploadId = data.upload_id || data.id;
      showToast('Document parsed successfully!', 'success');
      navigate(`/upload/${uploadId}/images`, { state: { uploadData: data } });
    } catch (err) {
      setError(err.message);
      showToast(err.message || 'Upload failed', 'error');
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div id="upload-screen">
      <TopBar title="New Upload" subtitle="Parse a Word document into structured content" />

      <StepIndicator currentStep={1} />

      <div className="card" style={{ maxWidth: 680, margin: '0 auto' }}>
        <div className="card-body">
          {processing ? (
            <LoadingSpinner message="Processing document… This may take a moment." />
          ) : (
            <>
              <DropZone
                onFileDrop={handleFileDrop}
                accept=".docx"
                label="Drop your Word document here"
                sublabel="Only .docx files are supported"
                id="upload-dropzone"
              />

              {error && (
                <div style={{
                  marginTop: 16,
                  padding: '12px 16px',
                  background: 'var(--color-error-light)',
                  color: 'var(--color-error)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '0.875rem',
                  fontWeight: 500,
                }} id="upload-error" role="alert">
                  {error}
                </div>
              )}

              <div style={{ marginTop: 28, borderTop: '1px solid var(--color-border-light)', paddingTop: 24 }}>
                <Toggle
                  checked={autoDetect}
                  onChange={setAutoDetect}
                  label="Auto-detect page type"
                  id="toggle-auto-detect"
                />

                {!autoDetect && (
                  <div style={{ marginTop: 20, animation: 'fadeIn 0.3s ease' }}>
                    <label className="input-label" style={{ marginBottom: 12, display: 'block' }}>
                      Select Page Type
                    </label>
                    <PageTypeSelector
                      value={pageType}
                      onChange={setPageType}
                    />
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {!processing && (
          <div className="card-footer">
            <button
              className="btn btn-primary btn-lg"
              onClick={handleParse}
              disabled={!file || processing}
              id="btn-parse-document"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              Parse Document
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
