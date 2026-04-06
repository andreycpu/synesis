import type { OAuthProvider } from "./types.js";

// Provider templates - users supply their own client IDs/secrets via config
export function getProvider(
  name: string,
  clientId: string,
  clientSecret: string
): OAuthProvider | null {
  const templates: Record<string, Omit<OAuthProvider, "clientId" | "clientSecret">> = {
    google: {
      name: "google",
      authUrl: "https://accounts.google.com/o/oauth2/v2/auth",
      tokenUrl: "https://oauth2.googleapis.com/token",
      scopes: [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
      ],
      callbackPath: "/callback",
    },
    twitter: {
      name: "twitter",
      authUrl: "https://twitter.com/i/oauth2/authorize",
      tokenUrl: "https://api.twitter.com/2/oauth2/token",
      scopes: ["tweet.read", "users.read", "offline.access"],
      callbackPath: "/callback",
    },
    notion: {
      name: "notion",
      authUrl: "https://api.notion.com/v1/oauth/authorize",
      tokenUrl: "https://api.notion.com/v1/oauth/token",
      scopes: [],
      callbackPath: "/callback",
    },
    slack: {
      name: "slack",
      authUrl: "https://slack.com/oauth/v2/authorize",
      tokenUrl: "https://slack.com/api/oauth.v2.access",
      scopes: [
        "channels:history",
        "channels:read",
        "im:history",
        "users:read",
      ],
      callbackPath: "/callback",
    },
    github: {
      name: "github",
      authUrl: "https://github.com/login/oauth/authorize",
      tokenUrl: "https://github.com/login/oauth/access_token",
      scopes: ["read:user", "repo"],
      callbackPath: "/callback",
    },
    linear: {
      name: "linear",
      authUrl: "https://linear.app/oauth/authorize",
      tokenUrl: "https://api.linear.app/oauth/token",
      scopes: ["read"],
      callbackPath: "/callback",
    },
    spotify: {
      name: "spotify",
      authUrl: "https://accounts.spotify.com/authorize",
      tokenUrl: "https://accounts.spotify.com/api/token",
      scopes: [
        "user-read-recently-played",
        "user-read-currently-playing",
        "user-top-read",
      ],
      callbackPath: "/callback",
    },
  };

  const template = templates[name];
  if (!template) return null;

  return { ...template, clientId, clientSecret };
}

export function listProviders(): string[] {
  return ["google", "twitter", "notion", "slack", "github", "linear", "spotify"];
}
