import type { RawConversation, ConnectorConfig } from "../kb/types.js";
import { BaseConnector } from "./base.js";
import { OAuthManager } from "../auth/oauth.js";
import { getProvider } from "../auth/providers.js";

interface GmailMessage {
  id: string;
  threadId: string;
  snippet: string;
  payload: {
    headers: { name: string; value: string }[];
    body?: { data?: string };
    parts?: { mimeType: string; body?: { data?: string } }[];
  };
  internalDate: string;
}

interface GmailThread {
  id: string;
  messages: GmailMessage[];
}

export class GmailConnector extends BaseConnector {
  name = "gmail";
  private oauth: OAuthManager;
  private projectDir: string;

  constructor(config: ConnectorConfig) {
    super(config);
    this.projectDir = (config.project_dir as string) || process.cwd();
    this.oauth = new OAuthManager(this.projectDir);
  }

  async validate(): Promise<boolean> {
    await this.oauth.init();
    const token = await this.oauth.getToken("google");
    return token !== null;
  }

  async fetch(since?: Date): Promise<RawConversation[]> {
    await this.oauth.init();

    const provider = getProvider(
      "google",
      this.config.client_id as string,
      this.config.client_secret as string
    );
    if (!provider) return [];

    const tokens = await this.oauth.authenticate(provider);
    const conversations: RawConversation[] = [];

    // Build search query
    let query = "in:inbox";
    if (since) {
      const dateStr = since.toISOString().split("T")[0].replace(/-/g, "/");
      query += ` after:${dateStr}`;
    }
    // Filter for meaningful emails (skip promotions/spam)
    query += " -category:promotions -category:social -category:updates";

    const maxResults = (this.config.max_results as number) || 50;

    // List threads
    const listUrl = `https://gmail.googleapis.com/gmail/v1/users/me/threads?q=${encodeURIComponent(query)}&maxResults=${maxResults}`;
    const listRes = await this.gmailFetch(listUrl, tokens.access_token);

    if (!listRes.threads) return [];

    for (const threadRef of listRes.threads) {
      try {
        const threadUrl = `https://gmail.googleapis.com/gmail/v1/users/me/threads/${threadRef.id}?format=full`;
        const thread: GmailThread = await this.gmailFetch(threadUrl, tokens.access_token);

        const messages = thread.messages.map((msg) => {
          const from = this.getHeader(msg, "From") || "unknown";
          const subject = this.getHeader(msg, "Subject") || "No subject";
          const body = this.extractBody(msg);
          const role = from.includes(this.config.user_email as string)
            ? "user" as const
            : "assistant" as const;

          return {
            role,
            content: `From: ${from}\nSubject: ${subject}\n\n${body}`,
            timestamp: new Date(parseInt(msg.internalDate)).toISOString(),
          };
        });

        if (messages.length > 0) {
          const subject = this.getHeader(thread.messages[0], "Subject") || "No subject";
          conversations.push({
            source: "gmail",
            id: `gmail-${thread.id}`,
            messages,
            timestamp: new Date(
              parseInt(thread.messages[thread.messages.length - 1].internalDate)
            ).toISOString(),
            metadata: { thread_id: thread.id, subject },
          });
        }
      } catch {
        // skip failed threads
      }
    }

    return conversations;
  }

  private getHeader(msg: GmailMessage, name: string): string | undefined {
    return msg.payload.headers.find(
      (h) => h.name.toLowerCase() === name.toLowerCase()
    )?.value;
  }

  private extractBody(msg: GmailMessage): string {
    // Try plain text part first
    if (msg.payload.parts) {
      const textPart = msg.payload.parts.find(
        (p) => p.mimeType === "text/plain"
      );
      if (textPart?.body?.data) {
        return Buffer.from(textPart.body.data, "base64url").toString("utf-8");
      }
    }

    // Fall back to body
    if (msg.payload.body?.data) {
      return Buffer.from(msg.payload.body.data, "base64url").toString("utf-8");
    }

    return msg.snippet || "";
  }

  private async gmailFetch(url: string, accessToken: string): Promise<any> {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!res.ok) {
      throw new Error(`Gmail API error: ${res.status} ${await res.text()}`);
    }
    return res.json();
  }
}
