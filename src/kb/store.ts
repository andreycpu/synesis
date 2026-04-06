import fs from "fs/promises";
import path from "path";
import matter from "gray-matter";
import fg from "fast-glob";
import type { KnowledgeEntry } from "./types.js";

export class KnowledgeStore {
  constructor(private baseDir: string) {}

  async init(): Promise<void> {
    await fs.mkdir(this.baseDir, { recursive: true });
    const categories = [
      "facts",
      "decisions",
      "preferences",
      "contacts",
      "ideas",
    ];
    for (const cat of categories) {
      await fs.mkdir(path.join(this.baseDir, cat), { recursive: true });
    }
  }

  async write(entry: KnowledgeEntry): Promise<string> {
    const filePath = path.join(this.baseDir, entry.category, `${entry.id}.md`);
    await fs.mkdir(path.dirname(filePath), { recursive: true });

    const frontmatter = {
      id: entry.id,
      title: entry.title,
      category: entry.category,
      source: entry.source,
      tags: entry.tags,
      created: entry.created,
      updated: entry.updated,
      ...entry.metadata,
    };

    const fileContent = matter.stringify(entry.content, frontmatter);
    await fs.writeFile(filePath, fileContent, "utf-8");
    return filePath;
  }

  async read(category: string, id: string): Promise<KnowledgeEntry | null> {
    const filePath = path.join(this.baseDir, category, `${id}.md`);
    try {
      const raw = await fs.readFile(filePath, "utf-8");
      return this.parseEntry(raw);
    } catch {
      return null;
    }
  }

  async list(category?: string): Promise<KnowledgeEntry[]> {
    const pattern = category ? `${category}/*.md` : "**/*.md";
    const files = await fg(pattern, { cwd: this.baseDir, absolute: true });
    const entries: KnowledgeEntry[] = [];

    for (const file of files) {
      const raw = await fs.readFile(file, "utf-8");
      const entry = this.parseEntry(raw);
      if (entry) entries.push(entry);
    }

    return entries.sort(
      (a, b) =>
        new Date(b.updated).getTime() - new Date(a.updated).getTime()
    );
  }

  async search(query: string, category?: string): Promise<KnowledgeEntry[]> {
    const entries = await this.list(category);
    const lower = query.toLowerCase();
    return entries.filter(
      (e) =>
        e.title.toLowerCase().includes(lower) ||
        e.content.toLowerCase().includes(lower) ||
        e.tags.some((t) => t.toLowerCase().includes(lower))
    );
  }

  async delete(category: string, id: string): Promise<boolean> {
    const filePath = path.join(this.baseDir, category, `${id}.md`);
    try {
      await fs.unlink(filePath);
      return true;
    } catch {
      return false;
    }
  }

  async update(
    category: string,
    id: string,
    updates: Partial<KnowledgeEntry>
  ): Promise<KnowledgeEntry | null> {
    const existing = await this.read(category, id);
    if (!existing) return null;

    const updated: KnowledgeEntry = {
      ...existing,
      ...updates,
      updated: new Date().toISOString(),
    };

    await this.write(updated);
    return updated;
  }

  private parseEntry(raw: string): KnowledgeEntry | null {
    try {
      const { data, content } = matter(raw);
      return {
        id: data.id || "unknown",
        title: data.title || "Untitled",
        category: data.category || "facts",
        content: content.trim(),
        source: data.source || "unknown",
        tags: data.tags || [],
        created: data.created || new Date().toISOString(),
        updated: data.updated || new Date().toISOString(),
        metadata: Object.fromEntries(
          Object.entries(data).filter(
            ([k]) =>
              ![
                "id",
                "title",
                "category",
                "source",
                "tags",
                "created",
                "updated",
              ].includes(k)
          )
        ),
      };
    } catch {
      return null;
    }
  }
}
