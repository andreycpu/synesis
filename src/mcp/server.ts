#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import path from "path";
import { KnowledgeStore } from "../kb/store.js";
import { ConfigManager } from "../config/index.js";
import { SyncEngine } from "../sync/index.js";
import { SearchIndex } from "../kb/search.js";
import { Compactor } from "../kb/compactor.js";

const PROJECT_DIR = process.env.SYNESIS_DIR || process.cwd();
const store = new KnowledgeStore(path.join(PROJECT_DIR, "knowledge"));
const configManager = new ConfigManager(
  path.join(PROJECT_DIR, "config", "synesis.yaml")
);
const searchIndex = new SearchIndex();
let indexLoaded = false;

async function ensureIndex() {
  if (indexLoaded) return;
  await store.init();
  const entries = await store.list();
  for (const entry of entries) {
    searchIndex.add(entry);
  }
  indexLoaded = true;
}

const server = new McpServer({
  name: "synesis",
  version: "0.1.0",
});

// Search knowledge base (TF-IDF ranked)
server.tool(
  "search",
  "Search the knowledge base for entries matching a query. Returns ranked results.",
  { query: z.string(), category: z.string().optional(), limit: z.number().optional() },
  async ({ query, category, limit }) => {
    await ensureIndex();
    const results = searchIndex.search(query, limit || 10, category);
    const text = results.length === 0
      ? "No results found."
      : results
          .map(
            (e) =>
              `## ${e.title}\n**Category:** ${e.category} | **Source:** ${e.source} | **Tags:** ${e.tags.join(", ")}\n\n${e.content}`
          )
          .join("\n\n---\n\n");

    return { content: [{ type: "text" as const, text }] };
  }
);

// Context-aware retrieval - fits results within a token budget
server.tool(
  "context",
  "Get relevant knowledge entries that fit within a token budget. Use this instead of search when you need to load knowledge into your context window efficiently.",
  { query: z.string(), max_tokens: z.number().optional(), category: z.string().optional() },
  async ({ query, max_tokens, category }) => {
    await ensureIndex();
    const entries = searchIndex.getContext(query, max_tokens || 8000, category);
    const text = entries.length === 0
      ? "No relevant knowledge found."
      : `*${entries.length} entries loaded (~${Math.ceil(entries.reduce((sum, e) => sum + (e.title.length + e.content.length) / 4, 0))} tokens)*\n\n` +
        entries
          .map((e) => `## ${e.title} [${e.category}]\n${e.content}`)
          .join("\n\n---\n\n");

    return { content: [{ type: "text" as const, text }] };
  }
);

// Compact knowledge base - merge related entries to reduce bloat
server.tool(
  "compact",
  "Run compaction to merge related entries and reduce knowledge base size. Use when the KB grows too large.",
  { max_per_category: z.number().optional() },
  async ({ max_per_category }) => {
    const compactor = new Compactor(store);
    const result = await compactor.compact(max_per_category || 50);
    const text = result.merged === 0
      ? "No compaction needed - all categories are within threshold."
      : `Compacted: ${result.merged} merge operations, ${result.archived} entries archived.\n` +
        result.categories
          .map((c) => `  ${c.category}: merged ${c.merged} groups, archived ${c.archived} entries`)
          .join("\n");

    // Rebuild search index after compaction
    indexLoaded = false;

    return { content: [{ type: "text" as const, text }] };
  }
);

// Get category summaries for quick orientation
server.tool(
  "summarize",
  "Generate a concise summary of a knowledge category. Use for quick orientation without loading all entries.",
  { category: z.string() },
  async ({ category }) => {
    const compactor = new Compactor(store);
    const summary = await compactor.summarizeCategory(category);
    if (!summary) {
      return { content: [{ type: "text" as const, text: `No entries in category: ${category}` }] };
    }
    // Save the summary for future quick access
    await store.write(summary);
    return { content: [{ type: "text" as const, text: summary.content }] };
  }
);

// List entries
server.tool(
  "list",
  "List all knowledge entries, optionally filtered by category",
  { category: z.string().optional() },
  async ({ category }) => {
    await store.init();
    const entries = await store.list(category);
    const text = entries.length === 0
      ? "No entries found."
      : entries
          .map((e) => `- **${e.title}** [${e.category}] (${e.source}) - ${e.updated}`)
          .join("\n");

    return { content: [{ type: "text" as const, text }] };
  }
);

// Read a specific entry
server.tool(
  "read",
  "Read a specific knowledge entry by category and ID",
  { category: z.string(), id: z.string() },
  async ({ category, id }) => {
    await store.init();
    const entry = await store.read(category, id);
    if (!entry) {
      return { content: [{ type: "text" as const, text: "Entry not found." }] };
    }
    const text = `# ${entry.title}\n\n**Category:** ${entry.category}\n**Source:** ${entry.source}\n**Tags:** ${entry.tags.join(", ")}\n**Created:** ${entry.created}\n**Updated:** ${entry.updated}\n\n${entry.content}`;
    return { content: [{ type: "text" as const, text }] };
  }
);

// Write a new entry
server.tool(
  "write",
  "Write a new knowledge entry to the base",
  {
    title: z.string(),
    category: z.string(),
    content: z.string(),
    tags: z.array(z.string()).optional(),
    source: z.string().optional(),
  },
  async ({ title, category, content, tags, source }) => {
    await store.init();
    const id = title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 50);
    const now = new Date().toISOString();

    const entry = {
      id,
      title,
      category,
      content,
      source: source || "mcp",
      tags: tags || [],
      created: now,
      updated: now,
      metadata: {},
    };

    const filePath = await store.write(entry);
    return {
      content: [
        { type: "text" as const, text: `Entry written to ${filePath}` },
      ],
    };
  }
);

// Delete an entry
server.tool(
  "delete",
  "Delete a knowledge entry",
  { category: z.string(), id: z.string() },
  async ({ category, id }) => {
    await store.init();
    const success = await store.delete(category, id);
    return {
      content: [
        {
          type: "text" as const,
          text: success ? "Entry deleted." : "Entry not found.",
        },
      ],
    };
  }
);

// Trigger sync
server.tool("sync", "Trigger a sync to pull new conversations and extract knowledge", {}, async () => {
  const engine = new SyncEngine(PROJECT_DIR);
  const result = await engine.run();
  return {
    content: [
      {
        type: "text" as const,
        text: `Sync complete: ${result.entries} entries extracted, ${result.configUpdates.length} config updates applied.`,
      },
    ],
  };
});

// Get config
server.tool("get_config", "Read the current Synesis configuration", {}, async () => {
  const config = await configManager.load();
  return {
    content: [
      { type: "text" as const, text: JSON.stringify(config, null, 2) },
    ],
  };
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
