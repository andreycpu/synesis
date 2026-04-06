import fs from "fs/promises";
import path from "path";
import fg from "fast-glob";
import type { RawConversation, ConnectorConfig } from "../kb/types.js";
import { BaseConnector } from "./base.js";

export class ClaudeAIConnector extends BaseConnector {
  name = "claude_ai";
  private exportPath: string;

  constructor(config: ConnectorConfig) {
    super(config);
    this.exportPath = config.export_path as string || "";
  }

  async validate(): Promise<boolean> {
    if (!this.exportPath) return false;
    try {
      await fs.access(this.exportPath);
      return true;
    } catch {
      return false;
    }
  }

  async fetch(since?: Date): Promise<RawConversation[]> {
    if (!this.exportPath) return [];

    // Claude.ai export is a directory of JSON files
    const files = await fg("*.json", {
      cwd: this.exportPath,
      absolute: true,
    });

    const results: RawConversation[] = [];

    for (const file of files) {
      try {
        const stat = await fs.stat(file);
        if (since && stat.mtime < since) continue;

        const raw = await fs.readFile(file, "utf-8");
        const conv = JSON.parse(raw);

        const messages = (conv.chat_messages || [])
          .map((m: { sender: string; text: string; created_at?: string }) => ({
            role: m.sender === "human" ? "user" as const : "assistant" as const,
            content: m.text || "",
            timestamp: m.created_at,
          }))
          .filter((m: { content: string }) => m.content.trim());

        if (messages.length > 0) {
          results.push({
            source: "claude_ai",
            id: path.basename(file, ".json"),
            messages,
            timestamp: stat.mtime.toISOString(),
            metadata: { file_path: file, name: conv.name },
          });
        }
      } catch {
        // skip
      }
    }

    return results;
  }
}
