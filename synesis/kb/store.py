from __future__ import annotations

import glob
import os
from datetime import datetime
from pathlib import Path

import frontmatter

from synesis.kb.types import KnowledgeEntry


class KnowledgeStore:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def init(self) -> None:
        for category in ("facts", "decisions", "preferences", "contacts", "ideas"):
            (self.base_dir / category).mkdir(parents=True, exist_ok=True)

    def write(self, entry: KnowledgeEntry) -> Path:
        file_path = self.base_dir / entry.category / f"{entry.id}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        post = frontmatter.Post(
            entry.content,
            id=entry.id,
            title=entry.title,
            category=entry.category,
            source=entry.source,
            tags=entry.tags,
            created=entry.created,
            updated=entry.updated,
            **entry.metadata,
        )
        file_path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return file_path

    def read(self, category: str, id: str) -> KnowledgeEntry | None:
        file_path = self.base_dir / category / f"{id}.md"
        if not file_path.exists():
            return None
        return self._parse_file(file_path)

    def list(self, category: str | None = None) -> list[KnowledgeEntry]:
        pattern = f"{category}/*.md" if category else "**/*.md"
        files = sorted(
            glob.glob(str(self.base_dir / pattern), recursive=True),
            key=os.path.getmtime,
            reverse=True,
        )
        entries = []
        for f in files:
            entry = self._parse_file(Path(f))
            if entry:
                entries.append(entry)
        return entries

    def search(self, query: str, category: str | None = None) -> list[KnowledgeEntry]:
        entries = self.list(category)
        lower = query.lower()
        return [
            e
            for e in entries
            if lower in e.title.lower()
            or lower in e.content.lower()
            or any(lower in t.lower() for t in e.tags)
        ]

    def delete(self, category: str, id: str) -> bool:
        file_path = self.base_dir / category / f"{id}.md"
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def update(self, category: str, id: str, **updates) -> KnowledgeEntry | None:
        existing = self.read(category, id)
        if not existing:
            return None
        for k, v in updates.items():
            setattr(existing, k, v)
        existing.updated = datetime.now().isoformat()
        self.write(existing)
        return existing

    def _parse_file(self, path: Path) -> KnowledgeEntry | None:
        try:
            post = frontmatter.load(str(path))
            meta = dict(post.metadata)
            reserved = {"id", "title", "category", "source", "tags", "created", "updated"}
            extra = {k: v for k, v in meta.items() if k not in reserved}
            return KnowledgeEntry(
                id=meta.get("id", path.stem),
                title=meta.get("title", "Untitled"),
                category=meta.get("category", path.parent.name),
                content=post.content.strip(),
                source=meta.get("source", "unknown"),
                tags=meta.get("tags", []),
                created=meta.get("created", ""),
                updated=meta.get("updated", ""),
                metadata=extra,
            )
        except Exception:
            return None
