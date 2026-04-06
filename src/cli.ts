#!/usr/bin/env node
import { Command } from "commander";
import path from "path";
import { SyncEngine } from "./sync/index.js";
import { KnowledgeStore } from "./kb/store.js";
import { ConfigManager } from "./config/index.js";
import { Cron } from "croner";
import { OAuthManager } from "./auth/oauth.js";
import { getProvider, listProviders } from "./auth/providers.js";

const PROJECT_DIR = process.env.SYNESIS_DIR || process.cwd();

const program = new Command();

program
  .name("synesis")
  .description("Self-evolving agent memory system")
  .version("0.1.0");

program
  .command("sync")
  .description("Run a sync cycle: fetch conversations, extract knowledge, apply self-modifications")
  .action(async () => {
    const engine = new SyncEngine(PROJECT_DIR);
    await engine.run();
  });

program
  .command("search")
  .description("Search the knowledge base")
  .argument("<query>", "Search query")
  .option("-c, --category <category>", "Filter by category")
  .action(async (query: string, opts: { category?: string }) => {
    const store = new KnowledgeStore(path.join(PROJECT_DIR, "knowledge"));
    const results = await store.search(query, opts.category);

    if (results.length === 0) {
      console.log("No results found.");
      return;
    }

    for (const entry of results) {
      console.log(`\n[${entry.category}] ${entry.title}`);
      console.log(`  Source: ${entry.source} | Tags: ${entry.tags.join(", ")}`);
      console.log(`  ${entry.content.slice(0, 200)}${entry.content.length > 200 ? "..." : ""}`);
    }
  });

program
  .command("list")
  .description("List knowledge entries")
  .option("-c, --category <category>", "Filter by category")
  .action(async (opts: { category?: string }) => {
    const store = new KnowledgeStore(path.join(PROJECT_DIR, "knowledge"));
    const entries = await store.list(opts.category);

    if (entries.length === 0) {
      console.log("No entries found.");
      return;
    }

    console.log(`\n${entries.length} entries:\n`);
    for (const entry of entries) {
      console.log(`  [${entry.category}] ${entry.title} (${entry.source}) - ${entry.updated}`);
    }
  });

program
  .command("daemon")
  .description("Run as a daemon with scheduled sync")
  .action(async () => {
    const configManager = new ConfigManager(
      path.join(PROJECT_DIR, "config", "synesis.yaml")
    );
    const config = await configManager.load();

    console.log(`Synesis daemon starting...`);
    console.log(`Schedule: ${config.sync_schedule}`);

    // Run immediately on start
    const engine = new SyncEngine(PROJECT_DIR);
    await engine.run();

    // Schedule recurring syncs
    new Cron(config.sync_schedule, async () => {
      console.log(`\n[${new Date().toISOString()}] Scheduled sync starting...`);
      const freshEngine = new SyncEngine(PROJECT_DIR);
      await freshEngine.run();
    });

    console.log("Daemon running. Press Ctrl+C to stop.");
  });

program
  .command("config")
  .description("Show current configuration")
  .action(async () => {
    const configManager = new ConfigManager(
      path.join(PROJECT_DIR, "config", "synesis.yaml")
    );
    const config = await configManager.load();
    console.log(JSON.stringify(config, null, 2));
  });

program
  .command("init")
  .description("Initialize a new Synesis knowledge base in the current directory")
  .action(async () => {
    const store = new KnowledgeStore(path.join(PROJECT_DIR, "knowledge"));
    await store.init();

    const configManager = new ConfigManager(
      path.join(PROJECT_DIR, "config", "synesis.yaml")
    );
    await configManager.load();

    console.log("Synesis initialized.");
    console.log(`  Knowledge base: ${path.join(PROJECT_DIR, "knowledge")}`);
    console.log(`  Config: ${path.join(PROJECT_DIR, "config", "synesis.yaml")}`);
    console.log(`\nRun 'synesis sync' to start extracting knowledge.`);
  });

const auth = program
  .command("auth")
  .description("Manage OAuth authentication for connectors");

auth
  .command("login")
  .description("Authenticate with a provider")
  .argument("<provider>", `Provider name (${listProviders().join(", ")})`)
  .requiredOption("--client-id <id>", "OAuth client ID")
  .requiredOption("--client-secret <secret>", "OAuth client secret")
  .action(async (providerName: string, opts: { clientId: string; clientSecret: string }) => {
    const provider = getProvider(providerName, opts.clientId, opts.clientSecret);
    if (!provider) {
      console.error(`Unknown provider: ${providerName}`);
      console.log(`Available: ${listProviders().join(", ")}`);
      process.exit(1);
    }

    const oauth = new OAuthManager(PROJECT_DIR);
    await oauth.init();
    await oauth.authenticate(provider);
    console.log(`\nAuthenticated with ${providerName}.`);
  });

auth
  .command("list")
  .description("List authenticated providers")
  .action(async () => {
    const oauth = new OAuthManager(PROJECT_DIR);
    await oauth.init();
    const providers = await oauth.listAuthenticated();
    if (providers.length === 0) {
      console.log("No authenticated providers.");
      console.log(`Available: ${listProviders().join(", ")}`);
    } else {
      console.log("Authenticated providers:");
      for (const p of providers) {
        console.log(`  - ${p}`);
      }
    }
  });

auth
  .command("revoke")
  .description("Revoke authentication for a provider")
  .argument("<provider>", "Provider name")
  .action(async (providerName: string) => {
    const oauth = new OAuthManager(PROJECT_DIR);
    await oauth.init();
    const success = await oauth.revoke(providerName);
    console.log(success ? `Revoked ${providerName}.` : `No auth found for ${providerName}.`);
  });

program.parse();
