"""Agent learner - manages the _agent/ directory for self-improvement.

Agents improve the system by writing to _agent/ through MCP tools.
No LLM calls - just filesystem operations.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


AGENT_DIR_NAME = "_agent"


def _agent_dir(kb_dir: Path) -> Path:
    return kb_dir / AGENT_DIR_NAME


def generate_index(kb_dir: Path) -> str:
    """Generate _agent/index.md by scanning the KB directory structure.
    Returns the generated content."""
    agent_dir = _agent_dir(kb_dir)
    agent_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Synesis Knowledge Base Index",
        f"Generated: {datetime.now().isoformat()}",
        "",
        "## Directory Structure",
        "",
    ]

    if not kb_dir.exists():
        lines.append("Knowledge base is empty.")
        content = "\n".join(lines)
        (agent_dir / "index.md").write_text(content, encoding="utf-8")
        return content

    # Scan directories
    total_files = 0
    total_size = 0
    sources: dict[str, dict] = {}

    for entry in sorted(kb_dir.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        md_files = list(entry.rglob("*.md"))
        count = len(md_files)
        size = sum(f.stat().st_size for f in md_files)
        total_files += count
        total_size += size

        # Find most recent file
        recent = None
        if md_files:
            newest = max(md_files, key=lambda f: f.stat().st_mtime)
            recent = newest.name

        sources[name] = {"count": count, "size": size, "recent": recent}

    lines.append(f"Total: {total_files} files, {_human_size(total_size)}")
    lines.append("")

    for name, info in sorted(sources.items()):
        recent_str = f" (latest: {info['recent']})" if info["recent"] else ""
        lines.append(f"- **{name}/** - {info['count']} files, {_human_size(info['size'])}{recent_str}")

    lines.append("")
    lines.append("## Agent Files")
    lines.append("")

    # List agent files
    for fname in ("preferences.md", "rules.md"):
        fpath = agent_dir / fname
        if fpath.exists():
            lines.append(f"- {fname} ({_human_size(fpath.stat().st_size)})")
        else:
            lines.append(f"- {fname} (not yet created)")

    lines.append("")

    content = "\n".join(lines)
    (agent_dir / "index.md").write_text(content, encoding="utf-8")
    return content


def append_learning(kb_dir: Path, learning: str) -> str:
    """Append a learning to _agent/rules.md."""
    agent_dir = _agent_dir(kb_dir)
    agent_dir.mkdir(parents=True, exist_ok=True)

    rules_file = agent_dir / "rules.md"

    timestamp = datetime.now().isoformat()
    entry = f"\n- [{timestamp}] {learning}\n"

    if rules_file.exists():
        existing = rules_file.read_text(encoding="utf-8")
    else:
        existing = "# Agent-Learned Rules\n\nRules discovered by agents during interactions.\n"

    rules_file.write_text(existing + entry, encoding="utf-8")
    return f"Learning recorded: {learning}"


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size // 1024}K"
    else:
        return f"{size // (1024 * 1024)}M"
