// Session startup only reports newer published versions. Node built-ins only.
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { get } from 'node:https';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const manifest = new URL('../.claude-plugin/plugin.json', import.meta.url);
const publishedManifest = 'https://raw.githubusercontent.com/some1one/Understand-Anything/main/understand-anything-plugin/.claude-plugin/plugin.json';
const day = 24 * 60 * 60 * 1000;

function readJson(path) {
  try { return JSON.parse(readFileSync(path, 'utf8')); } catch { return null; }
}

function parts(version) {
  if (typeof version !== 'string' || !/^\d+\.\d+\.\d+$/.test(version)) return null;
  const values = version.split('.').map(Number);
  return values.every(Number.isSafeInteger) ? values : null;
}

export function newer(latest, installed) {
  const a = parts(latest), b = parts(installed);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return false;
}

export function requestVersion() {
  return new Promise((resolve, reject) => {
    const request = get(publishedManifest, { agent: false }, response => {
      if (response.statusCode !== 200) {
        response.destroy();
        reject(new Error('Version unavailable'));
        return;
      }
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => {
        body += chunk;
        if (body.length > 16384) response.destroy(new Error('Manifest too large'));
      });
      response.on('error', reject);
      response.on('end', () => {
        try { resolve(JSON.parse(body).version); } catch (error) { reject(error); }
      });
    });
    // A wall-clock limit includes DNS, connection and response time.
    const timer = setTimeout(() => request.destroy(new Error('Version check timed out')), 1000);
    request.on('close', () => clearTimeout(timer));
    request.on('error', reject);
  });
}

export async function checkVersion({
  installed = readJson(manifest)?.version,
  cacheFile = join(process.env.XDG_CACHE_HOME || process.env.LOCALAPPDATA || join(homedir(), '.cache'),
    'understand-anything', 'published-version.json'),
  now = Date.now(),
  request = requestVersion,
} = {}) {
  if (!parts(installed)) return null;
  let cache = readJson(cacheFile);
  const age = now - cache?.checkedAt;
  if (!Number.isFinite(age) || age < 0 || age >= day) {
    let version = parts(cache?.version) ? cache.version : null;
    try {
      const latest = await request();
      if (parts(latest)) version = latest;
    } catch { /* Offline startup stays quiet; retry tomorrow. */ }
    cache = { checkedAt: now, version };
    try {
      mkdirSync(dirname(cacheFile), { recursive: true });
      writeFileSync(cacheFile, JSON.stringify(cache));
    } catch { /* A read-only cache must not fail session startup. */ }
  }
  if (!newer(cache?.version, installed)) return null;
  return `[understand-anything] Version ${cache.version} is available (installed: ${installed}). Update/reinstall the plugin through your installation method, then reload it. Do not update or run setup automatically.`;
}

export async function run(event, options) {
  if (event?.hook_event_name !== 'SessionStart' || process.env.UA_SKIP_UPDATE_CHECK === '1') return null;
  const message = await checkVersion(options);
  return message ? {
    systemMessage: message,
    hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: message },
  } : null;
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  // Also bound stdin and OS-level DNS work that can outlive an aborted request.
  const deadline = setTimeout(() => process.exit(0), 1500);
  try {
    let input = '';
    for await (const chunk of process.stdin) {
      input += chunk;
      if (input.length > 1024 * 1024) process.exit(0);
    }
    const result = await run(JSON.parse(input));
    if (result) process.stdout.write(JSON.stringify(result) + '\n');
  } catch { /* Optional notices never fail startup. */ }
  clearTimeout(deadline);
  process.exit(0);
}
