"""Synesis CLI - self-evolving agent memory system.

Run `synesis` and it just works. No manual syncing, no manual anything.
The agent handles everything autonomously.
"""
from __future__ import annotations

import json
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


def _print_header():
    click.echo()
    click.echo("  \033[1;35mSYNESIS\033[0m  self-evolving agent memory")
    click.echo("  \033[2m" + "-" * 42 + "\033[0m")


def _print_status(config: dict, store: KnowledgeStore):
    entries = store.list()
    by_cat: dict[str, int] = {}
    for e in entries:
        by_cat[e.category] = by_cat.get(e.category, 0) + 1

    # Count active connectors
    connectors = config.get("connectors", {})
    active = [n for n, c in connectors.items() if c.get("enabled")]

    click.echo(f"  \033[2mdata\033[0m     ~/synesis-data")
    click.echo(f"  \033[2mentries\033[0m  {len(entries)} total", nl=False)
    if by_cat:
        parts = [f"{v} {k}" for k, v in sorted(by_cat.items())]
        click.echo(f" ({', '.join(parts)})")
    else:
        click.echo()
    click.echo(f"  \033[2msources\033[0m  {', '.join(active) if active else 'none'}")
    click.echo(f"  \033[2mschedule\033[0m {config.get('sync_schedule', '0 */12 * * *')}")
    click.echo()


def _log(msg: str, level: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    colors = {"info": "36", "ok": "32", "warn": "33", "err": "31", "dim": "2"}
    c = colors.get(level, "0")
    click.echo(f"  \033[2m{ts}\033[0m  \033[{c}m{msg}\033[0m")


@click.group(invoke_without_command=True)
@click.version_option("0.1.0")
@click.pass_context
def cli(ctx):
    """Synesis - self-evolving agent memory system.

    Run without arguments to start the agent. It will auto-sync
    on schedule and evolve its own configuration over time.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
def run():
    """Start the Synesis agent. Runs autonomously forever."""
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)

    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    store.init()

    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    config = config_manager.load()

    _print_header()
    _print_status(config, store)

    schedule = config.get("sync_schedule", "0 */12 * * *")

    # Run first sync immediately
    _log("starting initial sync...")
    try:
        engine = SyncEngine(str(PROJECT_DIR))
        result = engine.run()
        _log(f"synced: {result['entries']} entries extracted, {len(result['config_updates'])} self-modifications", "ok")
    except Exception as e:
        _log(f"sync failed: {e}", "err")

    # Reload config (may have been self-modified)
    config = config_manager.load()
    _print_status(config, store)

    # Schedule loop
    cron = croniter(schedule)
    _log(f"agent running, next sync at {datetime.fromtimestamp(cron.get_next(float)).strftime('%H:%M')}", "dim")
    _log("ctrl+c to stop", "dim")

    try:
        while True:
            next_run = cron.get_next(float)
            sleep_time = max(0, next_run - time.time())
            time.sleep(sleep_time)

            _log("scheduled sync starting...")
            try:
                config = config_manager.load()
                fresh_engine = SyncEngine(str(PROJECT_DIR))
                result = fresh_engine.run()
                _log(
                    f"synced: {result['entries']} entries, {len(result['config_updates'])} self-mods",
                    "ok",
                )
            except Exception as e:
                _log(f"sync failed: {e}", "err")

            cron = croniter(schedule)
            _log(f"next sync at {datetime.fromtimestamp(cron.get_next(float)).strftime('%H:%M')}", "dim")
    except KeyboardInterrupt:
        click.echo()
        _log("agent stopped", "dim")


@cli.command()
def status():
    """Show what Synesis knows."""
    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    store.init()
    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    config = config_manager.load()

    _print_header()
    _print_status(config, store)

    entries = store.list()
    if entries:
        click.echo("  \033[2mrecent:\033[0m")
        for e in entries[:10]:
            click.echo(f"    \033[35m{e.category:12s}\033[0m {e.title}")
        if len(entries) > 10:
            click.echo(f"    \033[2m... and {len(entries) - 10} more\033[0m")
    click.echo()


@cli.command()
@click.argument("query")
def ask(query: str):
    """Ask Synesis what it knows about something."""
    from synesis.kb.search import SearchIndex

    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    store.init()

    index = SearchIndex()
    for entry in store.list():
        index.add(entry)

    results = index.get_context(query, max_tokens=4000)

    if not results:
        click.echo("  \033[2mno relevant knowledge found\033[0m")
        return

    click.echo()
    for e in results:
        click.echo(f"  \033[35m[{e.category}]\033[0m \033[1m{e.title}\033[0m")
        # Indent content
        for line in e.content.split("\n")[:4]:
            click.echo(f"    \033[2m{line}\033[0m")
        if e.tags:
            click.echo(f"    \033[36m{' '.join('#' + t for t in e.tags)}\033[0m")
        click.echo()


@cli.command()
@click.argument("provider_name")
@click.option("--client-id", required=True, help="OAuth client ID")
@click.option("--client-secret", required=True, help="OAuth client secret")
def connect(provider_name: str, client_id: str, client_secret: str):
    """Connect an account via OAuth."""
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)

    provider = get_provider(provider_name, client_id, client_secret)
    if not provider:
        click.echo(f"  \033[31munknown provider: {provider_name}\033[0m")
        click.echo(f"  available: {', '.join(list_providers())}")
        return

    oauth = OAuthManager(str(PROJECT_DIR))
    oauth.init()

    # Also save credentials to config so syncs can use them
    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    config = config_manager.load()
    connector_name = "gmail" if provider_name == "google" else provider_name
    config.setdefault("connectors", {}).setdefault(connector_name, {})
    config["connectors"][connector_name]["client_id"] = client_id
    config["connectors"][connector_name]["client_secret"] = client_secret
    config["connectors"][connector_name]["enabled"] = True
    config_manager.config = config
    config_manager.save()

    oauth.authenticate(provider)
    _log(f"connected to {provider_name}", "ok")


@cli.command()
def connections():
    """Show connected accounts."""
    oauth = OAuthManager(str(PROJECT_DIR))
    oauth.init()
    authenticated = oauth.list_authenticated()

    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    config = config_manager.load()
    connectors = config.get("connectors", {})

    click.echo()
    for name, conf in connectors.items():
        enabled = conf.get("enabled", False)
        authed = name in authenticated or name == "claude_code"
        if enabled and authed:
            click.echo(f"  \033[32m*\033[0m {name}")
        elif enabled:
            click.echo(f"  \033[33m*\033[0m {name} \033[2m(not authenticated)\033[0m")
        else:
            click.echo(f"  \033[2m  {name} (disabled)\033[0m")

    available = [p for p in list_providers() if p not in connectors]
    if available:
        click.echo(f"\n  \033[2mavailable: {', '.join(available)}\033[0m")
    click.echo()


if __name__ == "__main__":
    cli()
