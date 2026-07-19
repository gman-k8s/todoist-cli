# Telegram Bridge Watchdog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect a silently-hung Telegram long-poll in the Node-RED bridge, auto-recover it by toggling just the bot node, and notify the user (Telegram on success, HA app push on failure).

**Architecture:** A new "Watchdog" tab in `node-red-telegram-bridge.json` runs a self-scheduling timer that actively probes Telegram's `getUpdates` endpoint (409 = healthy, 200 = dead — Telegram only allows one long-poll session per token, so this is a definitive signal, not a heuristic). On a dead reading it uses Node-RED's local Admin API to disable and re-enable the `tb_bot_cfg` node, re-probes, and fires an HA event reporting success or failure. Two new HA automations turn those events into a Telegram message (success) or an `notify.aiden_2` push (failure — Telegram may still be down in that case). The tricky state-machine and HTTP-status logic is extracted into small, unit-tested plain JS files before being inlined into the Node-RED function nodes (Node-RED's sandboxed functions can't `require()` local project files, so the tested source and the deployed copy are kept in sync by hand — each embedding step says exactly what to copy).

**Tech Stack:** Node-RED flow JSON (hand-authored, matches existing repo convention), Node.js built-in test runner (`node --test`, no new dependencies — Node 26 is already on this machine), Home Assistant automations via the `ha_config_set_automation` MCP tool.

## Global Constraints

- Full design is `docs/superpowers/specs/2026-07-19-telegram-bridge-watchdog-design.md` — every task below implements a section of it.
- Node-RED Admin API has no `adminAuth` configured (confirmed with user) — no credentials needed in the toggle requests.
- Recovery must touch only the `tb_bot_cfg` node — no other flow/tab may be disabled or redeployed.
- Probe interval: 15 minutes normally, backs off to 60 minutes after a failed recovery attempt, resets to 15 minutes once healthy again.
- Failure notification fires at most once per failure episode (no repeat spam on every hourly retry).
- Recovery success → Telegram message via `rest_command.telegram_send` to chat_id `-1003579017248` (existing group chat, per `automation.telegram_smart_router`). Recovery failure → `notify.aiden_2` push (the only `notify.*` entity currently registered in this HA instance).
- `node-red-telegram-bridge.json` must remain valid JSON after every edit — validate with `python3 -m json.tool node-red-telegram-bridge.json > /dev/null` after every step that touches it.

---

### Task 1: Share Telegram/Gemini tokens across tabs (global context)

**Problem:** `tb_set_vars` (existing "Set Tokens" function, `node-red-telegram-bridge.json:46-60`) currently calls `flow.set(...)`. Node-RED's `flow` context is scoped per-tab. The new Watchdog tab is a separate tab and needs `telegram_token` to build its probe URL, so the token must move to `global` context, which is shared across all tabs.

**Files:**
- Modify: `node-red-telegram-bridge.json` (5 call sites: `tb_set_vars`, `tb_callback_event`, `tb_voice_prep`, `tb_prep_gemini` — 3 reads there)

**Interfaces:**
- Produces: `global.get('telegram_token')`, `global.get('gemini_api_key')`, `global.get('gemini_model')` — used by Task 5's `wd_build_url` node.

- [ ] **Step 1: Confirm current call sites**

Run: `grep -n "flow\.\(get\|set\)('telegram_token'\|'gemini_api_key'\|'gemini_model'" node-red-telegram-bridge.json`

Expected output (5 lines, one per call site — line numbers may shift slightly but these are the current ones):
```
50:        "func": "// ===== TODO: Enter your keys here =====\nflow.set('telegram_token', 'YOUR_TELEGRAM_BOT_TOKEN');\nflow.set('gemini_api_key', 'YOUR_GOOGLE_API_KEY');\nflow.set('gemini_model', 'gemini-3.1-flash-lite-preview');\n...
114:        "func": "...const token = flow.get('telegram_token');...
197:        "func": "...const token = flow.get('telegram_token');...
269:        "func": "...const apiKey = flow.get('gemini_api_key');\nconst model = flow.get('gemini_model')...
```

- [ ] **Step 2: Edit `tb_set_vars` (line ~50) to use `global.set`**

Using the Edit tool on `node-red-telegram-bridge.json`, in the `func` string of the node with `"id": "tb_set_vars"`, change:
```
flow.set('telegram_token', 'YOUR_TELEGRAM_BOT_TOKEN');\nflow.set('gemini_api_key', 'YOUR_GOOGLE_API_KEY');\nflow.set('gemini_model', 'gemini-3.1-flash-lite-preview');
```
to:
```
global.set('telegram_token', 'YOUR_TELEGRAM_BOT_TOKEN');\nglobal.set('gemini_api_key', 'YOUR_GOOGLE_API_KEY');\nglobal.set('gemini_model', 'gemini-3.1-flash-lite-preview');
```

