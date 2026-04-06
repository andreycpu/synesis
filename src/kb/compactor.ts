import Anthropic from "@anthropic-ai/sdk";
import type { KnowledgeEntry } from "./types.js";
import { KnowledgeStore } from "./store.js";

const COMPACTION_PROMPT = `You are Synesis, a knowledge compaction agent. Your job is to merge multiple related knowledge entries into a single, denser summary entry.

Rules:
- Preserve all important facts, decisions, and nuance
- Remove redundancy and duplicates
- Keep the summary concise but complete - nothing important should be lost
- If entries conflict, keep the most recent information and note the change
- Output a single merged entry as JSON:

{
  "title": "merged title",
  "content": "the merged knowledge",
  "tags": ["merged", "tags"]
}

Entries to merge:
`;

/**
 * Compactor handles hierarchical summarization of knowledge entries.
 * When a category exceeds a threshold, related entries get merged into
 * summary nodes. Raw entries move to an archive subfolder.
 *
 * This prevents context bloat while preserving all information.
 */
export class Compactor {
  private client: Anthropic;
  private model: string;

  constructor(
    private store: KnowledgeStore,
    model?: string
  ) {
    this.client = new Anthropic();
    this.model = model || "claude-sonnet-4-20250514";
  }

  /**
   * Run compaction on all categories that exceed the threshold.
   */
  async compact(maxEntriesPerCategory: number = 50): Promise<CompactionResult> {
    const result: CompactionResult = { merged: 0, archived: 0, categories: [] };

    const allEntries = await this.store.list();
    const byCategory = this.groupByCategory(allEntries);

    for (const [category, entries] of byCategory) {
      if (entries.length <= maxEntriesPerCategory) continue;

      console.log(`Compacting ${category}: ${entries.length} entries (threshold: ${maxEntriesPerCategory})`);

      const groups = this.findRelatedGroups(entries);
      let categoryMerged = 0;
      let categoryArchived = 0;

      for (const group of groups) {
        if (group.length < 2) continue;

        const merged = await this.mergeEntries(category, group);
        if (merged) {
          await this.store.write(merged);

          // Archive originals
          for (const entry of group) {
            const archived: KnowledgeEntry = {
              ...entry,
              category: `_archive/${entry.category}`,
              metadata: {
                ...entry.metadata,
                merged_into: merged.id,
                archived_at: new Date().toISOString(),
              },
            };
            await this.store.write(archived);
            await this.store.delete(entry.category, entry.id);
          }

          categoryMerged++;
          categoryArchived += group.length;
        }
      }

      if (categoryMerged > 0) {
        result.categories.push({
          category,
          merged: categoryMerged,
          archived: categoryArchived,
        });
        result.merged += categoryMerged;
        result.archived += categoryArchived;
      }
    }

    return result;
  }

  /**
   * Generate a category-level summary for context-efficient retrieval.
   */
  async summarizeCategory(category: string): Promise<KnowledgeEntry | null> {
    const entries = await this.store.list(category);
    if (entries.length === 0) return null;

    const entriesText = entries
      .map((e) => `## ${e.title}\n${e.content}`)
      .join("\n\n");

    try {
      const response = await this.client.messages.create({
        model: this.model,
        max_tokens: 2048,
        messages: [
          {
            role: "user",
            content: `Summarize these ${entries.length} knowledge entries in the "${category}" category into a concise overview. This summary will be used when an agent needs a quick understanding of what's known about ${category}, without loading every individual entry.\n\nEntries:\n${entriesText}`,
          },
        ],
      });

      const text = response.content[0].type === "text" ? response.content[0].text : "";
      const now = new Date().toISOString();

      return {
        id: `_summary-${category}`,
        title: `Summary: ${category}`,
        category: "_summaries",
        content: text,
        source: "compactor",
        tags: [category, "summary", "auto-generated"],
        created: now,
        updated: now,
        metadata: { entry_count: entries.length, category },
      };
    } catch (error) {
      console.error(`Failed to summarize ${category}:`, error);
      return null;
    }
  }

