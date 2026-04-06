# Synesis

A self-evolving agent memory system. Connect all your AI tools, conversations, and services into a single knowledge base that any agent can access. The system extracts structured knowledge, compresses it to stay within context limits, and autonomously rewrites its own configuration as it learns about you.

Everything is stored as plain markdown files. Fully observable, fully git-trackable. No black boxes.

---

## How it works

Synesis operates as a continuous loop with five stages:

```
  Ingest          Extract          Store          Compress          Serve
┌─────────┐    ┌──────────┐    ┌──────────┐    ┌───────────┐    ┌─────────┐
│ Connect  │───>│ LLM pass │───>│ Markdown │───>│ Compactor │───>│  MCP    │
│ to your  │    │ pulls    │    │ files w/ │    │ merges    │    │ server  │
│ sources  │    │ facts,   │    │ YAML     │    │ related   │    │ returns │
│ via OAuth│    │ decisions│    │ front-   │    │ entries,  │    │ only    │
│ or local │    │ prefs,   │    │ matter   │    │ archives  │    │ what's  │
│ files    │    │ contacts │    │          │    │ originals │    │relevant │
└─────────┘    └──────────┘    └──────────┘    └───────────┘    └─────────┘
                                                    │
                                              ┌─────┴──────┐
                                              │Self-modify │
                                              │config based│
                                              │on patterns │
                                              └────────────┘
```

### 1. Ingest

Connectors pull raw data from your sources. Some read local files (Claude Code conversations, ChatGPT exports), others authenticate via OAuth with PKCE (Gmail, Slack, Twitter, Notion, GitHub, and more). Each connector implements a simple interface: validate access, then fetch conversations since last sync.

Supported connectors:
- **Claude Code** - reads conversation history and memory files from `~/.claude`
- **ChatGPT** - parses the JSON export from OpenAI
- **Claude.ai** - parses the JSON export from Anthropic
- **Gmail** - authenticates via Google OAuth, fetches email threads from your inbox
- More coming: Slack, Twitter/X, Notion, GitHub, Linear, Spotify

### 2. Extract

An LLM processes each conversation and extracts structured knowledge into five categories:

| Category | What it captures |
|---|---|
| **Facts** | Concrete truths - about you, your work, your world |
| **Decisions** | Choices made and the reasoning behind them |
| **Preferences** | How you like things done, your style, your taste |
| **Contacts** | People mentioned, their roles, relationships |
| **Ideas** | Thoughts, plans, aspirations, hypotheses |

