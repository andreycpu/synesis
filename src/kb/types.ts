export interface KnowledgeEntry {
  id: string;
  title: string;
  category: string;
  content: string;
  source: string;
  tags: string[];
  created: string;
  updated: string;
  metadata: Record<string, unknown>;
}

export interface SynesisConfig {
  knowledge_dir: string;
  sync_schedule: string;
  categories: string[];
  extraction: {
    provider: string;
    model: string;
    extract: string[];
  };
  self_modify: {
    enabled: boolean;
    modifiable: string[];
  };
  connectors: Record<string, ConnectorConfig>;
}

export interface ConnectorConfig {
  enabled: boolean;
  [key: string]: unknown;
}

export interface RawConversation {
  source: string;
  id: string;
  messages: ConversationMessage[];
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface ConversationMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: string;
}

export interface ExtractionResult {
  entries: KnowledgeEntry[];
  config_updates?: ConfigUpdate[];
}

export interface ConfigUpdate {
  file: string;
  path: string;
  value: unknown;
  reason: string;
}
