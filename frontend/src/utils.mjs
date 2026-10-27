export function safeUrl(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}

export function domain(value) {
  try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return 'Source'; }
}

export function seconds(ms) { return `${(ms / 1000).toFixed(2)}s`; }

// Keep model output as text. Only valid source references become navigation links.
export function answerParts(text, sourceIds) {
  return text.split(/(\[S\d+(?:\s*,\s*S\d+)*\])/g).filter(Boolean).map(part => {
    if (!/^\[S\d+(?:\s*,\s*S\d+)*\]$/.test(part)) return { text: part, ids: [] };
    const ids = part.match(/S\d+/g) || [];
    return { text: part, ids: ids.every(id => sourceIds.includes(id)) ? ids : [] };
  });
}
