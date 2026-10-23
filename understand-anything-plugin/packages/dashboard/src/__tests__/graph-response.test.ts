import { describe, expect, it } from "vitest";
import { readGraphResponse } from "../graph-response";

describe("knowledge graph HTTP responses", () => {
  it("surfaces the server's actionable missing-graph error", async () => {
    const response = Response.json({ error: "No knowledge graph found. Run /understand first." }, { status: 404 });
    await expect(readGraphResponse(response)).rejects.toThrow("No knowledge graph found. Run /understand first.");
  });
  it("retains status for non-JSON and malformed error payloads", async () => {
    for (const body of ["<html>Unavailable</html>", "", '{"error":{}}', '{"error":"  "}']) {
      await expect(readGraphResponse(new Response(body, { status: 503 }))).rejects.toThrow("HTTP 503");
    }
  });
  it("returns successful JSON unchanged for schema validation", async () => {
    const graph = { project: { name: "example" }, nodes: [], edges: [] };
    expect(await readGraphResponse(Response.json(graph))).toEqual(graph);
    await expect(readGraphResponse(new Response("not JSON", { status: 200 }))).rejects.toThrow();
  });
});
