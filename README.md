# Synesis

Self-evolving agent memory system. A file-based, MCP-accessible knowledge base that automatically ingests conversations from AI tools, extracts structured knowledge, and autonomously rewrites its own configuration to get smarter over time.

## What it does

1. **Connects** to your AI conversation sources (Claude Code, ChatGPT, Claude.ai, more coming)
2. **Extracts** structured knowledge: facts, decisions, preferences, contacts, ideas
3. **Stores** everything as markdown files with YAML frontmatter - fully observable, git-trackable
4. **Self-modifies** its own configuration based on what it learns about you
5. **Exposes an MCP server** so any AI agent can read/write your knowledge base

No approval gates. The agent is trusted to evolve autonomously. You can intervene anytime, but shouldn't have to.

## Quick start

```bash
# Install
npm install

# Initialize
npx synesis init

# Run your first sync (extracts knowledge from Claude Code conversations)
ANTHROPIC_API_KEY=your-key npx synesis sync

# Search your knowledge
npx synesis search "some topic"

# Run as daemon (syncs on schedule)
ANTHROPIC_API_KEY=your-key npx synesis daemon
```

## MCP Server

Add to your Claude Code config (`~/.claude.json`):

```json
{
  "mcpServers": {
    "synesis": {
      "command": "node",
      "args": ["/path/to/synesis/dist/mcp/server.js"],
      "env": {
        "SYNESIS_DIR": "/path/to/synesis",
        "ANTHROPIC_API_KEY": "your-key"
      }
    }
  }
}
```

Available MCP tools:
- `search` - search the knowledge base
- `list` - list entries by category
- `read` - read a specific entry
- `write` - write a new entry
- `delete` - delete an entry
- `sync` - trigger a sync cycle
- `get_config` - read current configuration

## Architecture

```
synesis/
  config/synesis.yaml    # self-modifying config
  knowledge/             # the KB (markdown files)
    facts/
    decisions/
    preferences/
    contacts/
    ideas/
  src/
    connectors/          # source plugins
    extractor/           # LLM knowledge extraction
    config/              # self-modification engine
    sync/                # orchestration
    mcp/                 # MCP server
    cli.ts               # CLI interface
```

## Adding connectors

Extend `BaseConnector` in `src/connectors/` and register it in the index. Each connector needs:
- `name` - unique identifier
- `validate()` - check if the source is accessible
- `fetch(since?)` - pull conversations since a given date

## Self-modification

Synesis modifies its own `config/synesis.yaml` based on what it learns. For example, if it detects you use a new AI tool, it can enable that connector. If it notices you care more about certain categories, it can adjust extraction priorities.

All changes are git-tracked, so you have full audit history.

## License

MIT
