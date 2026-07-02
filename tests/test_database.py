"""Tests for database.py — covering core logic."""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


# ── Users ─────────────────────────────────────────────────────────────────────

async def test_add_and_get_user(db):
    await db.add_user(1, "Nguyen Van A", "usera")
    user = await db.get_user(1)
    assert user["full_name"] == "Nguyen Van A"
    assert user["username"] == "usera"
    assert user["active"] == 1


async def test_add_user_twice_updates_without_reset_index(db):
    await db.add_user(1, "Name A", "usera")
    await db.add_user(1, "Name A Updated", "usera2")
    user = await db.get_user(1)
    assert user["full_name"] == "Name A Updated"
    assert user["rotation_index"] == 1  # index unchanged on re-add


async def test_new_members_get_next_index(db):
    await db.add_user(1, "A", "a")
    await db.add_user(2, "B", "b")
    await db.add_user(3, "C", "c")
    users = await db.get_active_users()
    indices = [u["rotation_index"] for u in users]
    assert indices == sorted(indices)  # monotonically increasing


async def test_deactivate_user(db):
    await db.add_user(1, "A", "a")
    removed = await db.deactivate_user(1)
    assert removed is True
    user = await db.get_user(1)
    assert user["active"] == 0


async def test_deactivate_nonexistent_user(db):
    removed = await db.deactivate_user(999)
    assert removed is False


# ── Daily votes ───────────────────────────────────────────────────────────────

async def test_create_and_get_daily_vote(db):
    await db.create_daily_vote("2026-03-10", 100, 35000, 20000)
    vote = await db.get_daily_vote("2026-03-10")
    assert vote["status"] == "open"
    assert vote["price"] == 35000


async def test_get_daily_vote_missing(db):
    result = await db.get_daily_vote("2026-01-01")
    assert result is None


async def test_set_vote_closed(db):
    await db.create_daily_vote("2026-03-10", 100, 35000, 20000)
    await db.set_vote_closed("2026-03-10")
    vote = await db.get_daily_vote("2026-03-10")
    assert vote["status"] == "closed"
    assert vote["picker_user_id"] is None  # not assigned yet


async def test_close_daily_vote_sets_picker(db):
    await db.add_user(1, "A", "a")
    await db.create_daily_vote("2026-03-10", 100, 35000, 20000)
    await db.close_daily_vote("2026-03-10", picker_user_id=1)
    vote = await db.get_daily_vote("2026-03-10")
    assert vote["picker_user_id"] == 1
    user = await db.get_user(1)
    assert user["last_picked_at"] == "2026-03-10"


async def test_get_daily_vote_by_message_id(db):
    await db.create_daily_vote("2026-03-10", 777, 35000, 20000)
    vote = await db.get_daily_vote_by_message_id(777)
    assert vote is not None
    assert vote["date"] == "2026-03-10"


async def test_get_daily_vote_by_message_id_missing(db):
    result = await db.get_daily_vote_by_message_id(99999)
    assert result is None


# ── Vote entries ──────────────────────────────────────────────────────────────

async def test_toggle_vote_in_and_out(db):
    await db.add_user(1, "A", "a")
    await db.create_daily_vote("2026-03-10", 100, 35000, 20000)

    voted_in = await db.toggle_vote("2026-03-10", 1)
    assert voted_in is True
    voters = await db.get_voters("2026-03-10")
    assert len(voters) == 1

    voted_in = await db.toggle_vote("2026-03-10", 1)
    assert voted_in is False
    voters = await db.get_voters("2026-03-10")
    assert len(voters) == 0


async def test_vote_for_dish_insert(db):
    await db.add_user(1, "A", "a")
    await db.create_daily_vote("2026-03-10", 100, 35000, 20000)
    result = await db.vote_for_dish("2026-03-10", 1, "Bún bò")
    assert result == "Bún bò"
    voters = await db.get_voters_with_dish("2026-03-10")
    assert voters[0]["dish"] == "Bún bò"