- [ ] **Step 3: Edit `tb_callback_event` (line ~114) read site**

In that node's `func` string, change `const token = flow.get('telegram_token');` to `const token = global.get('telegram_token');`.

- [ ] **Step 4: Edit `tb_voice_prep` (line ~197) read site**

Same change: `const token = flow.get('telegram_token');` → `const token = global.get('telegram_token');`.

- [ ] **Step 5: Edit `tb_prep_gemini` (line ~269) read sites**

In that node's `func` string, change:
```
const apiKey = flow.get('gemini_api_key');\nconst model = flow.get('gemini_model') || 'gemini-2.0-flash-lite';
```
to:
```
const apiKey = global.get('gemini_api_key');\nconst model = global.get('gemini_model') || 'gemini-2.0-flash-lite';
```

- [ ] **Step 6: Validate JSON and confirm no `flow.get`/`flow.set` remain for these three keys**

Run:
```bash
python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo "valid json"
grep -c "flow\.\(get\|set\)('telegram_token'\|'gemini_api_key'\|'gemini_model'" node-red-telegram-bridge.json
```
Expected: `valid json` printed, and the grep count is `0`.

`tb_voice_prep`'s unrelated `flow.set('voice_meta', ...)` / `tb_parse_stt`'s `flow.get('voice_meta')` stay as `flow.*` — that's tab-local pipeline state, not a token, and doesn't need cross-tab access. Confirm they're untouched:

Run: `grep -n "voice_meta" node-red-telegram-bridge.json`
Expected: 2 matches, both still using `flow.set`/`flow.get`.

- [ ] **Step 7: Commit**

```bash
git add node-red-telegram-bridge.json
git commit -m "Switch Telegram/Gemini tokens to global context

Watchdog tab (next commits) needs cross-tab access to telegram_token;
flow context is scoped per-tab so global is required."
```

---

### Task 2: Probe logic — `buildProbeUrl` and `evaluateProbe`

**Files:**
- Create: `node-red-functions/watchdog-probe.js`
- Test: `node-red-functions/test/watchdog-probe.test.js`

**Interfaces:**
- Produces: `buildProbeUrl(token: string): string`, `evaluateProbe(statusCode: number): 'healthy' | 'dead' | 'unknown'` — logic copied into the `wd_build_url` and `wd_evaluate` Node-RED function nodes in Task 5.

- [ ] **Step 1: Write the failing test**

Create `node-red-functions/test/watchdog-probe.test.js`:
```javascript
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test node-red-functions/test/watchdog-probe.test.js`
Expected: FAIL — `Cannot find module '../watchdog-probe.js'`

- [ ] **Step 3: Write minimal implementation**

Create `node-red-functions/watchdog-probe.js`:
```javascript
function buildProbeUrl(token) {
    return `https://api.telegram.org/bot${token}/getUpdates?timeout=0&limit=1`;
}

function evaluateProbe(statusCode) {
    if (statusCode === 409) return 'healthy';
    if (statusCode === 200) return 'dead';
    return 'unknown';
}

module.exports = { buildProbeUrl, evaluateProbe };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test node-red-functions/test/watchdog-probe.test.js`
Expected: PASS, 4 tests passing, 0 failing.

- [ ] **Step 5: Commit**

```bash
git add node-red-functions/watchdog-probe.js node-red-functions/test/watchdog-probe.test.js
git commit -m "Add tested probe logic for Telegram watchdog

getUpdates returns 409 if Node-RED's long-poll still holds the
session, 200 if it's died. buildProbeUrl/evaluateProbe will be
inlined into the Watchdog flow's function nodes."
```

---

### Task 3: State machine — `trackState`

**Files:**
- Create: `node-red-functions/watchdog-state.js`
- Test: `node-red-functions/test/watchdog-state.test.js`

**Interfaces:**
- Consumes: nothing (pure function, no dependency on Task 2's module).
- Produces: `trackState({state, notified, probeResult, isReprobe}): {state, notified, action, intervalMs}` where `state` is `'ok' | 'recovering' | 'failed'` and `action` is `'none' | 'recover' | 'notifyRecovered' | 'notifyFailed'`. Copied into the `wd_state` Node-RED function node in Task 5.

- [ ] **Step 1: Write the failing test**

Create `node-red-functions/test/watchdog-state.test.js`:
```javascript
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test node-red-functions/test/watchdog-state.test.js`
Expected: FAIL — `Cannot find module '../watchdog-state.js'`

- [ ] **Step 3: Write minimal implementation**

Create `node-red-functions/watchdog-state.js`:
```javascript
const FIFTEEN_MIN = 15 * 60 * 1000;
const HOUR = 60 * 60 * 1000;

