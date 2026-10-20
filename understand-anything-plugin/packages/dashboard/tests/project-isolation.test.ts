import { describe, expect, test } from "vitest";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, renameSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const dashboard = fileURLToPath(new URL("..", import.meta.url));
const viteEntry = pathToFileURL(path.join(path.dirname(createRequire(import.meta.url).resolve("vite/package.json")), "dist/node/index.js")).href;
const token = "project-isolation-fixture";
const artifact = (root: string, name: string, value: unknown) =>
  writeFileSync(path.join(root, ".understand-anything", name), JSON.stringify(value));

async function start(mode: string, cwd: string, project?: string): Promise<{ child: ChildProcess; url: string }> {
  const env: NodeJS.ProcessEnv = { ...process.env, UNDERSTAND_ACCESS_TOKEN: token, HOST: "127.0.0.1", PORT: "0" };
  delete env.GRAPH_DIR;
  if (project) env.GRAPH_DIR = project;
  const args = mode === "standalone" ? [path.join(dashboard, "serve.mjs")] : [
    "--input-type=module", "-e",
    `import {createServer} from ${JSON.stringify(viteEntry)};
     const server = await createServer({configFile:${JSON.stringify(path.join(dashboard, "vite.config.ts"))},
       root:process.cwd(), server:{port:0,host:"127.0.0.1",watch:null,open:false},
       optimizeDeps:{noDiscovery:true,include:[]}});
     await server.listen();`,
  ];
  const child = spawn(process.execPath, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
  let log = "";
  const url = await new Promise<string>((resolve, reject) => {
    const timeout = setTimeout(() => { child.kill(); reject(new Error(`Server startup timed out: ${log}`)); }, 15000);
    const consume = (data: Buffer) => {
      log += data.toString();
      const found = log.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[^\s]+/);
      if (found) { clearTimeout(timeout); resolve(found[0]); }
    };
    child.stdout!.on("data", consume);
    child.stderr!.on("data", consume);
    child.once("error", (error) => { clearTimeout(timeout); reject(error); });
    child.once("exit", (code) => { clearTimeout(timeout); reject(new Error(`Server exited ${code}: ${log}`)); });
  });
  return { child, url };
}
async function stop(child: ChildProcess) {
  if (child.exitCode !== null) return;
  const closed = new Promise<void>((resolve) => child.once("exit", () => resolve()));
  child.kill();
  await closed;
}
async function request(url: string, endpoint: string, source?: string) {
  const target = new URL(endpoint, url);
  target.searchParams.set("token", token);
  if (source) target.searchParams.set("path", source);
  return fetch(target);
}

describe.each(["standalone", "vite"])("%s project isolation", (mode) => {
  test("explicit project owns graphs, optional artifacts, and source authorization; implicit discovery still works", async () => {
    const fixture = mkdtempSync(path.join(tmpdir(), "ua-dashboard-isolation-"));
    const a = path.join(fixture, "a"), b = path.join(fixture, "b");
    for (const root of [a, b]) mkdirSync(path.join(root, ".understand-anything"), { recursive: true });
    artifact(a, "knowledge-graph.json", { project: { name: "A" }, nodes: [{ id: "a", filePath: "a.txt" }] });
    artifact(b, "knowledge-graph.json", { project: { name: "B" }, nodes: [{ id: "b", filePath: "b.txt" }] });
    writeFileSync(path.join(a, "a.txt"), "source A");
    writeFileSync(path.join(b, "b.txt"), "source B");
    for (const name of ["domain-graph.json", "meta.json", "diff-overlay.json", "embeddings.json", "config.json"])
      artifact(b, name, { marker: "B" });
    try {
      const explicit = await start(mode, b, a);
      try {
        expect((await (await request(explicit.url, "knowledge-graph.json")).json()).project.name).toBe("A");
        for (const name of ["domain-graph.json", "meta.json", "diff-overlay.json", "embeddings.json"])
          expect((await request(explicit.url, name)).status).toBe(404);
        expect(await (await request(explicit.url, "config.json")).json()).toEqual({ autoUpdate: false });
        expect((await request(explicit.url, "file-content.json", "a.txt")).status).toBe(200);
        expect((await request(explicit.url, "file-content.json", "b.txt")).status).toBe(404);
        renameSync(path.join(a, ".understand-anything/knowledge-graph.json"), path.join(a, "saved-graph.json"));
        expect((await request(explicit.url, "knowledge-graph.json")).status).toBe(404);
        expect((await request(explicit.url, "file-content.json", "b.txt")).status).toBe(404);
      } finally { await stop(explicit.child); }
      const implicit = await start(mode, b);
      try {
        expect((await (await request(implicit.url, "knowledge-graph.json")).json()).project.name).toBe("B");
        for (const name of ["domain-graph.json", "meta.json", "diff-overlay.json", "embeddings.json", "config.json"])
          expect(await (await request(implicit.url, name)).json()).toEqual({ marker: "B" });
        expect((await request(implicit.url, "file-content.json", "b.txt")).status).toBe(200);
      } finally { await stop(implicit.child); }
    } finally { rmSync(fixture, { recursive: true, force: true }); }
  }, 40000);
});