async def test_vote_for_dish_same_cancels(db):
    await db.add_user(1, "A", "a")
    await db.create_daily_vote("2026-03-10", 100, 35000, 20000)
    await db.vote_for_dish("2026-03-10", 1, "Bún bò")
    result = await db.vote_for_dish("2026-03-10", 1, "Bún bò")
    assert result is None
    voters = await db.get_voters("2026-03-10")
    assert len(voters) == 0


async def test_vote_for_dish_changes(db):
    await db.add_user(1, "A", "a")
    await db.create_daily_vote("2026-03-10", 100, 35000, 20000)
    await db.vote_for_dish("2026-03-10", 1, "Bún bò")
    result = await db.vote_for_dish("2026-03-10", 1, "Cơm gà")
    assert result == "Cơm gà"


# ── Round-robin: pick_next_fetcher ────────────────────────────────────────────

async def _setup_voters(db, date, user_ids):
    """Add users, open vote, and vote-in all specified user_ids."""
    for i, uid in enumerate(user_ids):
        await db.add_user(uid, f"User{uid}", None)
    await db.create_daily_vote(date, 100, 35000, 20000)
    for uid in user_ids:
        await db.toggle_vote(date, uid)


async def test_pick_fetcher_first_time(db):
    await _setup_voters(db, "2026-03-10", [1, 2, 3])
    picker = await db.pick_next_fetcher("2026-03-10")
    assert picker is not None
    assert picker["id"] in [1, 2, 3]


async def test_pick_fetcher_round_robin(db):
    """Second day should pick a different person than first day."""
    await _setup_voters(db, "2026-03-10", [1, 2, 3])
    picker1 = await db.pick_next_fetcher("2026-03-10")
    await db.close_daily_vote("2026-03-10", picker1["id"])

    await _setup_voters(db, "2026-03-11", [1, 2, 3])
    picker2 = await db.pick_next_fetcher("2026-03-11")
    assert picker2["id"] != picker1["id"]


async def test_pick_fetcher_wraps_around(db):
    """After all members have been picked, it wraps back to first."""
    users = [1, 2, 3]
    picked = []
    for day_n, uid in enumerate(users, 1):
        date = f"2026-03-{day_n:02d}"
        await _setup_voters(db, date, users)
        picker = await db.pick_next_fetcher(date)
        picked.append(picker["id"])
        await db.close_daily_vote(date, picker["id"])

    # 4th day wraps to first picked
    await _setup_voters(db, "2026-03-04", users)
    picker4 = await db.pick_next_fetcher("2026-03-04")
    assert picker4["id"] == picked[0]


# ── Round-robin: pick_next_returner ───────────────────────────────────────────

async def test_pick_returner_excludes_picker(db):
    await _setup_voters(db, "2026-03-10", [1, 2, 3])
    picker = await db.pick_next_fetcher("2026-03-10")
    returner = await db.pick_next_returner("2026-03-10", picker["id"])
    assert returner["id"] != picker["id"]


async def test_pick_returner_single_voter_same_person(db):
    """1 voter → picker = returner (cùng người lấy và trả hộp)."""
    await _setup_voters(db, "2026-03-10", [1])
    picker = await db.pick_next_fetcher("2026-03-10")
    returner = await db.pick_next_returner("2026-03-10", picker["id"])
    assert returner["id"] == picker["id"]


# ── Menu items ────────────────────────────────────────────────────────────────

async def test_save_and_get_menu_items(db):
    await db.save_menu_items("2026-03-10", ["Bún bò", "Cơm gà", "Phở"])
    items = await db.get_menu_items("2026-03-10")
    assert items == ["Bún bò", "Cơm gà", "Phở"]


async def test_get_menu_items_empty(db):
    items = await db.get_menu_items("2026-01-01")
    assert items == []


async def test_save_menu_items_creates_placeholder_row(db):
    await db.save_menu_items("2026-03-10", ["Món A"])
    vote = await db.get_daily_vote("2026-03-10")
    assert vote is not None
    assert vote["status"] == "none"


