import test from 'node:test';
import assert from 'node:assert/strict';
import {createDemoHandler} from '../server/demo.mjs';

const env = {NSE_API_TOKEN:'backend-secret', NSE_DEMO_CODE:'visitor-code', NSE_DEMO_EXPIRES_AT:'2030-01-01T00:00:00Z', NSE_BACKEND_URL:'https://example.trycloudflare.com'};
const request = (path, options={}) => new Request(`https://demo.example${path}`, options);
const auth = {Authorization:'Bearer visitor-code'};
test('anonymous requests never call the backend', async () => {
  const handle=createDemoHandler(env, () => {throw new Error('must not call');});
  assert.equal((await handle(request('/search',{method:'POST'}))).status,401);
  assert.equal((await handle(request('/demo-session',{method:'POST',body:JSON.stringify({code:'wrong'})}))).status,401);
});
test('login cookie authenticates; tampering and expiry are rejected', async () => {
  const handle=createDemoHandler(env, undefined, () => 1800000000000);
  const login=await handle(request('/demo-session',{method:'POST',body:JSON.stringify({code:env.NSE_DEMO_CODE})}));
  assert.equal(login.status,200);
  const cookie=login.headers.get('set-cookie');
  assert.match(cookie,/HttpOnly; Secure; SameSite=Strict/);
  assert.equal((await handle(request('/demo-session',{headers:{cookie}}))).status,200);
  assert.equal((await handle(request('/demo-session',{headers:{cookie:cookie.replace('nse_demo=','nse_demo=0')}}))).status,401);
  assert.equal((await createDemoHandler(env,undefined,()=>2000000000000)(request('/health',{headers:auth}))).status,410);
});
test('proxy uses only fixed paths and the server secret, preserving MCP metadata', async () => {
  const handle=createDemoHandler(env, async (url, options) => {
    assert.equal(url.href,'https://example.trycloudflare.com/mcp');
    assert.equal(options.headers.get('authorization'),'Bearer backend-secret');
    assert.equal(options.headers.get('cookie'),null);
    assert.equal(options.headers.get('origin'),null);
    assert.equal(options.headers.get('mcp-protocol-version'),'2025-06-18');
    return Response.json({ok:true});
  });
  const result=await handle(request('/api/demo?route=/mcp',{method:'POST',headers:{...auth,'mcp-protocol-version':'2025-06-18'},body:'{}'}));
  assert.deepEqual(await result.json(),{ok:true});
  assert.equal((await handle(request('/anything',{headers:auth}))).status,404);
  assert.equal((await handle(request('/mcp',{headers:auth}))).status,405);
  assert.equal((await handle(request('/search',{method:'POST',headers:auth,body:'x'.repeat(16385)}))).status,413);
});
test('cross-origin requests and upstream failures fail closed without exposing secrets', async () => {
  const handle=createDemoHandler(env,async () => {throw new Error('backend-secret');});
  assert.equal((await handle(request('/health',{headers:{...auth,origin:'https://evil.example'}}))).status,403);
  const failure=await handle(request('/health',{headers:auth}));
  assert.equal(failure.status,503);
  assert.ok(!(await failure.text()).includes('backend-secret'));
});
