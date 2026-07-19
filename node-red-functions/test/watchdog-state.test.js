const test = require('node:test');
const assert = require('node:assert/strict');
const { trackState, FIFTEEN_MIN, HOUR } = require('../watchdog-state.js');

test('healthy probe while ok stays ok, no action', () => {
  const r = trackState({ state: 'ok', notified: false, probeResult: 'healthy', isReprobe: false });
  assert.deepEqual(r, { state: 'ok', notified: false, action: 'none', intervalMs: FIFTEEN_MIN });
});

test('dead probe while ok triggers recovery, moves to recovering', () => {
  const r = trackState({ state: 'ok', notified: false, probeResult: 'dead', isReprobe: false });
  assert.deepEqual(r, { state: 'recovering', notified: false, action: 'recover', intervalMs: FIFTEEN_MIN });
});

test('dead probe while already failed (backoff) retries recovery again', () => {
  const r = trackState({ state: 'failed', notified: true, probeResult: 'dead', isReprobe: false });
  assert.deepEqual(r, { state: 'recovering', notified: true, action: 'recover', intervalMs: FIFTEEN_MIN });
});

test('reprobe after recovery attempt comes back healthy: notify recovered, reset notified, reset interval', () => {
  const r = trackState({ state: 'recovering', notified: false, probeResult: 'healthy', isReprobe: true });
  assert.deepEqual(r, { state: 'ok', notified: false, action: 'notifyRecovered', intervalMs: FIFTEEN_MIN });
});

test('reprobe still dead, first time: notify failed once, back off to hourly', () => {
  const r = trackState({ state: 'recovering', notified: false, probeResult: 'dead', isReprobe: true });
  assert.deepEqual(r, { state: 'failed', notified: true, action: 'notifyFailed', intervalMs: HOUR });
});

test('reprobe still dead, already notified this episode: no repeat notification', () => {
  const r = trackState({ state: 'failed', notified: true, probeResult: 'dead', isReprobe: true });
  assert.deepEqual(r, { state: 'failed', notified: true, action: 'none', intervalMs: HOUR });
});

test('unknown status (e.g. Telegram 500) while ok: no state change, no action', () => {
  const r = trackState({ state: 'ok', notified: false, probeResult: 'unknown', isReprobe: false });
  assert.deepEqual(r, { state: 'ok', notified: false, action: 'none', intervalMs: FIFTEEN_MIN });
});

test('unknown status while in failed backoff: stays in hourly backoff, no action', () => {
  const r = trackState({ state: 'failed', notified: true, probeResult: 'unknown', isReprobe: false });
  assert.deepEqual(r, { state: 'failed', notified: true, action: 'none', intervalMs: HOUR });
});
