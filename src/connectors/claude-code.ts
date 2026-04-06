import fs from "fs/promises";
import path from "path";
import fg from "fast-glob";
import type { RawConversation, ConnectorConfig } from "../kb/types.js";
import { BaseConnector } from "./base.js";

export class ClaudeCodeConnector extends BaseConnector {
  name = "claude_code";
  private basePath: string;

  constructor(config: ConnectorConfig) {
    super(config);
    this.basePath = (config.path as string) || path.join(process.env.HOME || "~", ".claude");
  }

  async validate(): Promise<boolean> {
    try {
      await fs.access(this.basePath);
      return true;
    } catch {
      return false;
    }
  }

  async fetch(since?: Date): Promise<RawConversation[]> {
    const conversations: RawConversation[] = [];

    // Read conversation JSONL files from ~/.claude/projects/
    const projectsDir = path.join(this.basePath, "projects");
    try {
      await fs.access(projectsDir);
    } catch {
      return conversations;
    }

    const jsonlFiles = await fg("**/*.jsonl", {
      cwd: projectsDir,
      absolute: true,
    });

    for (const file of jsonlFiles) {
      try {
        const stat = await fs.stat(file);
        if (since && stat.mtime < since) continue;

        const content = await fs.readFile(file, "utf-8");
        const lines = content.trim().split("\n").filter(Boolean);

        const messages = [];
        for (const line of lines) {
          try {
            const msg = JSON.parse(line);
            if (msg.type === "human" || msg.type === "assistant") {
              const textContent = typeof msg.message?.content === "string"
                ? msg.message.content
                : Array.isArray(msg.message?.content)
                  ? msg.message.content
                      .filter((b: { type: string }) => b.type === "text")
                      .map((b: { text: string }) => b.text)
                      .join("\n")
                  : "";

              if (textContent) {
                messages.push({
                  role: msg.type === "human" ? "user" as const : "assistant" as const,
                  content: textContent,
                  timestamp: msg.timestamp,
                });
              }
            }
          } catch {
            // skip malformed lines
          }
        }

        if (messages.length > 0) {
          conversations.push({
            source: "claude_code",
            id: path.basename(file, ".jsonl"),
            messages,
            timestamp: stat.mtime.toISOString(),
            metadata: { file_path: file },
          });
        }
      } catch {
        // skip unreadable files
      }
    }

    // Also read memory files
    const memoryFiles = await fg("**/memory/**/*.md", {
      cwd: this.basePath,
      absolute: true,
    });

    for (const file of memoryFiles) {
      try {
        const stat = await fs.stat(file);
        if (since && stat.mtime < since) continue;

        const content = await fs.readFile(file, "utf-8");
        conversations.push({
          source: "claude_code_memory",
          id: `memory-${path.basename(file, ".md")}`,
          messages: [{ role: "system" as const, content }],
          timestamp: stat.mtime.toISOString(),
          metadata: { file_path: file, type: "memory" },
        });
      } catch {
        // skip
      }
    }

    return conversations;
  }
}
