"""Agent optimizer - autonomously modifies the user's setup based on observed patterns.

No confirmation needed. The agent notices patterns and acts on them:
- Repeated manual commands become hooks
- Common workflows become skills
- Frequently used settings get pre-configured
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"


def install_hook(event: str, matcher: str, command: str, timeout: int = 30, reason: str = "") -> str:
    """Install a Claude Code hook autonomously.

    event: PreToolUse, PostToolUse, SessionStart, etc.
    matcher: tool name or pattern to match
    command: shell command to run
    """
    settings = _load_settings()

    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    # Check if a hook with this matcher already exists
    for existing in event_hooks:
        if existing.get("matcher") == matcher:
            # Check if this exact command is already there
            for h in existing.get("hooks", []):
                if h.get("command") == command:
                    return f"Hook already exists for {event}/{matcher}"

    # Find or create the matcher entry
    matcher_entry = None
    for existing in event_hooks:
        if existing.get("matcher") == matcher:
            matcher_entry = existing
            break

    if not matcher_entry:
        matcher_entry = {"matcher": matcher, "hooks": []}
        event_hooks.append(matcher_entry)

    matcher_entry["hooks"].append({
        "type": "command",
        "command": command,
        "timeout": timeout,
    })

    _save_settings(settings)
    _log_optimization("install_hook", f"{event}/{matcher}: {command}", reason)
    return f"Hook installed: {event}/{matcher} -> {command}"


def install_agent_hook(event: str, matcher: str, prompt: str, model: str = "claude-haiku-4-5-20251001", timeout: int = 60, reason: str = "") -> str:
    """Install an agent-based Claude Code hook that runs an AI review."""
    settings = _load_settings()

    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    matcher_entry = None
    for existing in event_hooks:
        if existing.get("matcher") == matcher:
            matcher_entry = existing
            break

    if not matcher_entry:
        matcher_entry = {"matcher": matcher, "hooks": []}
        event_hooks.append(matcher_entry)

    # Check for duplicate
    for h in matcher_entry.get("hooks", []):
        if h.get("type") == "agent" and h.get("prompt", "")[:50] == prompt[:50]:
            return f"Similar agent hook already exists for {event}/{matcher}"

    matcher_entry["hooks"].append({
        "type": "agent",
        "prompt": prompt,
        "model": model,
        "timeout": timeout,
    })

    _save_settings(settings)
    _log_optimization("install_agent_hook", f"{event}/{matcher}", reason)
    return f"Agent hook installed: {event}/{matcher}"


def add_instruction(instruction: str, section: str = "Auto-Optimizations", reason: str = "") -> str:
    """Add an instruction to CLAUDE.md that shapes agent behavior."""
    if not CLAUDE_MD.exists():
        CLAUDE_MD.parent.mkdir(parents=True, exist_ok=True)
        CLAUDE_MD.write_text(f"# Agent Instructions\n\n## {section}\n\n- {instruction}\n")
        _log_optimization("add_instruction", instruction, reason)
        return f"Instruction added to CLAUDE.md"

    content = CLAUDE_MD.read_text(encoding="utf-8")

    # Don't add duplicates
    if instruction in content:
        return "Instruction already exists"

    # Find or create the section
    section_header = f"## {section}"
    if section_header in content:
        # Append to existing section
        idx = content.index(section_header)
        # Find the end of the section header line
        newline_idx = content.index("\n", idx)
        # Find the next section or end of file
        next_section = content.find("\n## ", newline_idx + 1)
        if next_section == -1:
            insert_at = len(content)
        else:
            insert_at = next_section

        content = content[:insert_at].rstrip() + f"\n- {instruction}\n" + content[insert_at:]
    else:
        # Add new section at the end
        content = content.rstrip() + f"\n\n{section_header}\n\n- {instruction}\n"

    CLAUDE_MD.write_text(content, encoding="utf-8")
    _log_optimization("add_instruction", instruction, reason)
    return f"Instruction added: {instruction}"


def create_script(name: str, content: str, reason: str = "") -> str:
    """Create a reusable script in ~/.synesis/scripts/."""
    scripts_dir = Path.home() / ".synesis" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    script_path = scripts_dir / name
    script_path.write_text(content, encoding="utf-8")
    os.chmod(script_path, 0o755)

    _log_optimization("create_script", name, reason)
    return f"Script created: {script_path}"


def _load_settings() -> dict:
    if CLAUDE_SETTINGS.exists():
        return json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    return {}


def _save_settings(settings: dict) -> None:
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS.write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )


def _log_optimization(action: str, detail: str, reason: str) -> None:
    """Log what the agent did so it's auditable."""
    data_dir = Path(os.environ.get("SYNESIS_DIR", Path.home() / "synesis-data"))
    log_file = data_dir / "knowledge" / "_agent" / "optimizations.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    entry = f"- [{datetime.now().isoformat()}] **{action}**: {detail}"
    if reason:
        entry += f" (reason: {reason})"
    entry += "\n"

    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")
    else:
        content = "# Agent Optimizations Log\n\nAutonomous changes made by the agent to improve your workflow.\n\n"

    content += entry
    log_file.write_text(content, encoding="utf-8")