The extractor also proposes configuration changes when it detects patterns (e.g., noticing you use a tool it doesn't have a connector for yet).

### 3. Store

Each knowledge entry becomes a markdown file with YAML frontmatter:

```markdown
---
id: cre-vertical-strategy
title: CRE as first vertical for product-market fit
category: decisions
source: claude_code
tags: [cre, strategy, pmf]
created: 2026-04-06T12:00:00Z
updated: 2026-04-06T12:00:00Z
---

Chose commercial real estate as the first vertical. Legacy CRE software is ripe
for AI disruption. A 7-figure contract becomes the proof point for fundraising.
Top wedge: Deal Intelligence + Capital Access if the Invesco connection pans out.
```

Files live in `knowledge/` organized by category. Everything is git-tracked.

### 4. Compress

This is how context bloat is solved. Three mechanisms work together:

**Ranked retrieval** - The search index scores every entry against a query using TF-IDF cosine similarity. When an agent asks for context, it specifies a token budget (e.g., 8,000 tokens). The system returns only the highest-ranked entries that fit within that budget. The knowledge base can have 10,000 entries and the agent only sees the 5-10 that matter.

**Automatic compaction** - After each sync, if any category exceeds 50 entries, the compactor groups related entries by tag overlap and title similarity, merges each group into a single denser entry via LLM, and moves the originals to `_archive/`. The knowledge base self-compresses over time while preserving everything on disk.

**Category summaries** - On demand, the system generates a single-paragraph overview of an entire category. Agents can orient quickly ("what do I know about contacts?") without loading individual entries.

The result: the knowledge base grows unbounded on disk, but the context window stays lean.

### 5. Serve

The MCP server exposes the knowledge base to any AI agent. Available tools:

| Tool | Purpose |
|---|---|
| `search` | TF-IDF ranked search, returns top-k results |
| `context` | Budget-aware retrieval - fits results within a token limit |
| `list` | List entries, optionally filtered by category |
| `read` | Read a specific entry by category and ID |
| `write` | Write a new entry |
| `delete` | Delete an entry |
| `compact` | Trigger compaction manually |
| `summarize` | Generate a category summary |
| `sync` | Trigger a full sync cycle |
| `get_config` | Read current configuration |

### Self-modification

Synesis rewrites its own `config/synesis.yaml` autonomously. No approval gates. When the extractor detects a pattern - you mention a tool it doesn't track, you show a preference for certain categories, you change how you work - it updates its own configuration to adapt.

All config changes are git-tracked, so you have a full audit trail.

---

## Quick start

```bash
# Clone and install
git clone https://github.com/andreycpu/synesis.git
cd synesis
npm install
npm run build

# Initialize the knowledge base
npx synesis init

# Run your first sync (ingests Claude Code conversations)
ANTHROPIC_API_KEY=sk-... npx synesis sync

# Search your knowledge
npx synesis search "project strategy"

# Run as a daemon (syncs every 12 hours by default)
ANTHROPIC_API_KEY=sk-... npx synesis daemon
```

### Authenticate with OAuth services

```bash
# Gmail
npx synesis auth login google --client-id YOUR_ID --client-secret YOUR_SECRET

# View authenticated providers
npx synesis auth list

# Revoke access
npx synesis auth revoke google
```

### Connect via MCP

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "synesis": {
      "command": "node",
      "args": ["/path/to/synesis/dist/mcp/server.js"],
      "env": {
        "SYNESIS_DIR": "/path/to/synesis",
        "ANTHROPIC_API_KEY": "sk-..."
      }
    }
  }
}
```

Now any Claude Code session can search, read, and write to your knowledge base.

---

## Architecture

```
synesis/
  config/
    synesis.yaml           # self-modifying configuration
    connectors/            # per-connector config
  knowledge/               # the knowledge base (markdown files)
    facts/
    decisions/
    preferences/
    contacts/
    ideas/
    _archive/              # compacted originals
    _summaries/            # category summaries
  src/
    auth/                  # OAuth infrastructure
      oauth.ts             # PKCE flow, token refresh
      store.ts             # encrypted token storage
      providers.ts         # provider templates
    connectors/            # source plugins
      claude-code.ts       # local file reader
      chatgpt.ts           # JSON export parser
      claude-ai.ts         # JSON export parser
      gmail.ts             # OAuth + Gmail API
    extractor/             # LLM knowledge extraction
    kb/
      store.ts             # markdown file CRUD
      search.ts            # TF-IDF search index
      compactor.ts         # hierarchical summarization
    config/                # self-modification engine
    sync/                  # orchestration
    mcp/                   # MCP server
    cli.ts                 # CLI interface
```

## Adding a connector

Extend `BaseConnector` and register it in `src/connectors/index.ts`:

```typescript
export class MyConnector extends BaseConnector {
  name = "my_service";

  async validate(): Promise<boolean> {
    // Check if the source is accessible
  }

  async fetch(since?: Date): Promise<RawConversation[]> {
    // Pull conversations since the given date
  }
}
```

For OAuth-backed connectors, add a provider template in `src/auth/providers.ts` and use `OAuthManager` to handle authentication.

## Configuration

`config/synesis.yaml` controls everything. The agent modifies this file as it learns, but you can edit it manually too.

Key settings:
- `sync_schedule` - cron expression for automatic sync (default: every 12 hours)
- `extraction.model` - which LLM to use for extraction
- `self_modify.enabled` - toggle autonomous self-modification
- `connectors` - enable/disable and configure each source

## License

MIT
