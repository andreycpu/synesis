"""Synesis Web UI - zero-code interface for the knowledge base."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import Thread

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from synesis.auth import OAuthManager, get_provider, list_providers
from synesis.config import ConfigManager
from synesis.kb.compactor import Compactor
from synesis.kb.search import SearchIndex
from synesis.kb.store import KnowledgeStore
from synesis.kb.types import KnowledgeEntry
from synesis.sync import SyncEngine

PROJECT_DIR = Path(os.environ.get("SYNESIS_DIR", os.path.expanduser("~/synesis-data")))
PROJECT_DIR.mkdir(parents=True, exist_ok=True)

store = KnowledgeStore(PROJECT_DIR / "knowledge")
config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
oauth = OAuthManager(str(PROJECT_DIR))
search_index = SearchIndex()
_index_loaded = False

app = FastAPI(title="Synesis", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _ensure_init():
    store.init()
    config_manager.load()
    oauth.init()


def _ensure_index():
    global _index_loaded
    if _index_loaded:
        return
    store.init()
    for entry in store.list():
        search_index.add(entry)
    _index_loaded = True


def _reload_index():
    global _index_loaded
    search_index.clear()
    _index_loaded = False
    _ensure_index()


# ---- Pages ----

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    _ensure_init()
    return (Path(__file__).parent / "templates" / "index.html").read_text()


# ---- API: Knowledge ----

@app.get("/api/entries")
async def api_list_entries(category: str | None = None):
    store.init()
    entries = store.list(category)
    return [
        {
            "id": e.id, "title": e.title, "category": e.category,
            "content": e.content, "source": e.source, "tags": e.tags,
            "created": e.created, "updated": e.updated,
        }
        for e in entries
    ]


@app.get("/api/entries/{category}/{id}")
async def api_read_entry(category: str, id: str):
    store.init()
    entry = store.read(category, id)
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {
        "id": entry.id, "title": entry.title, "category": entry.category,
        "content": entry.content, "source": entry.source, "tags": entry.tags,
        "created": entry.created, "updated": entry.updated,
    }


@app.post("/api/entries")
async def api_create_entry(request: Request):
    data = await request.json()
    store.init()
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", data["title"].lower()).strip("-")[:50]
    now = datetime.now().isoformat()

    entry = KnowledgeEntry(
        id=slug, title=data["title"], category=data["category"],
        content=data["content"], source="web", tags=data.get("tags", []),
        created=now, updated=now,
    )
    store.write(entry)
    search_index.add(entry)
    return {"ok": True, "id": entry.id}


@app.delete("/api/entries/{category}/{id}")
async def api_delete_entry(category: str, id: str):
    store.init()
    success = store.delete(category, id)
    if success:
        search_index.remove(category, id)
    return {"ok": success}


@app.get("/api/search")
async def api_search(q: str, category: str | None = None, limit: int = 20):
    _ensure_index()
    results = search_index.search(q, limit=limit, category=category)
    return [
        {
            "id": e.id, "title": e.title, "category": e.category,
            "content": e.content[:300], "source": e.source, "tags": e.tags,
        }
        for e in results
    ]


@app.get("/api/stats")
async def api_stats():
    store.init()
    entries = store.list()
    by_cat: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for e in entries:
        by_cat[e.category] = by_cat.get(e.category, 0) + 1
        by_source[e.source] = by_source.get(e.source, 0) + 1
    return {
        "total": len(entries),
        "by_category": by_cat,
        "by_source": by_source,
    }


# ---- API: Sync ----

@app.post("/api/sync")
async def api_sync():
    def _run():
        engine = SyncEngine(str(PROJECT_DIR))
        engine.run()
        _reload_index()

    thread = Thread(target=_run)
    thread.start()
    return {"ok": True, "message": "Sync started in background"}


# ---- API: Compact ----

@app.post("/api/compact")
async def api_compact():
    store.init()
    compactor = Compactor(store)
    result = compactor.compact(50)
    _reload_index()
    return {"merged": result.merged, "archived": result.archived}


# ---- API: Config ----

@app.get("/api/config")
async def api_get_config():
    config = config_manager.load()
    return config


@app.post("/api/config")
async def api_save_config(request: Request):
    data = await request.json()
    config_manager.config = data
    config_manager.save()
    return {"ok": True}


# ---- API: Auth / Connectors ----

@app.get("/api/connectors")
async def api_list_connectors():
    config = config_manager.load()
    connectors = config.get("connectors", {})
    authenticated = oauth.list_authenticated()

    result = []
    for name, conf in connectors.items():
        needs_oauth = name in ("gmail",)  # Expand as more OAuth connectors are added
        result.append({
            "name": name,
            "enabled": conf.get("enabled", False),
            "authenticated": name in authenticated or (not needs_oauth and name in ("claude_code",)),
            "needs_oauth": needs_oauth,
            "config": {k: v for k, v in conf.items() if k not in ("client_secret",)},
        })

    # Add available but not configured providers
    for p in list_providers():
        if p not in connectors and p != "google":  # google maps to gmail connector
            result.append({
                "name": p,
                "enabled": False,
                "authenticated": p in authenticated,
                "needs_oauth": True,
                "config": {},
            })

    return result


@app.post("/api/connectors/{name}/enable")
async def api_enable_connector(name: str, request: Request):
    data = await request.json()
    config = config_manager.load()
    if name not in config.get("connectors", {}):
        config.setdefault("connectors", {})[name] = {}
    config["connectors"][name]["enabled"] = data.get("enabled", True)

    # Save any additional config (like export_path)
    for k, v in data.items():
        if k != "enabled":
            config["connectors"][name][k] = v

    config_manager.config = config
    config_manager.save()
    return {"ok": True}


@app.get("/api/auth/providers")
async def api_auth_providers():
    authenticated = oauth.list_authenticated()
    return [
        {"name": p, "authenticated": p in authenticated}
        for p in list_providers()
    ]


@app.post("/api/auth/login")
async def api_auth_login(request: Request):
    data = await request.json()
    provider = get_provider(
        data["provider"],
        data["client_id"],
        data["client_secret"],
    )
    if not provider:
        return JSONResponse({"error": f"Unknown provider: {data['provider']}"}, status_code=400)

    # Store credentials in config for future syncs
    config = config_manager.load()
    connector_name = "gmail" if data["provider"] == "google" else data["provider"]
    config.setdefault("connectors", {}).setdefault(connector_name, {})
    config["connectors"][connector_name]["client_id"] = data["client_id"]
    config["connectors"][connector_name]["client_secret"] = data["client_secret"]
    config["connectors"][connector_name]["enabled"] = True
    config_manager.config = config
    config_manager.save()

    # Start OAuth flow (this will open browser)
    tokens = oauth.authenticate(provider)
    if tokens:
        return {"ok": True}
    return JSONResponse({"error": "Authentication failed"}, status_code=400)


@app.post("/api/auth/revoke/{provider}")
async def api_auth_revoke(provider: str):
    success = oauth.revoke(provider)
    return {"ok": success}


@app.get("/api/auth/status")
async def api_auth_status():
    return {"authenticated": oauth.list_authenticated()}


def main():
    _ensure_init()
    port = int(os.environ.get("SYNESIS_PORT", "3000"))
    print(f"\n  Synesis is running at http://localhost:{port}\n")

    # Open browser
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", f"http://localhost:{port}"])
        elif sys.platform == "linux":
            subprocess.Popen(["xdg-open", f"http://localhost:{port}"])
    except Exception:
        pass

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
