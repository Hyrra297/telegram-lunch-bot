from __future__ import annotations
from datetime import date as dt_date
from typing import Optional
import aiosqlite
from config import DB_PATH


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        # Enable WAL mode for better concurrent read/write performance
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY,
                username        TEXT,
                full_name       TEXT NOT NULL,
                rotation_index  INTEGER NOT NULL DEFAULT 0,
                last_picked_at  TEXT,
                active          INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS daily_votes (
                date            TEXT PRIMARY KEY,
                poll_message_id INTEGER,
                picker_user_id  INTEGER,
                price           INTEGER NOT NULL DEFAULT 45000,
                status          TEXT NOT NULL DEFAULT 'open',
                menu_image      TEXT
            );

            CREATE TABLE IF NOT EXISTS vote_entries (
                date    TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (date, user_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key     TEXT PRIMARY KEY,
                value   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS monthly_payments (
                year_month  TEXT    NOT NULL,
                user_id     INTEGER NOT NULL,
                PRIMARY KEY (year_month, user_id)
            );
        """)
        # Migrations
        for col_sql in [
            "ALTER TABLE daily_votes ADD COLUMN menu_image TEXT",
            "ALTER TABLE daily_votes ADD COLUMN ship_fee INTEGER NOT NULL DEFAULT 20000",
            "ALTER TABLE daily_votes ADD COLUMN menu_description TEXT",
            "ALTER TABLE daily_votes ADD COLUMN dish1 TEXT",
            "ALTER TABLE daily_votes ADD COLUMN dish2 TEXT",
            "ALTER TABLE daily_votes ADD COLUMN dish3 TEXT",
            "ALTER TABLE daily_votes ADD COLUMN dish4 TEXT",
            "ALTER TABLE vote_entries ADD COLUMN dish TEXT",
            "ALTER TABLE daily_votes ADD COLUMN poll_id TEXT",
            "ALTER TABLE users ADD COLUMN return_index INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN last_returned_at TEXT",
            "ALTER TABLE daily_votes ADD COLUMN returner_user_id INTEGER",
            "ALTER TABLE daily_votes ADD COLUMN cost_per_person INTEGER",
        ]:
            try:
                await db.execute(col_sql)
            except Exception:
                pass
        await db.commit()


# ── Settings ──────────────────────────────────────────────────────────────────

async def get_setting(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


# ── Users ─────────────────────────────────────────────────────────────────────

async def add_user(user_id: int, full_name: str, username: Optional[str]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MAX(rotation_index) FROM users WHERE active = 1") as cur:
            row = await cur.fetchone()
            next_pick_idx = (row[0] or 0) + 1
        async with db.execute("SELECT MAX(return_index) FROM users WHERE active = 1") as cur:
            row = await cur.fetchone()
            next_ret_idx = (row[0] or 0) + 1
        await db.execute(
            """INSERT INTO users (id, username, full_name, rotation_index, return_index, active)
               VALUES (?, ?, ?, ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                   username = excluded.username,
                   full_name = excluded.full_name,
                   active = 1""",
            (user_id, username, full_name, next_pick_idx, next_ret_idx),
        )
        await db.commit()


async def deactivate_user(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("UPDATE users SET active = 0 WHERE id = ?", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def get_active_users() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE active = 1 ORDER BY rotation_index"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_user(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ── Daily votes ───────────────────────────────────────────────────────────────

async def create_daily_vote(date: str, poll_message_id: int, price: int, ship_fee: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO daily_votes (date, poll_message_id, price, ship_fee, status)
               VALUES (?, ?, ?, ?, 'open')
               ON CONFLICT(date) DO UPDATE SET
                   poll_message_id = excluded.poll_message_id,
                   price           = excluded.price,
                   ship_fee        = excluded.ship_fee,
                   status          = 'open'""",
            (date, poll_message_id, price, ship_fee),
        )
        await db.commit()


async def get_daily_vote(date: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_votes WHERE date = ?", (date,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_daily_vote_by_poll_id(poll_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_votes WHERE poll_id = ?", (poll_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def set_poll_id(date: str, poll_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE daily_votes SET poll_id = ? WHERE date = ?", (poll_id, date))
        await db.commit()


async def set_vote_closed(date: str) -> None:
    """Đóng vote (status='closed') mà chưa chọn người lấy/trả."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE daily_votes SET status = 'closed' WHERE date = ?", (date,)
        )
        await db.commit()


async def set_cost_per_person(date: str, cost: int) -> None:
    """Ghi chi phí mỗi người vào daily_votes (chạy lúc 12h)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE daily_votes SET cost_per_person = ? WHERE date = ?", (cost, date)
        )
        await db.commit()


async def close_daily_vote(date: str, picker_user_id: int, returner_user_id: Optional[int] = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE daily_votes SET status = 'closed', picker_user_id = ?, returner_user_id = ? WHERE date = ?",
            (picker_user_id, returner_user_id, date),
        )
        await db.execute(
            "UPDATE users SET last_picked_at = ? WHERE id = ?",
            (date, picker_user_id),
        )
        if returner_user_id and returner_user_id != picker_user_id:
            await db.execute(
                "UPDATE users SET last_returned_at = ? WHERE id = ?",
                (date, returner_user_id),
            )
        await db.commit()


async def set_menu_description(date: str, description: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE daily_votes SET menu_description = ? WHERE date = ?",
            (description, date),
        )
        await db.commit()


async def set_menu_image(date: str, filename: str) -> None:
    """Ensure daily_votes row exists then save menu image filename."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Create a placeholder row if vote hasn't started yet
        await db.execute(
            "INSERT OR IGNORE INTO daily_votes (date, price, status) VALUES (?, ?, 'none')",
            (date, 35000),
        )
        await db.execute(
            "UPDATE daily_votes SET menu_image = ? WHERE date = ?",
            (filename, date),
        )
        await db.commit()


# ── Vote entries ──────────────────────────────────────────────────────────────

async def toggle_vote(date: str, user_id: int) -> bool:
    """Returns True if user is now voted-in, False if removed."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM vote_entries WHERE date = ? AND user_id = ?", (date, user_id)
        ) as cur:
            exists = await cur.fetchone()
        if exists:
            await db.execute(
                "DELETE FROM vote_entries WHERE date = ? AND user_id = ?", (date, user_id)
            )
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT INTO vote_entries (date, user_id) VALUES (?, ?)", (date, user_id)
            )
            await db.commit()
            return True


async def get_voters(date: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.* FROM users u
               JOIN vote_entries v ON u.id = v.user_id
               WHERE v.date = ? AND u.active = 1
               ORDER BY u.rotation_index""",
            (date,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Round-robin picker ────────────────────────────────────────────────────────

async def pick_next_fetcher(date: str) -> Optional[dict]:
    """
    From today's voters, pick the next person in rotation after the last picker.
    Wraps around if needed. Returns the selected user dict or None if no voters.
    """
    voters = await get_voters(date)
    if not voters:
        return None

    # Find last picker's rotation_index
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT u.rotation_index FROM daily_votes dv
               JOIN users u ON u.id = dv.picker_user_id
               WHERE dv.date < ? AND dv.picker_user_id IS NOT NULL
               ORDER BY dv.date DESC LIMIT 1""",
            (date,),
        ) as cur:
            row = await cur.fetchone()
            last_idx = row[0] if row else -1

    # Find first voter with rotation_index > last_idx (wrap around if needed)
    candidates_after = [v for v in voters if v["rotation_index"] > last_idx]
    if candidates_after:
        return candidates_after[0]
    return voters[0]  # wrap around to start


async def pick_next_returner(date: str, exclude_user_id: int) -> Optional[dict]:
    """
    From today's voters (excluding picker), pick the next person in the return rotation.
    If only 1 voter, return that person (same as picker).
    """
    voters = await get_voters(date)
    if not voters:
        return None

    candidates = [v for v in voters if v["id"] != exclude_user_id]
    if not candidates:
        return voters[0]  # Only 1 voter → same person does both

    # Find last returner's return_index
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT u.return_index FROM daily_votes dv
               JOIN users u ON u.id = dv.returner_user_id
               WHERE dv.date < ? AND dv.returner_user_id IS NOT NULL
               ORDER BY dv.date DESC LIMIT 1""",
            (date,),
        ) as cur:
            row = await cur.fetchone()
            last_idx = row[0] if row else -1

    after = [v for v in candidates if v["return_index"] > last_idx]
    if after:
        return after[0]
    return candidates[0]  # wrap around


# ── Summary ───────────────────────────────────────────────────────────────────

async def get_monthly_summary(year_month: str, max_date: str = None) -> list:
    """
    year_month: 'YYYY-MM'
    max_date:   'YYYY-MM-DD' upper bound (inclusive). If None, no upper bound.
    Returns list of {full_name, meal_count, price_per_meal, total}
    Total = sum of (price + ship_fee/voter_count) per day — same formula as web dashboard.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        extra = " AND ve.date <= ?" if max_date else ""
        params = (f"{year_month}-%", max_date) if max_date else (f"{year_month}-%",)
        async with db.execute(
            f"""SELECT u.full_name, u.rotation_index, ve.date, dv.price, dv.ship_fee
               FROM users u
               JOIN vote_entries ve ON u.id = ve.user_id
               JOIN daily_votes dv  ON dv.date = ve.date
               WHERE ve.date LIKE ? AND dv.status = 'closed'{extra}
               ORDER BY u.rotation_index, ve.date""",
            params,
        ) as cur:
            entries = [dict(r) for r in await cur.fetchall()]

    # Count voters per day to split ship_fee correctly
    day_voter_counts: dict[str, int] = {}
    for e in entries:
        day_voter_counts[e["date"]] = day_voter_counts.get(e["date"], 0) + 1

    # Aggregate per user
    totals: dict[str, dict] = {}
    for e in entries:
        name = e["full_name"]
        if name not in totals:
            totals[name] = {"full_name": name, "meal_count": 0, "total": 0, "price_per_meal": e["price"]}
        count = day_voter_counts[e["date"]]
        ship = e.get("ship_fee") or 0
        totals[name]["meal_count"] += 1
        totals[name]["total"] += e["price"] + round(ship / count)

    return list(totals.values())


# ── Web dashboard queries ──────────────────────────────────────────────────────

async def get_daily_history(year_month: str) -> list:
    """
    Returns per-day records for the given month, newest first.
    Each item: {date, date_display, voter_names, picker_name}
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT dv.date, dv.picker_user_id,
                      u_picker.full_name AS picker_name
               FROM daily_votes dv
               LEFT JOIN users u_picker ON u_picker.id = dv.picker_user_id
               WHERE dv.date LIKE ? AND dv.status = 'closed'
               ORDER BY dv.date DESC""",
            (f"{year_month}-%",),
        ) as cur:
            days = [dict(r) for r in await cur.fetchall()]

        results = []
        for day in days:
            async with db.execute(
                """SELECT u.full_name FROM users u
                   JOIN vote_entries ve ON ve.user_id = u.id
                   WHERE ve.date = ?
                   ORDER BY u.rotation_index""",
                (day["date"],),
            ) as cur:
                voter_names = [r[0] for r in await cur.fetchall()]

            d = dt_date.fromisoformat(day["date"])
            weekdays = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"]
            date_display = f"{weekdays[d.weekday()]}, {d.day:02d}/{d.month:02d}"

            results.append({
                "date": day["date"],
                "date_display": date_display,
                "voter_names": voter_names,
                "picker_name": day["picker_name"],
            })

    return results


async def get_monthly_detail(year_month: str, max_date: str = None) -> dict:
    """
    Returns a matrix of who paid what each day.
    {
      "days":    [{"date": "YYYY-MM-DD", "date_short": "DD/MM", "weekday": "T2", "price": int}, ...],
      "members": [{"full_name": str, "votes": {date: price}, "total": int}, ...]
    }
    Only includes days with status='closed' and members who voted at least once.
    max_date: 'YYYY-MM-DD' upper bound (inclusive). If None, no upper bound.
    """
    WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # All closed days in the month
        extra = " AND date <= ?" if max_date else ""
        params = (f"{year_month}-%", max_date) if max_date else (f"{year_month}-%",)
        async with db.execute(
            f"SELECT date, price FROM daily_votes WHERE date LIKE ? AND status = 'closed'{extra} ORDER BY date",
            params,
        ) as cur:
            day_rows = [dict(r) for r in await cur.fetchall()]

        if not day_rows:
            return {"days": [], "members": []}

        days = []
        for r in day_rows:
            d = dt_date.fromisoformat(r["date"])
            days.append({
                "date": r["date"],
                "date_short": f"{d.day:02d}/{d.month:02d}",
                "weekday": WEEKDAYS[d.weekday()],
                "price": r["price"],
            })

        day_dates = [d["date"] for d in days]

        # All vote entries for those days
        placeholders = ",".join("?" * len(day_dates))
        async with db.execute(
            f"""SELECT ve.user_id, u.full_name, u.rotation_index, ve.date, dv.price, dv.ship_fee
                FROM vote_entries ve
                JOIN users u ON u.id = ve.user_id
                JOIN daily_votes dv ON dv.date = ve.date
                WHERE ve.date IN ({placeholders})
                ORDER BY u.rotation_index, ve.date""",
            day_dates,
        ) as cur:
            entries = [dict(r) for r in await cur.fetchall()]

    # Count voters per day to split ship fee
    day_voter_counts: dict[str, int] = {}
    for e in entries:
        day_voter_counts[e["date"]] = day_voter_counts.get(e["date"], 0) + 1

    # Build member map — amount per person = meal price + ship_fee / voter_count
    member_order = {}
    member_user_ids: dict[str, int] = {}
    votes_map: dict[str, dict[str, int]] = {}
    for e in entries:
        name = e["full_name"]
        if name not in member_order:
            member_order[name] = e["rotation_index"]
            member_user_ids[name] = e["user_id"]
            votes_map[name] = {}
        count = day_voter_counts[e["date"]]
        ship = e.get("ship_fee") or 0
        votes_map[name][e["date"]] = e["price"] + round(ship / count)

    members = []
    for name in sorted(member_order, key=lambda n: member_order[n]):
        votes = votes_map[name]
        members.append({
            "user_id": member_user_ids[name],
            "full_name": name,
            "votes": votes,
            "total": sum(votes.values()),
        })

    return {"days": days, "members": members}


async def get_paid_user_ids(year_month: str) -> set:
    """Returns set of user_ids who have paid for the given month."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM monthly_payments WHERE year_month = ?", (year_month,)
        ) as cur:
            rows = await cur.fetchall()
            return {r[0] for r in rows}


async def toggle_monthly_paid(year_month: str, user_id: int) -> bool:
    """Toggle paid status. Returns True if now paid, False if now unpaid."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM monthly_payments WHERE year_month = ? AND user_id = ?",
            (year_month, user_id),
        ) as cur:
            exists = await cur.fetchone()
        if exists:
            await db.execute(
                "DELETE FROM monthly_payments WHERE year_month = ? AND user_id = ?",
                (year_month, user_id),
            )
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT INTO monthly_payments (year_month, user_id) VALUES (?, ?)",
                (year_month, user_id),
            )
            await db.commit()
            return True


