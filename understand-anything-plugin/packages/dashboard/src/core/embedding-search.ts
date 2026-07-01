import type { GraphNode } from "./types.js";
import type { SearchResult, SearchOptions } from "./search.js";

/**
 * Options for a semantic search. Extends the lexical {@link SearchOptions}
 * with a similarity `threshold` so callers can drop weak matches.
 */
export interface SemanticSearchOptions extends SearchOptions {
  /** Minimum cosine similarity (0..1) for a node to be returned. Default 0. */
  threshold?: number;
}

/**
 * Cosine similarity between two equal-length vectors.
 * Returns 0 when either vector has zero magnitude.
 *
 * Mirrors the Python `understand_core.embedding_search.cosine_similarity`.
 */
export function cosineSimilarity(a: number[], b: number[]): number {
  let dot = 0;
  let magA = 0;
  let magB = 0;
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i];
    magA += a[i] * a[i];
    magB += b[i] * b[i];
  }
  magA = Math.sqrt(magA);
  magB = Math.sqrt(magB);
  if (magA === 0 || magB === 0) return 0;
  return dot / (magA * magB);
}

/**
 * Vector-embedding search engine using cosine similarity.
 *
 * Stores pre-computed per-node embeddings and ranks them against a query
 * embedding. Results share the lexical {@link SearchResult} shape so callers
 * can treat both engines uniformly (`score = 1 - similarity`; 0 = perfect).
 *
 * Mirrors the Python `understand_core.embedding_search.SemanticSearchEngine`.
 */
export class SemanticSearchEngine {
  private nodes: GraphNode[];
  private embeddings: Map<string, number[]>;

  constructor(nodes: GraphNode[], embeddings: Record<string, number[]>) {
    this.nodes = nodes;
    this.embeddings = new Map(Object.entries(embeddings));
  }

  hasEmbeddings(): boolean {
    return this.embeddings.size > 0;
  }

  addEmbedding(nodeId: string, embedding: number[]): void {
    this.embeddings.set(nodeId, embedding);
  }

  search(queryEmbedding: number[], options?: SemanticSearchOptions): SearchResult[] {
    const limit = options?.limit ?? 10;
    const threshold = options?.threshold ?? 0;
    const typeFilter = options?.types && options.types.length > 0 ? new Set(options.types) : null;

    const scored: SearchResult[] = [];
    for (const node of this.nodes) {
      if (typeFilter && !typeFilter.has(node.type)) continue;
      const embedding = this.embeddings.get(node.id);
      if (!embedding) continue;
      const similarity = cosineSimilarity(queryEmbedding, embedding);
      if (similarity >= threshold) {
        scored.push({ nodeId: node.id, score: 1 - similarity });
      }
    }

    scored.sort((a, b) => a.score - b.score);
    return scored.slice(0, limit);
  }

  updateNodes(nodes: GraphNode[]): void {
    this.nodes = nodes;
  }
}
