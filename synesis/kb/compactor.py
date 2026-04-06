from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

import anthropic

from synesis.kb.store import KnowledgeStore
from synesis.kb.types import KnowledgeEntry

COMPACTION_PROMPT = """You are Synesis, a knowledge compaction agent. Merge these related knowledge entries into a single, denser summary.

Rules:
- Preserve all important facts, decisions, and nuance
- Remove redundancy and duplicates
- If entries conflict, keep the most recent information and note the change
- Output JSON only:

{"title": "merged title", "content": "merged knowledge", "tags": ["merged", "tags"]}

Entries to merge:
"""

SUMMARY_PROMPT = """Summarize these {count} knowledge entries in the "{category}" category into a concise overview. This summary will be used when an agent needs quick orientation without loading every entry.

Entries:
{entries}"""


@dataclass
class CompactionResult:
    merged: int = 0
    archived: int = 0
    categories: list[dict] = field(default_factory=list)


class Compactor:
    def __init__(self, store: KnowledgeStore, model: str = "claude-sonnet-4-20250514"):
        self.store = store
        self.client = anthropic.Anthropic()
        self.model = model

    def compact(self, max_per_category: int = 50) -> CompactionResult:
        result = CompactionResult()
        all_entries = self.store.list()
        by_category: dict[str, list[KnowledgeEntry]] = {}

        for entry in all_entries:
            if entry.category.startswith("_"):
                continue
            by_category.setdefault(entry.category, []).append(entry)

        for category, entries in by_category.items():
            if len(entries) <= max_per_category:
                continue

            print(f"Compacting {category}: {len(entries)} entries (threshold: {max_per_category})")
            groups = self._find_related_groups(entries)

            cat_merged = 0
            cat_archived = 0

            for group in groups:
                if len(group) < 2:
                    continue

                merged = self._merge_entries(category, group)
                if not merged:
                    continue

                self.store.write(merged)

                for entry in group:
                    archived = KnowledgeEntry(
                        id=entry.id,
                        title=entry.title,
                        category=f"_archive/{entry.category}",
                        content=entry.content,
                        source=entry.source,
                        tags=entry.tags,
                        created=entry.created,
                        updated=entry.updated,
                        metadata={
                            **entry.metadata,
                            "merged_into": merged.id,
                            "archived_at": datetime.now().isoformat(),
                        },
                    )
                    self.store.write(archived)
                    self.store.delete(entry.category, entry.id)

                cat_merged += 1
                cat_archived += len(group)

            if cat_merged > 0:
                result.categories.append(
                    {"category": category, "merged": cat_merged, "archived": cat_archived}
                )
                result.merged += cat_merged
                result.archived += cat_archived

        return result

    def summarize_category(self, category: str) -> KnowledgeEntry | None:
        entries = self.store.list(category)
        if not entries:
            return None

        entries_text = "\n\n".join(f"## {e.title}\n{e.content}" for e in entries)
        prompt = SUMMARY_PROMPT.format(count=len(entries), category=category, entries=entries_text)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text if response.content else ""
            now = datetime.now().isoformat()

            return KnowledgeEntry(
                id=f"_summary-{category}",
                title=f"Summary: {category}",
                category="_summaries",
                content=text,
                source="compactor",
                tags=[category, "summary", "auto-generated"],
                created=now,
                updated=now,
                metadata={"entry_count": len(entries), "source_category": category},
            )
        except Exception as e:
            print(f"Failed to summarize {category}: {e}")
            return None

    def _find_related_groups(self, entries: list[KnowledgeEntry]) -> list[list[KnowledgeEntry]]:
        groups: list[list[KnowledgeEntry]] = []
        assigned: set[str] = set()

        sorted_entries = sorted(entries, key=lambda e: ",".join(e.tags))

        for entry in sorted_entries:
            if entry.id in assigned:
                continue

            group = [entry]
            assigned.add(entry.id)

            for candidate in sorted_entries:
                if candidate.id in assigned:
                    continue

                tag_overlap = self._tag_overlap(entry, candidate)
                title_sim = self._title_similarity(entry, candidate)

                if tag_overlap >= 0.5 or title_sim >= 0.6:
                    group.append(candidate)
                    assigned.add(candidate.id)

                if len(group) >= 5:
                    break

            groups.append(group)

        return [g for g in groups if len(g) >= 2]

    def _tag_overlap(self, a: KnowledgeEntry, b: KnowledgeEntry) -> float:
        if not a.tags and not b.tags:
            return 0.0
        set_a = set(a.tags)
        intersection = len(set_a & set(b.tags))
        union = len(set_a | set(b.tags))
        return intersection / union if union > 0 else 0.0

    def _title_similarity(self, a: KnowledgeEntry, b: KnowledgeEntry) -> float:
        words_a = set(a.title.lower().split())
        words_b = set(b.title.lower().split())
        intersection = len(words_a & words_b)
        union = len(words_a | words_b)
        return intersection / union if union > 0 else 0.0

    def _merge_entries(
        self, category: str, entries: list[KnowledgeEntry]
    ) -> KnowledgeEntry | None:
        entries_text = "\n\n---\n\n".join(
            f"### {e.title}\nTags: {', '.join(e.tags)}\nSource: {e.source}\n"
            f"Updated: {e.updated}\n\n{e.content}"
            for e in entries
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": COMPACTION_PROMPT + entries_text}],
            )
            text = response.content[0].text if response.content else ""
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                return None

            parsed = json.loads(match.group())
            now = datetime.now().isoformat()
            slug = re.sub(r"[^a-z0-9]+", "-", parsed["title"].lower())[:50]
            suffix = hex(int(datetime.now().timestamp()))[-4:]

            return KnowledgeEntry(
                id=f"merged-{slug}-{suffix}",
                title=parsed["title"],
                category=category,
                content=parsed["content"],
                source="compactor",
                tags=list(set(parsed.get("tags", []) + ["merged"])),
                created=now,
                updated=now,
                metadata={
                    "merged_from": [e.id for e in entries],
                    "merge_count": len(entries),
                },
            )
        except Exception as e:
            print(f"Merge failed: {e}")
            return None
