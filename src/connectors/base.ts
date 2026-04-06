import type { RawConversation, ConnectorConfig } from "../kb/types.js";

export abstract class BaseConnector {
  abstract name: string;

  constructor(protected config: ConnectorConfig) {}

  abstract fetch(since?: Date): Promise<RawConversation[]>;

  abstract validate(): Promise<boolean>;
}