function trackState({ state, notified, probeResult, isReprobe }) {
    if (probeResult === 'unknown') {
        return { state, notified, action: 'none', intervalMs: state === 'failed' ? HOUR : FIFTEEN_MIN };
    }

    if (!isReprobe) {
        if (probeResult === 'healthy') {
            return { state: 'ok', notified: false, action: 'none', intervalMs: FIFTEEN_MIN };
        }
        return { state: 'recovering', notified, action: 'recover', intervalMs: FIFTEEN_MIN };
    }

    // isReprobe === true: this probe follows a recovery attempt
    if (probeResult === 'healthy') {
        return { state: 'ok', notified: false, action: 'notifyRecovered', intervalMs: FIFTEEN_MIN };
    }
    if (notified) {
        return { state: 'failed', notified: true, action: 'none', intervalMs: HOUR };
    }
    return { state: 'failed', notified: true, action: 'notifyFailed', intervalMs: HOUR };
}

module.exports = { trackState, FIFTEEN_MIN, HOUR };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test node-red-functions/test/watchdog-state.test.js`
Expected: PASS, 8 tests passing, 0 failing.

- [ ] **Step 5: Commit**

```bash
git add node-red-functions/watchdog-state.js node-red-functions/test/watchdog-state.test.js
git commit -m "Add tested watchdog state machine

Encodes the ok/recovering/failed transitions, the notify-once rule,
and the 15min/60min backoff. trackState will be inlined into the
Watchdog flow's Track State function node."
```

---

### Task 4: Node toggle logic — `setNodeDisabled`

**Files:**
- Create: `node-red-functions/watchdog-toggle.js`
- Test: `node-red-functions/test/watchdog-toggle.test.js`

**Interfaces:**
- Produces: `setNodeDisabled(nodes: object[], targetId: string, disabled: boolean): object[]` — returns a new array, does not mutate the input. Copied into the `wd_toggle_off` / `wd_toggle_on` Node-RED function nodes in Task 5.

- [ ] **Step 1: Write the failing test**

Create `node-red-functions/test/watchdog-toggle.test.js`:
```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const { setNodeDisabled } = require('../watchdog-toggle.js');

const sampleNodes = [
  { id: 'tb_bot_cfg', type: 'telegram bot', botname: 'Mia' },
  { id: 'tb_rx', type: 'telegram receiver', bot: 'tb_bot_cfg' },
];

test('sets d:true on the matching node, leaves others untouched', () => {
  const result = setNodeDisabled(sampleNodes, 'tb_bot_cfg', true);
  assert.equal(result.find(n => n.id === 'tb_bot_cfg').d, true);
  assert.equal(result.find(n => n.id === 'tb_rx').d, undefined);
});

test('sets d:false on the matching node', () => {
  const result = setNodeDisabled(sampleNodes, 'tb_bot_cfg', false);
  assert.equal(result.find(n => n.id === 'tb_bot_cfg').d, false);
});

test('does not mutate the input array or its objects', () => {
  const before = JSON.stringify(sampleNodes);
  setNodeDisabled(sampleNodes, 'tb_bot_cfg', true);
  assert.equal(JSON.stringify(sampleNodes), before);
});

