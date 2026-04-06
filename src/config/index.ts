import fs from "fs/promises";
import path from "path";
import YAML from "yaml";
import type { SynesisConfig, ConfigUpdate } from "../kb/types.js";

const DEFAULT_CONFIG: SynesisConfig = {
  knowledge_dir: "./knowledge",
  sync_schedule: "0 */12 * * *",
  categories: ["facts", "decisions", "preferences", "contacts", "ideas"],
  extraction: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    extract: ["facts", "decisions", "preferences", "contacts", "action_items", "ideas"],
  },
  self_modify: {
    enabled: true,
    modifiable: ["config/synesis.yaml", "config/connectors/*.yaml", "knowledge/**/*.md"],
  },
  connectors: {
    claude_code: { enabled: true, path: path.join(process.env.HOME || "~", ".claude") },
    chatgpt: { enabled: false },
    claude_ai: { enabled: false },
  },
};

export class ConfigManager {
  private config: SynesisConfig | null = null;

  constructor(private configPath: string) {}

  async load(): Promise<SynesisConfig> {
    try {
      const raw = await fs.readFile(this.configPath, "utf-8");
      this.config = YAML.parse(raw) as SynesisConfig;
    } catch {
      this.config = DEFAULT_CONFIG;
      await this.save();
    }
    return this.config;
  }

  async save(): Promise<void> {
    if (!this.config) return;
    await fs.mkdir(path.dirname(this.configPath), { recursive: true });
    await fs.writeFile(this.configPath, YAML.stringify(this.config), "utf-8");
  }

  async applyUpdates(updates: ConfigUpdate[]): Promise<string[]> {
    if (!this.config || !this.config.self_modify.enabled) return [];

    const applied: string[] = [];

    for (const update of updates) {
      // Only modify allowed files
      const isAllowed = this.config.self_modify.modifiable.some((pattern) => {
        const regex = new RegExp(
          "^" + pattern.replace(/\*/g, ".*").replace(/\?/g, ".") + "$"
        );
        return regex.test(update.file);
      });

      if (!isAllowed) {
        console.log(`Self-modify blocked: ${update.file} not in modifiable list`);
        continue;
      }

      if (update.file === "config/synesis.yaml") {
        this.setNestedValue(this.config, update.path, update.value);
        await this.save();
        applied.push(`${update.path} = ${JSON.stringify(update.value)} (${update.reason})`);
      }
    }

    return applied;
  }

  get(): SynesisConfig {
    if (!this.config) throw new Error("Config not loaded. Call load() first.");
    return this.config;
  }

  private setNestedValue(obj: object, path: string, value: unknown): void {
    const target = obj as Record<string, unknown>;
    const keys = path.split(".");
    let current: Record<string, unknown> = target;
    for (let i = 0; i < keys.length - 1; i++) {
      if (!(keys[i] in current) || typeof current[keys[i]] !== "object") {
        current[keys[i]] = {};
      }
      current = current[keys[i]] as Record<string, unknown>;
    }
    current[keys[keys.length - 1]] = value;
  }
}
