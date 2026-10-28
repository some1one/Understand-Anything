import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { checkVersion, newer, run } from '../../understand-anything-plugin/hooks/check_version.mjs';

function fixture() {
  return { installed: '2.8.1', now: 100000000,
    cacheFile: join(mkdtempSync(join(tmpdir(), 'ua-hook-')), 'cache.json') };
}

test('compares stable version components numerically, ignoring malformed/prerelease values', () => {
  for (const value of ['2.8.2', '2.10.0', '3.0.0']) assert.ok(newer(value, '2.8.1'));
  for (const value of ['2.8.1', '2.7.99', '1.99.99', '2.9.0-beta', '', null, {}, '9999999999999999999.0.0']) {
    assert.equal(newer(value, '2.8.1'), false);
  }
});

test('first check reports a newer version and subsequent sessions reuse the cache', async () => {
  const options = fixture();
  let requests = 0;
  options.request = async () => { requests++; return '2.9.0'; };
  const result = await run({ hook_event_name: 'SessionStart', cwd: '/not-a-git-repo' }, options);
  assert.match(result.systemMessage, /2.9.0.*2.8.1/);
  assert.equal(result.hookSpecificOutput.additionalContext, result.systemMessage);
  assert.match(result.systemMessage, /Do not update or run setup automatically/);
  assert.equal(await checkVersion(options), result.systemMessage);
  assert.equal(requests, 1);
  assert.equal(JSON.parse(readFileSync(options.cacheFile)).version, '2.9.0');
});

test('current, locally newer, malformed and prerelease responses stay quiet', async () => {
  for (const version of ['2.8.1', '2.8.0', '2.9.0-rc.1', undefined, {}, 'bad']) {
    assert.equal(await checkVersion({ ...fixture(), request: async () => version }), null);
  }
});

test('offline failures are silent and cached, then retried after 24 hours', async () => {
  const options = fixture();
  let requests = 0;
  options.request = async () => { requests++; throw new Error('offline'); };
  assert.equal(await checkVersion(options), null);
  assert.equal(await checkVersion(options), null);
  assert.equal(requests, 1);
  assert.equal(await checkVersion({ ...options, now: options.now + 86400000 }), null);
  assert.equal(requests, 2);
});

test('expired cache refreshes; invalid and future timestamps cannot suppress checks', async () => {
  for (const checkedAt of [0, 'invalid', 200000000]) {
    const options = fixture();
    writeFileSync(options.cacheFile, JSON.stringify({ checkedAt, version: '2.8.1' }));
    assert.match(await checkVersion({ ...options, request: async () => '2.9.0' }), /2.9.0/);
  }
});

test('corrupt and unwritable cache does not fail the hook', async () => {
  const options = fixture();
  writeFileSync(options.cacheFile, 'malformed');
  assert.match(await checkVersion({ ...options, request: async () => '2.9.0' }), /2.9.0/);
  // The cache file cannot also be a directory; this reliably fails even as root.
  assert.match(await checkVersion({ ...options, cacheFile: join(options.cacheFile, 'child'),
    request: async () => '2.9.0' }), /2.9.0/);
});

test('unrelated events and opt-out skip even reading the version cache', async () => {
  const options = { ...fixture(), request: () => { throw new Error('must not request'); } };
  for (const event of [null, [], {}, { hook_event_name: 'PostToolUse' }]) {
    assert.equal(await run(event, options), null);
  }
  process.env.UA_SKIP_UPDATE_CHECK = '1';
  try { assert.equal(await run({ hook_event_name: 'SessionStart' }, options), null); }
  finally { delete process.env.UA_SKIP_UPDATE_CHECK; }
});
