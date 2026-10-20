import React, { useEffect, useRef, useState } from 'react';
import { catalogRequest, settingsBody, syncLabel, describeSync, ACTIVE_SYNC_STATES } from './catalogApi.mjs';

const POLL_MS = 8000;

// Poll only while the sender is actually working, and never from a hidden
// tab. Polling every 5s unconditionally used to keep the single backend
// instance busy for every open page.
function usePolling(active, refresh) {
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => {
      if (typeof document === 'undefined' || !document.hidden) refreshRef.current();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [active]);
}

export default function CatalogSync({ uploadId, initialSync = null }) {
  const [sync, setSync] = useState(initialSync);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [slug, setSlug] = useState('');
  const [clears, setClears] = useState('');
  const [approved, setApproved] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [postId, setPostId] = useState('');
  const seeded = useRef(false);

  const refresh = async () => {
    try {
      const data = await catalogRequest(`/uploads/${uploadId}`);
      setSync(data);
      setError('');
      if (!seeded.current) {
        setSlug(data.catalog_slug || '');
        setClears((data.clear_fields || []).join(', '));
        setPostId(data.wp_post_id || '');
        seeded.current = true;
      }
    } catch (err) { setError(err.message); }
  };

  useEffect(() => {
    seeded.current = false;
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadId]);

  usePolling(ACTIVE_SYNC_STATES.includes(sync?.status), refresh);

  const action = async (suffix, method = 'POST', body) => {
    setBusy(true);
    setError('');
    try {
      const data = await catalogRequest(`/uploads/${uploadId}/${suffix}`, { method, body });
      setSync(data);
      if (suffix === 'settings') setApproved(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const view = describeSync(sync);
  const showRetry = view.canRetry || view.active;

  return (
    <section className="card sync-panel" aria-label="Chatbot catalog sync">
      <div className="sync-panel-head">
        <span className="sync-panel-title">Chatbot</span>
        <span className={`badge badge--${view.tone}`} aria-label={syncLabel(sync)}><span className="badge-dot" />{view.label}</span>
        {sync?.entity_slug && <span className="sync-panel-detail" style={{ marginTop: 0 }}>· {sync.entity_slug}</span>}
        {showRetry && (
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => action('retry')}>
            {busy ? 'Working…' : 'Retry catalog sync'}
          </button>
        )}
      </div>
      {view.detail && !error && (
        <p className={`sync-panel-detail${view.tone === 'error' ? ' sync-panel-detail--error' : ''}`} role={view.tone === 'error' ? 'alert' : undefined}>
          {view.detail}
        </p>
      )}
      {error && <p role="alert" className="sync-panel-detail sync-panel-detail--error">{error}</p>}
      {sync?.warnings?.length > 0 && (
        <ul className="notice notice--warning" role="status" style={{ marginTop: 10, paddingLeft: 28 }}>
          {sync.warnings.map((warning, index) => <li key={index}>{warning}</li>)}
        </ul>
      )}

      <details className="disclosure" open={view.needsLinking || undefined}>
        <summary>{view.needsLinking ? 'Link this upload to its WordPress post' : 'Chatbot settings and WordPress link'}</summary>
        <div className="disclosure-body">
          <h4>Link to an existing WordPress post</h4>
          <p style={{ margin: 0 }}>
            For pages that were already live before chatbot sync existed. This only reads the post; it never republishes it.
          </p>
          <label className="field-label">WordPress post ID
            <input className="form-input" value={postId} onChange={(e) => setPostId(e.target.value)} inputMode="numeric" placeholder="e.g. 4827" />
          </label>
          <label className="check-label">
            <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
            I checked that this upload matches the live WordPress page.
          </label>
          <div>
            <button className="btn btn-secondary btn-sm" disabled={busy || !reviewed || !postId} onClick={() => action('reconcile', 'POST', JSON.stringify({ wp_post_id: postId || null, reviewed }))}>
              Read WordPress references for review
            </button>
          </div>

          <h4>Advanced: chatbot record mapping</h4>
          <label className="field-label">Reviewed catalog slug
            <input className="form-input" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="Leave empty for a new entity" />
          </label>
          <label className="field-label">Fields to remove from the chatbot (comma separated)
            <input className="form-input" value={clears} onChange={(e) => setClears(e.target.value)} placeholder="about_content, faqs" />
          </label>
          <label className="check-label">
            <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
            I approve removing these fields from the chatbot.
          </label>
          <div>
            <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => action('settings', 'PUT', settingsBody(slug, clears, approved))}>
              Save chatbot settings
            </button>
          </div>
          <p style={{ margin: 0 }}>
            Only live pages are sent. Unpublishing or deleting a WordPress page does not remove it from the chatbot, and edits made directly in WordPress are not picked up.
          </p>
        </div>
      </details>
    </section>
  );
}

export function CatalogBackfill() {
  const [preview, setPreview] = useState(null);
  const [runs, setRuns] = useState([]);
  const [reviewed, setReviewed] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try { setRuns(await catalogRequest('/backfills')); }
    catch (err) { setError(err.message); }
  };
  useEffect(() => { refresh(); }, []);
  usePolling(runs.some((item) => !item.complete), refresh);

  const run = async (start) => {
    setBusy(true);
    setError('');
    try {
      const data = await catalogRequest(start ? '/backfills' : '/backfills/preview', { method: 'POST' });
      if (start) { setRuns((previous) => [data, ...previous]); setPreview(null); setReviewed(false); }
      else { setPreview(data); setReviewed(false); }
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const counts = preview?.counts || {};
  return (
    <section className="card backfill-card" aria-label="Chatbot backfill">
      <div className="backfill-head">
        <div>
          <strong>Send live pages to the chatbot</strong>
          <p>Universities go first, then courses, then specializations. Start with a preview — nothing is sent until you confirm.</p>
        </div>
        <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => run(false)}>
          {busy && !preview ? 'Checking…' : 'Preview'}
        </button>
      </div>
      {error && <p role="alert" className="notice notice--error" style={{ marginTop: 10 }}>{error}</p>}
      {preview && (
        <div style={{ marginTop: 12 }}>
          <p className="notice notice--info">
            Ready: <strong>{counts.ready || 0}</strong> · Already sent: <strong>{counts.existing || 0}</strong> · Blocked: <strong>{counts.blocked || 0}</strong> · Not eligible: <strong>{counts.ineligible || 0}</strong>
            <br /><span style={{ fontSize: '0.75rem' }}>{preview.coverage}</span>
          </p>
          {preview.posts.length > 0 && (
            <ul className="backfill-list">
              {preview.posts.map((post) => (
                <li key={post.post_id}>
                  <span style={{ textTransform: 'capitalize' }}>{post.page_type}</span> #{post.wp_post_id}: <strong>{post.state}</strong>
                  {post.catalog_slug ? ` → ${post.catalog_slug}` : ''}
                  {post.error ? ` — ${post.error}` : ''}
                  {' '}<a href={`/upload/${post.upload_id}/validation`}>Open</a>
                </li>
              ))}
            </ul>
          )}
          <label className="check-label" style={{ margin: '12px 0' }}>
            <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
            I reviewed the mappings and the published content.
          </label>
          <button className="btn btn-primary btn-sm" disabled={busy || !reviewed || !counts.ready} onClick={() => run(true)}>
            Send {counts.ready || 0} ready page{counts.ready === 1 ? '' : 's'}
          </button>
        </div>
      )}
      {runs.map((item) => (
        <details key={item.id} className="disclosure">
          <summary>
            Run {item.id.slice(0, 8)} · {item.complete ? 'finished' : 'in progress'} · {item.total} pages · {Object.entries(item.counts).map(([state, count]) => `${state}: ${count}`).join(', ')}
          </summary>
          <ul className="backfill-list">
            {item.items.map((post) => <li key={post.event_id}>Page {post.post_id}: {post.status}{post.last_error ? ` — ${post.last_error}` : ''}</li>)}
          </ul>
        </details>
      ))}
    </section>
  );
}