async def get_available_months() -> list:
    """Returns list of {value: 'YYYY-MM', label: 'Tháng M/YYYY'} for months with data."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT DISTINCT substr(date, 1, 7) AS ym
               FROM daily_votes
               WHERE status = 'closed'
               ORDER BY ym DESC"""
        ) as cur:
            rows = await cur.fetchall()

    months = []
    for (ym,) in rows:
        year, m = ym.split("-")
        months.append({"value": ym, "label": f"Tháng {int(m)}/{year}"})
    return months


async def get_week_data(week_dates: list) -> list:
    """
    week_dates: list of date strings 'YYYY-MM-DD' (Mon → Fri)
    Returns list of day dicts: {date, date_display, weekday, status, voters, picker_name}
    """
    WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"]

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        results = []
        for date_str in week_dates:
            d = dt_date.fromisoformat(date_str)
            date_display = f"{WEEKDAYS[d.weekday()]}, {d.day:02d}/{d.month:02d}"

            async with db.execute(
                "SELECT * FROM daily_votes WHERE date = ?", (date_str,)
            ) as cur:
                dv = await cur.fetchone()

            if not dv:
                results.append({
                    "date": date_str,
                    "date_display": date_display,
                    "weekday": WEEKDAYS[d.weekday()],
                    "status": "none",
                    "voters": [],
                    "picker_name": None,
                    "menu_image": None,
                })
                continue

            async with db.execute(
                """SELECT u.full_name FROM users u
                   JOIN vote_entries ve ON ve.user_id = u.id
                   WHERE ve.date = ? ORDER BY u.rotation_index""",
                (date_str,),
            ) as cur:
                voters = [r[0] for r in await cur.fetchall()]

            picker_name = None
            if dv["picker_user_id"]:
                async with db.execute(
                    "SELECT full_name FROM users WHERE id = ?", (dv["picker_user_id"],)
                ) as cur:
                    row = await cur.fetchone()
                    picker_name = row[0] if row else None

            # Nếu ngày đã qua mà vote vẫn open → hiện là closed
            status = dv["status"]
            if status == "open" and d < dt_date.today():
                status = "closed"

            results.append({
                "date": date_str,
                "date_display": date_display,
                "weekday": WEEKDAYS[d.weekday()],
                "status": status,
                "voters": voters,
                "picker_name": picker_name,
                "menu_image": dv["menu_image"],
            })

    return results