test('unknown target id leaves all nodes unchanged', () => {
  const result = setNodeDisabled(sampleNodes, 'does_not_exist', true);
  assert.equal(result.every(n => n.d === undefined), true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test node-red-functions/test/watchdog-toggle.test.js`
Expected: FAIL — `Cannot find module '../watchdog-toggle.js'`

- [ ] **Step 3: Write minimal implementation**

Create `node-red-functions/watchdog-toggle.js`:
```javascript
function setNodeDisabled(nodes, targetId, disabled) {
    return nodes.map(n => n.id === targetId ? Object.assign({}, n, { d: disabled }) : n);
}

module.exports = { setNodeDisabled };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test node-red-functions/test/watchdog-toggle.test.js`
Expected: PASS, 4 tests passing, 0 failing.

- [ ] **Step 5: Commit**

```bash
git add node-red-functions/watchdog-toggle.js node-red-functions/test/watchdog-toggle.test.js
git commit -m "Add tested node-disable toggle for watchdog recovery

setNodeDisabled builds the mutated node array used in the Admin API
PUT body that disables/re-enables tb_bot_cfg."
```

---

### Task 5: Wire the Watchdog tab into the Node-RED flow

This task embeds the three tested modules from Tasks 2-4 as inline function-node
code (Node-RED's sandboxed functions can't `require()` local files) and adds
the timer/probe/recovery/notify plumbing around them. Every step ends with a
JSON-validity check; there's no way to unit-test Node-RED wiring itself
outside a running Node-RED instance, so Task 7 covers live verification.

**Files:**
- Modify: `node-red-telegram-bridge.json` (append 17 new nodes + 1 new tab)

**Interfaces:**
- Consumes: `global.get('telegram_token')` (Task 1). `tb_bot_cfg` node id (existing, `node-red-telegram-bridge.json:10`).
- Produces: HA events `telegram_bridge_recovered` and `telegram_bridge_recovery_failed`, consumed by Task 6's automations.

- [ ] **Step 1: Add the Watchdog tab**

Using the Edit tool, insert a new tab object right after the existing `tb_flow` tab (after line 8, before the `tb_bot_cfg` node starts at line 9):

```json
    {
        "id": "tb_watchdog",
        "type": "tab",
        "label": "Watchdog",
        "disabled": false,
        "info": "Detects a silently-hung Telegram long-poll (getUpdates 200 = no one holds the session = dead; 409 = someone does = healthy) and recovers by toggling tb_bot_cfg via the Node-RED Admin API. Fires telegram_bridge_recovered / telegram_bridge_recovery_failed HA events.\n\nRequires Node-RED Admin API reachable at http://localhost:1880 with no adminAuth."
    },
```

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 2: Add `wd_timer` (self-scheduling probe trigger)**

Append at the end of the array (before the closing `]` on the last line), as the first node of the new tab:

```json
    ,{
        "id": "wd_timer",
        "type": "function",
        "z": "tb_watchdog",
        "name": "Self-Scheduling Timer",
        "func": "return null;",
        "outputs": 1,
        "timeout": "",
        "noerr": 0,
        "initialize": "function scheduleNext() {\n    const interval = flow.get('watchdog_interval_ms') || 15 * 60 * 1000;\n    const t = setTimeout(() => {\n        node.send({ payload: {}, topic: 'probe' });\n        scheduleNext();\n    }, interval);\n    context.set('timer', t);\n}\nscheduleNext();",
        "finalize": "const t = context.get('timer');\nif (t) { clearTimeout(t); }",
        "libs": [],
        "x": 130,
        "y": 80,
        "wires": [["wd_build_url"]]
    }
```

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 3: Add `wd_build_url` (inlines `buildProbeUrl` from Task 2)**

Append after `wd_timer`:

```json
    ,{
        "id": "wd_build_url",
        "type": "function",
        "z": "tb_watchdog",
        "name": "Build Probe URL",
        "func": "const token = global.get('telegram_token');\nmsg.url = `https://api.telegram.org/bot${token}/getUpdates?timeout=0&limit=1`;\nmsg.method = 'GET';\nreturn msg;",
        "outputs": 1,
        "timeout": "",
        "noerr": 0,
        "initialize": "",
        "finalize": "",
        "libs": [],
        "x": 340,
        "y": 80,
        "wires": [["wd_probe"]]
    }
```

Confirm the URL template matches `node-red-functions/watchdog-probe.js`'s `buildProbeUrl` exactly (same path, same query string) — this hand-copy is the one place drift could sneak in.

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 4: Add `wd_probe` (http request)**

```json
    ,{
        "id": "wd_probe",
        "type": "http request",
        "z": "tb_watchdog",
        "name": "getUpdates Probe",
        "method": "GET",
        "ret": "obj",
        "paytoqs": "ignore",
        "url": "",
        "tls": "",
        "persist": false,
        "proxy": "",
        "insecureHTTPParser": false,
        "authType": "",
        "senderr": false,
        "headers": [],
        "x": 560,
        "y": 80,
        "wires": [["wd_evaluate"]]
    }
```

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 5: Add `wd_evaluate` (inlines `evaluateProbe` from Task 2) and `wd_debug_probe`**

```json
    ,{
        "id": "wd_evaluate",
        "type": "function",
        "z": "tb_watchdog",
        "name": "Evaluate Probe",
        "func": "const code = msg.statusCode;\nlet result;\nif (code === 409) {\n    result = 'healthy';\n} else if (code === 200) {\n    result = 'dead';\n} else {\n    result = 'unknown';\n}\nmsg.probeResult = result;\nreturn msg;",
        "outputs": 1,
        "timeout": "",
        "noerr": 0,
        "initialize": "",
        "finalize": "",
        "libs": [],
        "x": 780,
        "y": 80,
        "wires": [["wd_state", "wd_debug_probe"]]
    },
    {
        "id": "wd_debug_probe",
        "type": "debug",
        "z": "tb_watchdog",
        "name": "Probe Result",
        "active": true,
        "tosidebar": true,
        "console": false,
        "tostatus": true,
        "complete": "probeResult",
        "targetType": "msg",
        "statusVal": "probeResult",
        "statusType": "msg",
        "x": 780,
        "y": 160,
        "wires": []
    }
```

Confirm the if/else branches match `evaluateProbe` in `node-red-functions/watchdog-probe.js` exactly (409→healthy, 200→dead, else→unknown).

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 6: Add `wd_state` (inlines `trackState` from Task 3)**

```json
    ,{
        "id": "wd_state",
        "type": "function",
        "z": "tb_watchdog",
        "name": "Track State",
        "func": "const FIFTEEN_MIN = 15 * 60 * 1000;\nconst HOUR = 60 * 60 * 1000;\n\nconst state = flow.get('watchdog_state') || 'ok';\nconst notified = flow.get('watchdog_notified') || false;\nconst probeResult = msg.probeResult;\nconst isReprobe = msg.topic === 'reprobe';\n\nlet next;\nif (probeResult === 'unknown') {\n    next = { state, notified, action: 'none', intervalMs: state === 'failed' ? HOUR : FIFTEEN_MIN };\n} else if (!isReprobe) {\n    if (probeResult === 'healthy') {\n        next = { state: 'ok', notified: false, action: 'none', intervalMs: FIFTEEN_MIN };\n    } else {\n        next = { state: 'recovering', notified, action: 'recover', intervalMs: FIFTEEN_MIN };\n    }\n} else if (probeResult === 'healthy') {\n    next = { state: 'ok', notified: false, action: 'notifyRecovered', intervalMs: FIFTEEN_MIN };\n} else if (notified) {\n    next = { state: 'failed', notified: true, action: 'none', intervalMs: HOUR };\n} else {\n    next = { state: 'failed', notified: true, action: 'notifyFailed', intervalMs: HOUR };\n}\n\nflow.set('watchdog_state', next.state);\nflow.set('watchdog_notified', next.notified);\nflow.set('watchdog_interval_ms', next.intervalMs);\n\nnode.status({ fill: next.state === 'ok' ? 'green' : (next.state === 'recovering' ? 'yellow' : 'red'), shape: 'dot', text: `${next.state} (${probeResult})` });\n\nconst recoverMsg = next.action === 'recover' ? msg : null;\nconst recoveredMsg = next.action === 'notifyRecovered' ? { payload: {} } : null;\nconst failedMsg = next.action === 'notifyFailed' ? { payload: {} } : null;\nreturn [recoverMsg, recoveredMsg, failedMsg];",
        "outputs": 3,
        "timeout": "",
        "noerr": 0,
        "initialize": "",
        "finalize": "",
        "libs": [],
        "x": 1000,
        "y": 80,
        "wires": [["wd_get_flow"], ["wd_fire_recovered"], ["wd_fire_failed"]]
    }
```

Confirm this function's branching matches `trackState` in `node-red-functions/watchdog-state.js` transition-for-transition (compare against the 8 test cases in Task 3).

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 7: Add `wd_get_flow` (fetch current tb_flow tab from Admin API)**

```json
    ,{
        "id": "wd_get_flow",
        "type": "http request",
        "z": "tb_watchdog",
        "name": "GET /flow/tb_flow",
        "method": "GET",
        "ret": "obj",
        "paytoqs": "ignore",
        "url": "http://localhost:1880/flow/tb_flow",
        "tls": "",
        "persist": false,
        "proxy": "",
        "insecureHTTPParser": false,
        "authType": "",
        "senderr": false,
        "headers": [],
        "x": 1000,
        "y": 160,
        "wires": [["wd_toggle_off"]]
    }
```

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 8: Add `wd_toggle_off` (inlines `setNodeDisabled` from Task 4, disable direction)**

```json
    ,{
        "id": "wd_toggle_off",
        "type": "function",
        "z": "tb_watchdog",
        "name": "Disable Bot Node",
        "func": "const flowDef = msg.payload;\nconst origNodes = flowDef.nodes;\nmsg.origNodes = origNodes;\nmsg.flowId = flowDef.id;\nmsg.flowLabel = flowDef.label;\n\nconst toggled = origNodes.map(n => n.id === 'tb_bot_cfg' ? Object.assign({}, n, { d: true }) : n);\n\nmsg.url = 'http://localhost:1880/flow/tb_flow';\nmsg.method = 'PUT';\nmsg.headers = { 'Content-Type': 'application/json' };\nmsg.payload = { id: flowDef.id, label: flowDef.label, nodes: toggled };\nreturn msg;",
        "outputs": 1,
        "timeout": "",
        "noerr": 0,
        "initialize": "",
        "finalize": "",
        "libs": [],
        "x": 1000,
        "y": 220,
        "wires": [["wd_put_off"]]
    }
```

The `Object.assign({}, n, { d: true })` map matches `setNodeDisabled(origNodes, 'tb_bot_cfg', true)` from `node-red-functions/watchdog-toggle.js`. `msg.origNodes` stashes the pre-toggle array so `wd_toggle_on` (Step 11) can flip it back without a second GET.

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 9: Add `wd_put_off` (http request PUT)**

```json
    ,{
        "id": "wd_put_off",
        "type": "http request",
        "z": "tb_watchdog",
        "name": "PUT disable",
        "method": "PUT",
        "ret": "obj",
        "paytoqs": "ignore",
        "url": "",
        "tls": "",
        "persist": false,
        "proxy": "",
        "insecureHTTPParser": false,
        "authType": "",
        "senderr": false,
        "headers": [],
        "x": 1000,
        "y": 280,
        "wires": [["wd_delay"]]
    }
```

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 10: Add `wd_delay` (3s pause before re-enabling)**

```json
    ,{
        "id": "wd_delay",
        "type": "delay",
        "z": "tb_watchdog",
        "name": "3s",
        "pauseType": "delay",
        "timeout": "3",
        "timeoutUnits": "seconds",
        "rate": "1",
        "nbRateUnits": "1",
        "rateUnits": "second",
        "randomFirst": "1",
        "randomLast": "5",
        "randomUnits": "seconds",
        "drop": false,
        "allowrate": false,
        "outputs": 1,
        "x": 1000,
        "y": 340,
        "wires": [["wd_toggle_on"]]
    }
```

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 11: Add `wd_toggle_on` (inlines `setNodeDisabled`, re-enable direction)**

```json
    ,{
        "id": "wd_toggle_on",
        "type": "function",
        "z": "tb_watchdog",
        "name": "Re-enable Bot Node",
        "func": "const origNodes = msg.origNodes;\nconst toggled = origNodes.map(n => n.id === 'tb_bot_cfg' ? Object.assign({}, n, { d: false }) : n);\n\nmsg.url = 'http://localhost:1880/flow/tb_flow';\nmsg.method = 'PUT';\nmsg.headers = { 'Content-Type': 'application/json' };\nmsg.payload = { id: msg.flowId, label: msg.flowLabel, nodes: toggled };\nreturn msg;",
        "outputs": 1,
        "timeout": "",
        "noerr": 0,
        "initialize": "",
        "finalize": "",
        "libs": [],
        "x": 1000,
        "y": 400,
        "wires": [["wd_put_on"]]
    }
```

Matches `setNodeDisabled(origNodes, 'tb_bot_cfg', false)`.

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 12: Add `wd_put_on` (http request PUT)**

```json
    ,{
        "id": "wd_put_on",
        "type": "http request",
        "z": "tb_watchdog",
        "name": "PUT re-enable",
        "method": "PUT",
        "ret": "obj",
        "paytoqs": "ignore",
        "url": "",
        "tls": "",
        "persist": false,
        "proxy": "",
        "insecureHTTPParser": false,
        "authType": "",
        "senderr": false,
        "headers": [],
        "x": 1000,
        "y": 460,
        "wires": [["wd_delay2"]]
    }
```

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 13: Add `wd_delay2` (30s pause before verifying recovery) and `wd_set_reprobe`**

```json
    ,{
        "id": "wd_delay2",
        "type": "delay",
        "z": "tb_watchdog",
        "name": "30s",
        "pauseType": "delay",
        "timeout": "30",
        "timeoutUnits": "seconds",
        "rate": "1",
        "nbRateUnits": "1",
        "rateUnits": "second",
        "randomFirst": "1",
        "randomLast": "5",
        "randomUnits": "seconds",
        "drop": false,
        "allowrate": false,
        "outputs": 1,
        "x": 1000,
        "y": 520,
        "wires": [["wd_set_reprobe"]]
    },
    {
        "id": "wd_set_reprobe",
        "type": "function",
        "z": "tb_watchdog",
        "name": "Mark Reprobe",
        "func": "msg.topic = 'reprobe';\nreturn msg;",
        "outputs": 1,
        "timeout": "",
        "noerr": 0,
        "initialize": "",
        "finalize": "",
        "libs": [],
        "x": 1000,
        "y": 580,
        "wires": [["wd_build_url"]]
    }
```

This wires back into `wd_build_url` (Step 3) — the same probe → evaluate → state path handles both the initial timer-driven probe and the post-recovery reprobe; `wd_state` tells them apart via `msg.topic === 'reprobe'`.

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 14: Add `wd_fire_recovered`, `wd_fire_failed`, `wd_debug`**

```json
    ,{
        "id": "wd_fire_recovered",
        "type": "ha-fire-event",
        "z": "tb_watchdog",
        "name": "Fire telegram_bridge_recovered",
        "server": "",
        "version": 2,
        "event": "telegram_bridge_recovered",
        "data": "payload",
        "dataType": "jsonata",
        "x": 1260,
        "y": 80,
        "wires": [["wd_debug"]]
    },
    {
        "id": "wd_fire_failed",
        "type": "ha-fire-event",
        "z": "tb_watchdog",
        "name": "Fire telegram_bridge_recovery_failed",
        "server": "",
        "version": 2,
        "event": "telegram_bridge_recovery_failed",
        "data": "payload",
        "dataType": "jsonata",
        "x": 1280,
        "y": 140,
        "wires": [["wd_debug"]]
    },
    {
        "id": "wd_debug",
        "type": "debug",
        "z": "tb_watchdog",
        "name": "Watchdog Events",
        "active": true,
        "tosidebar": true,
        "console": false,
        "tostatus": false,
        "complete": "true",
        "targetType": "full",
        "statusVal": "",
        "statusType": "auto",
        "x": 1500,
        "y": 110,
        "wires": []
    }
```

Validate: `python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo valid`

- [ ] **Step 15: Full-file sanity check**

Run:
```bash
python3 -m json.tool node-red-telegram-bridge.json > /dev/null && echo "valid json"
python3 -c "
import json
nodes = json.load(open('node-red-telegram-bridge.json'))
ids = [n['id'] for n in nodes]
assert len(ids) == len(set(ids)), 'duplicate node id found'
watchdog_ids = {n['id'] for n in nodes if n.get('z') == 'tb_watchdog'}
expected = {'wd_timer','wd_build_url','wd_probe','wd_evaluate','wd_debug_probe','wd_state',
            'wd_get_flow','wd_toggle_off','wd_put_off','wd_delay','wd_toggle_on','wd_put_on',
            'wd_delay2','wd_set_reprobe','wd_fire_recovered','wd_fire_failed','wd_debug'}
assert watchdog_ids == expected, f'missing/extra: {expected ^ watchdog_ids}'
print('all 17 watchdog nodes present, no duplicate ids')
"
```
Expected: `valid json` then `all 17 watchdog nodes present, no duplicate ids`.

- [ ] **Step 16: Commit**

```bash
git add node-red-telegram-bridge.json
git commit -m "Add Watchdog tab: detect and auto-recover hung Telegram poll

Self-scheduling timer probes getUpdates every 15min (409=healthy,
200=dead — Telegram allows only one poller per token). On dead,
toggles tb_bot_cfg off/on via the local Admin API, re-probes, and
fires telegram_bridge_recovered / telegram_bridge_recovery_failed.
Backs off to hourly retries after a failed recovery; notifies once
per failure episode. Logic matches the tested node-red-functions/
modules — see docs/superpowers/specs/2026-07-19-telegram-bridge-watchdog-design.md."
```

---

### Task 6: HA automations for recovery notifications

**Files:** None local — this task makes live calls against the running HA instance via MCP tools.

**Interfaces:**
- Consumes: HA events `telegram_bridge_recovered` / `telegram_bridge_recovery_failed` (fired by Task 5's `wd_fire_recovered` / `wd_fire_failed`).

- [ ] **Step 1: Read the HA best-practices skill and get the attestation key**

`ha_config_set_automation` requires a `BestPracticeKey` read-receipt. Read it via:
```
ReadMcpResourceTool(server="claude_ai_Homeassistant", uri="skill://home-assistant-best-practices/SKILL.md")
```
If that 502s (seen intermittently earlier in this session), retry once, then fall back to `ha_get_skill_guide`. Note the attestation phrase from the top of the returned content for use in Steps 2 and 3.

- [ ] **Step 2: Create `automation.telegram_bridge_recovered`**

Call `ha_config_set_automation` with:
```json
{
  "config": {
    "alias": "Telegram: Bridge Recovered",
    "description": "Watchdog (Node-RED) auto-recovered a hung Telegram long-poll. Notify via Telegram since it's confirmed working again.",
    "triggers": [
      {"trigger": "event", "event_type": "telegram_bridge_recovered"}
    ],
    "actions": [
      {
        "action": "rest_command.telegram_send",
        "data": {
          "chat_id": "-1003579017248",
          "message": "🔄 Bot auto-recovered from stuck polling."
        }
      }
    ],
    "mode": "single"
  },
  "BestPracticeKey": "<attestation phrase from Step 1>"
}
```

- [ ] **Step 3: Create `automation.telegram_bridge_recovery_failed`**

Call `ha_config_set_automation` with:
```json
{
  "config": {
    "alias": "Telegram: Bridge Recovery Failed",
    "description": "Watchdog (Node-RED) tried to recover a hung Telegram long-poll and it's still dead. Telegram itself may be unreachable, so notify via HA app push instead.",
    "triggers": [
      {"trigger": "event", "event_type": "telegram_bridge_recovery_failed"}
    ],
    "actions": [
      {
        "action": "notify.aiden_2",
        "data": {
          "title": "Todoist Bot",
          "message": "⚠️ Telegram bridge stuck, auto-recovery failed — needs manual reconnect in Node-RED."
        }
      }
    ],
    "mode": "single"
  },
  "BestPracticeKey": "<attestation phrase from Step 1>"
}
```

- [ ] **Step 4: Verify both automations**

Call `ha_config_get_automation("automation.telegram_bridge_recovered")` and `ha_config_get_automation("automation.telegram_bridge_recovery_failed")`.
Expected: each returns `"success": true` with `triggers`/`actions` matching what was submitted in Steps 2/3.

No git commit — this task only changes live HA config, not files in this repo.

---

### Task 7: Deploy and manually verify end-to-end

Node-RED flow changes only take effect once imported/deployed in the Node-RED editor — there's no remote deploy API used elsewhere in this repo's workflow, so this step is manual, same as the existing bridge file's own setup instructions.

**Files:** None (verification only).

- [ ] **Step 1: Import the updated flow**

In the Node-RED editor: Menu → Import → select the updated `node-red-telegram-bridge.json` → import into the existing tabs (this updates "Telegram Bridge" and adds the new "Watchdog" tab) → Deploy.

- [ ] **Step 2: Confirm the watchdog is ticking**

Open the "Watchdog" tab's debug sidebar. Within 15 minutes (or trigger `wd_timer` manually once by wiring a temporary inject node to `wd_build_url` and clicking it, then removing the inject node), confirm the "Probe Result" debug entry shows `healthy` (since the real bot connection is up at this point) and `wd_state`'s status pill under "Track State" shows `ok (healthy)`.

- [ ] **Step 3: Simulate a stuck poller and confirm recovery**

In the Node-RED editor, manually disable the `tb_bot_cfg` config node (right-click → disable), which stops Node-RED's own poll — mimicking the hang without needing to wait for a real one. Trigger `wd_timer` once manually (temporary inject node into `wd_build_url`, as in Step 2). Confirm, in order:
1. "Probe Result" debug shows `dead`.
2. `wd_state` status pill shows `recovering (dead)`.
3. Within ~3s, the Admin API calls fire (visible as `wd_put_off`/`wd_put_on` entries if their outputs are tapped, or confirm indirectly via Step 4).
4. `tb_bot_cfg` becomes re-enabled automatically (check its right-click menu no longer offers "Enable").
5. ~30s later, "Watchdog Events" debug shows a `telegram_bridge_recovered` event fire.
6. A Telegram message "🔄 Bot auto-recovered from stuck polling." arrives in the group chat.

- [ ] **Step 4: Confirm the failure-notification path**

This is harder to simulate without genuinely breaking Telegram connectivity — acceptable to verify only that the automation itself works, independent of the real trigger condition:

Call (via HA MCP) `ha_call_service` with `ws_command="fire_event"` equivalent, or more simply use `ha_eval_template` to fire a test event, OR directly trigger the automation for a dry run:
```
ha_call_service(domain="automation", service="trigger", target={"entity_id": "automation.telegram_bridge_recovery_failed"})
```
Expected: a push notification "⚠️ Telegram bridge stuck, auto-recovery failed — needs manual reconnect in Node-RED." arrives on the "Aiden" device (`notify.aiden_2`).

- [ ] **Step 5: Restore real state**

If `tb_bot_cfg` is still disabled from Step 3 for any reason, re-enable it and redeploy. Confirm `automation.telegram_smart_router` traces resume (send a real "neues todo: test" message, confirm it's created in Todoist, then delete the test task).
