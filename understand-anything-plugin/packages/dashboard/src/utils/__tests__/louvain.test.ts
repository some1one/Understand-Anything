import { describe, expect, it, vi } from "vitest";
import { detectCommunities } from "../louvain";

// Isolate the post-processing from the library's clustering cost so this
// regression exercises inputs above JavaScript's function-argument limit.
vi.mock("graphology-communities-louvain", () => ({
  default: (graph: { nodes(): string[] }) =>
    Object.fromEntries(graph.nodes().map((id, i) => [id, i === 0 ? -1 : i])),
}));

describe("community ID normalization", () => {
  it("handles large graphs without spreading node IDs into call arguments", () => {
    const ids = Array.from({ length: 150_000 }, (_, i) => `node-${i}`);
    const communities = detectCommunities(ids, []);
    expect(communities.size).toBe(ids.length);
    expect(communities.get("node-0")).toBe(ids.length);
    expect(communities.get("node-149999")).toBe(149_999);
  });

  it("handles an empty graph", () => {
    expect(detectCommunities([], []).size).toBe(0);
  });
});
