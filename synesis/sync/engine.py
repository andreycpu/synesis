"""Sync engine - ingests raw conversations and stores them as browsable files.

No LLM extraction. The raw data IS the knowledge base. Agents navigate
it with grep, cat, tree - tools they already know.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from synesis.config import ConfigManager
from synesis.connectors import create_connector
from synesis.kb.types import RawConversation


class SyncEngine:
    def __init__(self, project_dir: str | Path):
        project_dir = Path(project_dir)
        self.project_dir = project_dir
        self.config_manager = ConfigManager(project_dir / "config" / "synesis.yaml")
        self.data_dir = project_dir / "knowledge"
        self.state_file = project_dir / ".sync-state.json"

    def run(self) -> dict:
        config = self.config_manager.load()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        last_sync = self._get_last_sync()
        print(f"Synesis sync starting... (since: {last_sync or 'beginning'})")

        # Fetch from all enabled connectors
        all_conversations: list[RawConversation] = []
        for name, conn_config in config.get("connectors", {}).items():
            if not conn_config.get("enabled"):
                continue

            connector = create_connector(name, conn_config)
            if not connector:
                print(f"Unknown connector: {name}")
                continue

            if not connector.validate():
                print(f"Connector {name} validation failed, skipping")
                continue

            print(f"Fetching from {name}...")
            conversations = connector.fetch(since=last_sync)
            print(f"  Found {len(conversations)} conversations")
            all_conversations.extend(conversations)

        if not all_conversations:
            print("No new conversations to process")
            self._save_last_sync()
            return {"entries": 0, "config_updates": []}

        # Write conversations as browsable files - no LLM, just raw data
        written = 0
        for conv in all_conversations:
            path = self._write_conversation(conv)
            if path:
                written += 1
                print(f"  + {path.relative_to(self.data_dir)}")

        self._save_last_sync()
        print(f"Sync complete: {written} files written")

        return {"entries": written, "config_updates": []}

    def _write_conversation(self, conv: RawConversation) -> Path | None:
        """Write a conversation as a markdown file, organized by source."""
        source_dir = self.data_dir / conv.source
        source_dir.mkdir(parents=True, exist_ok=True)

        # Clean up the ID for use as filename
        filename = re.sub(r"[^a-zA-Z0-9_-]", "-", conv.id)[:80] + ".md"
        file_path = source_dir / filename

        # Build markdown content
        lines = []

        # Frontmatter
        lines.append("---")
        lines.append(f"source: {conv.source}")
        lines.append(f"id: {conv.id}")
        lines.append(f"synced: {datetime.now().isoformat()}")
        lines.append(f"timestamp: {conv.timestamp}")
        if conv.metadata:
            for k, v in conv.metadata.items():
                if isinstance(v, str):
                    lines.append(f"{k}: {v}")
        lines.append("---")
        lines.append("")

        # Conversation content
        for msg in conv.messages:
            role = msg.role.upper()
            lines.append(f"## {role}")
            lines.append("")
            lines.append(msg.content)
            lines.append("")

        file_path.write_text("\n".join(lines), encoding="utf-8")
        return file_path

    def _get_last_sync(self) -> str | None:
        if not self.state_file.exists():
            return None
        try:
            data = json.loads(self.state_file.read_text())
            return data.get("lastSync")
        except Exception:
            return None

    def _save_last_sync(self) -> None:
        self.state_file.write_text(
            json.dumps({"lastSync": datetime.now().isoformat()})
        )
