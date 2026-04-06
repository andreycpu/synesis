import fs from "fs/promises";
import path from "path";
import crypto from "crypto";
import type { StoredAuth, TokenSet } from "./types.js";

const ALGORITHM = "aes-256-gcm";

export class AuthStore {
  private dir: string;
  private encryptionKey: Buffer | null = null;

  constructor(baseDir: string) {
    this.dir = path.join(baseDir, ".auth");
  }

  async init(): Promise<void> {
    await fs.mkdir(this.dir, { recursive: true });

    // Derive encryption key from a machine-specific seed
    const keyFile = path.join(this.dir, ".key");
    try {
      const existing = await fs.readFile(keyFile);
      this.encryptionKey = existing;
    } catch {
      const key = crypto.randomBytes(32);
      await fs.writeFile(keyFile, key, { mode: 0o600 });
      this.encryptionKey = key;
    }
  }

  async save(provider: string, tokens: TokenSet): Promise<void> {
    const auth: StoredAuth = {
      provider,
      tokens,
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
    };

    const encrypted = this.encrypt(JSON.stringify(auth));
    const filePath = path.join(this.dir, `${provider}.enc`);
    await fs.writeFile(filePath, encrypted, "utf-8");
  }

  async load(provider: string): Promise<StoredAuth | null> {
    const filePath = path.join(this.dir, `${provider}.enc`);
    try {
      const encrypted = await fs.readFile(filePath, "utf-8");
      const decrypted = this.decrypt(encrypted);
      return JSON.parse(decrypted);
    } catch {
      return null;
    }
  }

  async delete(provider: string): Promise<boolean> {
    const filePath = path.join(this.dir, `${provider}.enc`);
    try {
      await fs.unlink(filePath);
      return true;
    } catch {
      return false;
    }
  }

  async list(): Promise<string[]> {
    try {
      const files = await fs.readdir(this.dir);
      return files
        .filter((f) => f.endsWith(".enc"))
        .map((f) => f.replace(".enc", ""));
    } catch {
      return [];
    }
  }

  private encrypt(text: string): string {
    if (!this.encryptionKey) throw new Error("AuthStore not initialized");
    const iv = crypto.randomBytes(16);
    const cipher = crypto.createCipheriv(ALGORITHM, this.encryptionKey, iv);
    let encrypted = cipher.update(text, "utf8", "hex");
    encrypted += cipher.final("hex");
    const tag = cipher.getAuthTag();
    return `${iv.toString("hex")}:${tag.toString("hex")}:${encrypted}`;
  }

  private decrypt(text: string): string {
    if (!this.encryptionKey) throw new Error("AuthStore not initialized");
    const [ivHex, tagHex, encrypted] = text.split(":");
    const iv = Buffer.from(ivHex, "hex");
    const tag = Buffer.from(tagHex, "hex");
    const decipher = crypto.createDecipheriv(ALGORITHM, this.encryptionKey, iv);
    decipher.setAuthTag(tag);
    let decrypted = decipher.update(encrypted, "hex", "utf8");
    decrypted += decipher.final("utf8");
    return decrypted;
  }
}
