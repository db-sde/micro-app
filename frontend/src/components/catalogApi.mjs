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

export function syncLabel(sync) {
  return `Chatbot: ${sync?.status || 'loading'}`;
}