  /**
   * Group entries by tag overlap and content similarity.
   */
  private findRelatedGroups(entries: KnowledgeEntry[]): KnowledgeEntry[][] {
    const groups: KnowledgeEntry[][] = [];
    const assigned = new Set<string>();

    // Sort by tags to cluster related entries
    const sorted = [...entries].sort((a, b) => {
      const aTags = a.tags.join(",");
      const bTags = b.tags.join(",");
      return aTags.localeCompare(bTags);
    });

    for (const entry of sorted) {
      if (assigned.has(entry.id)) continue;

      const group = [entry];
      assigned.add(entry.id);

      for (const candidate of sorted) {
        if (assigned.has(candidate.id)) continue;

        const overlap = this.tagOverlap(entry, candidate);
        const titleSimilarity = this.titleSimilarity(entry, candidate);

        if (overlap >= 0.5 || titleSimilarity >= 0.6) {
          group.push(candidate);
          assigned.add(candidate.id);
        }

        if (group.length >= 5) break; // Cap group size
      }

      groups.push(group);
    }

    return groups.filter((g) => g.length >= 2);
  }

  private tagOverlap(a: KnowledgeEntry, b: KnowledgeEntry): number {
    if (a.tags.length === 0 && b.tags.length === 0) return 0;
    const setA = new Set(a.tags);
    const intersection = b.tags.filter((t) => setA.has(t));
    const union = new Set([...a.tags, ...b.tags]);
    return union.size === 0 ? 0 : intersection.length / union.size;
  }

  private titleSimilarity(a: KnowledgeEntry, b: KnowledgeEntry): number {
    const wordsA = new Set(a.title.toLowerCase().split(/\s+/));
    const wordsB = new Set(b.title.toLowerCase().split(/\s+/));
    const intersection = [...wordsA].filter((w) => wordsB.has(w));
    const union = new Set([...wordsA, ...wordsB]);
    return union.size === 0 ? 0 : intersection.length / union.size;
  }

  private async mergeEntries(
    category: string,
    entries: KnowledgeEntry[]
  ): Promise<KnowledgeEntry | null> {
    const entriesText = entries
      .map(
        (e) =>
          `### ${e.title}\nTags: ${e.tags.join(", ")}\nSource: ${e.source}\nUpdated: ${e.updated}\n\n${e.content}`
      )
      .join("\n\n---\n\n");

    try {
      const response = await this.client.messages.create({
        model: this.model,
        max_tokens: 1024,
        messages: [
          { role: "user", content: COMPACTION_PROMPT + entriesText },
        ],
      });

      const text = response.content[0].type === "text" ? response.content[0].text : "";
      const jsonMatch = text.match(/\{[\s\S]*\}/);
      if (!jsonMatch) return null;

      const parsed = JSON.parse(jsonMatch[0]);
      const now = new Date().toISOString();
      const id = parsed.title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .slice(0, 50);

      return {
        id: `merged-${id}-${Date.now().toString(36).slice(-4)}`,
        title: parsed.title,
        category,
        content: parsed.content,
        source: "compactor",
        tags: [...new Set([...(parsed.tags || []), "merged"])],
        created: now,
        updated: now,
        metadata: {
          merged_from: entries.map((e) => e.id),
          merge_count: entries.length,
        },
      };
    } catch (error) {
      console.error("Merge failed:", error);
      return null;
    }
  }

  private groupByCategory(entries: KnowledgeEntry[]): Map<string, KnowledgeEntry[]> {
    const map = new Map<string, KnowledgeEntry[]>();
    for (const entry of entries) {
      if (entry.category.startsWith("_")) continue; // Skip system categories
      const existing = map.get(entry.category) || [];
      existing.push(entry);
      map.set(entry.category, existing);
    }
    return map;
  }
}

interface CompactionResult {
  merged: number;
  archived: number;
  categories: { category: string; merged: number; archived: number }[];
}
