const test = require('node:test');
const assert = require('node:assert/strict');
const { buildProbeUrl, evaluateProbe } = require('../watchdog-probe.js');

test('buildProbeUrl embeds the token with timeout=0 and limit=1', () => {
  const url = buildProbeUrl('123:ABC');
  assert.equal(url, 'https://api.telegram.org/bot123:ABC/getUpdates?timeout=0&limit=1');
});

test('evaluateProbe: 409 Conflict means another poller holds the session (healthy)', () => {
  assert.equal(evaluateProbe(409), 'healthy');
});

test('evaluateProbe: 200 OK means no one holds the session (dead)', () => {
  assert.equal(evaluateProbe(200), 'dead');
});

test('evaluateProbe: any other status is unknown, not actionable', () => {
  assert.equal(evaluateProbe(500), 'unknown');
  assert.equal(evaluateProbe(401), 'unknown');
});
