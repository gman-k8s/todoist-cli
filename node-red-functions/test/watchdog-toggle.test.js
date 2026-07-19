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
