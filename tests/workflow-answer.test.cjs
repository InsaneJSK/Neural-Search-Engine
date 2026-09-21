// Runs the actual embedded Code-node programs without live web/model calls.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const workflow = require('../workflows/nse-answer.json');
const programs = Object.fromEntries(workflow.nodes.filter(n => n.parameters.jsCode)
  .map(n => [n.name, new Function('$input', '$', n.parameters.jsCode)]));
const evidence = {query: 'test', results: [{source_id: 'S7', snippet: 'Evidence', title: 'Source', url: 'https://example.com'}]};
const run = (name, value, sources = evidence) => programs[name](
  {first: () => ({json: value})}, () => ({first: () => ({json: sources})}));
const response = content => ({done: true, done_reason: 'stop', model: 'qwen3:4b', message: {content}});

test('request uses schema-constrained generation and retains excerpts', () => {
  const body = run('Prepare answer request', evidence)[0].json;
  assert.deepEqual(body.format.required, ['answer']);
  assert.equal(body.format.additionalProperties, false);
  assert.equal(body.think, false);
  assert.ok(body.messages[1].content.includes('Evidence'));
});
test('oversized evidence is rejected before generation', () => {
  assert.throws(() => run('Prepare answer request', {...evidence, results: [{snippet: 'x'.repeat(15000)}]}), /context budget/);
});
test('truncation has an actionable error, including the screenshot failure', () => {
  assert.throws(() => run('Answer and evidence', {...response('unfinished'), done_reason: 'length'}), /output token limit/);
});
test('invalid JSON, incomplete responses, reasoning and empty answers fail', () => {
  for (const value of [response('not JSON'), {...response('{}'), done: false},
    response('{"answer":""}'), response('{"answer":"<think>draft</think>"}'), response('null')]) {
    assert.throws(() => run('Answer and evidence', value));
  }
});
test('citations must exist in the same evidence, including grouped citations', () => {
  for (const answer of ['Uncited fact.', 'Unknown [S9]', 'Mixed [S7, S99]']) {
    assert.throws(() => run('Answer and evidence', response(JSON.stringify({answer}))), /source/);
  }
});
test('valid answer retains the exact evidence object', () => {
  const value = run('Answer and evidence', response('{"answer":"Supported answer [S7]."}'))[0].json;
  assert.equal(value.answer, 'Supported answer [S7].');
  assert.strictEqual(value.evidence, evidence);
});
test('empty evidence accepts an explicit lack of evidence without citations', () => {
  const value = run('Answer and evidence', response('{"answer":"Not enough evidence to answer."}'), {query:'test',results:[]});
  assert.equal(value[0].json.evidence.results.length, 0);
});
