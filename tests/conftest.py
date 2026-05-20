"""Shared fixtures for all tests."""
import os
import pytest
import pytest_asyncio

# Stub env vars before importing project modules
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("CHAT_ID", "-100000001")
os.environ.setdefault("ADMIN_IDS", "1001")
os.environ.setdefault("ADMIN_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh SQLite DB in a temp file for each test."""
    import database as db_mod
    db_path = str(tmp_path / "test.db")
    db_mod.DB_PATH = db_path  # patch module-level constant

    # Also patch config so other modules pick up the right path
    import config
    config.DB_PATH = db_path

    await db_mod.init_db()
    yield db_mod
