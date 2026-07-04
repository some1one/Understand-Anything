#!/usr/bin/env node
// Standalone static server for the pre-built dashboard.
//
// Serves the production build in ./dist and the same token-gated data
// endpoints the Vite dev server exposed (knowledge-graph.json, domain-graph.json,
// diff-overlay.json, meta.json, config.json, file-content.json). Zero runtime
// dependencies — only Node's stdlib — so it runs from a bundled plugin without
// `pnpm install`.
//
// Env:
//   GRAPH_DIR                 project root that holds .understand-anything/
//   UNDERSTAND_ACCESS_TOKEN   fixed access token (else a random one is generated)
//   PORT / HOST               listen address (default 127.0.0.1:0 → random port)
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIST_DIR = path.resolve(__dirname, "dist");
const ACCESS_TOKEN = process.env.UNDERSTAND_ACCESS_TOKEN || crypto.randomBytes(16).toString("hex");
const HOST = process.env.HOST || "127.0.0.1";
const PORT = Number(process.env.PORT || 0); // 0 → OS picks a free port
const MAX_SOURCE_FILE_BYTES = 1024 * 1024;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".map": "application/json; charset=utf-8",
};

// ---- data-endpoint helpers (ported from vite.config.ts) --------------------

function graphFileCandidates(fileName) {
  const graphDir = process.env.GRAPH_DIR;
  return [
    ...(graphDir ? [path.resolve(graphDir, `.understand-anything/${fileName}`)] : []),
    path.resolve(process.cwd(), `.understand-anything/${fileName}`),
  ];
}

function findGraphFile(fileName) {
  return graphFileCandidates(fileName).find((c) => fs.existsSync(c)) ?? null;
}

function projectRootFromGraphFile(candidate) {
  return path.dirname(path.dirname(candidate));
}

function normalizeGraphPath(filePath, projectRoot) {
  const rawPath = path.isAbsolute(filePath)
    ? filePath.startsWith(projectRoot)
      ? path.relative(projectRoot, filePath)
      : null
    : filePath;
  if (rawPath === null) return null;
  const normalized = path.normalize(rawPath);
  if (
    !normalized ||
    normalized === "." ||
    normalized.includes("\0") ||
    normalized === ".." ||
    normalized.startsWith(`..${path.sep}`) ||
    path.isAbsolute(normalized)
  ) {
    return null;
  }
  return normalized.split(path.sep).join("/");
}

function graphFilePathSet(graphFile, projectRoot) {
  const allowed = new Set();
  try {
    const raw = JSON.parse(fs.readFileSync(graphFile, "utf-8"));
    for (const node of raw.nodes ?? []) {
      if (typeof node.filePath !== "string") continue;
      const normalized = normalizeGraphPath(node.filePath, projectRoot);
      if (normalized) allowed.add(normalized);
    }
  } catch {
    return allowed;
  }
  return allowed;
}

function detectLanguage(filePath) {
  const ext = path.extname(filePath).slice(1).toLowerCase();
  const byExt = {
    bash: "bash", c: "c", cc: "cpp", cpp: "cpp", cs: "csharp", css: "css",
    go: "go", h: "c", hpp: "cpp", html: "markup", java: "java", js: "javascript",
    jsx: "jsx", json: "json", md: "markdown", mjs: "javascript", py: "python",
    rb: "ruby", rs: "rust", sh: "bash", ts: "typescript", tsx: "tsx", txt: "text",
    yaml: "yaml", yml: "yaml",
  };
  return byExt[ext] ?? "text";
}

function reject(message, statusCode = 400) {
  return { statusCode, payload: { error: message } };
}

function readSourceFile(url) {
  const requestedPath = url.searchParams.get("path") ?? "";
  if (!requestedPath) return reject("Missing path");
  if (requestedPath.includes("\0")) return reject("Invalid path");
  if (path.isAbsolute(requestedPath)) return reject("Absolute paths are not allowed");

  const normalizedPath = path.normalize(requestedPath);
  if (
    normalizedPath === "." ||
    normalizedPath.startsWith(`..${path.sep}`) ||
    normalizedPath === ".." ||
    path.isAbsolute(normalizedPath)
  ) {
    return reject("Path must stay inside the project");
  }

  const graphFile = findGraphFile("knowledge-graph.json");
  if (!graphFile) return reject("No knowledge graph found. Run /understand first.", 404);

  const projectRoot = projectRootFromGraphFile(graphFile);
  const absoluteFile = path.resolve(projectRoot, normalizedPath);
  const relativeToRoot = path.relative(projectRoot, absoluteFile);
  if (
    !relativeToRoot ||
    relativeToRoot.startsWith(`..${path.sep}`) ||
    relativeToRoot === ".." ||
    path.isAbsolute(relativeToRoot)
  ) {
    return reject("Path must stay inside the project");
  }
  const safeRelativePath = relativeToRoot.split(path.sep).join("/");
  if (!graphFilePathSet(graphFile, projectRoot).has(safeRelativePath)) {
    return reject("File is not in the knowledge graph", 404);
  }

  let stat;
  try {
    stat = fs.statSync(absoluteFile);
  } catch {
    return reject("File not found", 404);
  }
  if (!stat.isFile()) return reject("Path is not a file");
  if (stat.size > MAX_SOURCE_FILE_BYTES) return reject("File is too large to preview", 413);

  const buffer = fs.readFileSync(absoluteFile);
  if (buffer.includes(0)) return reject("Binary files cannot be previewed", 415);

  const content = buffer.toString("utf8");
  return {
    statusCode: 200,
    payload: {
      path: safeRelativePath,
      language: detectLanguage(relativeToRoot),
      content,
      sizeBytes: buffer.byteLength,
      lineCount: content.length === 0 ? 0 : content.split(/\r\n|\n|\r/).length,
    },
  };
}

