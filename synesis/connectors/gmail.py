from __future__ import annotations

import base64
from datetime import datetime

import httpx

from synesis.auth import OAuthManager, get_provider
from synesis.connectors.base import BaseConnector
from synesis.kb.types import ConversationMessage, RawConversation


class GmailConnector(BaseConnector):
    name = "gmail"

    def __init__(self, config: dict):
        super().__init__(config)
        self.project_dir = config.get("project_dir", ".")
        self.oauth = OAuthManager(self.project_dir)

    def validate(self) -> bool:
        self.oauth.init()
        token = self.oauth.get_token("google")
        return token is not None

    def fetch(self, since: str | None = None) -> list[RawConversation]:
        self.oauth.init()
        provider = get_provider(
            "google",
            self.config.get("client_id", ""),
            self.config.get("client_secret", ""),
        )
        if not provider:
            return []

        tokens = self.oauth.authenticate(provider)
        if not tokens:
            return []

        query = "in:inbox -category:promotions -category:social -category:updates"
        if since:
            date_str = since[:10].replace("-", "/")
            query += f" after:{date_str}"

        max_results = self.config.get("max_results", 50)
        conversations: list[RawConversation] = []

        with httpx.Client() as client:
            headers = {"Authorization": f"Bearer {tokens['access_token']}"}

            # List threads
            resp = client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/threads",
                params={"q": query, "maxResults": max_results},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            for thread_ref in data.get("threads", []):
                try:
                    resp = client.get(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_ref['id']}",
                        params={"format": "full"},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    thread = resp.json()

                    messages = []
                    for msg in thread.get("messages", []):
                        sender = self._get_header(msg, "From") or "unknown"
                        subject = self._get_header(msg, "Subject") or "No subject"
                        body = self._extract_body(msg)
                        user_email = self.config.get("user_email", "")

                        messages.append(
                            ConversationMessage(
                                role="user" if user_email and user_email in sender else "assistant",
                                content=f"From: {sender}\nSubject: {subject}\n\n{body}",
                                timestamp=datetime.fromtimestamp(
                                    int(msg.get("internalDate", 0)) / 1000
                                ).isoformat(),
                            )
                        )

                    if messages:
                        subject = self._get_header(thread["messages"][0], "Subject") or "No subject"
                        conversations.append(
                            RawConversation(
                                source="gmail",
                                id=f"gmail-{thread_ref['id']}",
                                messages=messages,
                                timestamp=messages[-1].timestamp or "",
                                metadata={"thread_id": thread_ref["id"], "subject": subject},
                            )
                        )
                except Exception:
                    continue

        return conversations

    def _get_header(self, msg: dict, name: str) -> str | None:
        headers = msg.get("payload", {}).get("headers", [])
        for h in headers:
            if h.get("name", "").lower() == name.lower():
                return h.get("value")
        return None

    def _extract_body(self, msg: dict) -> str:
        payload = msg.get("payload", {})

        # Try text/plain part
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    try:
                        return base64.urlsafe_b64decode(data).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        continue

        # Fall back to body
        data = payload.get("body", {}).get("data")
        if data:
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                pass

        return msg.get("snippet", "")
