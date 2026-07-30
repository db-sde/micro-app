import React, { useState, useRef, useCallback } from 'react';
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import {
  TopBar, StepIndicator, showToast, formatFileSize
} from '../components/Components';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

// Same two slots for every page type — hero image and certificate image.
const IMAGE_SLOTS_COMMON = [
  { key: 'hero_image', label: 'Hero Image', hint: 'Recommended: 1200×630px' },
  { key: 'certificate_image', label: 'Certificate Image', hint: 'Certificate scan or sample' },
];

const IMAGE_SLOTS = {
  university: IMAGE_SLOTS_COMMON,
  course: IMAGE_SLOTS_COMMON,
  specialization: IMAGE_SLOTS_COMMON,
};

export default function ImageUploadScreen() {
  const { uploadId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const uploadData = location.state?.uploadData || {};
  const pageType = uploadData.page_type || 'university';

  const slots = IMAGE_SLOTS[pageType] || IMAGE_SLOTS.university;
  const [images, setImages] = useState({});
  const [uploading, setUploading] = useState({});
  const fileRefs = useRef({});

  // True while any slot's /upload-image request is still in flight. Used to
  // block navigating away early — otherwise Validation can load and show a
  // field as "missing" moments before that same upload actually commits.
  const anyUploading = Object.values(uploading).some(Boolean);

  const handleImageSelect = useCallback(async (slotKey, file) => {
    if (!file) return;

    const validTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
    if (!validTypes.includes(file.type)) {
      showToast('Please select a valid image file (JPEG, PNG, WebP, or GIF)', 'error');
      return;
    }

    // Create preview
    const previewUrl = URL.createObjectURL(file);
    setImages((prev) => ({ ...prev, [slotKey]: { file, preview: previewUrl, name: file.name, size: file.size } }));

    // Upload
    setUploading((prev) => ({ ...prev, [slotKey]: true }));
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('slot_name', slotKey);
      formData.append('upload_id', uploadId);

      const res = await fetch(`${API_BASE}/upload-image`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Image upload failed');
      }

      const result = await res.json();
      // Track the real stored URL (Cloudinary or local fallback) so
      // downstream screens know the field is genuinely populated.
      setImages((prev) => ({
        ...prev,
        [slotKey]: { ...prev[slotKey], url: result.url, source: result.source, warning: result.warning },
      }));
      if (result.warning) {
        // Local-only fallback — this URL will NOT be reachable once published.
        showToast(result.warning, 'warning', 8000);
      } else {
        showToast(`${slotKey.replace(/_/g, ' ')} uploaded to Cloudinary`, 'success');
      }
    } catch (err) {
      showToast(err.message || 'Image upload failed', 'error');
    } finally {
      setUploading((prev) => ({ ...prev, [slotKey]: false }));
    }
  }, [uploadId]);

  const removeImage = (slotKey) => {
    setImages((prev) => {
      const next = { ...prev };
      if (next[slotKey]?.preview) URL.revokeObjectURL(next[slotKey].preview);
      delete next[slotKey];
      return next;
    });
  };

  return (
    <div id="image-upload-screen">
      <TopBar title="Upload Images" subtitle={`Add images for your ${pageType} page`} />

      <StepIndicator currentStep={2} />

      <div className="card" style={{ maxWidth: 800, margin: '0 auto' }}>
        <div className="card-header">
          <h3 className="card-header-title">Image Slots</h3>
          <span className="text-muted" style={{ fontSize: '0.8125rem' }}>
            {Object.keys(images).length} of {slots.length} uploaded
          </span>
        </div>

        <div className="card-body">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 20 }}>
            {slots.map((slot) => {
              const img = images[slot.key];
              const isUploading = uploading[slot.key];

              return (
                <div
                  key={slot.key}
                  className={`image-slot ${img ? 'image-slot--filled' : ''}`}
                  id={`image-slot-${slot.key}`}
                >
                  {img ? (
                    <>
                      <img src={img.preview} alt={slot.label} className="image-preview" />
                      {img.warning && (
                        <div
                          title={img.warning}
                          style={{
                            marginTop: 6, fontSize: '0.6875rem', fontWeight: 700,
                            color: '#B45309', background: '#FEF3C7', border: '1px solid #FDE68A',
                            borderRadius: 'var(--radius-full)', padding: '2px 8px',
                            display: 'inline-flex', alignItems: 'center', gap: 4,
                          }}
                        >
                          ⚠ Local only — won't work once published
                        </div>
                      )}
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', marginTop: 8, padding: '0 4px' }}>
                        <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>
                          {img.name}
                        </span>
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => removeImage(slot.key)}
                          style={{ color: 'var(--color-error)', padding: '4px 8px', fontSize: '0.75rem' }}
                          aria-label={`Remove ${slot.label}`}
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      {isUploading ? (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                          <div className="spinner" style={{ width: 28, height: 28, borderWidth: 2 }} />
                          <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Uploading…</span>
                        </div>
                      ) : (
                        <>
                          <div style={{ fontSize: 32, marginBottom: 8, opacity: 0.4 }}>🖼️</div>
                          <span className="image-slot-label">{slot.label}</span>
                          <span style={{ fontSize: '0.6875rem', color: 'var(--color-text-muted)', marginBottom: 12 }}>{slot.hint}</span>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => fileRefs.current[slot.key]?.click()}
                            id={`btn-upload-${slot.key}`}
                          >
                            Choose Image
                          </button>
                          <input
                            ref={(el) => (fileRefs.current[slot.key] = el)}
                            type="file"
                            accept="image/jpeg,image/png,image/webp,image/gif"
                            onChange={(e) => {
                              if (e.target.files?.[0]) handleImageSelect(slot.key, e.target.files[0]);
                            }}
                            style={{ display: 'none' }}
                          />
                        </>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="card-footer" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          {/* No uploadData passed onward — ValidationScreen re-fetches fresh
              so any images uploaded here (now part of the ACF payload) show up. */}
          {anyUploading ? (
            <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
              Waiting for upload{Object.values(uploading).filter(Boolean).length > 1 ? 's' : ''} to finish…
            </span>
          ) : (
            <Link
              to={`/upload/${uploadId}/validation`}
              className="btn btn-ghost"
              id="btn-skip-images"
            >
              Skip this step →
            </Link>
          )}
          <button
            className="btn btn-primary"
            onClick={() => navigate(`/upload/${uploadId}/validation`)}
            disabled={anyUploading}
            title={anyUploading ? 'Wait for the upload to finish first' : undefined}
            id="btn-continue-validation"
          >
            Continue to Validation
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
