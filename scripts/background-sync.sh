#!/bin/bash
# Run Synesis sync in background, silently
SYNESIS_DIR="${SYNESIS_DIR:-$HOME/synesis-data}"
export SYNESIS_DIR

cd "$(dirname "$0")/.." || exit

# Only sync if last sync was more than 1 hour ago
STATE_FILE="$SYNESIS_DIR/.sync-state.json"
if [ -f "$STATE_FILE" ]; then
    LAST_SYNC=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('lastSync',''))" 2>/dev/null)
    if [ -n "$LAST_SYNC" ]; then
        LAST_EPOCH=$(python3 -c "from datetime import datetime; print(int(datetime.fromisoformat('$LAST_SYNC').timestamp()))" 2>/dev/null)
        NOW_EPOCH=$(date +%s)
        DIFF=$((NOW_EPOCH - LAST_EPOCH))
        if [ "$DIFF" -lt 3600 ]; then
            exit 0  # Less than 1 hour since last sync, skip
        fi
    fi
fi

# Run sync silently in background
.venv/bin/python -c "
from synesis.sync.engine import SyncEngine
import os
engine = SyncEngine(os.environ['SYNESIS_DIR'])
engine.run()
" > /dev/null 2>&1 &
