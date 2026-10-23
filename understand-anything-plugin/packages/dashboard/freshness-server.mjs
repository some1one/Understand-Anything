// Shared by the development and packaged dashboard servers.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execute = promisify(execFile);
const rustDir = fileURLToPath(new URL("../rust/", import.meta.url));
const unknown = () => ({ status: "unknown", reason: "freshness-request-failed" });

// Use an already-built engine: opening a dashboard must not start a build.
function enginePath() {
  return ["bin/understand-anything-rs", "target/release/understand-anything-rs"]
    .map((name) => path.join(rustDir, name))
    .find((name) => { try { fs.accessSync(name, fs.constants.X_OK); return true; } catch { return false; } });
}

export function createFreshnessReader(findGraphFile, executeEngine = execute, binary = enginePath) {
  let pending;
  return function readFreshness() {
    // Coalesce simultaneous requests, but never retain a completed Git snapshot.
    if (pending) return pending;
    pending = (async () => {
      const knowledge = findGraphFile("knowledge-graph.json");
      if (!knowledge) return { graphs: { knowledge: unknown() } };
      const root = path.dirname(path.dirname(knowledge));
      // Resolve optional graphs beside the selected code graph, never in another project.
      const domain = path.join(path.dirname(knowledge), "domain-graph.json");
      const graphs = {};
      const engine = binary();
      for (const [name, file] of [["knowledge", knowledge], ["domain", domain]]) {
        if (name === "domain" && !fs.existsSync(file)) continue;
        try {
          if (!engine) throw new Error("Engine unavailable");
          const { stdout } = await executeEngine(engine, ["graph_freshness", root, file], {
            timeout: 15000, killSignal: "SIGKILL", maxBuffer: 4 * 1024 * 1024,
            windowsHide: true,
          });
          const result = JSON.parse(stdout);
          if (!["fresh", "dirty", "stale", "unknown"].includes(result?.status)) throw new Error("Invalid freshness result");
          graphs[name] = result;
        } catch { graphs[name] = unknown(); }
      }
      return { graphs };
    })().finally(() => { pending = undefined; });
    return pending;
  };
}
