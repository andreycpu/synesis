export interface OAuthProvider {
  name: string;
  clientId: string;
  clientSecret: string;
  authUrl: string;
  tokenUrl: string;
  scopes: string[];
  callbackPath?: string;
}

export interface TokenSet {
  access_token: string;
  refresh_token?: string;
  expires_at?: number;
  token_type: string;
  scope?: string;
}

export interface StoredAuth {
  provider: string;
  tokens: TokenSet;
  created: string;
  updated: string;
}
