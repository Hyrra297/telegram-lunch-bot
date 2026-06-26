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


async def test_price_inputs_only_on_friday(web_app, admin_cookie):
    """Ô giá/ship chỉ hiện ở thứ 6 (bún đậu). Tuần luôn gồm T2–T6 → đúng 1 thứ 6."""
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.get("/")
    html = resp.text
    assert html.count('name="dish1"') == 5     # cả 5 ngày đều có ô tên món
    assert html.count('name="price1"') == 1    # chỉ thứ 6 có ô giá món
    assert html.count('name="ship_fee"') == 1  # chỉ thứ 6 có ô ship


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


async def test_save_menu_items_with_dish_prices(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-01-02",
            "dish1": "Bún đậu thường", "price1": "35000",
            "dish2": "Bún đậu đầy đủ", "price2": "50000",
            "ship_fee": "10000",
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    dv = await db_mod.get_daily_vote("2026-01-02")
    assert dv["dish1_price"] == 35000
    assert dv["dish2_price"] == 50000
    assert dv["ship_fee"] == 10000

async def test_save_menu_items_prices_align_after_empty_dish(web_app, admin_cookie):
    # dish2 rỗng → dish3 dồn thành slot 2; giá phải dồn theo
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-01-02",
            "dish1": "A", "price1": "10000",
            "dish2": "", "price2": "",
            "dish3": "C", "price3": "30000",
        })
    assert resp.status_code == 200
    dv = await db_mod.get_daily_vote("2026-01-02")
    items = await db_mod.get_menu_items("2026-01-02")
    assert items == ["A", "C"]
    assert dv["dish1_price"] == 10000
    assert dv["dish2_price"] == 30000   # giá của C dồn về slot 2 khớp tên
    assert dv["dish3_price"] is None


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
