"""Synesis CLI - self-evolving agent memory system.

Run `synesis`. It asks you what to connect. Then it runs forever.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import click
from croniter import croniter

from synesis.auth import OAuthManager, get_provider, list_providers
from synesis.config import ConfigManager
from synesis.kb.store import KnowledgeStore
from synesis.sync import SyncEngine

PROJECT_DIR = Path(os.environ.get("SYNESIS_DIR", os.path.expanduser("~/synesis-data")))

# Friendly names and descriptions for the setup flow
SOURCE_INFO = {
    "claude_code": {
        "name": "Claude Code",
        "desc": "your Claude Code conversations",
        "oauth": False,
        "auto": True,  # no setup needed, just works
    },
    "google": {
        "name": "Gmail + Google Calendar + Drive",
        "desc": "emails, calendar events, documents",
        "oauth": True,
        "connector": "gmail",
    },
    "slack": {
        "name": "Slack",
        "desc": "messages and channels",
        "oauth": True,
    },
    "notion": {
        "name": "Notion",
        "desc": "pages and databases",
        "oauth": True,
    },
    "github": {
        "name": "GitHub",
        "desc": "issues, PRs, discussions",
        "oauth": True,
    },
    "twitter": {
        "name": "Twitter / X",
        "desc": "tweets and DMs",
        "oauth": True,
    },
    "linear": {
        "name": "Linear",
        "desc": "issues and projects",
        "oauth": True,
    },
    "spotify": {
        "name": "Spotify",
        "desc": "listening history",
        "oauth": True,
    },
}


def _header():
    click.echo()
    click.echo("  \033[1;35mSYNESIS\033[0m  self-evolving agent memory")
    click.echo("  \033[2m" + "-" * 42 + "\033[0m")
    click.echo()


def _log(msg: str, level: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    colors = {"info": "36", "ok": "32", "warn": "33", "err": "31", "dim": "2"}
    c = colors.get(level, "0")
    click.echo(f"  \033[2m{ts}\033[0m  \033[{c}m{msg}\033[0m")


def _check_api_key() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return True

    click.echo("  \033[33mSynesis needs an Anthropic API key to extract knowledge.\033[0m")
    click.echo()
    key = click.prompt("  Enter your ANTHROPIC_API_KEY", hide_input=True)
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
        # Persist it
        env_file = PROJECT_DIR / ".env"
        env_file.write_text(f"ANTHROPIC_API_KEY={key}\n")
        os.chmod(env_file, 0o600)
        click.echo("  \033[32mSaved.\033[0m")
        click.echo()
        return True
    return False


def _load_env():
    """Load .env from project dir if it exists."""
    env_file = PROJECT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().strip().split("\n"):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _is_first_run() -> bool:
    return not (PROJECT_DIR / "config" / "synesis.yaml").exists()


def _run_setup():
    """Interactive setup - asks user what to connect, handles everything."""
    click.echo("  Let's set you up. This takes about 30 seconds.")
    click.echo()

    # API key
    if not _check_api_key():
        click.echo("  \033[31mCan't run without an API key.\033[0m")
        raise SystemExit(1)

    # Initialize
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    store.init()
    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    config = config_manager.load()
    oauth = OAuthManager(str(PROJECT_DIR))
    oauth.init()

    # Claude Code is automatic
    click.echo("  \033[32m+\033[0m Claude Code \033[2m(auto-detected, no setup needed)\033[0m")

    # Ask about each OAuth source
    click.echo()
    click.echo("  \033[2mWhat else do you want to connect?\033[0m")
    click.echo()

    oauth_sources = {k: v for k, v in SOURCE_INFO.items() if v.get("oauth")}

    for key, info in oauth_sources.items():
        answer = click.confirm(f"  {info['name']} ({info['desc']})?", default=False)
        if not answer:
            continue

        connector_name = info.get("connector", key)

        click.echo()
        click.echo(f"  \033[2mTo connect {info['name']}, you need OAuth credentials.\033[0m")
        click.echo(f"  \033[2mCreate an app at the provider's developer console and paste the credentials below.\033[0m")
        click.echo()

        client_id = click.prompt(f"  Client ID for {info['name']}")
        client_secret = click.prompt(f"  Client Secret for {info['name']}", hide_input=True)

        # Save to config
        config.setdefault("connectors", {}).setdefault(connector_name, {})
        config["connectors"][connector_name]["client_id"] = client_id
        config["connectors"][connector_name]["client_secret"] = client_secret
        config["connectors"][connector_name]["enabled"] = True
        config_manager.config = config
        config_manager.save()

        # Run OAuth flow
        provider = get_provider(key, client_id, client_secret)
        if provider:
            click.echo(f"  \033[2mOpening browser for {info['name']} authentication...\033[0m")
            try:
                oauth.authenticate(provider)
                click.echo(f"  \033[32m+\033[0m {info['name']} connected")
            except Exception as e:
                click.echo(f"  \033[31mx\033[0m {info['name']} failed: {e}")
        click.echo()

    click.echo("  \033[32mSetup complete.\033[0m You won't need to do this again.")
    click.echo()


def _show_status(config: dict, store: KnowledgeStore):
    entries = store.list()
    by_cat: dict[str, int] = {}
    for e in entries:
        by_cat[e.category] = by_cat.get(e.category, 0) + 1

    connectors = config.get("connectors", {})
    active = [n for n, c in connectors.items() if c.get("enabled")]

    click.echo(f"  \033[2mentries\033[0m  {len(entries)} total", nl=False)
    if by_cat:
        parts = [f"{v} {k}" for k, v in sorted(by_cat.items())]
        click.echo(f" ({', '.join(parts)})")
    else:
        click.echo()
    click.echo(f"  \033[2msources\033[0m  {', '.join(active) if active else 'claude_code'}")
    click.echo()


@click.command()
@click.version_option("0.1.0")
def cli():
    """Synesis - self-evolving agent memory system.

    Just run `synesis`. It handles everything.
    """
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    _load_env()
    _header()

    # First run: interactive setup
    if _is_first_run():
        _run_setup()
    else:
        # Not first run, but still check API key
        if not _check_api_key():
            raise SystemExit(1)

    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    store.init()
    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    config = config_manager.load()

    _show_status(config, store)

    schedule = config.get("sync_schedule", "0 */12 * * *")

    # Sync immediately
    _log("syncing...")
    try:
        engine = SyncEngine(str(PROJECT_DIR))
        result = engine.run()
        n = result["entries"]
        m = len(result["config_updates"])
        _log(f"done: {n} entries extracted{f', {m} self-modifications' if m else ''}", "ok")
    except Exception as e:
        _log(f"sync failed: {e}", "err")

    # Show updated status
    config = config_manager.load()
    _show_status(config, store)

    # Run forever
    cron = croniter(schedule)
    next_time = datetime.fromtimestamp(cron.get_next(float)).strftime("%H:%M")
    _log(f"running. next sync at {next_time}", "dim")

    try:
        while True:
            next_run = cron.get_next(float)
            time.sleep(max(0, next_run - time.time()))

            _log("syncing...")
            try:
                fresh = SyncEngine(str(PROJECT_DIR))
                result = fresh.run()
                n = result["entries"]
                m = len(result["config_updates"])
                _log(f"done: {n} entries{f', {m} self-mods' if m else ''}", "ok")
            except Exception as e:
                _log(f"sync failed: {e}", "err")

            cron = croniter(schedule)
            next_time = datetime.fromtimestamp(cron.get_next(float)).strftime("%H:%M")
            _log(f"next sync at {next_time}", "dim")
    except KeyboardInterrupt:
        click.echo()
        _log("stopped", "dim")


if __name__ == "__main__":
    cli()
