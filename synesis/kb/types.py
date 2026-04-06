from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class KnowledgeEntry:
    id: str
    title: str
    category: str
    content: str
    source: str
    tags: list[str] = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    updated: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict = field(default_factory=dict)


@dataclass
class ConversationMessage:
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: str | None = None


@dataclass
class RawConversation:
    source: str
    id: str
    messages: list[ConversationMessage]
    timestamp: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractionResult:
    entries: list[KnowledgeEntry]
    config_updates: list[ConfigUpdate] = field(default_factory=list)


@dataclass
class ConfigUpdate:
    file: str
    path: str
    value: object
    reason: str