# ── Menu items (dishes) ───────────────────────────────────────────────────────

async def save_menu_items(date: str, dishes: list) -> None:
    """Save up to 4 dish names for a given date. Creates placeholder row if needed."""
    d1 = dishes[0] if len(dishes) > 0 else None
    d2 = dishes[1] if len(dishes) > 1 else None
    d3 = dishes[2] if len(dishes) > 2 else None
    d4 = dishes[3] if len(dishes) > 3 else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO daily_votes (date, price, status) VALUES (?, ?, 'none')",
            (date, 35000),
        )
        await db.execute(
            "UPDATE daily_votes SET dish1=?, dish2=?, dish3=?, dish4=? WHERE date=?",
            (d1, d2, d3, d4, date),
        )
        await db.commit()


async def get_menu_items(date: str) -> list:
    """Returns list of non-empty dish names for a date (up to 4)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT dish1, dish2, dish3, dish4 FROM daily_votes WHERE date=?", (date,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return []
    return [row[k] for k in ("dish1", "dish2", "dish3", "dish4") if row[k]]


async def vote_for_dish(date: str, user_id: int, dish: str) -> Optional[str]:
    """
    Vote for a specific dish.
    - Same dish again → cancel (delete), return None
    - Different dish → update dish, return new dish
    - No existing vote → insert, return dish
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT dish FROM vote_entries WHERE date=? AND user_id=?", (date, user_id)
        ) as cur:
            row = await cur.fetchone()

        if row is not None:
            if row[0] == dish:
                # Same dish → cancel
                await db.execute(
                    "DELETE FROM vote_entries WHERE date=? AND user_id=?", (date, user_id)
                )
                await db.commit()
                return None
            else:
                # Different dish → update
                await db.execute(
                    "UPDATE vote_entries SET dish=? WHERE date=? AND user_id=?",
                    (dish, date, user_id),
                )
                await db.commit()
                return dish
        else:
            await db.execute(
                "INSERT INTO vote_entries (date, user_id, dish) VALUES (?, ?, ?)",
                (date, user_id, dish),
            )
            await db.commit()
            return dish


async def get_voters_with_dish(date: str) -> list:
    """Like get_voters but includes the dish field."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.*, ve.dish FROM users u
               JOIN vote_entries ve ON u.id = ve.user_id
               WHERE ve.date = ? AND u.active = 1
               ORDER BY u.rotation_index""",
            (date,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
