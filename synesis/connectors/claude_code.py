from __future__ import annotations

import glob
import json
import os
from datetime import datetime
from pathlib import Path

from synesis.connectors.base import BaseConnector
from synesis.kb.types import ConversationMessage, RawConversation


class ClaudeCodeConnector(BaseConnector):
    name = "claude_code"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_path = Path(config.get("path", os.path.expanduser("~/.claude")))

    def validate(self) -> bool:
        return self.base_path.exists()

    def fetch(self, since: str | None = None) -> list[RawConversation]:
        since_dt = datetime.fromisoformat(since) if since else None
        conversations: list[RawConversation] = []

        # Read conversation JSONL files
        projects_dir = self.base_path / "projects"
        if projects_dir.exists():
            for jsonl_file in glob.glob(str(projects_dir / "**/*.jsonl"), recursive=True):
                path = Path(jsonl_file)
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                if since_dt and mtime < since_dt:
                    continue

                messages = self._parse_jsonl(path)
                if messages:
                    conversations.append(
                        RawConversation(
                            source="claude_code",
                            id=path.stem,
                            messages=messages,
                            timestamp=mtime.isoformat(),
                            metadata={"file_path": str(path)},
                        )
                    )

        # Read memory files
        for md_file in glob.glob(str(self.base_path / "**/memory/**/*.md"), recursive=True):
            path = Path(md_file)
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if since_dt and mtime < since_dt:
                continue

            content = path.read_text(encoding="utf-8")
            conversations.append(
                RawConversation(
                    source="claude_code_memory",
                    id=f"memory-{path.stem}",
                    messages=[ConversationMessage(role="system", content=content)],
                    timestamp=mtime.isoformat(),
                    metadata={"file_path": str(path), "type": "memory"},
                )
            )

        return conversations

    def _parse_jsonl(self, path: Path) -> list[ConversationMessage]:
        messages = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") not in ("user", "assistant"):
                    continue

                content = msg.get("message", {}).get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        b.get("text", "") for b in content if b.get("type") == "text"
                    )

                if content:
                    messages.append(
                        ConversationMessage(
                            role=msg["type"],  # "user" or "assistant"
                            content=content,
                            timestamp=msg.get("timestamp"),
                        )
                    )
            except (json.JSONDecodeError, KeyError):
                continue
        return messages
