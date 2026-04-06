# Synesis

Your conversations, emails, and messages - stored as files on your machine. Any AI agent can navigate them with `grep`, `cat`, `tree`, and `find`.

No LLM extraction. No database. No cloud. Just your raw data as a filesystem that agents already know how to use.

---

## Why not LLM extraction?

Most knowledge base tools run an LLM over your data to "extract" structured knowledge. This is wrong for three reasons:

1. **It's lossy.** The LLM decides at sync time what's important and throws away the rest. Context that matters later gets discarded now.
2. **It's expensive.** Every sync cycle burns API credits to process conversations you already have.
3. **It's unnecessary.** Agents are pre-trained on billions of tokens of filesystem interactions. `grep`, `cat`, `tree`, `find` - these aren't tools agents learn to use. They're tools agents already know.

Synesis takes the opposite approach: store the raw data as files, let agents navigate it at query time. The filesystem is the interface.

---

## Get started

```
pip install synesis
synesis
```

First run, it asks you what to connect:

```
  SYNESIS  self-evolving agent memory
  ------------------------------------------

  Let's set you up. This takes about 30 seconds.

  + Claude Code (auto-detected, no setup needed)

  What else do you want to connect?

  Gmail + Google Calendar + Drive (emails, calendar events, documents)? [y/N]: y
  Client ID for Gmail: ****
  Client Secret for Gmail: ****
  Opening browser...
  + Gmail connected

  Slack (messages and channels)? [y/N]: n
  ...

  Setup complete. You won't need to do this again.
```

After that, it syncs and runs forever. No API keys needed for the core system. No LLM in the loop.

---

## What happens

1. **Syncs** your sources - reads Claude Code conversations from disk, calls Gmail/Slack/etc APIs from your machine
2. **Writes** each conversation as a markdown file in `~/synesis-data/knowledge/`
3. **Sleeps** until the next cycle (every 12 hours by default)

That's it. No extraction, no summarization, no processing. The raw data is the knowledge base.

---

## How agents use it

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "synesis": {
      "command": "synesis-mcp",
      "env": { "SYNESIS_DIR": "~/synesis-data" }
    }
  }
}
```

Now any Claude Code session can navigate your full conversation history:

```
# Orient - what's in the knowledge base?
tree /

# Find files that mention a topic
grep_files "CRE strategy"

# Read a specific conversation
cat claude_code/abc123.md

# Search for exact content
grep "Invesco" /

# Find files by name
find "*strategy*"
```

Agents already know this workflow: `tree` to orient, `grep` to find, `cat` to read. It's how every developer navigates a codebase. The knowledge base is just another directory.

### MCP tools

| Tool | What it does |
|---|---|
| `tree` | Show directory structure |
| `cat` | Read a file |
| `grep` | Search file contents (regex) |
| `grep_files` | List files matching a pattern (like `grep -rl`) |
| `ls` | List directory contents |
| `find` | Find files by name (glob) |
| `write_file` | Write a file (agents can contribute) |
| `sync` | Trigger a sync |
| `stats` | File counts by source |

---

## How context bloat is prevented

The filesystem approach solves context bloat naturally:

**Agents only load what they need.** An agent doesn't dump the entire KB into context. It runs `grep_files "topic"` to find 3 relevant files out of 5,000, then `cat`s those 3. The other 4,997 are never loaded.

**The data is already structured.** Conversations are organized by source (`claude_code/`, `gmail/`, `slack/`). Each file has frontmatter with metadata. Agents can narrow their search to a specific source directory.

**No compression needed.** Since agents navigate the raw files at query time, there's nothing to compress. The filesystem can grow unbounded - agents just grep through it.

---

## Where data lives

```
~/synesis-data/
  config/synesis.yaml         # agent config
  knowledge/                  # your data as files
    claude_code/              # Claude Code conversations
      session-abc123.md
      session-def456.md
    claude_code_memory/       # Claude Code memory files
      memory-project-foo.md
    gmail/                    # email threads
      gmail-thread-xyz.md
    slack/                    # messages
    ...
  .auth/                      # encrypted OAuth tokens
```

Every file is a readable markdown document with YAML frontmatter:

```markdown
---
source: claude_code
id: abc123
synced: 2026-04-06T16:00:00
timestamp: 2026-04-06T14:30:00
---

## USER

How should we approach the CRE vertical?

## ASSISTANT

The commercial real estate market has five main wedges...
```

---

## What gets connected

| Source | How it syncs | Setup |
|---|---|---|
| Claude Code | Reads local files from `~/.claude/` | Automatic |
| Gmail / Calendar / Drive | OAuth, API calls from your machine | Browser login during setup |
| Slack | OAuth, API calls from your machine | Browser login during setup |
| Notion | OAuth, API calls from your machine | Browser login during setup |
| GitHub | OAuth, API calls from your machine | Browser login during setup |
| Twitter / X | OAuth, API calls from your machine | Browser login during setup |
| Linear | OAuth, API calls from your machine | Browser login during setup |
| Spotify | OAuth, API calls from your machine | Browser login during setup |

All data stays on your machine. The only network calls are to the source APIs themselves.

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

Register in `synesis/connectors/__init__.py`. The sync engine writes each returned conversation as a markdown file automatically.

### Project structure

```
synesis/
  auth/          # OAuth (PKCE, encrypted token storage)
  connectors/    # Source plugins
  kb/            # Types and store utilities
  config/        # Configuration manager
  sync/          # Sync engine (raw file writer, no LLM)
  mcp/           # MCP server (filesystem tools: tree, cat, grep, find, ls)
  cli.py         # Entry point
```

---

## License

MIT
