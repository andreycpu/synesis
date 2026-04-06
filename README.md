# Synesis

A self-evolving agent memory system that runs locally on your machine. Install it, start it, forget about it. The agent watches your AI conversations, extracts what matters, compresses it to prevent context bloat, and serves it to any AI tool via MCP.

No cloud. No manual syncing. No databases. Just markdown files on your disk that the agent manages autonomously.

---

## Install and run

```bash
pip install synesis
export ANTHROPIC_API_KEY=sk-...
synesis
```

Three commands. The agent is now running. Here's what happens next, without you doing anything:

1. It finds your Claude Code conversations at `~/.claude/` and reads them
2. It sends each conversation through an LLM to extract facts, decisions, preferences, contacts, and ideas
3. It writes each piece of knowledge as a markdown file in `~/synesis-data/knowledge/`
4. If any category gets too large, it merges related entries to keep things compact
5. It checks whether it should modify its own configuration based on what it learned
6. It sleeps until the next scheduled sync (every 12 hours by default) and repeats

You can close the terminal and restart `synesis` whenever - it picks up where it left off.

---

## Where does the data live?

Everything is local. Nothing leaves your machine except API calls to Anthropic for the LLM extraction pass.

```
~/synesis-data/
  config/synesis.yaml       # the agent's config (it rewrites this itself)
  knowledge/                # your knowledge base
    facts/                  # things that are true
      cre-vertical-strategy.md
      andrey-is-solo-founder.md
    decisions/              # choices and reasoning
    preferences/            # how you like things
    contacts/               # people and relationships
    ideas/                  # thoughts and plans
    _archive/               # compacted originals (nothing is deleted)
    _summaries/             # auto-generated category overviews
  .auth/                    # encrypted OAuth tokens (never leaves disk)
  .sync-state.json          # last sync timestamp
```

Every knowledge entry is a markdown file you can open and read:

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

Chose commercial real estate as the first vertical. Legacy CRE software
is ripe for AI disruption. A 7-figure contract becomes the proof point
for fundraising. Top wedge: Deal Intelligence + Capital Access.
```

---

## How sync works

Synesis syncs by reading data sources directly. No intermediary cloud service.

| Source | How it reads | Auth required |
|---|---|---|
| **Claude Code** | Reads `~/.claude/projects/**/*.jsonl` and memory files directly from disk | None - it's local files |
| **ChatGPT** | Parses the JSON export you download from OpenAI (Settings > Export) | None - you drop the folder path in config |
| **Claude.ai** | Parses the JSON export you download from Anthropic | None - same as above |
| **Gmail** | Calls Gmail API from your machine using OAuth tokens stored locally | OAuth (one-time browser login) |
| **Slack, Twitter, Notion, GitHub, Linear, Spotify** | Same pattern - OAuth + direct API calls from your machine | OAuth |

To add an OAuth source:

```bash
synesis connect google --client-id YOUR_ID --client-secret YOUR_SECRET
```

This opens your browser once for authentication. Tokens are encrypted and stored locally at `~/synesis-data/.auth/`. After that, the agent syncs this source automatically on every cycle.

---

## How context bloat is prevented

This is the core problem Synesis solves. Your knowledge base grows over time, but context windows are finite. Three mechanisms keep things lean:

### 1. Ranked retrieval with token budgets

When an agent queries the knowledge base, it doesn't get everything. The search index scores every entry against the query using TF-IDF cosine similarity and returns only the top results that fit within a token budget.

Example: your KB has 5,000 entries. An agent asks "what do I know about CRE strategy?" The MCP server returns the 8 most relevant entries that fit within 8,000 tokens. The other 4,992 entries are never loaded.

### 2. Automatic compaction

After every sync, the agent checks each category. If any category exceeds 50 entries, it:
- Groups related entries by tag overlap and title similarity
- Merges each group into a single, denser entry using the LLM
- Moves the originals to `_archive/` (nothing is ever deleted)

Over time, your knowledge base self-compresses. 200 raw entries might become 40 dense ones, with the originals preserved on disk if you ever need them.

### 3. Category summaries

On demand, the agent generates a one-paragraph overview of an entire category. An agent can ask "summarize contacts" and get a quick orientation without loading any individual entries.

**The result:** the knowledge base grows unbounded on disk, but the context window only ever sees what's relevant and what fits.

---

## How agents access the knowledge base

Synesis exposes an MCP server that any AI tool can connect to. Add this to `~/.claude.json`:

```json
{
  "mcpServers": {
    "synesis": {
      "command": "synesis-mcp",
      "env": {
        "SYNESIS_DIR": "~/synesis-data",
        "ANTHROPIC_API_KEY": "sk-..."
      }
    }
  }
}
```

Now any Claude Code session has access to your full knowledge base. The MCP server provides these tools:

| Tool | What it does |
|---|---|
| `context` | Returns the most relevant entries that fit within a token budget. This is the main tool agents should use. |
| `search` | TF-IDF ranked search, returns top-k results |
| `list` | List entries by category |
| `read` | Read a specific entry |
| `write` | Add a new entry (agents can contribute knowledge too) |
| `delete` | Remove an entry |
| `compact` | Trigger compaction |
| `summarize` | Generate a category summary |
| `sync` | Trigger a sync cycle |
| `get_config` | Read current configuration |

---

## Self-modification

The agent rewrites its own `config/synesis.yaml` based on patterns it detects. No approval required.

Examples of what it might change:
- Enable a connector it notices you mention frequently
- Adjust extraction categories based on what kind of knowledge you generate
- Change the sync schedule if it detects you're most active at certain times

All modifications happen in `config/synesis.yaml`, which is a plain text file you can inspect anytime. If you're tracking `~/synesis-data/` with git, you get a full audit trail of every self-modification.

---

## CLI reference

```bash
synesis              # start the agent (runs autonomously)
synesis status       # show what it knows (entry counts, sources, schedule)
synesis ask "query"  # search the knowledge base from the terminal
synesis connections  # show connected accounts and their status
synesis connect <provider> --client-id ID --client-secret SECRET
```

The `synesis` command with no arguments is the primary way to use it. Everything else is optional - the agent handles itself.

---

## For developers

### Adding a connector

```python
from synesis.connectors.base import BaseConnector
from synesis.kb.types import RawConversation

class MyConnector(BaseConnector):
    name = "my_service"

    def validate(self) -> bool:
        # Return True if the source is accessible
        ...

    def fetch(self, since: str | None = None) -> list[RawConversation]:
        # Pull conversations since the given ISO timestamp
        ...
```

Register it in `synesis/connectors/__init__.py`. For OAuth-backed connectors, add a provider template in `synesis/auth/providers.py`.

### Project structure

```
synesis/
  auth/          # OAuth (PKCE flow, encrypted token storage, provider templates)
  connectors/    # Source plugins (claude_code, chatgpt, claude_ai, gmail)
  extractor/     # LLM knowledge extraction
  kb/            # Store, search index, compactor, types
  config/        # Self-modification engine
  sync/          # Orchestration
  mcp/           # MCP server (FastMCP)
  cli.py         # Agent entry point
```

---

## License

MIT
