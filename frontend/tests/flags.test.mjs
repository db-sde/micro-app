import test from 'node:test';
import assert from 'node:assert/strict';
import { flagsByField, flagLevel, flagBadge, sourceColors } from '../src/components/flags.mjs';

const report = {
  field_report: [
    { field_key: 'total_fee', flags: [{ severity: 'error', code: 'money_without_amount', message: 'No amount' }] },
    { field_key: 'spec_name', flags: [{ severity: 'info', code: 'derived', message: 'Set by rule: title_name' }] },
    { field_key: 'mode', flags: [] },
    { field_key: 'duration' },
  ],
};

test('v1 reports have no flags to show', () => {
  assert.deepEqual(flagsByField({ field_report: [{ field_key: 'mode', status: 'mapped' }] }), {});
  assert.deepEqual(flagsByField(undefined), {});
  assert.equal(flagBadge(undefined), null);
});

test('flags are grouped by field and empty lists are skipped', () => {
  const byField = flagsByField(report);
  assert.deepEqual(Object.keys(byField).sort(), ['spec_name', 'total_fee']);
});

test('the most serious flag decides the badge', () => {
  const flags = [
    { severity: 'info', message: 'Set by rule' },
    { severity: 'warning', message: 'Not found in the document' },
    { severity: 'error', message: 'Heading contains a fee' },
  ];
  assert.equal(flagLevel(flags), 'error');
  const badge = flagBadge(flags);
  assert.equal(badge.level, 'error');
  assert.equal(badge.text, '⚠ 2 to check');
  assert.equal(badge.tooltip.split('\n')[0], 'ERROR: Heading contains a fee');
});

test('a value set by a rule shows as auto-set, not as a problem', () => {
  const badge = flagBadge([{ severity: 'info', message: 'Set by rule: title_name' }]);
  assert.equal(badge.level, 'info');
  assert.equal(badge.text, 'ℹ auto-set');
});

test('v2 sources get their own colours; unknown ones stay neutral', () => {
  assert.equal(sourceColors('LLM').color, '#0F766E');
  assert.equal(sourceColors('embedding').color, '#7C3AED');
  assert.equal(sourceColors('KV').color, '#64748B');
});
