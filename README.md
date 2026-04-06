# Synesis

A self-evolving agent memory system. Install it, run it, it asks you what to connect, then it handles everything forever.

No manual syncing. No config files. No dashboards to check. The agent runs autonomously on your machine, ingests your conversations, extracts knowledge, compresses it to prevent context bloat, and serves it to any AI tool.

---

## Get started

```bash
pip install synesis
synesis
```

That's it. On first run, Synesis walks you through setup:

```
  SYNESIS  self-evolving agent memory
  ------------------------------------------

  Let's set you up. This takes about 30 seconds.

  Enter your ANTHROPIC_API_KEY: ****

  + Claude Code (auto-detected, no setup needed)

  What else do you want to connect?

  Gmail + Google Calendar + Drive (emails, calendar events, documents)? [y/N]: y
  Client ID for Gmail: ****
  Client Secret for Gmail: ****
  Opening browser for Gmail authentication...
  + Gmail connected

  Slack (messages and channels)? [y/N]: n
  Notion (pages and databases)? [y/N]: y
  ...

  Setup complete. You won't need to do this again.
```

After setup, the agent syncs immediately and then runs on a 12-hour loop. You never interact with it again unless you want to.

---

## What happens after you run it

1. **Ingests** - reads your Claude Code conversations from `~/.claude/`, calls Gmail API, hits whatever else you connected. All local, nothing goes to a cloud service.
2. **Extracts** - sends conversations through an LLM to pull out facts, decisions, preferences, contacts, and ideas. This is the only external call (Anthropic API).
3. **Stores** - writes each piece of knowledge as a markdown file in `~/synesis-data/knowledge/`. You can open any file and read it.
4. **Compresses** - if any category exceeds 50 entries, merges related ones into denser entries. Originals are archived, never deleted. Your context window stays clean.
5. **Self-modifies** - rewrites its own config based on patterns it detects. No approval needed.
6. **Sleeps** - waits until the next sync cycle and repeats.

---

## How context bloat is prevented

This is the core problem. Your knowledge base grows, but context windows are finite. Three layers solve this:

**Ranked retrieval** - when an agent queries the KB, the search index scores every entry against the query and returns only what fits within a token budget. 5,000 entries in the KB, but the agent only sees the 8 most relevant ones.

**Automatic compaction** - after every sync, related entries get merged into denser summaries. 200 raw entries become 40 dense ones over time. Originals stay on disk in `_archive/`.

**Category summaries** - one-paragraph overviews of entire categories. Quick orientation without loading individual entries.

---

## How agents access the knowledge base

Add this to `~/.claude.json`:

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

Now any Claude Code session can query your full knowledge base. The main tool is `context` - it returns the most relevant entries that fit within a token budget. Agents can also `write` new entries, so the KB grows from both your conversations and agent activity.

---

## What gets connected

| Source | How it syncs | Setup |
|---|---|---|
| Claude Code | Reads local files at `~/.claude/` | Automatic, no setup |
| Gmail / Calendar / Drive | OAuth, calls Google API from your machine | Browser login during setup |
| Slack | OAuth, calls Slack API from your machine | Browser login during setup |
| Notion | OAuth, calls Notion API from your machine | Browser login during setup |
| GitHub | OAuth, calls GitHub API from your machine | Browser login during setup |
| Twitter / X | OAuth, calls Twitter API from your machine | Browser login during setup |
| Linear | OAuth, calls Linear API from your machine | Browser login during setup |
| Spotify | OAuth, calls Spotify API from your machine | Browser login during setup |
| ChatGPT | JSON export from OpenAI (Settings > Export) | Drop the file path in config |
| Claude.ai | JSON export from Anthropic | Drop the file path in config |

All API calls happen from your machine. Data never passes through a third-party cloud service.

---

## Where data lives

```
~/synesis-data/
  config/synesis.yaml       # agent config (self-modifying)
  knowledge/                # your knowledge base (markdown files)
    facts/
    decisions/
    preferences/
    contacts/
    ideas/
    _archive/               # compacted originals
    _summaries/             # auto-generated overviews
  .auth/                    # encrypted OAuth tokens
  .env                      # API key (created during setup)
```

---

## For developers

### Adding a connector

```python
from synesis.connectors.base import BaseConnector
from synesis.kb.types import RawConversation

class MyConnector(BaseConnector):
    name = "my_service"

    def validate(self) -> bool: ...
    def fetch(self, since: str | None = None) -> list[RawConversation]: ...
```

Register in `synesis/connectors/__init__.py`. For OAuth connectors, add a provider template in `synesis/auth/providers.py`.

### Project structure

```
synesis/
  auth/          # OAuth (PKCE, encrypted token storage, provider templates)
  connectors/    # Source plugins
  extractor/     # LLM knowledge extraction
  kb/            # Store, TF-IDF search, compactor
  config/        # Self-modification engine
  sync/          # Orchestration
  mcp/           # MCP server
  cli.py         # Entry point
```

---

## License

MIT