# ── Monthly payments ──────────────────────────────────────────────────────────

async def test_toggle_paid(db):
    await db.add_user(1, "A", "a")
    paid = await db.toggle_monthly_paid("2026-03", 1)
    assert paid is True
    paid_ids = await db.get_paid_user_ids("2026-03")
    assert 1 in paid_ids


async def test_toggle_paid_twice_unpays(db):
    await db.add_user(1, "A", "a")
    await db.toggle_monthly_paid("2026-03", 1)
    paid = await db.toggle_monthly_paid("2026-03", 1)
    assert paid is False
    paid_ids = await db.get_paid_user_ids("2026-03")
    assert 1 not in paid_ids


# ── Settings ──────────────────────────────────────────────────────────────────

async def test_set_and_get_setting(db):
    await db.set_setting("price", "40000")
    val = await db.get_setting("price")
    assert val == "40000"


async def test_get_setting_missing(db):
    val = await db.get_setting("nonexistent")
    assert val is None


async def test_set_setting_overwrite(db):
    await db.set_setting("price", "35000")
    await db.set_setting("price", "40000")
    val = await db.get_setting("price")
    assert val == "40000"


async def test_is_voter(db):
    await db.add_user(1, "A", "a")
    assert await db.is_voter("2026-06-03", 1) is False
    await db.toggle_vote("2026-06-03", 1)
    assert await db.is_voter("2026-06-03", 1) is True
    await db.toggle_vote("2026-06-03", 1)  # bỏ vote
    assert await db.is_voter("2026-06-03", 1) is False


class TestDayDishPrices:
    async def test_set_dish_prices_stores_positional(self, db):
        await db.save_menu_items("2026-01-02", ["Bún đậu thường", "Bún đậu đầy đủ"])
        await db.set_day_dish_prices("2026-01-02", [35000, 50000])
        dv = await db.get_daily_vote("2026-01-02")
        assert dv["dish1_price"] == 35000
        assert dv["dish2_price"] == 50000
        assert dv["dish3_price"] is None
        assert dv["dish4_price"] is None

    async def test_set_dish_prices_none_clears(self, db):
        await db.set_day_dish_prices("2026-01-02", [35000, 50000])
        await db.set_day_dish_prices("2026-01-02", [None, None])
        dv = await db.get_daily_vote("2026-01-02")
        assert dv["dish1_price"] is None
        assert dv["dish2_price"] is None

    async def test_set_day_ship_updates(self, db):
        await db.set_day_ship("2026-01-02", 10000)
        dv = await db.get_daily_vote("2026-01-02")
        assert dv["ship_fee"] == 10000

    async def test_vote_entries_cost_column_exists(self, db):
        # cột cost nullable, mặc định NULL
        await db.create_daily_vote("2026-01-02", 100, 45000, 20000)
        await db.toggle_vote("2026-01-02", 1)
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT cost FROM vote_entries WHERE date=? AND user_id=?", ("2026-01-02", 1)) as cur:
                row = await cur.fetchone()
        assert row["cost"] is None


