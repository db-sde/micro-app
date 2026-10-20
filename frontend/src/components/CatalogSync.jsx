import React, { useEffect, useState } from 'react';
import { catalogRequest, settingsBody, syncLabel } from './catalogApi.mjs';

export default function CatalogSync({ uploadId, initialSync = null }) {
  const [sync, setSync] = useState(initialSync);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [slug, setSlug] = useState('');
  const [clears, setClears] = useState('');
  const [approved, setApproved] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [postId, setPostId] = useState('');

  useEffect(() => {
    let active = true;
    let first = true;
    const refresh = async () => {
      try {
        const data = await catalogRequest(`/uploads/${uploadId}`);
        if (!active) return;
        setSync(data);
        if (first) {
          setSlug(data.catalog_slug || '');
          setClears((data.clear_fields || []).join(', '));
          setPostId(data.wp_post_id || '');
          first = false;
        }
      } catch (err) { if (active) setError(err.message); }
    };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => { active = false; clearInterval(timer); };
  }, [uploadId]);

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

  return (
    <section className="card" style={{ padding: 16, margin: '16px 0' }} aria-label="Chatbot catalog sync">
      <strong>{syncLabel(sync)}</strong>
      {sync?.version > 0 && <span> · version {sync.version}</span>}
      {sync?.entity_slug && <span> · {sync.entity_slug}</span>}
      {(error || sync?.last_error) && <p role="alert" style={{ color: 'var(--color-error)', marginTop: 8 }}>{error || sync.last_error}</p>}
      {sync?.warnings?.map((warning, index) => <p key={index} role="status">{warning}</p>)}
      {['failed', 'queued', 'syncing'].includes(sync?.status) && (
        <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => action('retry')}>
          {busy ? 'Working…' : 'Retry catalog sync'}
        </button>
      )}
      <details style={{ marginTop: 12 }}>
        <summary>Review mapping, explicit removals and existing WordPress references</summary>
        <p>Published upserts only. Draft/private/deleted pages remain in the chatbot until operator action. Direct WordPress edits are not observed.</p>
        <p>Before backfill, review existing entities using the chatbot operator’s admin session. Leave the catalog slug empty for new records. No admin token is needed here.</p>
        <label style={{ display: 'block', marginTop: 8 }}>Reviewed catalog slug
          <input className="form-input" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="Leave empty for a new entity" />
        </label>
        <label style={{ display: 'block', marginTop: 8 }}>Explicit fields to clear (comma separated)
          <input className="form-input" value={clears} onChange={(e) => setClears(e.target.value)} placeholder="about_content, faqs" />
        </label>
        <label style={{ display: 'block', margin: '8px 0' }}>
          <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} /> I approve these removals from chatbot knowledge.
        </label>
        <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => action('settings', 'PUT', settingsBody(slug, clears, approved))}>Save per-post settings</button>
        <p>Settings apply to the next event. Failed events keep their original bytes; retry creates a new version of the last published snapshot. Publish reviewed content corrections to WordPress first. Superseded snapshots cannot be forced over newer data.</p>
        <label style={{ display: 'block', marginTop: 8 }}>Existing WordPress post ID (for legacy publications or missing parents)
          <input className="form-input" value={postId} onChange={(e) => setPostId(e.target.value)} inputMode="numeric" />
        </label>
        <label style={{ display: 'block', margin: '8px 0' }}>
          <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} /> I reviewed that this upload’s original content matches the published page.
        </label>
        <button className="btn btn-secondary btn-sm" disabled={busy || !reviewed} onClick={() => action('reconcile', 'POST', JSON.stringify({ wp_post_id: postId || null, reviewed }))}>Read WordPress references for review</button>
        <p>This reads the existing post; it does not republish or enqueue. Save the reviewed catalog mapping, then retry sync or start backfill. To add a missing parent, upload its original document, review it, then link its existing WordPress ID here and sync it first. Catalog delivery waits for both parents to apply.</p>
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
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try { const data = await catalogRequest('/backfills'); if (active) setRuns(data); }
      catch (err) { if (active) setError(err.message); }
    };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => { active = false; clearInterval(timer); };
  }, []);
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
  return (
    <section className="card" style={{ padding: 16, marginBottom: 20 }} aria-label="Chatbot backfill">
      <strong>Chatbot catalog backfill</strong>
      <p>Preview saved published posts, deduplicated by WordPress ID. Delivery applies universities, then their courses, then specializations. Progress resumes after restarts without publishing to WordPress.</p>
      <p>Review existing catalog mappings in the chatbot operator’s admin session before the initial backfill. Coverage is limited to this parser’s saved records; pages absent here are not discovered.</p>
      <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => run(false)}>Preview / dry-run</button>
      {error && <p role="alert" style={{ color: 'var(--color-error)' }}>{error}</p>}
      {preview && <div>
        <p>{preview.coverage}</p>
        <p>{Object.entries(preview.counts).map(([state, count]) => `${state}: ${count}`).join(' · ')}</p>
        <ul>{preview.posts.map((post) => <li key={post.post_id}>
          {post.page_type} #{post.wp_post_id}: {post.state}{post.catalog_slug ? ` → ${post.catalog_slug}` : ''}{post.error ? ` — ${post.error}` : ''}
          {' '}<a href={`/upload/${post.upload_id}/validation`}>Review / sync parent</a>
        </li>)}</ul>
        <label style={{ display: 'block', margin: '8px 0' }}><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} /> I reviewed mappings and the complete published content before this backfill.</label>
        <button className="btn btn-primary btn-sm" disabled={busy || !reviewed || !preview.counts.ready} onClick={() => run(true)}>Start resumable backfill</button>
      </div>}
      {runs.map((item) => <details key={item.id} style={{ marginTop: 12 }}>
        <summary>Backfill {item.id.slice(0, 8)} · {item.complete ? 'finished (review failures)' : 'in progress'} · {item.total} posts · {Object.entries(item.counts).map(([state, count]) => `${state}: ${count}`).join(', ')}</summary>
        <ul>{item.items.map((post) => <li key={post.event_id}>Post reference {post.post_id}: {post.status}{post.last_error ? ` — ${post.last_error}` : ''}</li>)}</ul>
      </details>)}
    </section>
  );
}
