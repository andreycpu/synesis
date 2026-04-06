import http from "http";
import { URL } from "url";
import crypto from "crypto";
import type { OAuthProvider, TokenSet } from "./types.js";
import { AuthStore } from "./store.js";

const CALLBACK_PORT = 9876;
const CALLBACK_HOST = "localhost";

export class OAuthManager {
  private store: AuthStore;

  constructor(projectDir: string) {
    this.store = new AuthStore(projectDir);
  }

  async init(): Promise<void> {
    await this.store.init();
  }

  async authenticate(provider: OAuthProvider): Promise<TokenSet> {
    // Check for existing valid tokens
    const existing = await this.store.load(provider.name);
    if (existing && existing.tokens.expires_at) {
      if (existing.tokens.expires_at > Date.now() / 1000 + 300) {
        return existing.tokens;
      }
      // Try refresh
      if (existing.tokens.refresh_token) {
        try {
          const refreshed = await this.refreshToken(provider, existing.tokens.refresh_token);
          await this.store.save(provider.name, refreshed);
          return refreshed;
        } catch {
          // Fall through to re-auth
        }
      }
    }

    // Start OAuth flow
    const tokens = await this.startOAuthFlow(provider);
    await this.store.save(provider.name, tokens);
    return tokens;
  }

  async getToken(providerName: string): Promise<TokenSet | null> {
    const auth = await this.store.load(providerName);
    return auth?.tokens || null;
  }

  async listAuthenticated(): Promise<string[]> {
    return this.store.list();
  }

  async revoke(providerName: string): Promise<boolean> {
    return this.store.delete(providerName);
  }

  private async startOAuthFlow(provider: OAuthProvider): Promise<TokenSet> {
    const state = crypto.randomBytes(16).toString("hex");
    const codeVerifier = crypto.randomBytes(32).toString("base64url");
    const codeChallenge = crypto
      .createHash("sha256")
      .update(codeVerifier)
      .digest("base64url");

    const callbackUrl = `http://${CALLBACK_HOST}:${CALLBACK_PORT}${provider.callbackPath || "/callback"}`;

    const authParams = new URLSearchParams({
      client_id: provider.clientId,
      redirect_uri: callbackUrl,
      response_type: "code",
      scope: provider.scopes.join(" "),
      state,
      code_challenge: codeChallenge,
      code_challenge_method: "S256",
      access_type: "offline",
      prompt: "consent",
    });

    const authUrl = `${provider.authUrl}?${authParams.toString()}`;

    console.log(`\nOpen this URL in your browser to authenticate with ${provider.name}:\n`);
    console.log(authUrl);
    console.log(`\nWaiting for callback...`);

    // Try to open browser automatically
    const { exec } = await import("child_process");
    exec(`open "${authUrl}"`);

    // Start local server to receive callback
    const code = await this.waitForCallback(state, provider.callbackPath || "/callback");

    // Exchange code for tokens
    const tokens = await this.exchangeCode(provider, code, callbackUrl, codeVerifier);
    return tokens;
  }

  private waitForCallback(expectedState: string, callbackPath: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        server.close();
        reject(new Error("OAuth callback timed out (120s)"));
      }, 120000);

      const server = http.createServer((req, res) => {
        const url = new URL(req.url || "", `http://${CALLBACK_HOST}:${CALLBACK_PORT}`);

        if (url.pathname !== callbackPath) {
          res.writeHead(404);
          res.end("Not found");
          return;
        }

        const code = url.searchParams.get("code");
        const state = url.searchParams.get("state");
        const error = url.searchParams.get("error");

        if (error) {
          res.writeHead(400);
          res.end(`Authentication failed: ${error}`);
          clearTimeout(timeout);
          server.close();
          reject(new Error(`OAuth error: ${error}`));
          return;
        }

        if (state !== expectedState) {
          res.writeHead(400);
          res.end("Invalid state parameter");
          clearTimeout(timeout);
          server.close();
          reject(new Error("OAuth state mismatch"));
          return;
        }

        if (!code) {
          res.writeHead(400);
          res.end("No code received");
          clearTimeout(timeout);
          server.close();
          reject(new Error("No OAuth code received"));
          return;
        }

        res.writeHead(200, { "Content-Type": "text/html" });
        res.end(`
          <html><body style="font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;">
            <div style="text-align: center;">
              <h1>Synesis</h1>
              <p>Authentication successful. You can close this tab.</p>
            </div>
          </body></html>
        `);

        clearTimeout(timeout);
        server.close();
        resolve(code);
      });

      server.listen(CALLBACK_PORT, CALLBACK_HOST, () => {
        // Server ready
      });
    });
  }

  private async exchangeCode(
    provider: OAuthProvider,
    code: string,
    redirectUri: string,
    codeVerifier: string
  ): Promise<TokenSet> {
    const body = new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      client_id: provider.clientId,
      client_secret: provider.clientSecret,
      code_verifier: codeVerifier,
    });

    const response = await fetch(provider.tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Token exchange failed: ${response.status} ${text}`);
    }

    const data = await response.json();
    return {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at: data.expires_in
        ? Math.floor(Date.now() / 1000) + data.expires_in
        : undefined,
      token_type: data.token_type || "Bearer",
      scope: data.scope,
    };
  }

  private async refreshToken(
    provider: OAuthProvider,
    refreshToken: string
  ): Promise<TokenSet> {
    const body = new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: provider.clientId,
      client_secret: provider.clientSecret,
    });

    const response = await fetch(provider.tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });

    if (!response.ok) {
      throw new Error(`Token refresh failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      access_token: data.access_token,
      refresh_token: data.refresh_token || refreshToken,
      expires_at: data.expires_in
        ? Math.floor(Date.now() / 1000) + data.expires_in
        : undefined,
      token_type: data.token_type || "Bearer",
      scope: data.scope,
    };
  }
}
