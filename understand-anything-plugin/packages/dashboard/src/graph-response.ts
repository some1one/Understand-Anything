/** Keep server failures out of graph-schema validation. */
export async function readGraphResponse(response: Response): Promise<unknown> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "error" in body &&
          typeof body.error === "string" && body.error.trim()) {
        detail = body.error;
      }
    } catch {
      // An HTML or empty error response still has a useful status code.
    }
    throw new Error(detail);
  }
  return response.json();
}