class TestSnapshotDayCosts:
    async def _setup(self, db, date):
        await db.add_user(1, "An", "an")
        await db.add_user(2, "Binh", "binh")
        await db.create_daily_vote(date, 100, 45000, 0)   # price=45000 (fallback), ship=0
        await db.save_menu_items(date, ["Bún đậu thường", "Bún đậu đầy đủ"])
        await db.set_day_dish_prices(date, [35000, 50000])
        await db.set_day_ship(date, 10000)                # ship 10k chia 2 = 5k
        await db.vote_for_dish(date, 1, "Bún đậu thường")  # 35000 + 5000
        await db.vote_for_dish(date, 2, "Bún đậu đầy đủ")  # 50000 + 5000
        await db.set_vote_closed(date)

    async def _cost(self, db, date, user_id):
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            async with conn.execute("SELECT cost FROM vote_entries WHERE date=? AND user_id=?", (date, user_id)) as cur:
                row = await cur.fetchone()
        return row[0]

    async def test_snapshot_computes_per_dish(self, db):
        date = "2026-01-02"
        await self._setup(db, date)
        n = await db.snapshot_day_costs(date)
        assert n == 2
        assert await self._cost(db, date, 1) == 40000   # 35000 + round(10000/2)
        assert await self._cost(db, date, 2) == 55000   # 50000 + round(10000/2)

    async def test_snapshot_fallback_when_no_dish_price(self, db):
        date = "2026-01-02"
        await db.add_user(1, "An", "an")
        await db.create_daily_vote(date, 100, 45000, 0)
        await db.save_menu_items(date, ["Món chưa có giá"])
        await db.vote_for_dish(date, 1, "Món chưa có giá")
        await db.set_vote_closed(date)
        await db.snapshot_day_costs(date)
        assert await self._cost(db, date, 1) == 45000   # fallback daily.price, ship 0

    async def test_snapshot_no_voters_returns_zero(self, db):
        date = "2026-01-02"
        await db.create_daily_vote(date, 100, 45000, 0)
        await db.set_vote_closed(date)
        assert await db.snapshot_day_costs(date) == 0

    async def test_snapshot_keeps_manual_cost(self, db):
        """Ô cost đã khoá tay không bị ghi đè; chỉ điền ô còn trống."""
        date = "2026-01-02"
        await db.add_user(1, "An", "an")
        await db.add_user(2, "Binh", "binh")
        await db.create_daily_vote(date, 100, 45000, 0)
        await db.save_menu_items(date, ["X"])
        await db.set_day_dish_prices(date, [30000])
        await db.vote_for_dish(date, 1, "X")
        await db.vote_for_dish(date, 2, "X")
        await db.set_vote_closed(date)
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute("UPDATE vote_entries SET cost=? WHERE date=? AND user_id=?", (99999, date, 1))
            await conn.commit()
        n = await db.snapshot_day_costs(date)
        assert n == 1                                  # chỉ khoá ô còn trống (user 2)
        assert await self._cost(db, date, 1) == 99999  # số khoá tay giữ nguyên
        assert await self._cost(db, date, 2) == 30000  # 30000 + round(0/2)

    async def test_snapshot_matches_live_on_duplicate_names(self, db):
        date = "2026-01-02"
        await db.add_user(1, "An", "an")
        await db.create_daily_vote(date, 100, 45000, 0)   # ship 0
        await db.save_menu_items(date, ["X", "X"])         # trùng tên
        await db.set_day_dish_prices(date, [30000, 60000]) # dish1=30k, dish2=60k
        await db.vote_for_dish(date, 1, "X")
        await db.set_vote_closed(date)
        live = {r["full_name"]: r["total"] for r in await db.get_monthly_summary("2026-01")}["An"]
        await db.snapshot_day_costs(date)
        locked = {r["full_name"]: r["total"] for r in await db.get_monthly_summary("2026-01")}["An"]
        assert live == locked == 30000   # SQL CASE khớp slot đầu (dish1=30000)


class TestWeekDataDishPrices:
    async def test_week_data_includes_dish_prices_and_ship(self, db):
        await db.save_menu_items("2026-01-02", ["Bún đậu thường", "Bún đậu đầy đủ"])
        await db.set_day_dish_prices("2026-01-02", [35000, 50000])
        await db.set_day_ship("2026-01-02", 10000)
        rows = await db.get_week_data(["2026-01-02"])
        assert rows[0]["dish1_price"] == 35000
        assert rows[0]["dish2_price"] == 50000
        assert rows[0]["ship_fee"] == 10000
        assert "price_override" not in rows[0]
        assert rows[0]["dish3_price"] is None
        assert rows[0]["dish4_price"] is None

    async def test_week_data_no_row_dish_prices_none(self, db):
        rows = await db.get_week_data(["2026-01-02"])
        assert rows[0]["dish1_price"] is None
        assert rows[0]["ship_fee"] is None
        assert rows[0]["dish2_price"] is None
        assert rows[0]["dish3_price"] is None
        assert rows[0]["dish4_price"] is None
        assert "price_override" not in rows[0]


