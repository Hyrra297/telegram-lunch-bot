"""Tests for FastAPI web dashboard endpoints."""
import os
import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


@pytest.fixture
def web_app(tmp_path, monkeypatch):
    """Return FastAPI app with patched DB path."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))

    import database as db_mod
    import config
    db_path = str(tmp_path / "test.db")
    db_mod.DB_PATH = db_path
    config.DB_PATH = db_path

    from web.app import app
    return app


@pytest.fixture
def admin_cookie(web_app):
    """Return valid admin token cookie value."""
    import config
    import hashlib
    token = hashlib.sha256(
        (config.SECRET_KEY + ":" + config.ADMIN_PASSWORD).encode()
    ).hexdigest()
    return {"admin_token": token}


# ── Index (smoke) ─────────────────────────────────────────────────────────────

async def test_index_renders_ok(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.get("/")
    assert resp.status_code == 200


# ── Health ────────────────────────────────────────────────────────────────────

async def test_health(web_app):
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────

async def test_login_wrong_password(web_app):
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test") as client:
        resp = await client.post("/login", data={"password": "wrong", "next": "/"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "login_error=1" in resp.headers["location"]


async def test_login_correct_password(web_app):
    import config
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test") as client:
        resp = await client.post("/login", data={"password": config.ADMIN_PASSWORD, "next": "/"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "admin_token" in resp.cookies


# ── Save menu items ───────────────────────────────────────────────────────────

async def test_save_menu_items_requires_auth(web_app):
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test") as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-03-10", "dish1": "Bún bò",
        })
    assert resp.status_code == 403


async def test_save_menu_items_success(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-03-10",
            "dish1": "Bún bò",
            "dish2": "Cơm gà",
            "dish3": "",
            "dish4": "",
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    items = await db_mod.get_menu_items("2026-03-10")
    assert "Bún bò" in items
    assert "Cơm gà" in items


async def test_save_menu_items_with_price_override(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-01-02",
            "dish1": "Bún đậu mắm tôm",
            "price": "40000",
            "ship_fee": "0",
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    dv = await db_mod.get_daily_vote("2026-01-02")
    assert dv["price_override"] == 40000
    assert dv["ship_fee_override"] == 0


async def test_save_menu_items_empty_price_no_override(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-01-05", "dish1": "Cơm gà", "price": "", "ship_fee": "",
        })
    assert resp.status_code == 200
    dv = await db_mod.get_daily_vote("2026-01-05")
    assert dv["price_override"] is None
    assert dv["ship_fee_override"] is None


# ── Toggle paid ───────────────────────────────────────────────────────────────

async def test_toggle_paid_requires_auth(web_app):
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test") as client:
        resp = await client.post("/toggle-paid", data={"year_month": "2026-03", "user_id": 1})
    assert resp.status_code == 403


async def test_toggle_paid_success(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    await db_mod.add_user(1, "Test User", "testuser")

    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/toggle-paid", data={"year_month": "2026-03", "user_id": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["paid"] is True
