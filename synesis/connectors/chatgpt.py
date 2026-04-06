from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from synesis.connectors.base import BaseConnector
from synesis.kb.types import ConversationMessage, RawConversation


class ChatGPTConnector(BaseConnector):
    name = "chatgpt"

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
        conv_file = Path(self.export_path) / "conversations.json"
        if not conv_file.exists():
            return []

        conversations = json.loads(conv_file.read_text(encoding="utf-8"))
        results: list[RawConversation] = []

        for conv in conversations:
            conv_date = datetime.fromtimestamp(conv.get("update_time", 0))
            if since_dt and conv_date < since_dt:
                continue

            messages = []
            for node in sorted(
                conv.get("mapping", {}).values(),
                key=lambda n: (n.get("message", {}) or {}).get("create_time", 0) or 0,
            ):
                msg = node.get("message")
                if not msg or msg.get("author", {}).get("role") == "system":
                    continue

                parts = (msg.get("content", {}) or {}).get("parts", [])
                content = "\n".join(str(p) for p in parts if p).strip()
                if not content:
                    continue

                ts = msg.get("create_time")
                messages.append(
                    ConversationMessage(
                        role=msg["author"]["role"],
                        content=content,
                        timestamp=datetime.fromtimestamp(ts).isoformat() if ts else None,
                    )
                )

            if messages:
                title = conv.get("title", "untitled")
                slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:60]
                results.append(
                    RawConversation(
                        source="chatgpt",
                        id=slug,
                        messages=messages,
                        timestamp=conv_date.isoformat(),
                        metadata={"title": title},
                    )
                )

        return results
