import { createHash, createHmac, timingSafeEqual } from 'node:crypto';

function equal(a, b) {
  return timingSafeEqual(createHash('sha256').update(a).digest(), createHash('sha256').update(b).digest());
}
function json(value, status = 200, headers = {}) {
  return Response.json(value, {status, headers: {'Cache-Control':'no-store', ...headers}});
}
function signature(value, key) { return createHmac('sha256', key).update(value).digest('base64url'); }
function validSession(request, key, now) {
  const cookie = (request.headers.get('cookie') || '').split(';').map(v => v.trim()).find(v => v.startsWith('nse_demo='));
  if (!cookie) return false;
  const [expires, signed, extra] = cookie.slice(9).split('.');
  return !extra && /^\d+$/.test(expires || '') && Number(expires) > now && equal(signed || '', signature(expires, key));
}
async function boundedBody(request, limit = 16384) {
  if (!request.body) return '';
  const reader = request.body.getReader(); let size = 0; const parts = [];
  try {
    while (true) { const {done, value} = await reader.read(); if (done) break;
      size += value.length; if (size > limit) { await reader.cancel(); throw new Error('too_large'); } parts.push(value);
    }
  } finally { reader.releaseLock(); }
  return Buffer.concat(parts).toString('utf8');
}

export function createDemoHandler(env = process.env, upstreamFetch = fetch, clock = Date.now) {
  return async function handle(request) {
    const now = clock();
    const cutoff = Date.parse(env.NSE_DEMO_EXPIRES_AT || '');
    const key = env.NSE_API_TOKEN;
    const code = env.NSE_DEMO_CODE;
    if (!key || !code || !Number.isFinite(cutoff)) return json({error:'Demo configuration is incomplete.'}, 503);
    if (now >= cutoff) return json({error:'This demo has ended.'}, 410);
    const url = new URL(request.url);
    const path = url.searchParams.get('route') || url.pathname;
    const origin = request.headers.get('origin');
    if (origin && origin !== url.origin) return json({error:'Origin not allowed.'}, 403);
    const authorized = validSession(request, key, now) || equal(request.headers.get('authorization') || '', `Bearer ${code}`);
    if (path === '/demo-session') {
      if (request.method === 'GET') return json({authenticated: authorized}, authorized ? 200 : 401);
      if (request.method !== 'POST') return json({error:'Method not allowed.'}, 405);
      let body;
      try { body = JSON.parse(await boundedBody(request, 1024)); } catch { return json({error:'Invalid sign-in request.'}, 400); }
      if (typeof body?.code !== 'string' || !equal(body.code, code)) return json({error:'Incorrect demo code.'}, 401);
      const expires = String(Math.min(now + 8 * 60 * 60 * 1000, cutoff));
      return json({authenticated:true}, 200, {'Set-Cookie':`nse_demo=${expires}.${signature(expires,key)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${Math.floor((Number(expires)-now)/1000)}`});
    }
    if (!authorized) return json({error:'Sign in with the demo code to continue.'}, 401);
    const methods = {'/health':['GET'], '/search':['POST'], '/answer':['POST'], '/mcp':['POST','DELETE']};
    if (!methods[path]) return json({error:'Not found.'}, 404);
    if (!methods[path].includes(request.method)) return json({error:'Method not allowed.'}, 405);
    let base;
    try { base = new URL(env.NSE_BACKEND_URL); if (base.protocol !== 'https:' || base.username || base.password) throw new Error(); }
    catch { return json({error:'Demo backend is not configured.'}, 503); }
    let body;
    try { body = request.method === 'POST' ? await boundedBody(request) : undefined; }
    catch { return json({error:'Request exceeds 16 KiB.'}, 413); }
    const headers = new Headers({'Authorization':`Bearer ${key}`, 'Content-Type':'application/json', 'Accept':'application/json, text/event-stream'});
    for (const name of ['mcp-protocol-version','mcp-session-id']) {
      const value = request.headers.get(name); if (value) headers.set(name, value);
    }
    try {
      const response = await upstreamFetch(new URL(path, base), {method:request.method, headers, body,
        signal:AbortSignal.timeout(path === '/health' ? 8000 : 240000), redirect:'error'});
      if (response.status >= 500) return json({error:'The demo host is unavailable. Keep the host PC and demo launcher running.'}, 503);
      const contentType = response.headers.get('content-type') || '';
      if (response.status !== 202 && response.status !== 204 && !contentType.includes('application/json')) return json({error:'Unexpected response from demo host.'}, 502);
      const outgoing = new Headers({'Content-Type':'application/json', 'Cache-Control':'no-store'});
      for (const name of ['retry-after','mcp-session-id','mcp-protocol-version']) {
        const value = response.headers.get(name); if (value) outgoing.set(name, value);
      }
      return new Response([202,204].includes(response.status) ? null : response.body, {status:response.status, headers:outgoing});
    } catch { return json({error:'The demo host is offline or timed out. Please retry once it is running.'}, 503); }
  };
}
