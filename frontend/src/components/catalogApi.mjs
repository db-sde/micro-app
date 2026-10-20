export async function catalogRequest(path, options = {}, fetcher = fetch) {
  const base = import.meta.env?.VITE_API_BASE || '/api';
  const response = await fetcher(`${base}/catalog${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Catalog request failed (${response.status})`);
  return body;
}

export function settingsBody(slug, clears, approved) {
  return JSON.stringify({
    catalog_slug: slug.trim() || null,
    clear_fields: clears.split(',').map((field) => field.trim()).filter(Boolean),
    removals_approved: approved,
  });
}

// Statuses where the sender is still working, so the UI should keep polling.
export const ACTIVE_SYNC_STATES = ['queued', 'syncing'];

export function isLegacyNeedsLinking(sync) {
  return sync?.status === 'failed' && /^Legacy (publication|snapshot)/.test(sync?.last_error || '');
}

/**
 * Turn a raw catalog_sync status into what an editor needs to know: a tone,
 * a short label, one sentence of explanation, and which action makes sense.
 * The raw status strings ("not eligible/draft", "Legacy snapshot needs
 * review ... reconciliation ...") are accurate but read as errors to someone
 * who just wants to know whether the chatbot has this page.
 */
export function describeSync(sync) {
  const status = sync?.status;
  const raw = sync?.last_error || '';
  if (!status) return { tone: 'muted', label: 'Checking…', detail: '', active: false };
  if (status === 'not configured') {
    return { tone: 'muted', label: 'Chatbot sync off', detail: 'The chatbot connection is not configured on the server.', active: false };
  }
  if (status === 'not eligible/draft') {
    return { tone: 'muted', label: 'Not sent to chatbot', detail: 'Only pages published live on WordPress are sent to the chatbot.', active: false };
  }
  if (ACTIVE_SYNC_STATES.includes(status)) {
    return { tone: 'info', label: 'Sending to chatbot…', detail: raw || 'Queued. This updates automatically.', active: true };
  }
  if (status === 'synced') {
    return { tone: 'success', label: 'In chatbot', detail: sync?.version ? `Version ${sync.version} applied.` : 'Applied.', active: false };
  }
  if (status === 'superseded') {
    return { tone: 'muted', label: 'Superseded', detail: raw || 'A newer version of this page was sent instead.', active: false };
  }
  if (isLegacyNeedsLinking(sync)) {
    return {
      tone: 'warning', label: 'Needs linking', needsLinking: true, active: false,
      detail: 'Published before chatbot sync existed. Link it to its WordPress post below, then send it.',
    };
  }
  if (status === 'failed') {
    return { tone: 'error', label: 'Sync failed', detail: raw || 'The chatbot rejected this page.', canRetry: true, active: false };
  }
  return { tone: 'muted', label: status, detail: raw, active: false };
}

export function syncLabel(sync) {
  return `Chatbot: ${describeSync(sync).label}`;
}
