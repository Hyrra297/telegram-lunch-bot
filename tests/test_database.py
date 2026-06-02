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
