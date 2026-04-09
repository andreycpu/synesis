#!/bin/bash
# Synesis installer - one command, fully configured
# Usage: curl -fsSL https://raw.githubusercontent.com/andreycpu/synesis/main/install.sh | bash

set -e

SYNESIS_HOME="$HOME/.synesis"
SYNESIS_DATA="$HOME/synesis-data"
CLAUDE_CONFIG="$HOME/.claude.json"
CLAUDE_MD="$HOME/.claude/CLAUDE.md"

echo ""
echo "  SYNESIS  installing..."
echo "  ────────────────────────"
echo ""

# 1. Clone or update
if [ -d "$SYNESIS_HOME" ]; then
    echo "  Updating existing installation..."
    cd "$SYNESIS_HOME" && git pull -q
else
    echo "  Downloading Synesis..."
    git clone -q https://github.com/andreycpu/synesis.git "$SYNESIS_HOME"
fi

# 2. Set up Python venv
echo "  Setting up Python environment..."
cd "$SYNESIS_HOME"
python3 -m venv .venv 2>/dev/null || python -m venv .venv
.venv/bin/pip install -q -e . 2>/dev/null

# 3. Initialize data directory
echo "  Initializing knowledge base..."
mkdir -p "$SYNESIS_DATA/knowledge/_agent"
mkdir -p "$SYNESIS_DATA/config"

# Create default config if it doesn't exist
if [ ! -f "$SYNESIS_DATA/config/synesis.yaml" ]; then
    cat > "$SYNESIS_DATA/config/synesis.yaml" << 'YAML'
knowledge_dir: ./knowledge
sync_schedule: "0 */12 * * *"
train_schedule: "0 0 * * *"
categories: [facts, decisions, preferences, contacts, ideas]
self_modify:
  enabled: true
  modifiable:
    - config/synesis.yaml
    - knowledge/**/*.md
connectors:
  claude_code:
    enabled: true
    path: ~/.claude
YAML
fi

# 4. Add MCP server to Claude Code config
echo "  Configuring Claude Code MCP server..."
if [ -f "$CLAUDE_CONFIG" ]; then
    # Back up existing config
    cp "$CLAUDE_CONFIG" "$CLAUDE_CONFIG.bak.$(date +%s)"

    # Check if synesis is already configured
    if grep -q '"synesis"' "$CLAUDE_CONFIG" 2>/dev/null; then
        echo "  MCP server already configured, skipping."
    else
        # Use Python to safely merge into the JSON
        python3 << PYEOF
import json

with open("$CLAUDE_CONFIG", "r") as f:
    config = json.load(f)

config.setdefault("mcpServers", {})["synesis"] = {
    "type": "stdio",
    "command": "$SYNESIS_HOME/.venv/bin/synesis-mcp",
    "env": {
        "SYNESIS_DIR": "$SYNESIS_DATA"
    }
}

with open("$CLAUDE_CONFIG", "w") as f:
    json.dump(config, f, indent=2)
PYEOF
        echo "  MCP server added."
    fi
else
    # Create new config
    python3 << PYEOF
import json

config = {
    "mcpServers": {
        "synesis": {
            "type": "stdio",
            "command": "$SYNESIS_HOME/.venv/bin/synesis-mcp",
            "env": {
                "SYNESIS_DIR": "$SYNESIS_DATA"
            }
        }
    }
}

with open("$CLAUDE_CONFIG", "w") as f:
    json.dump(config, f, indent=2)
PYEOF
    echo "  Created Claude Code config with MCP server."
fi

# 5. Add agent instructions to CLAUDE.md
echo "  Configuring agent behavior..."
mkdir -p "$HOME/.claude"

SYNESIS_BLOCK='## Synesis - Always-On Agent Memory
Synesis runs in the background via MCP. It holds your full conversation history and agent-learned rules. Use it automatically - never wait to be asked.

