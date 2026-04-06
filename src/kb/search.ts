import type { KnowledgeEntry } from "./types.js";

/**
 * TF-IDF based semantic search over knowledge entries.
 * Works offline, no external API needed.
 * Entries are scored by relevance and only top-k are returned.
 */
export class SearchIndex {
  private documents: Map<string, { entry: KnowledgeEntry; terms: Map<string, number> }> = new Map();
  private idf: Map<string, number> = new Map();
  private dirty = true;

  add(entry: KnowledgeEntry): void {
    const text = `${entry.title} ${entry.content} ${entry.tags.join(" ")} ${entry.category}`;
    const terms = this.tokenize(text);
    const tf = this.computeTF(terms);
    this.documents.set(`${entry.category}/${entry.id}`, { entry, terms: tf });
    this.dirty = true;
  }

  remove(category: string, id: string): void {
    this.documents.delete(`${category}/${id}`);
    this.dirty = true;
  }

  search(query: string, limit: number = 10, category?: string): KnowledgeEntry[] {
    if (this.dirty) this.rebuildIDF();

    const queryTerms = this.tokenize(query);
    const queryTF = this.computeTF(queryTerms);
    const queryVector = this.toTFIDF(queryTF);

    const scored: { entry: KnowledgeEntry; score: number }[] = [];

    for (const [key, doc] of this.documents) {
      if (category && !key.startsWith(`${category}/`)) continue;

      const docVector = this.toTFIDF(doc.terms);
      const score = this.cosineSimilarity(queryVector, docVector);

      if (score > 0) {
        scored.push({ entry: doc.entry, score });
      }
    }

    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, limit).map((s) => s.entry);
  }

  /**
   * Get a relevance-ranked context window for an agent query.
   * Returns entries that fit within maxTokens (estimated).
   */
  getContext(query: string, maxTokens: number = 8000, category?: string): KnowledgeEntry[] {
    const results = this.search(query, 50, category);
    const selected: KnowledgeEntry[] = [];
    let tokenCount = 0;

    for (const entry of results) {
      const entryTokens = this.estimateTokens(entry);
      if (tokenCount + entryTokens > maxTokens) break;
      selected.push(entry);
      tokenCount += entryTokens;
    }

    return selected;
  }

  clear(): void {
    this.documents.clear();
    this.idf.clear();
    this.dirty = true;
  }

  get size(): number {
    return this.documents.size;
  }

  private tokenize(text: string): string[] {
    return text
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter((t) => t.length > 2)
      .filter((t) => !STOP_WORDS.has(t));
  }

  private computeTF(terms: string[]): Map<string, number> {
    const tf = new Map<string, number>();
    for (const term of terms) {
      tf.set(term, (tf.get(term) || 0) + 1);
    }
    // Normalize
    const max = Math.max(...tf.values(), 1);
    for (const [term, count] of tf) {
      tf.set(term, count / max);
    }
    return tf;
  }

  private rebuildIDF(): void {
    this.idf.clear();
    const docCount = this.documents.size;
    if (docCount === 0) return;

    const termDocCounts = new Map<string, number>();
    for (const doc of this.documents.values()) {
      for (const term of doc.terms.keys()) {
        termDocCounts.set(term, (termDocCounts.get(term) || 0) + 1);
      }
    }

    for (const [term, count] of termDocCounts) {
      this.idf.set(term, Math.log(docCount / count));
    }

    this.dirty = false;
  }

  private toTFIDF(tf: Map<string, number>): Map<string, number> {
    const tfidf = new Map<string, number>();
    for (const [term, freq] of tf) {
      const idf = this.idf.get(term) || 0;
      tfidf.set(term, freq * idf);
    }
    return tfidf;
  }

  private cosineSimilarity(a: Map<string, number>, b: Map<string, number>): number {
    let dotProduct = 0;
    let normA = 0;
    let normB = 0;

    for (const [term, val] of a) {
      normA += val * val;
      const bVal = b.get(term);
      if (bVal !== undefined) {
        dotProduct += val * bVal;
      }
    }

    for (const val of b.values()) {
      normB += val * val;
    }

    const denominator = Math.sqrt(normA) * Math.sqrt(normB);
    return denominator === 0 ? 0 : dotProduct / denominator;
  }

  private estimateTokens(entry: KnowledgeEntry): number {
    // Rough estimate: ~4 chars per token
    const text = `${entry.title}\n${entry.category}\n${entry.content}\n${entry.tags.join(", ")}`;
    return Math.ceil(text.length / 4);
  }
}

const STOP_WORDS = new Set([
  "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
  "her", "was", "one", "our", "out", "has", "have", "been", "some", "them",
  "than", "its", "over", "such", "that", "this", "with", "will", "each",
  "from", "they", "were", "which", "their", "what", "there", "when", "who",
  "how", "about", "into", "more", "other", "would", "just", "also", "then",
  "could", "these", "does", "like", "very", "your", "only", "should",
]);
