"""Conversation-level semantic index.

Builds a FAISS index over the full knowledge base (conversation files,
not just rules). Embeds the first 500 chars of each conversation -
enough to capture the topic. Enables "find me conversations about X"
with ML-powered similarity search.

Separate from the rule index. Stored in ml/conversations.index.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class ConversationIndex:
    def __init__(self, ml_dir: Path, kb_dir: Path):
        self._ml_dir = ml_dir
        self._kb_dir = kb_dir
        self._index_path = ml_dir / "conversations.index"
        self._map_path = ml_dir / "conversation_map.json"
        ml_dir.mkdir(parents=True, exist_ok=True)

    def build_index(self) -> int:
        """Scan all conversation files in the KB and build a FAISS index.

        Embeds the first 500 chars of each file (enough for topic detection).
        Returns number of conversations indexed.
        """
        import faiss
        from synesis.ml.embeddings import EmbeddingEngine

        engine = EmbeddingEngine(self._ml_dir)

        # Collect conversation files (skip _agent/ directory)
        entries = []
        for f in self._kb_dir.rglob("*.md"):
            if "_agent" in f.parts:
                continue
            try:
                content = f.read_text(encoding="utf-8")
                # Skip frontmatter, get the actual content
                text = self._strip_frontmatter(content)
                if len(text.strip()) < 50:
                    continue

                snippet = text[:500]
                rel_path = str(f.relative_to(self._kb_dir))
                entries.append({
                    "path": rel_path,
                    "snippet": snippet,
                    "size": f.stat().st_size,
                })
            except Exception:
                continue

        if not entries:
            return 0

        # Embed all snippets
        texts = [e["snippet"] for e in entries]
        vecs = engine.embed(texts)
        dim = vecs.shape[1]

        # Build and save FAISS index
        index = faiss.IndexFlatIP(dim)
        index.add(vecs)
        faiss.write_index(index, str(self._index_path))

        # Save the mapping
        conv_map = []
        for i, entry in enumerate(entries):
            conv_map.append({
                "id": i,
                "path": entry["path"],
                "snippet": entry["snippet"][:200],
                "size": entry["size"],
            })
        self._map_path.write_text(
            json.dumps(conv_map, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(f"Indexed {len(entries)} conversations")
        return len(entries)

    def search(self, query: str, k: int = 5) -> list[dict]:
        """Search conversations by semantic similarity.

        Returns [{path, snippet, similarity}, ...].
        """
        import faiss
        from synesis.ml.embeddings import EmbeddingEngine

        if not self._index_path.exists() or not self._map_path.exists():
            return []

        engine = EmbeddingEngine(self._ml_dir)
        index = faiss.read_index(str(self._index_path))
        conv_map = json.loads(self._map_path.read_text(encoding="utf-8"))

        if index.ntotal == 0:
            return []

        q = engine.embed_single(query).reshape(1, -1)
        k = min(k, index.ntotal)
        scores, indices = index.search(q, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(conv_map):
                continue
            entry = conv_map[idx]
            results.append({
                "path": entry["path"],
                "snippet": entry["snippet"],
                "similarity": round(float(score), 4),
            })

        return results

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                return content[end + 3:].strip()
        return content
