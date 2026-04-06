#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import path from "path";
import { KnowledgeStore } from "../kb/store.js";
import { ConfigManager } from "../config/index.js";
import { SyncEngine } from "../sync/index.js";

const PROJECT_DIR = process.env.SYNESIS_DIR || process.cwd();
const store = new KnowledgeStore(path.join(PROJECT_DIR, "knowledge"));
const configManager = new ConfigManager(
  path.join(PROJECT_DIR, "config", "synesis.yaml")
);

const server = new McpServer({
  name: "synesis",
  version: "0.1.0",
});

// Search knowledge base
server.tool(
  "search",
  "Search the knowledge base for entries matching a query",
  { query: z.string(), category: z.string().optional() },
  async ({ query, category }) => {
    await store.init();
    const results = await store.search(query, category);
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
