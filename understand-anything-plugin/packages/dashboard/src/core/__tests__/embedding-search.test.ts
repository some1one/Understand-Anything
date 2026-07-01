import { describe, expect, it } from "vitest";
import { cosineSimilarity, SemanticSearchEngine } from "../embedding-search.js";
import type { GraphNode } from "../types.js";

const NODES: GraphNode[] = [
  { id: "n1", type: "file", name: "auth.ts", summary: "Authentication module", tags: ["auth"], complexity: "moderate" },
  { id: "n2", type: "file", name: "db.ts", summary: "Database connection", tags: ["db"], complexity: "simple" },
  { id: "n3", type: "function", name: "login", summary: "User login handler", tags: ["auth", "login"], complexity: "moderate" },
];

const EMBEDDINGS: Record<string, number[]> = {
  n1: [1, 0, 0, 0],
  n2: [0, 1, 0, 0],
  n3: [0.9, 0, 0.1, 0],
};

describe("cosineSimilarity", () => {
  it("returns 1 for identical vectors", () => {
    expect(cosineSimilarity([1, 0, 0], [1, 0, 0])).toBeCloseTo(1);
  });

  it("returns 0 for orthogonal vectors", () => {
    expect(cosineSimilarity([1, 0, 0], [0, 1, 0])).toBeCloseTo(0);
  });

  it("returns high similarity for similar vectors", () => {
    expect(cosineSimilarity([1, 0, 0], [0.9, 0.1, 0])).toBeGreaterThan(0.9);
  });

  it("returns 0 for a zero-magnitude vector", () => {
    expect(cosineSimilarity([0, 0, 0], [1, 0, 0])).toBe(0);
  });
});

describe("SemanticSearchEngine", () => {
  it("returns results sorted by similarity (best first)", () => {
    const engine = new SemanticSearchEngine(NODES, EMBEDDINGS);
    const results = engine.search([1, 0, 0, 0]);
    expect(results[0].nodeId).toBe("n1");
    // scores non-decreasing (score = 1 - similarity)
    for (let i = 1; i < results.length; i++) {
      expect(results[i].score).toBeGreaterThanOrEqual(results[i - 1].score);
    }
  });

  it("respects the limit option", () => {
    const engine = new SemanticSearchEngine(NODES, EMBEDDINGS);
    expect(engine.search([1, 0, 0, 0], { limit: 2 })).toHaveLength(2);
  });

  it("respects the threshold option", () => {
    const engine = new SemanticSearchEngine(NODES, EMBEDDINGS);
    const ids = engine.search([1, 0, 0, 0], { threshold: 0.5 }).map((r) => r.nodeId);
    expect(ids).not.toContain("n2");
  });

  it("filters by node type", () => {
    const engine = new SemanticSearchEngine(NODES, EMBEDDINGS);
    const results = engine.search([1, 0, 0, 0], { types: ["function"] });
    for (const r of results) {
      const node = NODES.find((n) => n.id === r.nodeId);
      expect(node?.type).toBe("function");
    }
  });

  it("returns empty when no node has an embedding", () => {
    const engine = new SemanticSearchEngine(NODES, {});
    expect(engine.search([1, 0, 0, 0])).toHaveLength(0);
  });

  it("reports hasEmbeddings", () => {
    expect(new SemanticSearchEngine(NODES, EMBEDDINGS).hasEmbeddings()).toBe(true);
    expect(new SemanticSearchEngine(NODES, {}).hasEmbeddings()).toBe(false);
  });

  it("addEmbedding updates the index", () => {
    const engine = new SemanticSearchEngine(NODES, {});
    expect(engine.hasEmbeddings()).toBe(false);
    engine.addEmbedding("n1", [1, 0, 0, 0]);
    expect(engine.hasEmbeddings()).toBe(true);
    expect(engine.search([1, 0, 0, 0])[0]?.nodeId).toBe("n1");
  });
});