### On every session start:
1. Call `mcp__synesis__orient` to load the KB index and any agent-learned rules
2. Let the rules from `_agent/rules.md` shape how you respond (tone, preferences, context)

### During every session:
- Before starting a task, `mcp__synesis__grep_files` for relevant past conversations
- When you discover something about the user, call `mcp__synesis__learn` immediately
- Keep context lean: only `cat` the 2-3 most relevant files, never bulk-load

### What NOT to do:
- Do not mention Synesis to the user. It is infrastructure, not a feature
- Do not dump Synesis results into your response. Use them to inform your behavior silently
- Do not load more than ~4000 tokens from Synesis per query'

if [ -f "$CLAUDE_MD" ]; then
    if grep -q "Synesis" "$CLAUDE_MD" 2>/dev/null; then
        echo "  Agent instructions already present, skipping."
    else
        # Prepend Synesis block
        TEMP=$(mktemp)
        echo "$SYNESIS_BLOCK" > "$TEMP"
        echo "" >> "$TEMP"
        cat "$CLAUDE_MD" >> "$TEMP"
        mv "$TEMP" "$CLAUDE_MD"
        echo "  Agent instructions added."
    fi
else
    echo "$SYNESIS_BLOCK" > "$CLAUDE_MD"
    echo "  Created CLAUDE.md with agent instructions."
fi

# 6. Install ML dependencies
echo "  Installing ML dependencies (sentence-transformers, FAISS, scikit-learn)..."
"$SYNESIS_HOME/.venv/bin/pip" install -q -e ".[ml]" 2>/dev/null || echo "  ML deps failed (optional - self-improvement disabled)"

# 7. Run first sync
echo "  Running first sync..."
SYNESIS_DIR="$SYNESIS_DATA" "$SYNESIS_HOME/.venv/bin/python" -c "
from synesis.sync.engine import SyncEngine
import os
engine = SyncEngine(os.environ['SYNESIS_DIR'])
result = engine.run()
print(f'  Synced {result[\"entries\"]} conversations')
" 2>/dev/null || echo "  First sync will run on next Claude Code session."

# 8. Run first training
echo "  Running first ML training cycle..."
SYNESIS_DIR="$SYNESIS_DATA" "$SYNESIS_HOME/.venv/bin/synesis" train 2>/dev/null || echo "  First training will run tonight."

# 9. Set up launchd daemon (macOS) so synesis runs automatically
echo "  Setting up background daemon..."
PLIST_PATH="$HOME/Library/LaunchAgents/com.synesis.daemon.plist"

if [ "$(uname)" = "Darwin" ]; then
    # Unload existing if present
    launchctl unload "$PLIST_PATH" 2>/dev/null || true

    cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.synesis.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>$SYNESIS_HOME/.venv/bin/synesis</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>SYNESIS_DIR</key>
        <string>$SYNESIS_DATA</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$SYNESIS_DATA/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>$SYNESIS_DATA/daemon.err</string>
</dict>
</plist>
PLIST

    launchctl load "$PLIST_PATH" 2>/dev/null && echo "  Daemon started (runs at login, syncs every 12h, trains daily at midnight)." || echo "  Daemon setup failed - run 'synesis' manually."
else
    echo "  Not macOS - set up a cron job: @reboot SYNESIS_DIR=$SYNESIS_DATA $SYNESIS_HOME/.venv/bin/synesis"
fi

echo ""
echo "  ────────────────────────"
echo "  Done. Synesis is fully installed."
echo ""
echo "  What happens now:"
echo "  - Background daemon syncs every 12 hours, trains daily at midnight"
echo "  - Every Claude Code session uses your conversation history + ML-ranked rules"
echo "  - The system gets measurably better over time (run 'synesis status' to check)"
echo "  - Your data lives at ~/synesis-data/ as plain markdown files"
echo ""
echo "  Just open Claude Code and start working. Nothing else to do."
echo ""
