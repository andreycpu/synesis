from __future__ import annotations

from abc import ABC, abstractmethod

from synesis.kb.types import RawConversation


class BaseConnector(ABC):
    name: str

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def validate(self) -> bool:
        ...

    @abstractmethod
    def fetch(self, since: str | None = None) -> list[RawConversation]:
        ...
