from synesis.connectors.base import BaseConnector
from synesis.connectors.claude_code import ClaudeCodeConnector
from synesis.connectors.chatgpt import ChatGPTConnector
from synesis.connectors.claude_ai import ClaudeAIConnector
from synesis.connectors.gmail import GmailConnector

CONNECTOR_REGISTRY: dict[str, type[BaseConnector]] = {
    "claude_code": ClaudeCodeConnector,
    "chatgpt": ChatGPTConnector,
    "claude_ai": ClaudeAIConnector,
    "gmail": GmailConnector,
}


def create_connector(name: str, config: dict) -> BaseConnector | None:
    cls = CONNECTOR_REGISTRY.get(name)
    if not cls:
        return None
    return cls(config)


def list_connectors() -> list[str]:
    return list(CONNECTOR_REGISTRY.keys())
