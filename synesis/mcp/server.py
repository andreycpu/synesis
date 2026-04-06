"""Synesis MCP Server - exposes the knowledge base to any AI agent."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from synesis.kb.compactor import Compactor
from synesis.kb.search import SearchIndex
from synesis.kb.store import KnowledgeStore
from synesis.kb.types import KnowledgeEntry
from synesis.config import ConfigManager
from synesis.sync import SyncEngine

PROJECT_DIR = Path(os.environ.get("SYNESIS_DIR", "."))
store = KnowledgeStore(PROJECT_DIR / "knowledge")
config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
search_index = SearchIndex()
_index_loaded = False

mcp = FastMCP("synesis")


def _ensure_index():
    global _index_loaded
    if _index_loaded:
        return
    store.init()
    for entry in store.list():
        search_index.add(entry)
    _index_loaded = True


@mcp.tool()
def search(query: str, category: str | None = None, limit: int = 10) -> str:
    """Search the knowledge base. Returns TF-IDF ranked results."""
    _ensure_index()
    results = search_index.search(query, limit=limit, category=category)
    if not results:
        return "No results found."
    return "\n\n---\n\n".join(
        f"## {e.title}\n**Category:** {e.category} | **Source:** {e.source} | **Tags:** {', '.join(e.tags)}\n\n{e.content}"
        for e in results
    )


@mcp.tool()
def context(query: str, max_tokens: int = 8000, category: str | None = None) -> str:
    """Get relevant knowledge entries that fit within a token budget. Use this instead of search when loading knowledge into context."""
    _ensure_index()
    entries = search_index.get_context(query, max_tokens=max_tokens, category=category)
    if not entries:
        return "No relevant knowledge found."
    est_tokens = sum((len(e.title) + len(e.content)) // 4 for e in entries)
    header = f"*{len(entries)} entries loaded (~{est_tokens} tokens)*\n\n"
    body = "\n\n---\n\n".join(f"## {e.title} [{e.category}]\n{e.content}" for e in entries)
    return header + body


@mcp.tool()
def list_entries(category: str | None = None) -> str:
    """List all knowledge entries, optionally filtered by category."""
    store.init()
    entries = store.list(category)
    if not entries:
        return "No entries found."
    return "\n".join(
        f"- **{e.title}** [{e.category}] ({e.source}) - {e.updated}" for e in entries
    )


@mcp.tool()
def read(category: str, id: str) -> str:
    """Read a specific knowledge entry by category and ID."""
    store.init()
    entry = store.read(category, id)
    if not entry:
        return "Entry not found."
    return (
        f"# {entry.title}\n\n"
        f"**Category:** {entry.category}\n**Source:** {entry.source}\n"
        f"**Tags:** {', '.join(entry.tags)}\n**Created:** {entry.created}\n"
        f"**Updated:** {entry.updated}\n\n{entry.content}"
    )


@mcp.tool()
def write(title: str, category: str, content: str, tags: list[str] | None = None, source: str = "mcp") -> str:
    """Write a new knowledge entry."""
    store.init()
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    now = datetime.now().isoformat()

    entry = KnowledgeEntry(
        id=slug, title=title, category=category, content=content,
        source=source, tags=tags or [], created=now, updated=now,
    )
    path = store.write(entry)
    search_index.add(entry)
    return f"Entry written to {path}"


@mcp.tool()
def delete(category: str, id: str) -> str:
    """Delete a knowledge entry."""
    store.init()
    success = store.delete(category, id)
    if success:
        search_index.remove(category, id)
    return "Entry deleted." if success else "Entry not found."


@mcp.tool()
def compact(max_per_category: int = 50) -> str:
    """Merge related entries to reduce knowledge base size."""
    global _index_loaded
    compactor = Compactor(store)
    result = compactor.compact(max_per_category)
    _index_loaded = False  # Force reindex
    if result.merged == 0:
        return "No compaction needed."
    lines = [f"Compacted: {result.merged} merges, {result.archived} entries archived."]
    for c in result.categories:
        lines.append(f"  {c['category']}: {c['merged']} groups merged, {c['archived']} archived")
    return "\n".join(lines)


@mcp.tool()
def summarize(category: str) -> str:
    """Generate a concise summary of a knowledge category."""
    compactor = Compactor(store)
    summary = compactor.summarize_category(category)
    if not summary:
        return f"No entries in category: {category}"
    store.write(summary)
    return summary.content


@mcp.tool()
def sync() -> str:
    """Trigger a full sync cycle: fetch, extract, compact."""
    engine = SyncEngine(str(PROJECT_DIR))
    result = engine.run()
    return f"Sync complete: {result['entries']} entries, {len(result['config_updates'])} config updates."


@mcp.tool()
def get_config() -> str:
    """Read the current Synesis configuration."""
    import json
    config = config_manager.load()
    return json.dumps(config, indent=2, default=str)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
