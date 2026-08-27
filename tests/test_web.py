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


async def test_price_inputs_on_every_day(web_app, admin_cookie):
    """Mọi ngày đều nhập được giá từng món (một số suất 50k thay vì 45k mặc định).
    Ô ship vẫn chỉ ở thứ 6."""
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.get("/")
    html = resp.text
    assert html.count('name="dish1"') == 5     # cả 5 ngày đều có ô tên món
    assert html.count('name="price1"') == 5    # cả 5 ngày đều có ô giá món
    assert html.count('name="price5"') == 5
    assert html.count('name="ship_fee"') == 1  # chỉ thứ 6 có ô ship


async def test_weekday_dish_price_saved_and_used(web_app, admin_cookie):
    """Ngày thường: món để giá 50k thì người chọn món đó trả 50k, người chọn
    món không nhập giá vẫn trả 45k mặc định."""
    import database as db_mod
    await db_mod.init_db()
    tue = "2026-03-10"   # thứ 3
    await db_mod.add_user(1, "A", "a")
    await db_mod.add_user(2, "B", "b")

    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": tue,
            "dish1": "Cơm gà", "price1": "50000",
            "dish2": "Cơm thường", "price2": "",
        })
    assert resp.status_code == 200
    dv = await db_mod.get_daily_vote(tue)
    assert dv["dish1_price"] == 50000
    assert dv["dish2_price"] is None      # để trống → dùng giá mặc định của ngày

    await db_mod.create_daily_vote(tue, 900, 45000, 0)   # ship 0 cho dễ kiểm
    await db_mod.save_menu_items(tue, ["Cơm gà", "Cơm thường"])
    await db_mod.set_day_dish_prices(tue, [50000, None])
    await db_mod.vote_for_dish(tue, 1, "Cơm gà")
    await db_mod.vote_for_dish(tue, 2, "Cơm thường")
    await db_mod.set_vote_closed(tue)

    detail = await db_mod.get_monthly_detail("2026-03")
    by_name = {m["full_name"]: m["votes"][tue] for m in detail["members"]}
    assert by_name["A"] == 50000
    assert by_name["B"] == 45000


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


async def test_save_friday_menu_items_keeps_preview_image(web_app, admin_cookie):
    """T6: lưu món cho thứ 6 (đang preview từ tuần trước) phải giữ luôn ảnh menu.
    Nếu không, materialize món → preview tắt (đã có món) → ảnh biến mất."""
    import database as db_mod
    await db_mod.init_db()
    # Thứ 6 tuần trước có bún đậu + ảnh (nguồn get_friday_source)
    await db_mod.save_menu_items("2026-07-03", ["Bún đậu mắm tôm"])
    await db_mod.set_menu_image("2026-07-03", "fri.jpg")

    # Admin lưu form món thứ 6 tuần này (07-10) — form đang prefill từ preview,
    # nhưng KHÔNG gửi kèm ảnh (ảnh không phải field của form)
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-07-10",
            "dish1": "Bún đậu mắm tôm", "price1": "40000",
            "ship_fee": "15000",
        })
    assert resp.status_code == 200
    dv = await db_mod.get_daily_vote("2026-07-10")
    assert dv["menu_image"] == "fri.jpg"   # ảnh preview được kế thừa & lưu lại


async def test_save_friday_menu_items_preserves_uploaded_image(web_app, admin_cookie):
    """T6: nếu ngày đã có ảnh riêng (admin tự upload), lưu món KHÔNG ghi đè bằng ảnh tuần trước."""
    import database as db_mod
    await db_mod.init_db()
    await db_mod.save_menu_items("2026-07-03", ["Bún đậu cũ"])
    await db_mod.set_menu_image("2026-07-03", "fri.jpg")
    # Ngày này admin đã upload ảnh riêng trước đó
    await db_mod.set_menu_image("2026-07-10", "custom.jpg")

    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-07-10", "dish1": "Bún đậu mới", "price1": "40000",
        })
    assert resp.status_code == 200
    dv = await db_mod.get_daily_vote("2026-07-10")
    assert dv["menu_image"] == "custom.jpg"   # ảnh riêng được giữ nguyên


# ── Toggle day flags (cơm tòa nhà / freeship) ─────────────────────────────────

async def test_toggle_day_flag_requires_auth(web_app):
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test") as client:
        resp = await client.post("/toggle-day-flag", data={"date": "2026-03-10", "flag": "building_order", "enabled": "1"})
    assert resp.status_code == 403


