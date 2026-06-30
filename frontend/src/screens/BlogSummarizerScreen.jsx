import React, { useState, useEffect } from 'react';
import {
  TopBar, DropZone, PageTypeSelector,
  LoadingSpinner, showToast
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export default function BlogSummarizerScreen() {
  const [file, setFile] = useState(null);
  const [pageType, setPageType] = useState('blog');
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState('');
  
  const [result, setResult] = useState(null); // { summary: string (JSON), filename: string }
  const [editedJson, setEditedJson] = useState('');
  const [previewHtml, setPreviewHtml] = useState('');
  const [jsonError, setJsonError] = useState('');

  const handleFileDrop = (f) => {
    setError('');
    if (!f) {
      setFile(null);
      return;
    }
    if (f.name && !f.name.toLowerCase().endsWith('.docx')) {
      const msg = 'Please upload a valid Word document (.docx).';
      setError(msg);
      showToast(msg, 'error');
      setFile(null);
      return;
    }
    setFile(f);
  };

  const handleGenerate = async () => {
    if (!file) return;
    setProcessing(true);
    setError('');

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('page_type', pageType);

      const res = await fetch(`${API_BASE}/upload-blog`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        throw new Error("API_ERROR");
      }

      const data = await res.json();
      setResult(data);
      setEditedJson(data.summary);
      showToast('Summary generated successfully!', 'success');
    } catch (err) {
      const friendlyError = "We ran into an issue generating the summary. Please check your document and try again.";
      setError(friendlyError);
      showToast(friendlyError, 'error');
    } finally {
      setProcessing(false);
    }
  };

  useEffect(() => {
    if (!editedJson) return;
    try {
      const parsed = JSON.parse(editedJson);
      setPreviewHtml(parsed.complete_page_summary || '');
      setJsonError('');
    } catch (e) {
      setJsonError('Please ensure the JSON brackets and quotes are formatted correctly.');
    }
  }, [editedJson]);

  const handleCopy = () => {
    if (jsonError) {
      showToast('Cannot copy while the JSON has formatting errors.', 'error');
      return;
    }
    navigator.clipboard.writeText(editedJson);
    showToast('JSON Payload copied to clipboard!', 'success');
  };

  const handleReset = () => {
    setFile(null);
    setResult(null);
    setEditedJson('');
    setPreviewHtml('');
    setError('');
  };

  return (
    <div id="blog-summarizer-screen">
      <TopBar title="Blog & Category Summarizer" subtitle="Generate a 4-5 point engaging summary" />

      <div className="card" style={{ 
        maxWidth: result ? 1200 : 720, 
        margin: '2rem auto', 
        transition: 'all 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        boxShadow: result ? '0 12px 40px rgba(0,0,0,0.08)' : '0 4px 12px rgba(0,0,0,0.05)'
      }}>
        <div className="card-body">
          {processing ? (
            <div style={{ padding: '40px 0' }}>
              <LoadingSpinner message="Reading document and generating summary..." />
            </div>
          ) : result ? (
            // RESULT MODE - DUAL WINDOW
            <div className="animation-fade-in">
              <div style={{ 
                display: 'flex', 
                justifyContent: 'space-between', 
                alignItems: 'center', 
                marginBottom: 28,
                paddingBottom: 20,
                borderBottom: '1px solid var(--color-border-light)'
              }}>
                <div>
                  <h3 style={{ fontSize: '1.35rem', color: 'var(--color-text-main)', margin: 0, fontWeight: 600 }}>
                    Summary Generated
                  </h3>
                  <div style={{ fontSize: '0.95rem', color: 'var(--color-text-muted)', marginTop: 4 }}>
                    Source file: {result.filename}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <button className="btn btn-secondary" onClick={handleReset} style={{ padding: '8px 20px' }}>
                    Start Over
                  </button>
                  <button className="btn btn-primary" onClick={handleCopy} disabled={!!jsonError} style={{ padding: '8px 20px' }}>
                    Copy JSON to Clipboard
                  </button>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
                
                {/* JSON EDITOR WINDOW */}
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <div style={{ 
                    padding: '12px 18px', 
                    background: 'var(--color-bg-alt)', 
                    border: '1px solid var(--color-border-main)',
                    borderBottom: 'none',
                    borderTopLeftRadius: 'var(--radius-md)',
                    borderTopRightRadius: 'var(--radius-md)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8
                  }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--color-primary)' }} />
                    <span style={{ fontWeight: 600, color: 'var(--color-text-main)', fontSize: '0.95rem' }}>JSON Payload</span>
                    <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--color-text-muted)', fontWeight: 500 }}>EDITABLE</span>
                  </div>
                  <textarea
                    value={editedJson}
                    onChange={(e) => setEditedJson(e.target.value)}
                    spellCheck={false}
                    style={{
                      flex: 1,
                      minHeight: '450px',
                      padding: '20px',
                      borderBottomLeftRadius: 'var(--radius-md)',
                      borderBottomRightRadius: 'var(--radius-md)',
                      border: '1px solid var(--color-border-main)',
                      fontSize: '0.95rem',
                      lineHeight: '1.6',
                      fontFamily: 'monospace',
                      resize: 'vertical',
                      background: '#1a1a1a',
                      color: '#e4e4e4',
                      outline: 'none',
                      boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.1)'
                    }}
                  />
                  {jsonError && (
                    <div style={{ 
                      color: 'var(--color-error)', 
                      fontSize: '0.9rem', 
                      marginTop: 12, 
                      fontWeight: 500,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6
                    }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="12" y1="8" x2="12" y2="12"></line>
                        <line x1="12" y1="16" x2="12.01" y2="16"></line>
                      </svg>
                      {jsonError}
                    </div>
                  )}
                </div>

                {/* UI/UX PREVIEW WINDOW */}
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <div style={{ 
                    padding: '12px 18px', 
                    background: 'var(--color-bg-alt)', 
                    border: '1px solid var(--color-border-main)',
                    borderBottom: 'none',
                    borderTopLeftRadius: 'var(--radius-md)',
                    borderTopRightRadius: 'var(--radius-md)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8
                  }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--color-success)' }} />
                    <span style={{ fontWeight: 600, color: 'var(--color-text-main)', fontSize: '0.95rem' }}>Live UI Preview</span>
                    <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--color-text-muted)', fontWeight: 500 }}>REAL-TIME</span>
                  </div>
                  <div 
                    style={{
                      flex: 1,
                      minHeight: '450px',
                      padding: '32px',
                      borderBottomLeftRadius: 'var(--radius-md)',
                      borderBottomRightRadius: 'var(--radius-md)',
                      border: '1px solid var(--color-border-main)',
                      background: 'white',
                      color: '#1f2937',
                      overflowY: 'auto',
                      boxShadow: '0 4px 6px -1px rgba(0,0,0,0.05)'
                    }}
                  >
                    {jsonError ? (
                      <div style={{ color: 'var(--color-text-muted)', fontStyle: 'italic', textAlign: 'center', marginTop: 40 }}>
                        Preview is paused while you fix the JSON formatting.
                      </div>
                    ) : (
                      <div 
                        className="live-preview-content"
                        dangerouslySetInnerHTML={{ __html: previewHtml }}
                        style={{
                          lineHeight: '1.8',
                          fontSize: '1.05rem',
                        }}
                      />
                    )}
                  </div>
                </div>

              </div>
            </div>
          ) : (
            // UPLOAD MODE
            <>
              <DropZone
                onFileDrop={handleFileDrop}
                accept=".docx"
                label="Drop your Blog or Category .docx here"
                sublabel="Extracts raw text and generates a 4-5 point summary"
                id="blog-dropzone"
              />

              {error && (
                <div style={{
                  marginTop: 20,
                  padding: '14px 18px',
                  background: 'var(--color-error-light)',
                  color: 'var(--color-error)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '0.95rem',
                  fontWeight: 500,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8
                }} role="alert">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                  </svg>
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        {!processing && !result && (
          <div className="card-footer" style={{ padding: '24px', borderTop: '1px solid var(--color-border-light)', background: 'var(--color-bg-alt)', borderBottomLeftRadius: 'var(--radius-lg)', borderBottomRightRadius: 'var(--radius-lg)' }}>
            <button
              className="btn btn-primary btn-lg"
              onClick={handleGenerate}
              disabled={!file}
              style={{ width: '100%', justifyContent: 'center', padding: '14px' }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
              </svg>
              Generate Summary
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
