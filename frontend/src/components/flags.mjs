// Validation flags from extraction v2 (validation.field_report[i].flags).
// v1 uploads have no flags; every helper returns "nothing to show" for them.

const SEVERITY_ORDER = { error: 3, warning: 2, info: 1 };

/** Flags per field key, from a validation report. */
export function flagsByField(validation) {
  const out = {};
  for (const row of validation?.field_report || []) {
    if (Array.isArray(row.flags) && row.flags.length) out[row.field_key] = row.flags;
  }
  return out;
}

/** The most serious severity among the flags ('error' | 'warning' | 'info'), or null. */
export function flagLevel(flags) {
  let best = null;
  for (const f of flags || []) {
    if (SEVERITY_ORDER[f.severity] && (!best || SEVERITY_ORDER[f.severity] > SEVERITY_ORDER[best])) best = f.severity;
  }
  return best;
}

/** Badge text and tooltip, or null when there is nothing worth showing. */
export function flagBadge(flags) {
  const level = flagLevel(flags);
  if (!level) return null;
  const shown = (flags || []).filter((f) => SEVERITY_ORDER[f.severity]);
  const icon = level === 'info' ? 'ℹ' : '⚠';
  const label = level === 'info' ? 'auto-set' : `${shown.filter((f) => f.severity !== 'info').length} to check`;
  const tooltip = shown
    .slice()
    .sort((a, b) => SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity])
    .map((f) => `${f.severity.toUpperCase()}: ${f.message}`)
    .join('\n');
  return { level, text: `${icon} ${label}`, tooltip };
}

/** Colours for a mapping's source badge (unknown sources stay neutral). */
export function sourceColors(source) {
  const map = {
    embedding: ['#EDE9FE', '#7C3AED'],
    ai: ['#DBEAFE', '#2563EB'],
    LLM: ['#CCFBF1', '#0F766E'],
    DERIVED: ['#FEF3C7', '#92400E'],
  };
  const [background, color] = map[source] || ['#F1F5F9', '#64748B'];
  return { background, color };
}
