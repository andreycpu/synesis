from __future__ import annotations

import json
import re
from datetime import datetime

import anthropic

from synesis.kb.types import (
    ConfigUpdate,
    ExtractionResult,
    KnowledgeEntry,
    RawConversation,
)

EXTRACTION_PROMPT = """You are Synesis, a self-evolving knowledge extraction agent. Analyze the conversation and extract structured knowledge.

Extract:
1. **Facts** - concrete things that are true (about the user, their work, their world)
2. **Decisions** - choices made and reasoning behind them
3. **Preferences** - how the user likes things, their style, their taste
4. **Contacts** - people mentioned, roles, relationships
5. **Ideas** - thoughts, plans, aspirations, hypotheses

Output valid JSON:
{
  "entries": [
    {"title": "short title", "category": "facts|decisions|preferences|contacts|ideas", "content": "clear statement", "tags": ["relevant", "tags"]}
  ],
  "config_updates": [
    {"file": "config/synesis.yaml", "path": "some.path", "value": "new value", "reason": "why"}
  ]
}

Rules:
- Only extract genuinely useful, non-obvious knowledge
- Skip small talk and trivial exchanges
- config_updates only when you learn something that should change system behavior
- If nothing worth extracting, return {"entries": [], "config_updates": []}

Conversation:
"""


class Extractor:
    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic()
        self.model = model

    def extract(self, conversations: list[RawConversation]) -> ExtractionResult:
        all_entries: list[KnowledgeEntry] = []
        all_updates: list[ConfigUpdate] = []

        for conv in conversations:
            result = self._extract_one(conv)
            all_entries.extend(result.entries)
            all_updates.extend(result.config_updates)

        return ExtractionResult(entries=all_entries, config_updates=all_updates)

    def _extract_one(self, conv: RawConversation) -> ExtractionResult:
        transcript = "\n\n".join(
            f"{m.role.upper()}: {m.content}" for m in conv.messages
        )

        # Truncate long conversations
        if len(transcript) > 50000:
            transcript = transcript[:50000] + "\n\n[...truncated]"

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": EXTRACTION_PROMPT + transcript}],
            )

            text = response.content[0].text if response.content else ""
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                return ExtractionResult(entries=[])

            parsed = json.loads(match.group())
            now = datetime.now().isoformat()

            entries = []
            for e in parsed.get("entries", []):
                slug = re.sub(r"[^a-z0-9]+", "-", e["title"].lower()).strip("-")[:50]
                suffix = hex(int(datetime.now().timestamp()))[-4:]
                entries.append(
                    KnowledgeEntry(
                        id=f"{slug}-{suffix}",
                        title=e["title"],
                        category=e.get("category", "facts"),
                        content=e["content"],
                        source=conv.source,
                        tags=e.get("tags", []),
                        created=now,
                        updated=now,
                        metadata={"conversation_id": conv.id},
                    )
                )

            config_updates = [
                ConfigUpdate(
                    file=u["file"],
                    path=u["path"],
                    value=u["value"],
                    reason=u["reason"],
                )
                for u in parsed.get("config_updates", [])
            ]

            return ExtractionResult(entries=entries, config_updates=config_updates)

        except Exception as e:
            print(f"Extraction failed for {conv.id}: {e}")
            return ExtractionResult(entries=[])
