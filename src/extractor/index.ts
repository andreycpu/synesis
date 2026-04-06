import Anthropic from "@anthropic-ai/sdk";
import type {
  RawConversation,
  KnowledgeEntry,
  ExtractionResult,
  ConfigUpdate,
} from "../kb/types.js";

const EXTRACTION_PROMPT = `You are Synesis, a self-evolving knowledge extraction agent. Your job is to extract structured knowledge from conversations.

Analyze the following conversation and extract:
1. **Facts** - concrete things that are true (about the user, their work, their world)
2. **Decisions** - choices made and the reasoning behind them
3. **Preferences** - how the user likes things done, their style, their taste
4. **Contacts** - people mentioned, their roles, relationships
5. **Ideas** - thoughts, plans, aspirations, hypotheses

For each extracted item, output valid JSON in this exact format:
{
  "entries": [
    {
      "title": "short descriptive title",
      "category": "facts|decisions|preferences|contacts|ideas",
      "content": "the actual knowledge, written as a clear statement",
      "tags": ["relevant", "tags"],
      "importance": "high|medium|low"
    }
  ],
  "config_updates": [
    {
      "file": "config/synesis.yaml",
      "path": "some.config.path",
      "value": "new value",
      "reason": "why this config should change based on what was learned"
    }
  ]
}

Rules:
- Only extract genuinely useful, non-obvious knowledge
- Skip small talk, greetings, and trivial exchanges
- Merge related items rather than creating duplicates
- config_updates should only be suggested when you learn something that should change how the system behaves
- Be concise but complete
- If there's nothing worth extracting, return {"entries": [], "config_updates": []}

Conversation:
`;

export class Extractor {
  private client: Anthropic;
  private model: string;

  constructor(model?: string) {
    this.client = new Anthropic();
    this.model = model || "claude-sonnet-4-20250514";
  }

  async extract(conversations: RawConversation[]): Promise<ExtractionResult> {
    const allEntries: KnowledgeEntry[] = [];
    const allConfigUpdates: ConfigUpdate[] = [];

    for (const conv of conversations) {
      const result = await this.extractFromConversation(conv);
      allEntries.push(...result.entries);
      if (result.config_updates) {
        allConfigUpdates.push(...result.config_updates);
      }
    }

    return { entries: allEntries, config_updates: allConfigUpdates };
  }

  private async extractFromConversation(
    conv: RawConversation
  ): Promise<ExtractionResult> {
    const transcript = conv.messages
      .map((m) => `${m.role.toUpperCase()}: ${m.content}`)
      .join("\n\n");

    // Truncate very long conversations
    const maxChars = 50000;
    const truncated =
      transcript.length > maxChars
        ? transcript.slice(0, maxChars) + "\n\n[...truncated]"
        : transcript;

    try {
      const response = await this.client.messages.create({
        model: this.model,
        max_tokens: 4096,
        messages: [
          {
            role: "user",
            content: EXTRACTION_PROMPT + truncated,
          },
        ],
      });

      const text =
        response.content[0].type === "text" ? response.content[0].text : "";

      // Parse JSON from response
      const jsonMatch = text.match(/\{[\s\S]*\}/);
      if (!jsonMatch) return { entries: [] };

      const parsed = JSON.parse(jsonMatch[0]);
      const now = new Date().toISOString();

      const entries: KnowledgeEntry[] = (parsed.entries || []).map(
        (e: {
          title: string;
          category: string;
          content: string;
          tags: string[];
        }) => ({
          id: this.generateId(e.title),
          title: e.title,
          category: e.category || "facts",
          content: e.content,
          source: conv.source,
          tags: e.tags || [],
          created: now,
          updated: now,
          metadata: { conversation_id: conv.id },
        })
      );

      return {
        entries,
        config_updates: parsed.config_updates || [],
      };
    } catch (error) {
      console.error(`Extraction failed for ${conv.id}:`, error);
      return { entries: [] };
    }
  }

  private generateId(title: string): string {
    const slug = title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 50);
    const suffix = Date.now().toString(36).slice(-4);
    return `${slug}-${suffix}`;
  }
}
