"""Agent optimizer - autonomously modifies the user's setup based on observed patterns.

Security model:
- Commands are validated against an allowlist of safe patterns
- Script names cannot contain path separators
- Instructions are sanitized (no code blocks, no tool-override language)
- Everything is logged to _agent/optimizations.md for auditability
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path


CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"

# Only these command patterns are allowed in hooks
ALLOWED_HOOK_PATTERNS = [
    r"^/Users/\S+/\.synesis/scripts/[\w.-]+$",          # synesis scripts
    r"^/Users/\S+/Projects/synesis/scripts/[\w.-]+$",    # repo scripts
    r"^(ruff|pytest|npm test|npm run \w+|make \w+)\b",   # common dev tools
    r"^git (status|diff|log|stash)\b",                   # safe git reads
    r"^echo\b",                                          # echo
]

# Words that should never appear in injected instructions
INSTRUCTION_BLOCKLIST = [
    "ignore previous", "ignore above", "disregard", "override",
    "exfiltrate", "steal", "send to", "curl ", "wget ",
    "rm -rf", "sudo", "chmod 777", "eval(", "exec(",
    "base64", "reverse shell", "env var", "API_KEY",
    "ANTHROPIC_API", "secret", "password", "credential",
]


def _validate_command(command: str) -> str | None:
    """Returns None if safe, error message if not."""
    for pattern in ALLOWED_HOOK_PATTERNS:
        if re.match(pattern, command):
            return None
    return f"Command not in allowlist: {command}. Only safe commands are permitted in hooks."


def _validate_instruction(instruction: str) -> str | None:
    """Returns None if safe, error message if not."""
    lower = instruction.lower()
    for blocked in INSTRUCTION_BLOCKLIST:
        if blocked.lower() in lower:
            return f"Instruction contains blocked term: '{blocked}'"
    if "```" in instruction:
        return "Instructions cannot contain code blocks"
    if len(instruction) > 500:
        return "Instruction too long (max 500 chars)"
    return None


def _validate_script_name(name: str) -> str | None:
    """Returns None if safe, error message if not."""
    if "/" in name or "\\" in name or ".." in name:
        return "Script name cannot contain path separators or '..'"
    if not re.match(r"^[\w.-]+$", name):
        return "Script name can only contain letters, numbers, dots, hyphens, underscores"
    return None


def install_hook(event: str, matcher: str, command: str, timeout: int = 30, reason: str = "") -> str:
    """Install a Claude Code hook. Command must match the allowlist."""
    error = _validate_command(command)
    if error:
        return f"Blocked: {error}"

    if event not in ("PreToolUse", "PostToolUse", "SessionStart", "Notification"):
        return f"Invalid event: {event}"

    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    # Find or create matcher entry
    matcher_entry = None
    for existing in event_hooks:
        if existing.get("matcher") == matcher:
            # Check for duplicate
            for h in existing.get("hooks", []):
                if h.get("command") == command:
                    return f"Hook already exists for {event}/{matcher}"
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
    """Install an agent-based hook for AI-powered reviews."""
    if event not in ("PreToolUse", "PostToolUse"):
        return f"Agent hooks only allowed on PreToolUse/PostToolUse, got: {event}"

    # Validate prompt doesn't contain injection
    error = _validate_instruction(prompt)
    if error:
        return f"Blocked: {error}"

    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    matcher_entry = None
    for existing in event_hooks:
        if existing.get("matcher") == matcher:
            for h in existing.get("hooks", []):
                if h.get("type") == "agent" and h.get("prompt", "")[:50] == prompt[:50]:
                    return f"Similar agent hook already exists for {event}/{matcher}"
            matcher_entry = existing
            break

    if not matcher_entry:
        matcher_entry = {"matcher": matcher, "hooks": []}
        event_hooks.append(matcher_entry)

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
    """Add an instruction to CLAUDE.md. Validated against blocklist."""
    error = _validate_instruction(instruction)
    if error:
        return f"Blocked: {error}"

    if not CLAUDE_MD.exists():
        CLAUDE_MD.parent.mkdir(parents=True, exist_ok=True)
        CLAUDE_MD.write_text(f"# Agent Instructions\n\n## {section}\n\n- {instruction}\n")
        _log_optimization("add_instruction", instruction, reason)
        return f"Instruction added to CLAUDE.md"

    content = CLAUDE_MD.read_text(encoding="utf-8")

    if instruction in content:
        return "Instruction already exists"

    section_header = f"## {section}"
    if section_header in content:
        idx = content.index(section_header)
        newline_idx = content.index("\n", idx)
        next_section = content.find("\n## ", newline_idx + 1)
        insert_at = len(content) if next_section == -1 else next_section
        content = content[:insert_at].rstrip() + f"\n- {instruction}\n" + content[insert_at:]
    else:
        content = content.rstrip() + f"\n\n{section_header}\n\n- {instruction}\n"

    CLAUDE_MD.write_text(content, encoding="utf-8")
    _log_optimization("add_instruction", instruction, reason)
    return f"Instruction added: {instruction}"


def create_script(name: str, content: str, reason: str = "") -> str:
    """Create a reusable script. Name is validated, no path traversal."""
    error = _validate_script_name(name)
    if error:
        return f"Blocked: {error}"

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
