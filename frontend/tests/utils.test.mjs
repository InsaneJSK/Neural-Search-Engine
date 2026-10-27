import test from 'node:test';
import assert from 'node:assert/strict';
import {safeUrl, answerParts} from '../src/utils.mjs';

test('source links exclude executable and malformed URLs', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,hi', 'file:///private', '/relative', '']) assert.equal(safeUrl(value), null);
  assert.equal(safeUrl('https://example.com/source'), 'https://example.com/source');
});
test('only matching citation IDs become source navigation', () => {
  const parts = answerParts('A fact [S4, S2]. Another [S99]. <script>alert(1)</script>', ['S4', 'S2']);
  assert.deepEqual(parts[1].ids, ['S4', 'S2']);
  assert.deepEqual(parts[3], {text: '[S99]', ids: []});
  assert.equal(parts[4].text, '. <script>alert(1)</script>');
});
