from __future__ import annotations

PROVIDER_TEMPLATES: dict[str, dict] = {
    "google": {
        "name": "google",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    },
    "twitter": {
        "name": "twitter",
        "auth_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "scopes": ["tweet.read", "users.read", "offline.access"],
    },
    "notion": {
        "name": "notion",
        "auth_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scopes": [],
    },
    "slack": {
        "name": "slack",
        "auth_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scopes": ["channels:history", "channels:read", "im:history", "users:read"],
    },
    "github": {
        "name": "github",
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["read:user", "repo"],
    },
    "linear": {
        "name": "linear",
        "auth_url": "https://linear.app/oauth/authorize",
        "token_url": "https://api.linear.app/oauth/token",
        "scopes": ["read"],
    },
    "spotify": {
        "name": "spotify",
        "auth_url": "https://accounts.spotify.com/authorize",
        "token_url": "https://accounts.spotify.com/api/token",
        "scopes": ["user-read-recently-played", "user-read-currently-playing", "user-top-read"],
    },
}


def get_provider(name: str, client_id: str, client_secret: str) -> dict | None:
    template = PROVIDER_TEMPLATES.get(name)
    if not template:
        return None
    return {**template, "client_id": client_id, "client_secret": client_secret}


def list_providers() -> list[str]:
    return list(PROVIDER_TEMPLATES.keys())