class TestSummaryPerDish:
    async def _setup_bun_dau(self, db, date):
        await db.add_user(1, "An", "an")
        await db.add_user(2, "Binh", "binh")
        await db.create_daily_vote(date, 100, 45000, 0)
        await db.save_menu_items(date, ["Bún đậu thường", "Bún đậu đầy đủ"])
        await db.set_day_dish_prices(date, [35000, 50000])
        await db.set_day_ship(date, 10000)
        await db.vote_for_dish(date, 1, "Bún đậu thường")
        await db.vote_for_dish(date, 2, "Bún đậu đầy đủ")
        await db.set_vote_closed(date)

    async def test_summary_live_per_dish(self, db):
        date = "2026-01-09"
        await self._setup_bun_dau(db, date)
        rows = await db.get_monthly_summary("2026-01")
        by_name = {r["full_name"]: r["total"] for r in rows}
        assert by_name["An"] == 40000   # 35000 + round(10000/2)
        assert by_name["Binh"] == 55000  # 50000 + round(10000/2)

    async def test_summary_uses_snapshot_when_locked(self, db):
        date = "2026-01-09"
        await self._setup_bun_dau(db, date)
        await db.snapshot_day_costs(date)
        # sửa giá món sau khi chốt — không được đổi tổng
        await db.set_day_dish_prices(date, [99000, 99000])
        rows = await db.get_monthly_summary("2026-01")
        by_name = {r["full_name"]: r["total"] for r in rows}
        assert by_name["An"] == 40000
        assert by_name["Binh"] == 55000

    async def test_detail_per_dish(self, db):
        date = "2026-01-09"
        await self._setup_bun_dau(db, date)
        detail = await db.get_monthly_detail("2026-01")
        amounts = {m["full_name"]: m["votes"].get(date) for m in detail["members"]}
        assert amounts["An"] == 40000
        assert amounts["Binh"] == 55000

    async def test_summary_com_single_price_unchanged(self, db):
        # ngày cơm thường: không nhập giá món → mỗi người = dv.price + ship/count
        date = "2026-01-12"
        await db.add_user(1, "An", "an")
        await db.add_user(2, "Binh", "binh")
        await db.create_daily_vote(date, 100, 45000, 20000)
        await db.toggle_vote(date, 1)
        await db.toggle_vote(date, 2)
        await db.set_vote_closed(date)
        rows = await db.get_monthly_summary("2026-01")
        by_name = {r["full_name"]: r["total"] for r in rows}
        assert by_name["An"] == 45000 + round(20000 / 2)  # 55000
        assert by_name["Binh"] == 55000

    async def test_detail_com_single_price_unchanged(self, db):
        date = "2026-01-12"
        await db.add_user(1, "An", "an")
        await db.add_user(2, "Binh", "binh")
        await db.create_daily_vote(date, 100, 45000, 20000)
        await db.toggle_vote(date, 1)
        await db.toggle_vote(date, 2)
        await db.set_vote_closed(date)
        detail = await db.get_monthly_detail("2026-01")
        amounts = {m["full_name"]: m["votes"].get(date) for m in detail["members"]}
        assert amounts["An"] == 45000 + round(20000 / 2)   # 55000
        assert amounts["Binh"] == 55000


