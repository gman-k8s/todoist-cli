# Telegram Bridge Watchdog — Design

## Background

The Node-RED Telegram bridge (`node-red-telegram-bridge.json`) uses long-polling
(`updatemode: polling`) against the Telegram Bot API via the `telegram receiver`
node (`tb_rx`) / `telegram bot` config node (`tb_bot_cfg`). On 2026-07-19 this
polling connection silently hung: no error was logged, no automation fired, no
HA event arrived, for over a week (`automation.telegram_smart_router` had zero
traces and a `last_triggered` stuck at 2026-07-11). The user found the problem
by manually noticing missed "neues todo" messages, then fixed it by disabling
and re-enabling the Telegram node in the Node-RED editor.

Because the hang produces no error state (the node just stops emitting
updates), passive signals don't work:

- **Status-node / error-state watching** would miss it — nothing changes state
  on a silent hang.
- **"No message received in N hours"** is indistinguishable from the user
  simply not messaging the bot.

Goal: detect this specific failure mode automatically, recover without manual
intervention, and notify the user when it happens.

## Detection mechanism

Telegram's Bot API allows only one active `getUpdates` long-poll session per
bot token. If a second client calls `getUpdates` while Node-RED's poll is
still alive, Telegram returns **HTTP 409 Conflict**. If Node-RED's poll has
died, that same call succeeds with **HTTP 200**, non-destructively (no
`offset` is advanced, so nothing is consumed from Node-RED's eventual next
poll).

This gives a definitive, active health check instead of a heuristic:

- `GET https://api.telegram.org/bot<token>/getUpdates?timeout=0&limit=1`
- `409` → Node-RED's poll is alive. Healthy.
- `200` → Node-RED's poll is dead. Trigger recovery.

## Recovery mechanism

Node-RED's Admin API (open, no `adminAuth` configured) is used to toggle just
the Telegram config node (`tb_bot_cfg`), the same effect as manually
disabling/re-enabling it in the editor. No other flow/tab is touched.

1. `GET http://localhost:1880/flow/tb_flow` — fetch current tab definition.
2. Set `tb_bot_cfg` node's `d` (disabled) property to `true`.
3. `PUT http://localhost:1880/flow/tb_flow` — redeploys the tab, node disabled.
4. Wait 3s.
5. Set `d` to `false`, `PUT` again — redeploys with node re-enabled, forcing a
   fresh polling connection.
6. Wait ~30s for reconnect, then re-run the detection probe to confirm.

## New Node-RED flow: "Watchdog" tab

Added to `node-red-telegram-bridge.json` as a new tab, independent of the
existing "Telegram Bridge" tab (which is untouched).

Nodes:

- `inject` (timer) — interval controlled by flow context `watchdog_interval_ms`,
  default 15 minutes.
- `http request` — the `getUpdates` probe described above.
- `function` ("Evaluate Probe") — branches on HTTP status (409 vs 200).
- `function` + `http request` pair (x2) — the disable/re-enable Admin API
  calls, with the 3s delay via a `delay` node.
- `function` ("Re-probe") — second `getUpdates` call after recovery attempt.
- `function` ("Track State") — maintains flow-context state:
  - `watchdog_state`: `ok` | `recovering` | `failed`
  - `last_failure_notified`: boolean, reset to `false` whenever state returns
    to `ok`
- `ha-fire-event` (x2) — fires `telegram_bridge_recovered` on confirmed
  recovery, `telegram_bridge_recovery_failed` on confirmed still-dead (only
  fired once per failure episode, gated by `last_failure_notified`).

Backoff: on a failed recovery attempt, the watchdog timer interval switches
from 15 min to 60 min (via `watchdog_interval_ms`) until a probe reports
healthy again, to avoid hammering the Admin API and re-notifying repeatedly.
Interval resets to 15 min once `watchdog_state` returns to `ok`.

## HA-side changes

Two new automations, following the existing `rest_command.telegram_send`
pattern used by `automation.telegram_smart_router`:

- **`automation.telegram_bridge_recovered`**
  - Trigger: event `telegram_bridge_recovered`
  - Action: `rest_command.telegram_send` — "🔄 Bot auto-recovered from stuck
    polling."

- **`automation.telegram_bridge_recovery_failed`**
  - Trigger: event `telegram_bridge_recovery_failed`
  - Action: `notify.aiden_2` (HA companion app push, not Telegram — Telegram
    may still be unreachable in this case) — "⚠️ Telegram bridge stuck,
    auto-recovery failed — needs manual reconnect in Node-RED."

## Out of scope

- Multi-episode retry tuning beyond the single 15min/60min backoff.
- Detecting failure modes other than a hung `getUpdates` poll (e.g. bad token,
  revoked bot) — those already surface differently (immediate 401/403 from
  Telegram) and are not the failure observed here.
- Changing the existing "Telegram Bridge" tab's routing logic.
