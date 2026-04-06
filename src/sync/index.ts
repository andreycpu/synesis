import { KnowledgeStore } from "../kb/store.js";
import { ConfigManager } from "../config/index.js";
import { Extractor } from "../extractor/index.js";
import { createConnector } from "../connectors/index.js";
import type { RawConversation } from "../kb/types.js";
import fs from "fs/promises";
import path from "path";

export class SyncEngine {
  private store: KnowledgeStore;
  private config: ConfigManager;
  private extractor: Extractor;
  private stateFile: string;

  constructor(projectDir: string) {
    const configPath = path.join(projectDir, "config", "synesis.yaml");
    this.config = new ConfigManager(configPath);
    this.stateFile = path.join(projectDir, ".sync-state.json");
    this.store = new KnowledgeStore(path.join(projectDir, "knowledge"));
    this.extractor = new Extractor();
  }

  async run(): Promise<SyncResult> {
    const config = await this.config.load();
    await this.store.init();

    const lastSync = await this.getLastSync();
    const since = lastSync ? new Date(lastSync) : undefined;

    console.log(
      `Synesis sync starting... (since: ${since?.toISOString() || "beginning"})`
    );

    // Fetch from all enabled connectors
    const allConversations: RawConversation[] = [];
    for (const [name, connConfig] of Object.entries(config.connectors)) {
      if (!connConfig.enabled) continue;

      const connector = createConnector(name, connConfig);
      if (!connector) {
        console.log(`Unknown connector: ${name}`);
        continue;
      }

      const valid = await connector.validate();
      if (!valid) {
        console.log(`Connector ${name} validation failed, skipping`);
        continue;
      }

      console.log(`Fetching from ${name}...`);
      const conversations = await connector.fetch(since);
      console.log(`  Found ${conversations.length} conversations`);
      allConversations.push(...conversations);
    }

    if (allConversations.length === 0) {
      console.log("No new conversations to process");
      await this.saveLastSync();
      return { entries: 0, configUpdates: [] };
    }

    // Extract knowledge
    console.log(`Extracting knowledge from ${allConversations.length} conversations...`);
    const result = await this.extractor.extract(allConversations);

    // Write entries to store
    let written = 0;
    for (const entry of result.entries) {
      await this.store.write(entry);
      written++;
      console.log(`  + [${entry.category}] ${entry.title}`);
    }

    // Apply self-modifications
    const applied: string[] = [];
    if (result.config_updates && result.config_updates.length > 0) {
      console.log(`Applying ${result.config_updates.length} config updates...`);
      const results = await this.config.applyUpdates(result.config_updates);
      applied.push(...results);
      for (const a of results) {
        console.log(`  ~ ${a}`);
      }
    }

    await this.saveLastSync();

    console.log(`Sync complete: ${written} entries, ${applied.length} config updates`);

    return { entries: written, configUpdates: applied };
  }

  private async getLastSync(): Promise<string | null> {
    try {
      const raw = await fs.readFile(this.stateFile, "utf-8");
      const state = JSON.parse(raw);
      return state.lastSync || null;
    } catch {
      return null;
    }
  }

  private async saveLastSync(): Promise<void> {
    await fs.writeFile(
      this.stateFile,
      JSON.stringify({ lastSync: new Date().toISOString() }),
      "utf-8"
    );
  }
}

interface SyncResult {
  entries: number;
  configUpdates: string[];
}
