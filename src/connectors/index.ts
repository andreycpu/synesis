import type { ConnectorConfig } from "../kb/types.js";
import { BaseConnector } from "./base.js";
import { ClaudeCodeConnector } from "./claude-code.js";
import { ChatGPTConnector } from "./chatgpt.js";
import { ClaudeAIConnector } from "./claude-ai.js";
import { GmailConnector } from "./gmail.js";

const CONNECTOR_REGISTRY: Record<
  string,
  new (config: ConnectorConfig) => BaseConnector
> = {
  claude_code: ClaudeCodeConnector,
  chatgpt: ChatGPTConnector,
  claude_ai: ClaudeAIConnector,
  gmail: GmailConnector,
};

export function createConnector(
  name: string,
  config: ConnectorConfig
): BaseConnector | null {
  const Constructor = CONNECTOR_REGISTRY[name];
  if (!Constructor) return null;
  return new Constructor(config);
}

export function listConnectors(): string[] {
  return Object.keys(CONNECTOR_REGISTRY);
}

export { BaseConnector } from "./base.js";
