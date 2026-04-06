from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from synesis.config import ConfigManager
from synesis.connectors import create_connector
from synesis.extractor import Extractor
from synesis.kb.compactor import Compactor
from synesis.kb.store import KnowledgeStore
from synesis.kb.types import RawConversation


class SyncEngine:
    def __init__(self, project_dir: str | Path):
        project_dir = Path(project_dir)
        self.config_manager = ConfigManager(project_dir / "config" / "synesis.yaml")
        self.store = KnowledgeStore(project_dir / "knowledge")
        self.extractor = Extractor()
        self.state_file = project_dir / ".sync-state.json"

    def run(self) -> dict:
        config = self.config_manager.load()
        self.store.init()

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

        # Extract knowledge
        print(f"Extracting knowledge from {len(all_conversations)} conversations...")
        result = self.extractor.extract(all_conversations)

        # Write entries
        written = 0
        for entry in result.entries:
            self.store.write(entry)
            written += 1
            print(f"  + [{entry.category}] {entry.title}")

        # Apply self-modifications
        applied: list[str] = []
        if result.config_updates:
            print(f"Applying {len(result.config_updates)} config updates...")
            applied = self.config_manager.apply_updates(result.config_updates)
            for a in applied:
                print(f"  ~ {a}")

        # Run compaction
        compactor = Compactor(self.store)
        compaction = compactor.compact(50)
        if compaction.merged > 0:
            print(f"Compacted: {compaction.merged} merges, {compaction.archived} entries archived")

        self._save_last_sync()
        print(f"Sync complete: {written} entries, {len(applied)} config updates")

        return {"entries": written, "config_updates": applied}

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
