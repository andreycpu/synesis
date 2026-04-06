from __future__ import annotations

import hashlib
import secrets
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

from synesis.auth.store import AuthStore

CALLBACK_PORT = 9876


class OAuthManager:
    def __init__(self, project_dir: str):
        self.store = AuthStore(project_dir)

    def init(self) -> None:
        self.store.init()

    def authenticate(self, provider: dict) -> dict | None:
        # Check for existing valid tokens
        existing = self.store.load(provider["name"])
        if existing:
            expires_at = existing.get("expires_at", 0)
            if expires_at > time.time() + 300:
                return existing
            if existing.get("refresh_token"):
                try:
                    refreshed = self._refresh_token(provider, existing["refresh_token"])
                    self.store.save(provider["name"], refreshed)
                    return refreshed
                except Exception:
                    pass

        # Start OAuth flow
        tokens = self._run_oauth_flow(provider)
        if tokens:
            self.store.save(provider["name"], tokens)
        return tokens

    def get_token(self, provider_name: str) -> dict | None:
        return self.store.load(provider_name)

    def list_authenticated(self) -> list[str]:
        return self.store.list()

    def revoke(self, provider_name: str) -> bool:
        return self.store.delete(provider_name)

    def _run_oauth_flow(self, provider: dict) -> dict | None:
        state = secrets.token_hex(16)
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = (
            hashlib.sha256(code_verifier.encode())
            .digest()
            .hex()
        )
        # Proper base64url encoding for PKCE
        import base64
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        callback_url = f"http://localhost:{CALLBACK_PORT}/callback"

        params = {
            "client_id": provider["client_id"],
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": " ".join(provider["scopes"]),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }

        auth_url = f"{provider['auth_url']}?{urlencode(params)}"
        print(f"\nOpen this URL to authenticate with {provider['name']}:\n")
        print(auth_url)
        print("\nWaiting for callback...")

        # Try to open browser
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", auth_url])
            elif sys.platform == "linux":
                subprocess.Popen(["xdg-open", auth_url])
        except Exception:
            pass

        # Wait for callback
        code = self._wait_for_callback(state)
        if not code:
            return None

        return self._exchange_code(provider, code, callback_url, code_verifier)

    def _wait_for_callback(self, expected_state: str) -> str | None:
        result = {"code": None}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)

                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return

                error = params.get("error", [None])[0]
                if error:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(f"Error: {error}".encode())
                    return

                state = params.get("state", [None])[0]
                if state != expected_state:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Invalid state")
                    return

                code = params.get("code", [None])[0]
                if not code:
                    self.send_response(400)
                    self.end_headers()
                    return

                result["code"] = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:system-ui;display:flex;justify-content:center;"
                    b"align-items:center;height:100vh;margin:0'>"
                    b"<div style='text-align:center'><h1>Synesis</h1>"
                    b"<p>Authentication successful. You can close this tab.</p></div>"
                    b"</body></html>"
                )

            def log_message(self, *args):
                pass  # Suppress logs

        server = HTTPServer(("localhost", CALLBACK_PORT), Handler)
        server.timeout = 120

        # Run in thread with timeout
        thread = Thread(target=lambda: server.handle_request())
        thread.start()
        thread.join(timeout=120)

        server.server_close()
        return result["code"]

    def _exchange_code(
        self, provider: dict, code: str, redirect_uri: str, code_verifier: str
    ) -> dict | None:
        with httpx.Client() as client:
            resp = client.post(
                provider["token_url"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": provider["client_id"],
                    "client_secret": provider["client_secret"],
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_at": time.time() + data.get("expires_in", 3600),
                "token_type": data.get("token_type", "Bearer"),
                "scope": data.get("scope"),
            }

    def _refresh_token(self, provider: dict, refresh_token: str) -> dict:
        with httpx.Client() as client:
            resp = client.post(
                provider["token_url"],
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": provider["client_id"],
                    "client_secret": provider["client_secret"],
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
                "expires_at": time.time() + data.get("expires_in", 3600),
                "token_type": data.get("token_type", "Bearer"),
                "scope": data.get("scope"),
            }