class TestFridayTemplate:
    async def test_applies_when_no_dishes(self, db):
        import json
        tpl = {"dishes": ["A", "B"], "prices": [35000, 40000], "ship_fee": 20000, "menu_image": "fri.jpg"}
        await db.set_setting("friday_template", json.dumps(tpl))
        applied = await db.apply_friday_template("2026-01-02")
        assert applied is True
        assert await db.get_menu_items("2026-01-02") == ["A", "B"]
        dv = await db.get_daily_vote("2026-01-02")
        assert dv["dish1_price"] == 35000
        assert dv["dish2_price"] == 40000
        assert dv["ship_fee"] == 20000
        assert dv["menu_image"] == "fri.jpg"

    async def test_skips_when_dishes_exist(self, db):
        import json
        await db.set_setting("friday_template", json.dumps(
            {"dishes": ["A"], "prices": [1], "ship_fee": 0, "menu_image": "fri.jpg"}))
        await db.save_menu_items("2026-01-02", ["Món tay"])
        applied = await db.apply_friday_template("2026-01-02")
        assert applied is False
        assert await db.get_menu_items("2026-01-02") == ["Món tay"]
        dv = await db.get_daily_vote("2026-01-02")
        assert dv["ship_fee"] == 20000   # template ship=0 KHÔNG được áp (giữ default)

    async def test_returns_false_when_no_template(self, db):
        assert await db.apply_friday_template("2026-01-02") is False

    async def test_returns_false_when_bad_json(self, db):
        await db.set_setting("friday_template", "{not json")
        assert await db.apply_friday_template("2026-01-02") is False

    async def test_apply_copies_previous_friday_not_template(self, db):
        import json
        await db.set_setting("friday_template", json.dumps(
            {"dishes": ["TPL"], "prices": [1], "ship_fee": 20000, "menu_image": "t.jpg"}))
        await db.save_menu_items("2026-06-26", ["Prev1", "Prev2"])
        await db.set_day_dish_prices("2026-06-26", [35000, 40000])
        await db.set_day_ship("2026-06-26", 15000)
        await db.set_menu_image("2026-06-26", "fri.jpg")
        applied = await db.apply_friday_template("2026-07-03")
        assert applied is True
        assert await db.get_menu_items("2026-07-03") == ["Prev1", "Prev2"]
        dv = await db.get_daily_vote("2026-07-03")
        assert dv["dish1_price"] == 35000
        assert dv["ship_fee"] == 15000          # copy từ thứ 6 trước, KHÔNG phải template
        assert dv["menu_image"] == "fri.jpg"


class TestFridaySource:
    async def test_copies_previous_friday(self, db):
        await db.save_menu_items("2026-06-26", ["A", "B"])
        await db.set_day_dish_prices("2026-06-26", [35000, 40000])
        await db.set_day_ship("2026-06-26", 20000)
        await db.set_menu_image("2026-06-26", "fri.jpg")
        src = await db.get_friday_source("2026-07-03")  # thứ 6 kế tiếp
        assert src["dishes"] == ["A", "B"]
        assert src["prices"] == [35000, 40000]
        assert src["ship_fee"] == 20000
        assert src["menu_image"] == "fri.jpg"

    async def test_prefers_previous_friday_over_template(self, db):
        import json
        await db.set_setting("friday_template", json.dumps(
            {"dishes": ["TPL"], "prices": [1], "ship_fee": 0, "menu_image": "t.jpg"}))
        await db.save_menu_items("2026-06-26", ["Prev"])
        await db.set_day_dish_prices("2026-06-26", [50000])
        src = await db.get_friday_source("2026-07-03")
        assert src["dishes"] == ["Prev"]
        assert src["prices"] == [50000]

    async def test_skips_friday_without_dishes(self, db):
        # 06-26 không có món; 06-19 (xa hơn 1 tuần) có món
        await db.save_menu_items("2026-06-19", ["Xa"])
        await db.set_day_dish_prices("2026-06-19", [45000])
        src = await db.get_friday_source("2026-07-03")
        assert src["dishes"] == ["Xa"]

    async def test_falls_back_to_template(self, db):
        import json
        await db.set_setting("friday_template", json.dumps(
            {"dishes": ["TPL"], "prices": [1], "ship_fee": 20000, "menu_image": "t.jpg"}))
        src = await db.get_friday_source("2026-07-03")
        assert src["dishes"] == ["TPL"]
        assert src["menu_image"] == "t.jpg"

    async def test_none_when_nothing(self, db):
        assert await db.get_friday_source("2026-07-03") is None