function sendJson(res, statusCode, payload) {
  res.statusCode = statusCode;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(payload));
}

function serveGraphFile(res, fileName, pathname) {
  for (const candidate of graphFileCandidates(fileName)) {
    if (!fs.existsSync(candidate)) continue;
    try {
      const raw = JSON.parse(fs.readFileSync(candidate, "utf-8"));
      const projectRoot = projectRootFromGraphFile(candidate);
      if (Array.isArray(raw.nodes)) {
        raw.nodes = raw.nodes.map((node) => {
          if (typeof node.filePath !== "string") return node;
          const abs = node.filePath;
          const rel = abs.startsWith(projectRoot)
            ? abs.slice(projectRoot.length).replace(/^[\\/]/, "")
            : path.isAbsolute(abs)
            ? path.basename(abs)
            : abs;
          return { ...node, filePath: rel };
        });
      }
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(raw));
    } catch (err) {
      console.error("[understand-anything] Failed to sanitise graph file:", err);
      sendJson(res, 500, { error: "Failed to read graph file" });
    }
    return;
  }
  res.statusCode = 404;
  if (pathname === "/knowledge-graph.json") {
    sendJson(res, 404, { error: "No knowledge graph found. Run /understand first." });
  } else {
    res.end();
  }
}

// ---- static file serving ---------------------------------------------------

function serveStatic(res, pathname) {
  let rel = decodeURIComponent(pathname.replace(/^\/+/, ""));
  if (rel === "") rel = "index.html";
  const abs = path.resolve(DIST_DIR, rel);
  // Prevent path traversal outside DIST_DIR.
  if (abs !== DIST_DIR && !abs.startsWith(DIST_DIR + path.sep)) {
    res.statusCode = 403;
    res.end("Forbidden");
    return;
  }
  fs.stat(abs, (err, stat) => {
    if (err || !stat.isFile()) {
      // SPA fallback: serve index.html for client-side routes.
      const indexPath = path.join(DIST_DIR, "index.html");
      fs.readFile(indexPath, (e2, buf) => {
        if (e2) {
          res.statusCode = 404;
          res.end("Not found");
        } else {
          res.setHeader("Content-Type", MIME[".html"]);
          res.end(buf);
        }
      });
      return;
    }
    res.setHeader("Content-Type", MIME[path.extname(abs).toLowerCase()] || "application/octet-stream");
    fs.createReadStream(abs).pipe(res);
  });
}

const PROTECTED = new Set([
  "/knowledge-graph.json",
  "/domain-graph.json",
  "/diff-overlay.json",
  "/embeddings.json",
  "/meta.json",
  "/config.json",
  "/file-content.json",
]);

const server = http.createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://${HOST}`);
  const pathname = url.pathname;

  if (!PROTECTED.has(pathname)) {
    serveStatic(res, pathname);
    return;
  }

  if (url.searchParams.get("token") !== ACCESS_TOKEN) {
    sendJson(res, 403, { error: "Forbidden: missing or invalid token" });
    return;
  }

  if (pathname === "/file-content.json") {
    const result = readSourceFile(url);
    sendJson(res, result.statusCode, result.payload);
    return;
  }

  if (pathname === "/config.json") {
    for (const candidate of graphFileCandidates("config.json")) {
      if (fs.existsSync(candidate)) {
        try {
          sendJson(res, 200, JSON.parse(fs.readFileSync(candidate, "utf-8")));
        } catch {
          sendJson(res, 500, { error: "Failed to read config file" });
        }
        return;
      }
    }
    sendJson(res, 200, { autoUpdate: false });
    return;
  }

  const fileName =
    pathname === "/diff-overlay.json" ? "diff-overlay.json"
    : pathname === "/embeddings.json" ? "embeddings.json"
    : pathname === "/meta.json" ? "meta.json"
    : pathname === "/domain-graph.json" ? "domain-graph.json"
    : "knowledge-graph.json";
  serveGraphFile(res, fileName, pathname);
});

server.listen(PORT, HOST, () => {
  const addr = server.address();
  const port = typeof addr === "object" && addr ? addr.port : PORT;
  console.log(`http://${HOST}:${port}/?token=${ACCESS_TOKEN}`);
});
