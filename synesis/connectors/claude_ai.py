from __future__ import annotations

import glob
import json
from datetime import datetime
from pathlib import Path

from synesis.connectors.base import BaseConnector
from synesis.kb.types import ConversationMessage, RawConversation


class ClaudeAIConnector(BaseConnector):
    name = "claude_ai"

    def __init__(self, config: dict):
        super().__init__(config)
        self.export_path = config.get("export_path") or ""

    def validate(self) -> bool:
        if not self.export_path:
            return False
        return Path(self.export_path).exists()

    def fetch(self, since: str | None = None) -> list[RawConversation]:
        if not self.export_path:
            return []

        since_dt = datetime.fromisoformat(since) if since else None
        results: list[RawConversation] = []

        for json_file in glob.glob(str(Path(self.export_path) / "*.json")):
            path = Path(json_file)
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if since_dt and mtime < since_dt:
                continue

            try:
                conv = json.loads(path.read_text(encoding="utf-8"))
                messages = [
                    ConversationMessage(
                        role="user" if m.get("sender") == "human" else "assistant",
                        content=m.get("text", ""),
                        timestamp=m.get("created_at"),
                    )
                    for m in conv.get("chat_messages", [])
                    if m.get("text", "").strip()
                ]

                if messages:
                    results.append(
                        RawConversation(
                            source="claude_ai",
                            id=path.stem,
                            messages=messages,
                            timestamp=mtime.isoformat(),
                            metadata={"file_path": str(path), "name": conv.get("name")},
                        )
                    )
            except (json.JSONDecodeError, KeyError):
                continue

        return results
