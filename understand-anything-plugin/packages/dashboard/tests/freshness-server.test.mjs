import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createFreshnessReader } from '../freshness-server.mjs';
const binary = fileURLToPath(new URL('../../rust/target/debug/understand-anything-rs', import.meta.url));
test('checks individual graph identity and refreshes worktree state', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ua-freshness-server-'));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
  git('init', '-q'); git('config', 'user.email', 'test@example.com'); git('config', 'user.name', 'Test');
  fs.writeFileSync(path.join(root, 'source.txt'), 'one');
  git('add', '.'); git('commit', '-qm', 'first');
  const base = git('rev-parse', 'HEAD');
  fs.writeFileSync(path.join(root, 'source.txt'), 'two'); git('commit', '-qam', 'second');
  const head = git('rev-parse', 'HEAD');
  const data = path.join(root, '.ua'); fs.mkdirSync(data);
  const knowledge = path.join(data, 'knowledge-graph.json');
  fs.writeFileSync(knowledge, JSON.stringify({ project: { gitCommitHash: head } }));
  fs.writeFileSync(path.join(data, 'domain-graph.json'), JSON.stringify({ project: { gitCommitHash: base } }));
  const read = createFreshnessReader(() => knowledge, undefined, () => binary);
  const first = read(); assert.equal(read(), first);
  const report = await first;
  assert.equal(report.graphs.knowledge.status, 'fresh');
  assert.equal(report.graphs.domain.status, 'stale');
  fs.writeFileSync(path.join(root, 'source.txt'), 'dirty');
  assert.equal((await read()).graphs.knowledge.status, 'dirty');
});
test('missing graphs and unavailable, malformed or failed engines remain unknown', async () => {
  assert.equal((await createFreshnessReader(() => null)()).graphs.knowledge.status, 'unknown');
  for (const execute of [async () => { throw new Error('timeout'); }, async () => ({ stdout: '<html>' }), async () => ({ stdout: '{}' })]) {
    const read = createFreshnessReader(() => '/missing/.ua/knowledge-graph.json', execute, () => binary);
    assert.equal((await read()).graphs.knowledge.status, 'unknown');
  }
  assert.equal((await createFreshnessReader(() => '/missing/.ua/knowledge-graph.json', undefined, () => undefined)()).graphs.knowledge.status, 'unknown');
});
