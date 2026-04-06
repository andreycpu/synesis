from __future__ import annotations

import os
import fnmatch
from pathlib import Path

import yaml

from synesis.kb.types import ConfigUpdate

DEFAULT_CONFIG = {
    "knowledge_dir": "./knowledge",
    "sync_schedule": "0 */12 * * *",
    "categories": ["facts", "decisions", "preferences", "contacts", "ideas"],
    "extraction": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "extract": ["facts", "decisions", "preferences", "contacts", "action_items", "ideas"],
    },
    "self_modify": {
        "enabled": True,
        "modifiable": ["config/synesis.yaml", "config/connectors/*.yaml", "knowledge/**/*.md"],
    },
    "connectors": {
        "claude_code": {"enabled": True, "path": os.path.expanduser("~/.claude")},
        "chatgpt": {"enabled": False},
        "claude_ai": {"enabled": False},
        "gmail": {
            "enabled": False,
            "client_id": None,
            "client_secret": None,
            "user_email": None,
            "max_results": 50,
        },
    },
}


class ConfigManager:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.config: dict | None = None

    def load(self) -> dict:
        if self.config_path.exists():
            self.config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        else:
            self.config = DEFAULT_CONFIG.copy()
            self.save()
        return self.config

    def save(self) -> None:
        if not self.config:
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(yaml.dump(self.config, default_flow_style=False), encoding="utf-8")

    def apply_updates(self, updates: list[ConfigUpdate]) -> list[str]:
        if not self.config or not self.config.get("self_modify", {}).get("enabled"):
            return []

        applied = []
        modifiable = self.config.get("self_modify", {}).get("modifiable", [])

        for update in updates:
            is_allowed = any(
                fnmatch.fnmatch(update.file, pattern)
                for pattern in modifiable
            )

            if not is_allowed:
                print(f"Self-modify blocked: {update.file} not in modifiable list")
                continue

            if update.file == "config/synesis.yaml":
                self._set_nested(self.config, update.path, update.value)
                self.save()
                applied.append(f"{update.path} = {update.value!r} ({update.reason})")

        return applied

    def get(self) -> dict:
        if not self.config:
            raise RuntimeError("Config not loaded. Call load() first.")
        return self.config

    def _set_nested(self, obj: dict, path: str, value: object) -> None:
        keys = path.split(".")
        for key in keys[:-1]:
            if key not in obj or not isinstance(obj[key], dict):
                obj[key] = {}
            obj = obj[key]
        obj[keys[-1]] = value
