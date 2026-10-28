import test from 'node:test';
import assert from 'node:assert/strict';
import {createDemoHandler} from '../server/demo.mjs';

const env = {NSE_API_TOKEN:'backend-secret', NSE_DEMO_EXPIRES_AT:'2030-01-01T00:00:00Z', NSE_BACKEND_URL:'https://example.trycloudflare.com'};
const request = (path, options={}) => new Request(`https://demo.example${path}`, options);
test('public requests reach the backend without a code or cookie', async () => {
  const handle=createDemoHandler(env, async () => Response.json({ok:true}));
  for (const path of ['/health','/search','/answer']) {
    const response=await handle(request(path, path === '/health' ? {} : {method:'POST',body:'{}'}));
    assert.equal(response.status,200);
    assert.equal(response.headers.get('set-cookie'),null);
  }
  assert.equal((await handle(request('/demo-session'))).status,404);
});
test('cutoff and missing backend credentials still fail closed', async () => {
  const never=() => {throw new Error('must not call');};
  assert.equal((await createDemoHandler(env,never,()=>2000000000000)(request('/health'))).status,410);
  assert.equal((await createDemoHandler({...env,NSE_API_TOKEN:''},never)(request('/health'))).status,503);
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
  const result=await handle(request('/api/demo?route=/mcp',{method:'POST',headers:{'mcp-protocol-version':'2025-06-18'},body:'{}'}));
  assert.deepEqual(await result.json(),{ok:true});
  assert.equal((await handle(request('/anything',{}))).status,404);
  assert.equal((await handle(request('/mcp',{}))).status,405);
  assert.equal((await handle(request('/search',{method:'POST',body:'x'.repeat(16385)}))).status,413);
});
test('cross-origin requests and upstream failures fail closed without exposing secrets', async () => {
  const handle=createDemoHandler(env,async () => {throw new Error('backend-secret');});
  assert.equal((await handle(request('/health',{headers:{origin:'https://evil.example'}}))).status,403);
  const failure=await handle(request('/health',{}));
  assert.equal(failure.status,503);
  assert.ok(!(await failure.text()).includes('backend-secret'));
});
