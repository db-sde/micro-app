import React, { useState, useEffect } from 'react';
import {
  TopBar, DropZone, PageTypeSelector,
  LoadingSpinner, showToast, Modal, Toggle
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

/* ═══════════════════════════════════════
   PUBLISH TO WORDPRESS MODAL (blog/category)
   Same pattern as ValidationScreen's PublishModal, minus the
   image/taxonomy warning blocks — blog and category pages have neither.
   ═══════════════════════════════════════ */
function BlogPublishModal({ isOpen, onClose, uploadId }) {
  const [goLive, setGoLive] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [result, setResult] = useState(null);
  const [publishError, setPublishError] = useState('');

  useEffect(() => {
    if (isOpen) {
      setResult(null);
      setPublishError('');
      setGoLive(false);
    }
  }, [isOpen]);

  const handlePublish = async () => {
    setPublishing(true);
    setPublishError('');
    try {
      const res = await fetch(`${API_BASE}/publish/${uploadId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: goLive ? 'publish' : 'draft' }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Publish failed (${res.status})`);
      setResult(body);
      showToast(
        goLive ? 'Published live on WordPress!' : 'Saved as a WordPress draft!',
        'success'
      );
    } catch (err) {
      setPublishError(err.message || 'Publish failed');
    } finally {
      setPublishing(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Publish to WordPress">
      {!result ? (
        <>
          <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', marginBottom: 16 }}>
            This creates a new WordPress post populated with the Page Summary, SEO Title, Meta Description, and Reading Time from this upload.
          </p>
          <Toggle
            checked={goLive}
            onChange={setGoLive}
            label={goLive ? 'Publish live (public immediately)' : 'Save as draft (recommended)'}
            id="toggle-blog-publish-live"
          />
          {publishError && (
            <div style={{
              marginTop: 16, padding: '10px 14px', background: '#FEE2E2',
              color: '#DC2626', borderRadius: 'var(--radius-md)', fontSize: '0.8125rem',
            }}>
              ⚠ {publishError}
            </div>
          )}
          <div className="modal-footer" style={{ padding: '20px 0 0', borderTop: 'none' }}>
            <button className="btn btn-secondary" onClick={onClose} id="btn-cancel-blog-publish">
              Cancel
            </button>
            <button className="btn btn-primary" onClick={handlePublish} disabled={publishing} id="btn-confirm-blog-publish">
              {publishing ? (
                <>
                  <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                  Publishing…
                </>
              ) : (
                goLive ? 'Publish Live' : 'Save Draft to WordPress'
              )}
            </button>
          </div>
        </>
      ) : (
        <>
          <div style={{
            padding: '12px 16px', background: '#ECFDF5', color: '#059669',
            borderRadius: 'var(--radius-md)', fontSize: '0.875rem', fontWeight: 600, marginBottom: 16,
          }}>
            ✓ {result.wp_status === 'publish' ? 'Published live' : 'Saved as draft'} on WordPress (post #{result.wp_post_id})
          </div>
          {result.wp_warnings?.length > 0 && (
            <div style={{
              padding: '10px 14px', background: '#FEF3C7', color: '#92400E',
              borderRadius: 'var(--radius-md)', fontSize: '0.8125rem', marginBottom: 16,
            }}>
              ⚠ Published, but something didn't attach — likely a transient network hiccup, safe to retry:
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {result.wp_warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <a href={result.wp_edit_link} target="_blank" rel="noopener noreferrer" className="btn btn-secondary" style={{ textAlign: 'center' }}>
              Open in WordPress Editor →
            </a>
            {result.wp_post_url && (
              <a href={result.wp_post_url} target="_blank" rel="noopener noreferrer" className="btn btn-ghost" style={{ textAlign: 'center' }}>
                View Post →
              </a>
            )}
          </div>
          <div className="modal-footer" style={{ padding: '20px 0 0', borderTop: 'none' }}>
            <button className="btn btn-secondary" onClick={onClose} id="btn-close-blog-publish-result">
              Close
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

export default function BlogSummarizerScreen() {
  const [file, setFile] = useState(null);
  const [pageType, setPageType] = useState('blog');
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState('');
  
  const [result, setResult] = useState(null); // { upload_id, payload: {complete_page_summary, seo_title, meta_description, reading_time}, filename: string }
  const [editedJson, setEditedJson] = useState('');
  const [previewHtml, setPreviewHtml] = useState('');
  const [previewSeoTitle, setPreviewSeoTitle] = useState('');
  const [previewMetaDesc, setPreviewMetaDesc] = useState('');
  const [jsonError, setJsonError] = useState('');
  const [showPublishModal, setShowPublishModal] = useState(false);

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
      // Support both old (data.summary string) and new (data.payload object) response shapes
      const payloadObj = data.payload || {};
      setEditedJson(JSON.stringify(payloadObj, null, 2));
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
      setPreviewSeoTitle(parsed.seo_title || '');
      setPreviewMetaDesc(parsed.meta_description || '');
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
      <TopBar title="Blog & Category Summarizer" subtitle="Generate summary, SEO title & meta description" />

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
                    Summary & SEO Generated
                  </h3>
                  <div style={{ fontSize: '0.95rem', color: 'var(--color-text-muted)', marginTop: 4 }}>
                    Source file: {result.filename}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <button className="btn btn-secondary" onClick={handleReset} style={{ padding: '8px 20px' }}>
                    Start Over
                  </button>
                  <button className="btn btn-secondary" onClick={handleCopy} disabled={!!jsonError} style={{ padding: '8px 20px' }}>
                    Copy JSON to Clipboard
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={() => setShowPublishModal(true)}
                    disabled={!result.upload_id}
                    title={!result.upload_id ? 'This upload has no ID to publish' : undefined}
                    style={{ padding: '8px 20px' }}
                    id="btn-publish-blog"
                  >
                    🚀 Publish to WordPress
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
                <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                  {/* HTML Summary Preview */}
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
                      <span style={{ fontWeight: 600, color: 'var(--color-text-main)', fontSize: '0.95rem' }}>Live Summary Preview</span>
                      <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--color-text-muted)', fontWeight: 500 }}>REAL-TIME</span>
                    </div>
                    <div 
                      style={{
                        flex: 1,
                        minHeight: '260px',
                        padding: '24px',
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
                          style={{ lineHeight: '1.8', fontSize: '1.05rem' }}
                        />
                      )}
                    </div>
                  </div>

                  {/* SEO Fields Preview */}
                  {!jsonError && (previewSeoTitle || previewMetaDesc) && (
                    <div style={{
                      padding: '20px 24px',
                      border: '1px solid var(--color-border-main)',
                      borderRadius: 'var(--radius-md)',
                      background: 'var(--color-bg-alt)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 16,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-primary)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                        </svg>
                        <span style={{ fontWeight: 700, color: 'var(--color-text-main)', fontSize: '0.9rem', letterSpacing: '0.04em', textTransform: 'uppercase' }}>SEO Fields</span>
                      </div>
                      {previewSeoTitle && (
                        <div>
                          <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>SEO Title</div>
                          <div style={{ fontSize: '1rem', color: '#1a0dab', fontWeight: 500 }}>{previewSeoTitle}</div>
                          <div style={{ fontSize: '0.78rem', color: previewSeoTitle.length > 60 ? 'var(--color-error)' : 'var(--color-text-muted)', marginTop: 4 }}>{previewSeoTitle.length} / 60 chars</div>
                        </div>
                      )}
                      {previewMetaDesc && (
                        <div>
                          <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Meta Description</div>
                          <div style={{ fontSize: '0.93rem', color: '#006621' }}>{previewMetaDesc}</div>
                          <div style={{ fontSize: '0.78rem', color: previewMetaDesc.length > 160 ? 'var(--color-error)' : 'var(--color-text-muted)', marginTop: 4 }}>{previewMetaDesc.length} / 160 chars</div>
                        </div>
                      )}
                    </div>
                  )}
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

      {result?.upload_id && (
        <BlogPublishModal
          isOpen={showPublishModal}
          onClose={() => setShowPublishModal(false)}
          uploadId={result.upload_id}
        />
      )}
    </div>
  );
}
