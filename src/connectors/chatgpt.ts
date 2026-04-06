import fs from "fs/promises";
import path from "path";
import type { RawConversation, ConnectorConfig } from "../kb/types.js";
import { BaseConnector } from "./base.js";

interface ChatGPTExport {
  title: string;
  create_time: number;
  update_time: number;
  mapping: Record<string, {
    message?: {
      author: { role: string };
      content: { parts?: string[] };
      create_time?: number;
    };
  }>;
}

export class ChatGPTConnector extends BaseConnector {
  name = "chatgpt";
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

    const raw = await fs.readFile(
      path.join(this.exportPath, "conversations.json"),
      "utf-8"
    );
    const conversations: ChatGPTExport[] = JSON.parse(raw);
    const results: RawConversation[] = [];

    for (const conv of conversations) {
      const convDate = new Date(conv.update_time * 1000);
      if (since && convDate < since) continue;

      const messages = Object.values(conv.mapping)
        .filter((m) => m.message && m.message.author.role !== "system")
        .sort((a, b) => (a.message?.create_time || 0) - (b.message?.create_time || 0))
        .map((m) => ({
          role: m.message!.author.role as "user" | "assistant",
          content: m.message!.content.parts?.join("\n") || "",
          timestamp: m.message!.create_time
            ? new Date(m.message!.create_time * 1000).toISOString()
            : undefined,
        }))
        .filter((m) => m.content.trim());

      if (messages.length > 0) {
        results.push({
          source: "chatgpt",
          id: conv.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 60),
          messages,
          timestamp: convDate.toISOString(),
          metadata: { title: conv.title },
        });
      }
    }

    return results;
  }
}
