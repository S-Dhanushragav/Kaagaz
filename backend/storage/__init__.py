"""Case-file storage (Phase 9): Store interface, in-memory and Postgres implementations."""

import logging

from storage.store import MemoryStore, Store

logger = logging.getLogger(__name__)


def make_store(database_url: str) -> Store:
    """Postgres when a URL is configured, else in memory (local runs without a database; nothing is kept)."""
    if not database_url:
        logger.warning("DATABASE_URL is not set: case files are kept in memory only")
        return MemoryStore()
    from storage.postgres import PostgresStore

    return PostgresStore(database_url)
