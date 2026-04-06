"""Synesis MCP Server - filesystem-style access to the knowledge base.

Agents already know how to navigate filesystems. grep, cat, tree, find -
these are tools baked into every coding model's weights. We expose the
knowledge base through the same interface.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from synesis.sync import SyncEngine

PROJECT_DIR = Path(os.environ.get("SYNESIS_DIR", os.path.expanduser("~/synesis-data")))
KB_DIR = PROJECT_DIR / "knowledge"

mcp = FastMCP("synesis")


@mcp.tool()
def tree(path: str = "/", max_depth: int = 3) -> str:
    """Show the directory structure of the knowledge base. Use this first to orient yourself."""
    target = _resolve(path)
    if not target.exists():
        return f"Path not found: {path}"

    lines = []
    _tree_recurse(target, lines, prefix="", depth=0, max_depth=max_depth)
    return "\n".join(lines) if lines else "Empty."


def _tree_recurse(path: Path, lines: list, prefix: str, depth: int, max_depth: int):
    if depth > max_depth:
        return

    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "`-- " if is_last else "|-- "
        rel = entry.relative_to(KB_DIR)

        if entry.is_dir():
            file_count = sum(1 for _ in entry.rglob("*.md"))
            lines.append(f"{prefix}{connector}{entry.name}/ ({file_count} files)")
            extension = "    " if is_last else "|   "
            _tree_recurse(entry, lines, prefix + extension, depth + 1, max_depth)
        else:
            size = entry.stat().st_size
            lines.append(f"{prefix}{connector}{entry.name} ({_human_size(size)})")


@mcp.tool()
def cat(path: str) -> str:
    """Read the full contents of a file. Use after grep to read relevant files."""
    target = _resolve(path)
    if not target.exists():
        return f"File not found: {path}"
    if target.is_dir():
        return f"{path} is a directory. Use `tree` or `ls` to list contents."

    content = target.read_text(encoding="utf-8")
    # Truncate very large files
    if len(content) > 50000:
        return content[:50000] + f"\n\n... truncated ({len(content)} chars total)"
    return content


@mcp.tool()
def grep(pattern: str, path: str = "/", recursive: bool = True) -> str:
    """Search file contents with regex. Returns matching lines with file paths.
    Use `grep -rl` style: find which files mention a topic, then `cat` them."""
    target = _resolve(path)
    if not target.exists():
        return f"Path not found: {path}"

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex: {e}"

    results = []
    files = target.rglob("*.md") if (recursive and target.is_dir()) else [target]

    for f in files:
        if not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8")
            for i, line in enumerate(content.split("\n"), 1):
                if regex.search(line):
                    rel = f.relative_to(KB_DIR)
                    results.append(f"{rel}:{i}: {line.strip()}")
        except Exception:
            continue

        if len(results) > 200:
            results.append("... (truncated at 200 matches)")
            break

    return "\n".join(results) if results else "No matches."


@mcp.tool()
def grep_files(pattern: str, path: str = "/") -> str:
    """List files that contain a pattern (like grep -rl). Returns file paths only."""
    target = _resolve(path)
    if not target.exists():
        return f"Path not found: {path}"

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex: {e}"

    matching = []
    for f in target.rglob("*.md"):
        try:
            if regex.search(f.read_text(encoding="utf-8")):
                matching.append(str(f.relative_to(KB_DIR)))
        except Exception:
            continue

    return "\n".join(matching) if matching else "No files match."


@mcp.tool()
def ls(path: str = "/") -> str:
    """List directory contents."""
    target = _resolve(path)
    if not target.exists():
        return f"Path not found: {path}"
    if target.is_file():
        size = target.stat().st_size
        return f"{target.name} ({_human_size(size)})"

    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
    lines = []
    for entry in entries:
        if entry.is_dir():
            count = sum(1 for _ in entry.rglob("*.md"))
            lines.append(f"  {entry.name}/  ({count} files)")
        else:
            lines.append(f"  {entry.name}  ({_human_size(entry.stat().st_size)})")

    return "\n".join(lines) if lines else "Empty directory."


@mcp.tool()
def find(pattern: str, path: str = "/") -> str:
    """Find files by name pattern (glob). Example: find('*strategy*')"""
    target = _resolve(path)
    if not target.exists():
        return f"Path not found: {path}"

    matching = []
    for f in target.rglob("*"):
        if fnmatch.fnmatch(f.name, pattern):
            matching.append(str(f.relative_to(KB_DIR)))

    return "\n".join(matching) if matching else "No files match."


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write a markdown file to the knowledge base. Agents can contribute knowledge too."""
    if not path.endswith(".md"):
        return "Error: only .md files can be written to the knowledge base."

    target = _resolve(path)
    if target == KB_DIR:
        return "Error: invalid path."

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written: {path}"


@mcp.tool()
def sync() -> str:
    """Trigger a sync cycle to pull new data from connected sources."""
    engine = SyncEngine(str(PROJECT_DIR))
    result = engine.run()
    return f"Synced: {result['entries']} files written."


@mcp.tool()
def stats() -> str:
    """Show knowledge base stats: file counts by source, total size."""
    if not KB_DIR.exists():
        return "Knowledge base is empty."

    by_source: dict[str, int] = {}
    total_size = 0

    for f in KB_DIR.rglob("*.md"):
        source = f.parent.name
        by_source[source] = by_source.get(source, 0) + 1
        total_size += f.stat().st_size

    lines = [f"Total: {sum(by_source.values())} files ({_human_size(total_size)})", ""]
    for source, count in sorted(by_source.items()):
        lines.append(f"  {source}/  {count} files")

    return "\n".join(lines)


def _resolve(path: str) -> Path:
    """Resolve a path relative to the knowledge base root. Blocks traversal and symlinks."""
    clean = path.strip("/")
    if not clean:
        return KB_DIR

    # Build path without resolving symlinks first
    target = KB_DIR / clean

    # Block any symlinks in the path chain
    check = KB_DIR
    for part in Path(clean).parts:
        check = check / part
        if check.is_symlink():
            return KB_DIR

    # Resolve and verify it's still under KB_DIR
    resolved = target.resolve()
    kb_resolved = KB_DIR.resolve()
    if not str(resolved).startswith(str(kb_resolved) + os.sep) and resolved != kb_resolved:
        return KB_DIR
    return resolved


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size // 1024}K"
    else:
        return f"{size // (1024 * 1024)}M"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