async def test_toggle_day_flag_success(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/toggle-day-flag", data={"date": "2026-03-10", "flag": "building_order", "enabled": "1"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        resp = await client.post("/toggle-day-flag", data={"date": "2026-03-10", "flag": "freeship", "enabled": "1"})
        assert resp.json()["ok"] is True
        dv = await db_mod.get_daily_vote("2026-03-10")
        assert dv["building_order"] == 1
        assert dv["freeship"] == 1

        # bỏ tick
        resp = await client.post("/toggle-day-flag", data={"date": "2026-03-10", "flag": "building_order", "enabled": "0"})
        assert resp.json()["ok"] is True
        dv = await db_mod.get_daily_vote("2026-03-10")
        assert dv["building_order"] == 0
        assert dv["freeship"] == 1


async def test_only_building_order_checkbox_is_shown(web_app, admin_cookie):
    """Web chỉ còn MỘT ô tick: 🏢 Cơm tòa nhà (đã gồm freeship + đóng 9:30).
    Hai ô freeship / đóng 9:30 không hiện nữa."""
    import database as db_mod
    from web.app import _current_week_dates
    await db_mod.init_db()
    week = _current_week_dates()
    await db_mod.create_daily_vote(week[0], 702, 45000, 20000)
    await db_mod.set_day_flag(week[0], "building_order", True)

    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.get("/")
    html = resp.text
    assert html.count('name="building_order"') == 5    # 5 ngày T2–T6
    assert 'name="freeship"' not in html
    assert 'name="early_close"' not in html
    assert 'name="building_order" checked' in html     # ngày đã tick vẫn giữ trạng thái


async def test_toggle_day_flag_rejects_unknown_flag(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/toggle-day-flag", data={"date": "2026-03-10", "flag": "status", "enabled": "1"})
    assert resp.status_code == 400


async def test_day_flag_checkboxes_only_for_admin(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.get("/")
    assert resp.text.count('name="building_order"') == 5   # 5 ngày T2–T6 đều có ô tick

    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test") as client:
        resp = await client.get("/")
    assert 'name="building_order"' not in resp.text


# ── Toggle paid ───────────────────────────────────────────────────────────────

async def test_treasurer_shown_paid_without_toggle_button(web_app, admin_cookie):
    """Người thu tiền: luôn hiện đã đóng và KHÔNG có nút Huỷ/Đánh dấu
    (bấm cũng vô nghĩa vì luôn tính là đã đóng)."""
    import database as db_mod
    from web.app import _current_week_dates
    await db_mod.init_db()
    await db_mod.add_user(1, "Nguyen Quang Hung", "hung")
    await db_mod.add_user(2, "Nguoi Khac", "khac")
    day = _current_week_dates()[0]
    await db_mod.create_daily_vote(day, 800, 45000, 20000)
    await db_mod.toggle_vote(day, 1)
    await db_mod.toggle_vote(day, 2)
    await db_mod.set_vote_closed(day)
    await db_mod.set_setting("treasurer_user_id", "1")

    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.get("/?tab=payment")
    html = resp.text
    assert "togglePaid('%s', 1," % _current_month_for_test() not in html   # người thu: không có nút
    assert "togglePaid" in html                                            # người khác: vẫn có nút


def _current_month_for_test():
    import config
    import pytz
    from datetime import datetime
    return datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m")


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


# ── Friday preview overlay ────────────────────────────────────────────────────

async def test_friday_preview_overlays_from_previous_friday(web_app):
    import database as db_mod
    from web.app import _apply_friday_preview
    await db_mod.init_db()
    await db_mod.save_menu_items("2026-06-26", ["Bún đậu(35k)", "Bún đậu(40k)"])
    await db_mod.set_day_dish_prices("2026-06-26", [35000, 40000])
    await db_mod.set_day_ship("2026-06-26", 20000)
    await db_mod.set_menu_image("2026-06-26", "fri.jpg")
    week_days = [{
        "weekday": "Thứ 6", "date": "2026-07-03", "status": "none",
        "dish1_price": None, "dish2_price": None, "dish3_price": None,
        "dish4_price": None, "ship_fee": None, "menu_image": "fri.png",
    }]
    week_menu = {"2026-07-03": ["", "", "", ""]}
    await _apply_friday_preview(week_days, week_menu)
    assert week_menu["2026-07-03"][:2] == ["Bún đậu(35k)", "Bún đậu(40k)"]
    assert week_days[0]["dish1_price"] == 35000
    assert week_days[0]["dish2_price"] == 40000
    assert week_days[0]["ship_fee"] == 20000
    assert week_days[0]["menu_image"] == "fri.jpg"   # stray fri.png bị ghi đè bằng nguồn
    assert week_days[0]["is_template_preview"] is True


async def test_friday_preview_falls_back_to_template(web_app):
    import json
    import database as db_mod
    from web.app import _apply_friday_preview
    await db_mod.init_db()
    await db_mod.set_setting("friday_template", json.dumps(
        {"dishes": ["Bún đậu TPL"], "prices": [35000], "ship_fee": 20000, "menu_image": "fri.jpg"}))
    week_days = [{
        "weekday": "Thứ 6", "date": "2026-07-03", "status": "none",
        "dish1_price": None, "dish2_price": None, "dish3_price": None,
        "dish4_price": None, "ship_fee": None, "menu_image": None,
    }]
    week_menu = {"2026-07-03": ["", "", "", ""]}
    await _apply_friday_preview(week_days, week_menu)
    assert week_menu["2026-07-03"][0] == "Bún đậu TPL"
    assert week_days[0]["is_template_preview"] is True


async def test_friday_preview_skips_when_dishes_exist(web_app):
    import database as db_mod
    from web.app import _apply_friday_preview
    await db_mod.init_db()
    await db_mod.save_menu_items("2026-06-26", ["Bún đậu"])
    await db_mod.set_day_dish_prices("2026-06-26", [35000])
    week_days = [{
        "weekday": "Thứ 6", "date": "2026-07-03", "status": "open",
        "dish1_price": 99000, "dish2_price": None, "dish3_price": None,
        "dish4_price": None, "ship_fee": 5000, "menu_image": "admin.jpg",
    }]
    week_menu = {"2026-07-03": ["Món admin", "", "", ""]}
    await _apply_friday_preview(week_days, week_menu)
    assert week_menu["2026-07-03"] == ["Món admin", "", "", ""]     # giữ nguyên
    assert week_days[0]["dish1_price"] == 99000
    assert "is_template_preview" not in week_days[0]


# ── Món thứ 5 trên web ────────────────────────────────────────────────────────

async def test_form_has_five_dish_inputs(web_app, admin_cookie):
    """Mỗi ngày có 5 ô tên món, mỗi ô kèm 1 ô giá."""
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.get("/")
    html = resp.text
    assert html.count('name="dish5"') == 5     # 5 ngày T2–T6
    assert html.count('name="price5"') == 5    # mọi ngày đều nhập được giá


async def test_save_five_dishes_with_prices(web_app, admin_cookie):
    import database as db_mod
    await db_mod.init_db()
    async with AsyncClient(transport=ASGITransport(app=web_app), base_url="http://test", cookies=admin_cookie) as client:
        resp = await client.post("/save-menu-items", data={
            "date": "2026-01-02",
            "dish1": "A", "price1": "10000",
            "dish2": "B", "price2": "20000",
            "dish3": "C", "price3": "30000",
            "dish4": "D", "price4": "40000",
            "dish5": "E", "price5": "50000",
        })
    assert resp.status_code == 200
    assert await db_mod.get_menu_items("2026-01-02") == ["A", "B", "C", "D", "E"]
    dv = await db_mod.get_daily_vote("2026-01-02")
    assert dv["dish5_price"] == 50000


async def test_friday_preview_pads_to_five_slots(web_app):
    import database as db_mod
    from web.app import _apply_friday_preview
    await db_mod.init_db()
    await db_mod.save_menu_items("2026-06-26", ["A", "B", "C", "D", "E"])
    await db_mod.set_day_dish_prices("2026-06-26", [1, 2, 3, 4, 5])
    week_days = [{
        "weekday": "Thứ 6", "date": "2026-07-03", "status": "none",
        "dish1_price": None, "dish2_price": None, "dish3_price": None,
        "dish4_price": None, "dish5_price": None, "ship_fee": None, "menu_image": None,
    }]
    week_menu = {"2026-07-03": ["", "", "", "", ""]}
    await _apply_friday_preview(week_days, week_menu)
    assert week_menu["2026-07-03"] == ["A", "B", "C", "D", "E"]
    assert week_days[0]["dish5_price"] == 5
