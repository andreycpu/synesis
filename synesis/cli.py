"""Synesis CLI - self-evolving agent memory system."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import click

from synesis.auth import OAuthManager, get_provider, list_providers
from synesis.config import ConfigManager
from synesis.kb.compactor import Compactor
from synesis.kb.store import KnowledgeStore
from synesis.sync import SyncEngine

PROJECT_DIR = Path(os.environ.get("SYNESIS_DIR", "."))


@click.group()
@click.version_option("0.1.0")
def cli():
    """Synesis - self-evolving agent memory system."""
    pass


@cli.command()
@click.option("-p", "--port", default=3000, help="Port to run on")
def web(port: int):
    """Launch the Synesis web UI."""
    from synesis.web.app import main as run_web
    os.environ["SYNESIS_PORT"] = str(port)
    run_web()


@cli.command()
def init():
    """Initialize a new Synesis knowledge base."""
    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    store.init()

    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    config_manager.load()

    click.echo("Synesis initialized.")
    click.echo(f"  Knowledge base: {PROJECT_DIR / 'knowledge'}")
    click.echo(f"  Config: {PROJECT_DIR / 'config' / 'synesis.yaml'}")
    click.echo("\nRun 'synesis sync' to start extracting knowledge.")


@cli.command()
def sync():
    """Run a sync cycle: fetch, extract, compact."""
    engine = SyncEngine(str(PROJECT_DIR))
    engine.run()


@cli.command()
@click.argument("query")
@click.option("-c", "--category", default=None, help="Filter by category")
def search(query: str, category: str | None):
    """Search the knowledge base."""
    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    results = store.search(query, category)

    if not results:
        click.echo("No results found.")
        return

    for entry in results:
        click.echo(f"\n[{entry.category}] {entry.title}")
        click.echo(f"  Source: {entry.source} | Tags: {', '.join(entry.tags)}")
        preview = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
        click.echo(f"  {preview}")


@cli.command("list")
@click.option("-c", "--category", default=None, help="Filter by category")
def list_entries(category: str | None):
    """List knowledge entries."""
    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    entries = store.list(category)

    if not entries:
        click.echo("No entries found.")
        return

    click.echo(f"\n{len(entries)} entries:\n")
    for entry in entries:
        click.echo(f"  [{entry.category}] {entry.title} ({entry.source}) - {entry.updated}")


@cli.command()
@click.option("-t", "--threshold", default=50, help="Max entries per category")
def compact(threshold: int):
    """Merge related entries to reduce KB size."""
    store = KnowledgeStore(PROJECT_DIR / "knowledge")
    compactor = Compactor(store)
    result = compactor.compact(threshold)

    if result.merged == 0:
        click.echo("No compaction needed.")
    else:
        click.echo(f"Compacted: {result.merged} merges, {result.archived} entries archived")
        for c in result.categories:
            click.echo(f"  {c['category']}: {c['merged']} groups, {c['archived']} archived")


@cli.command()
def daemon():
    """Run as a daemon with scheduled sync."""
    from croniter import croniter

    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    config = config_manager.load()
    schedule = config.get("sync_schedule", "0 */12 * * *")

    click.echo(f"Synesis daemon starting...")
    click.echo(f"Schedule: {schedule}")

    # Run immediately
    engine = SyncEngine(str(PROJECT_DIR))
    engine.run()

    cron = croniter(schedule)
    click.echo("Daemon running. Press Ctrl+C to stop.")

    try:
        while True:
            next_run = cron.get_next(float)
            sleep_time = max(0, next_run - time.time())
            time.sleep(sleep_time)

            click.echo(f"\n[{__import__('datetime').datetime.now().isoformat()}] Scheduled sync...")
            fresh_engine = SyncEngine(str(PROJECT_DIR))
            fresh_engine.run()
    except KeyboardInterrupt:
        click.echo("\nDaemon stopped.")


@cli.command()
def config():
    """Show current configuration."""
    config_manager = ConfigManager(PROJECT_DIR / "config" / "synesis.yaml")
    cfg = config_manager.load()
    click.echo(json.dumps(cfg, indent=2, default=str))


# --- Auth commands ---

@cli.group()
def auth():
    """Manage OAuth authentication for connectors."""
    pass


@auth.command("login")
@click.argument("provider_name")
@click.option("--client-id", required=True, help="OAuth client ID")
@click.option("--client-secret", required=True, help="OAuth client secret")
def auth_login(provider_name: str, client_id: str, client_secret: str):
    """Authenticate with a provider."""
    provider = get_provider(provider_name, client_id, client_secret)
    if not provider:
        click.echo(f"Unknown provider: {provider_name}")
        click.echo(f"Available: {', '.join(list_providers())}")
        raise SystemExit(1)

    oauth = OAuthManager(str(PROJECT_DIR))
    oauth.init()
    oauth.authenticate(provider)
    click.echo(f"\nAuthenticated with {provider_name}.")


@auth.command("list")
def auth_list():
    """List authenticated providers."""
    oauth = OAuthManager(str(PROJECT_DIR))
    oauth.init()
    providers = oauth.list_authenticated()

    if not providers:
        click.echo("No authenticated providers.")
        click.echo(f"Available: {', '.join(list_providers())}")
    else:
        click.echo("Authenticated providers:")
        for p in providers:
            click.echo(f"  - {p}")


@auth.command("revoke")
@click.argument("provider_name")
def auth_revoke(provider_name: str):
    """Revoke authentication for a provider."""
    oauth = OAuthManager(str(PROJECT_DIR))
    oauth.init()
    success = oauth.revoke(provider_name)
    click.echo(f"Revoked {provider_name}." if success else f"No auth found for {provider_name}.")


if __name__ == "__main__":
    cli()
