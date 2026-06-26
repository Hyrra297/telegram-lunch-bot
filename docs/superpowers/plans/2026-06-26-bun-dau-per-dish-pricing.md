# Giá theo món cho ngày bún đậu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tính tiền ngày bún đậu **theo món** (mỗi người = giá món họ chọn + ship/số người), chốt (snapshot khoá) lúc 15h thứ 6; thay phần "đơn giá chung" (`price_override`) vừa làm.

**Architecture:** Thêm `dish1_price..dish4_price` (giá từng món) + `vote_entries.cost` (snapshot khoá) vào DB. Bảng tổng kết tính per-person = `ve.cost` nếu đã chốt, else `giá_món(hoặc giá_ngày) + ship/count`. Job 15h `_scheduled_friday_settle` đổi sang `snapshot_day_costs`. Web nhập giá từng món (bỏ ô "Giá/s"), ship ghi thẳng `daily_votes.ship_fee`. Ngừng dùng `price_override`/`ship_fee_override` (để lại cột dormant).

**Tech Stack:** Python 3.8, python-telegram-bot 21.x, FastAPI, aiosqlite, APScheduler, pytest + pytest-asyncio, httpx (AsyncClient/ASGITransport), Jinja2.

## Global Constraints

- Python 3.8; `scheduler.py`/`database.py` có `from __future__ import annotations` (`str | None` hợp lệ).
- `daily_votes.price`/`ship_fee` là `NOT NULL`. Cột mới `dish1_price..dish4_price` và `vote_entries.cost` đều **nullable** (NULL = chưa nhập/chưa chốt).
- Migration: thêm dòng vào vòng lặp `try/except ALTER TABLE` trong `init_db()`.
- Khớp món→giá: `vote_entries.dish` (text) khớp `daily_votes.dish1..dish4` → `dishN_price`. Không khớp/NULL → fallback `daily_votes.price`.
- Công thức 1 nguồn: `per_person = ve.cost nếu NOT NULL, else (dish_price hoặc dv.price) + round(ship / count)`; `ship = dv.ship_fee`, `count` = số entry ngày đó.
- `save_menu_items` lọc bỏ món rỗng (dồn vị trí). Vì vậy giá phải dồn **theo cặp (món, giá)** trước khi lưu để khớp slot.
- Test async: fixture `db` (test_database/test_scheduler) và `web_app` + `admin_cookie` (test_web). Chạy bằng `python -m pytest` (KHÔNG `pytest` trần). Bash = Git Bash trên Windows.
- Ngày test: `2026-01-02` = thứ 6 (weekday 4), `2026-01-05` = thứ 2 (weekday 0).
- Commit tiếng Việt, kết thúc bằng `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Branch: `bun-dau-per-dish-pricing` (đã tạo, đã commit spec). Baseline test trước khi bắt đầu: **127 passed**.

## File Structure

- `database.py` — migration `dish1_price..dish4_price` + `vote_entries.cost`; thêm `set_day_dish_prices`, `set_day_ship`, `snapshot_day_costs`; sửa `get_week_data` (trả `dishN_price` + `ship_fee`, bỏ override keys); sửa `get_monthly_summary` + `get_monthly_detail` (per-dish + đọc `ve.cost`); cuối cùng gỡ hàm chết `set_day_price`/`set_day_actual_price`.
- `scheduler.py` — `_scheduled_friday_settle` dùng `snapshot_day_costs`; `_scheduled_open_vote` bỏ đọc override.
- `web/app.py` — `/save-menu-items` nhận `price1..price4` + `ship_fee` (bỏ `price`); gọi `set_day_dish_prices` + `set_day_ship`.
- `web/templates/index.html` — ô giá mỗi món, bỏ "Giá/s", giữ "Ship".
- Tests: `test_database.py`, `test_scheduler.py`, `test_web.py` — gỡ/thay test override cũ, thêm test per-dish.

---

### Task 1: Migration + `set_day_dish_prices` + `set_day_ship`

**Files:**
- Modify: `database.py` (migration trong `init_db`; thêm 2 hàm setter; gỡ class test cũ `TestDayPrice`)
- Test: `tests/test_database.py` (gỡ `TestDayPrice`; thêm `TestDayDishPrices`)

**Interfaces:**
- Produces:
  - Cột nullable: `daily_votes.dish1_price..dish4_price` (INTEGER), `vote_entries.cost` (INTEGER).
  - `set_day_dish_prices(date: str, prices: list) -> None` — `prices` tối đa 4 phần tử (positional, None-able), pad None tới 4, UPDATE `dishN_price`. Tạo placeholder row nếu chưa có.
  - `set_day_ship(date: str, ship_fee: int) -> None` — UPDATE `daily_votes.ship_fee`. Tạo placeholder row nếu chưa có.

- [ ] **Step 1: Gỡ test cũ + viết test mới (RED)**

Trong `tests/test_database.py`: **xoá toàn bộ class `TestDayPrice`** (4 test override đơn giá — không còn dùng). Thêm class mới:

```python
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
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_database.py::TestDayDishPrices -v`
Expected: FAIL — chưa có `set_day_dish_prices`/`set_day_ship`, chưa có cột `dishN_price`/`cost`.

- [ ] **Step 3: Thêm migration + 2 hàm setter**

Trong `database.py::init_db`, thêm vào cuối list `col_sql` (trước `]`):

```python
            "ALTER TABLE daily_votes ADD COLUMN dish1_price INTEGER",
            "ALTER TABLE daily_votes ADD COLUMN dish2_price INTEGER",
            "ALTER TABLE daily_votes ADD COLUMN dish3_price INTEGER",
            "ALTER TABLE daily_votes ADD COLUMN dish4_price INTEGER",
            "ALTER TABLE vote_entries ADD COLUMN cost INTEGER",
```

Thêm 2 hàm (đặt sau `set_day_price`, hoặc bất kỳ chỗ nào trong vùng daily_votes helpers):

```python
async def set_day_dish_prices(date: str, prices: list) -> None:
    """Lưu giá cho từng món (positional dish1_price..dish4_price). None = không có giá."""
    p = (list(prices) + [None, None, None, None])[:4]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO daily_votes (date, status) VALUES (?, 'none')", (date,),
        )
        await db.execute(
            "UPDATE daily_votes SET dish1_price=?, dish2_price=?, dish3_price=?, dish4_price=? WHERE date=?",
            (p[0], p[1], p[2], p[3], date),
        )
        await db.commit()


async def set_day_ship(date: str, ship_fee: int) -> None:
    """Ghi ship/ngày thẳng vào daily_votes.ship_fee (bảng đọc live)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO daily_votes (date, status) VALUES (?, 'none')", (date,),
        )
        await db.execute(
            "UPDATE daily_votes SET ship_fee=? WHERE date=?", (ship_fee, date),
        )
        await db.commit()
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_database.py::TestDayDishPrices -v`
Expected: PASS cả 4 test.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: cột giá theo món + vote_entries.cost + setter dish prices/ship

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `get_week_data` trả giá món + ship (bỏ override keys)

**Files:**
- Modify: `database.py::get_week_data`
- Test: `tests/test_database.py` (class `TestWeekDataDishPrices`)

**Interfaces:**
- Consumes: cột `dish1_price..dish4_price`, `ship_fee` (Task 1).
- Produces: `get_week_data` mỗi ngày trả thêm `dish1_price, dish2_price, dish3_price, dish4_price, ship_fee`; **bỏ** `price_override`, `ship_fee_override`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_database.py`:

```python
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

    async def test_week_data_no_row_dish_prices_none(self, db):
        rows = await db.get_week_data(["2026-01-02"])
        assert rows[0]["dish1_price"] is None
        assert rows[0]["ship_fee"] is None
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_database.py::TestWeekDataDishPrices -v`
Expected: FAIL — get_week_data chưa trả `dish1_price`; còn `price_override`.

- [ ] **Step 3: Sửa `get_week_data`**

Trong `database.py::get_week_data`, nhánh **không có row** (`if not dv:`), thay 2 key override bằng:

```python
                results.append({
                    "date": date_str,
                    "date_display": date_display,
                    "weekday": WEEKDAYS[d.weekday()],
                    "status": "none",
                    "voters": [],
                    "picker_name": None,
                    "menu_image": None,
                    "dish1_price": None,
                    "dish2_price": None,
                    "dish3_price": None,
                    "dish4_price": None,
                    "ship_fee": None,
                })
                continue
```

Nhánh **có row** (`results.append` cuối hàm), thay 2 key override bằng:

```python
            results.append({
                "date": date_str,
                "date_display": date_display,
                "weekday": WEEKDAYS[d.weekday()],
                "status": status,
                "voters": voters,
                "picker_name": picker_name,
                "menu_image": dv["menu_image"],
                "dish1_price": dv["dish1_price"],
                "dish2_price": dv["dish2_price"],
                "dish3_price": dv["dish3_price"],
                "dish4_price": dv["dish4_price"],
                "ship_fee": dv["ship_fee"],
            })
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_database.py::TestWeekDataDishPrices -v`
Expected: PASS cả 2.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: get_week_data trả giá từng món + ship (bỏ override keys)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `snapshot_day_costs` (chốt khoá tiền mỗi người)

**Files:**
- Modify: `database.py` (thêm `snapshot_day_costs`)
- Test: `tests/test_database.py` (class `TestSnapshotDayCosts`)

**Interfaces:**
- Consumes: `dishN_price`, `ship_fee`, `vote_entries.dish`/`cost` (Task 1).
- Produces: `snapshot_day_costs(date: str) -> int` — với mỗi entry ngày đó, tính `cost = (dish_price khớp món, else daily.price) + round(ship/count)`, ghi `vote_entries.cost`. Trả số người đã chốt (0 nếu không có row/không ai vote).

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_database.py`:

```python
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
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_database.py::TestSnapshotDayCosts -v`
Expected: FAIL — chưa có `snapshot_day_costs`.

- [ ] **Step 3: Thêm `snapshot_day_costs`**

Trong `database.py` (đặt gần các hàm vote_entries):

```python
async def snapshot_day_costs(date: str) -> int:
    """Chốt khoá: tính & ghi cost mỗi người (giá món + ship/count) vào vote_entries.cost.
    Trả số người đã chốt."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_votes WHERE date=?", (date,)) as cur:
            dv = await cur.fetchone()
        if not dv:
            return 0
        async with db.execute("SELECT user_id, dish FROM vote_entries WHERE date=?", (date,)) as cur:
            entries = [dict(r) for r in await cur.fetchall()]
        if not entries:
            return 0
        count = len(entries)
        ship = dv["ship_fee"] or 0
        price_by_dish = {
            dv["dish1"]: dv["dish1_price"],
            dv["dish2"]: dv["dish2_price"],
            dv["dish3"]: dv["dish3_price"],
            dv["dish4"]: dv["dish4_price"],
        }
        for e in entries:
            dp = price_by_dish.get(e["dish"])
            unit = dp if dp is not None else dv["price"]
            cost = unit + round(ship / count)
            await db.execute(
                "UPDATE vote_entries SET cost=? WHERE date=? AND user_id=?",
                (cost, date, e["user_id"]),
            )
        await db.commit()
        return count
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_database.py::TestSnapshotDayCosts -v`
Expected: PASS cả 3.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: snapshot_day_costs — chốt khoá tiền mỗi người theo giá món

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Tổng kết tính theo món + đọc `ve.cost`

**Files:**
- Modify: `database.py::get_monthly_summary`, `database.py::get_monthly_detail`
- Test: `tests/test_database.py` (class `TestSummaryPerDish`)

**Interfaces:**
- Consumes: `snapshot_day_costs` (Task 3), cột giá món + `ve.cost`.
- Produces: cả 2 hàm tính `per_person = ve.cost nếu NOT NULL, else (dish_price hoặc dv.price) + round(ship/count)`. `get_monthly_summary` giữ key `price_per_meal` = `dv.price` (giá fallback, cho ảnh tổng kết).

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_database.py`:

```python
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
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_database.py::TestSummaryPerDish -v`
Expected: FAIL ở các test per-dish (hiện tổng = dv.price 45000 cho mọi người, chưa theo món).

- [ ] **Step 3: Sửa `get_monthly_summary`**

Trong `database.py::get_monthly_summary`, đổi câu SELECT (thêm `ve.cost`, `ve.dish`, và CASE giá món):

```python
        async with db.execute(
            f"""SELECT u.id AS user_id, u.full_name, u.rotation_index, ve.date, ve.cost,
                      dv.price, dv.ship_fee,
                      CASE ve.dish
                          WHEN dv.dish1 THEN dv.dish1_price
                          WHEN dv.dish2 THEN dv.dish2_price
                          WHEN dv.dish3 THEN dv.dish3_price
                          WHEN dv.dish4 THEN dv.dish4_price
                          ELSE NULL
                      END AS dish_price
               FROM users u
               JOIN vote_entries ve ON u.id = ve.user_id
               JOIN daily_votes dv  ON dv.date = ve.date
               WHERE ve.date LIKE ? AND dv.status = 'closed'{extra}
               ORDER BY u.rotation_index, ve.date""",
            params,
        ) as cur:
            entries = [dict(r) for r in await cur.fetchall()]
```

Sửa vòng tính tổng (thay đoạn `totals[uid]["total"] += ...`):

```python
    for e in entries:
        uid = e["user_id"]
        if uid not in totals:
            totals[uid] = {"user_id": uid, "full_name": e["full_name"], "meal_count": 0, "total": 0, "price_per_meal": e["price"]}
        if e["cost"] is not None:
            amount = e["cost"]
        else:
            count = day_voter_counts[e["date"]]
            ship = e.get("ship_fee") or 0
            unit = e["dish_price"] if e["dish_price"] is not None else e["price"]
            amount = unit + round(ship / count)
        totals[uid]["meal_count"] += 1
        totals[uid]["total"] += amount
```

- [ ] **Step 4: Sửa `get_monthly_detail`**

Trong `database.py::get_monthly_detail`, đổi câu SELECT entries tương tự (thêm `ve.cost` + CASE `dish_price`):

```python
        async with db.execute(
            f"""SELECT ve.user_id, u.full_name, u.rotation_index, ve.date, ve.cost,
                       dv.price, dv.ship_fee,
                       CASE ve.dish
                           WHEN dv.dish1 THEN dv.dish1_price
                           WHEN dv.dish2 THEN dv.dish2_price
                           WHEN dv.dish3 THEN dv.dish3_price
                           WHEN dv.dish4 THEN dv.dish4_price
                           ELSE NULL
                       END AS dish_price
                FROM vote_entries ve
                JOIN users u ON u.id = ve.user_id
                JOIN daily_votes dv ON dv.date = ve.date
                WHERE ve.date IN ({placeholders})
                ORDER BY u.rotation_index, ve.date""",
            day_dates,
        ) as cur:
            entries = [dict(r) for r in await cur.fetchall()]
```

Sửa vòng dựng `votes_map` (thay dòng `votes_map[name][e["date"]] = ...`):

```python
        if e["cost"] is not None:
            amount = e["cost"]
        else:
            count = day_voter_counts[e["date"]]
            ship = e.get("ship_fee") or 0
            unit = e["dish_price"] if e["dish_price"] is not None else e["price"]
            amount = unit + round(ship / count)
        votes_map[name][e["date"]] = amount
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_database.py::TestSummaryPerDish tests/test_database.py -k "summary or detail or monthly" -v`
Expected: PASS các test mới + test summary/detail cũ (ngày không có giá món vẫn fallback dv.price → không đổi).

- [ ] **Step 6: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: tổng kết tính theo món + đọc snapshot ve.cost

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `_scheduled_friday_settle` đổi sang snapshot

**Files:**
- Modify: `scheduler.py::_scheduled_friday_settle`
- Test: `tests/test_scheduler.py` (thay class `TestFridaySettle`)

**Interfaces:**
- Consumes: `db.snapshot_day_costs` (Task 3), `_is_friday`.
- Produces: `_scheduled_friday_settle(app, today=None)` chỉ T6 → gọi `snapshot_day_costs(today)`; im lặng; bỏ logic `price_override`/`set_day_actual_price`/`set_cost_per_person`.

- [ ] **Step 1: Thay test cũ (RED)**

Trong `tests/test_scheduler.py`: **xoá toàn bộ class `TestFridaySettle` cũ** (test snapshot 1 giá) và thay bằng:

```python
class TestFridaySettle:
    async def _cost(self, db_mod, date, user_id):
        import aiosqlite
        async with aiosqlite.connect(db_mod.DB_PATH) as conn:
            async with conn.execute("SELECT cost FROM vote_entries WHERE date=? AND user_id=?", (date, user_id)) as cur:
                row = await cur.fetchone()
        return row[0]

    async def test_friday_snapshots_per_dish(self, db):
        from scheduler import _scheduled_friday_settle
        friday = "2026-01-02"
        await db.add_user(1, "An", "an")
        await db.add_user(2, "Binh", "binh")
        await db.create_daily_vote(friday, 100, 45000, 0)
        await db.save_menu_items(friday, ["Bún đậu thường", "Bún đậu đầy đủ"])
        await db.set_day_dish_prices(friday, [35000, 50000])
        await db.set_day_ship(friday, 10000)
        await db.vote_for_dish(friday, 1, "Bún đậu thường")
        await db.vote_for_dish(friday, 2, "Bún đậu đầy đủ")
        await db.set_vote_closed(friday)
        app = FakeApp()
        await _scheduled_friday_settle(app, today=friday)
        assert await self._cost(db, friday, 1) == 40000
        assert await self._cost(db, friday, 2) == 55000
        assert app.bot.sent_messages == []   # im lặng

    async def test_non_friday_noop(self, db):
        from scheduler import _scheduled_friday_settle
        monday = "2026-01-05"
        await db.add_user(1, "An", "an")
        await db.create_daily_vote(monday, 100, 45000, 0)
        await db.vote_for_dish(monday, 1, "Cơm gà")
        await db.set_vote_closed(monday)
        app = FakeApp()
        await _scheduled_friday_settle(app, today=monday)
        assert await self._cost(db, monday, 1) is None  # không chốt ngày thường
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestFridaySettle -v`
Expected: FAIL — settle hiện vẫn dùng `set_day_actual_price`/`price_override`, chưa snapshot `ve.cost`.

- [ ] **Step 3: Sửa `_scheduled_friday_settle`**

Thay toàn bộ thân hàm (giữ chữ ký) bằng:

```python
async def _scheduled_friday_settle(app: Application, today: str | None = None) -> None:
    """15:00 thứ 6 — chốt khoá tiền bún đậu: snapshot tiền mỗi người (giá món + ship/số người)
    vào vote_entries.cost. Im lặng, không gửi thông báo."""
    if today is None:
        today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    if not _is_friday(today):
        return
    logger.info("⏰ Scheduler: friday_settle triggered for %s", today)
    try:
        daily = await db.get_daily_vote(today)
        if not daily or daily["status"] not in ("open", "closed"):
            return
        n = await db.snapshot_day_costs(today)
        logger.info("✅ Friday settle %s: chốt %d người", today, n)
    except Exception:
        logger.exception("❌ friday_settle failed for %s", today)
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py::TestFridaySettle tests/test_scheduler.py::TestBuildScheduler -v`
Expected: PASS (job `friday_settle` vẫn đăng ký, test_job_ids không đổi).

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: settle 15h thứ 6 snapshot tiền theo món (vote_entries.cost)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `_scheduled_open_vote` bỏ đọc override

**Files:**
- Modify: `scheduler.py::_scheduled_open_vote`
- Test: `tests/test_scheduler.py` (thay class `TestOpenVotePriceOverride`)

**Interfaces:**
- Produces: `_scheduled_open_vote` tạo vote với giá/ship **toàn cục** (settings/config), không đọc `price_override`/`ship_fee_override`.

- [ ] **Step 1: Thay test cũ (RED)**

Trong `tests/test_scheduler.py`: **xoá class `TestOpenVotePriceOverride` cũ** (2 test override) và thay bằng:

```python
class TestOpenVoteUsesGlobalPrice:
    async def test_ignores_old_price_override(self, db):
        from scheduler import _scheduled_open_vote, _target_date
        today = _target_date(0)
        await db.set_menu_image(today, "menu.jpg")
        # set price_override/ship_fee_override (cột dormant) trực tiếp bằng SQL —
        # tạo vote phải BỎ QUA, dùng giá toàn cục. (Raw SQL để test sống sót khi Task 8 gỡ set_day_price.)
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE daily_votes SET price_override=?, ship_fee_override=? WHERE date=?",
                (30000, 5000, today),
            )
            await conn.commit()
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=0)
        daily = await db.get_daily_vote(today)
        assert daily["price"] == config.PRICE_PER_MEAL   # 45000 — KHÔNG dùng override 30000
        assert daily["ship_fee"] == config.SHIP_FEE      # 20000 — KHÔNG dùng override 5000
```

(`import config` đã có sẵn đầu `tests/test_scheduler.py`.)

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestOpenVoteUsesGlobalPrice -v`
Expected: FAIL — code hiện đọc `price_override` → `daily["price"]` = 30000 (không bằng 45000).

- [ ] **Step 3: Sửa `_scheduled_open_vote` — bỏ block override**

Trong `scheduler.py::_scheduled_open_vote`, **xoá** đoạn:

```python
        # Giá/ship admin nhập tay cho ngày này (override) — ưu tiên nếu có
        if existing:
            if existing["price_override"] is not None:
                price = existing["price_override"]
            if existing["ship_fee_override"] is not None:
                ship_fee = existing["ship_fee_override"]
```

(Giữ nguyên phần lấy `price`/`ship_fee` từ settings/config phía trên.)

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS toàn bộ scheduler tests.

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "refactor: bỏ đọc price_override khi tạo vote (giá theo món thay thế)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Web — nhập giá từng món, bỏ "Giá/s", ship trực tiếp

**Files:**
- Modify: `web/app.py::save_menu_items_endpoint`
- Modify: `web/templates/index.html` (form lưu món)
- Test: `tests/test_web.py` (thay test override cũ)

**Interfaces:**
- Consumes: `db.set_day_dish_prices`, `db.set_day_ship` (Task 1); `day.dish1_price..dish4_price`, `day.ship_fee` từ `get_week_data` (Task 2).
- Produces: `/save-menu-items` nhận `price1..price4` + `ship_fee` (bỏ `price`); ghép cặp (món, giá) lọc món rỗng để khớp slot; gọi `set_day_dish_prices` + (nếu ship hợp lệ) `set_day_ship`.

- [ ] **Step 1: Thay test cũ (RED)**

Trong `tests/test_web.py`: **xoá** `test_save_menu_items_with_price_override` và `test_save_menu_items_empty_price_clears_override`. Thêm:

```python
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
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_web.py::test_save_menu_items_with_dish_prices tests/test_web.py::test_save_menu_items_prices_align_after_empty_dish -v`
Expected: FAIL — endpoint chưa nhận `price1..price4`, chưa ghi `dishN_price`.

- [ ] **Step 3: Sửa endpoint `save_menu_items_endpoint`**

Trong `web/app.py`, thay toàn bộ hàm:

```python
@app.post("/save-menu-items")
async def save_menu_items_endpoint(
    request: Request,
    date: str = Form(...),
    dish1: str = Form(""),
    dish2: str = Form(""),
    dish3: str = Form(""),
    dish4: str = Form(""),
    price1: str = Form(""),
    price2: str = Form(""),
    price3: str = Form(""),
    price4: str = Form(""),
    ship_fee: str = Form(""),
):
    if not _is_admin(request):
        return JSONResponse({"ok": False, "error": "Không có quyền"}, status_code=403)
    # Ghép cặp (món, giá), lọc món rỗng để giá khớp slot sau khi dồn
    pairs = [
        (d.strip(), _parse_int(p))
        for d, p in [(dish1, price1), (dish2, price2), (dish3, price3), (dish4, price4)]
        if d.strip()
    ]
    dishes = [d for d, _ in pairs]
    prices = [p for _, p in pairs]
    await db.save_menu_items(date, dishes)
    await db.set_day_dish_prices(date, prices)
    ship = _parse_int(ship_fee)
    if ship is not None:
        await db.set_day_ship(date, ship)
    return JSONResponse({"ok": True})
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_web.py -v`
Expected: PASS (gồm `test_save_menu_items_success` cũ vẫn xanh — nó không gửi price1..4 nên dishes lưu bình thường, dish prices None).

- [ ] **Step 5: Sửa template `index.html`**

Trong `web/templates/index.html`, thay khối form lưu món (từ `{% set dishes = week_menu[day.date] %}` tới `</form>`) bằng:

```html
          {# ── Dish + price form (admin only) ── #}
          {% set dishes = week_menu[day.date] %}
          <form style="margin-top:8px;display:flex;flex-direction:column;gap:6px"
                onsubmit="saveMenuItems(event, '{{ day.date }}')">
            <div style="display:grid;grid-template-columns:2fr 1fr;gap:6px">
              <input type="text" name="dish1" placeholder="Món 1" value="{{ dishes[0] }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
              <input type="number" name="price1" placeholder="Giá" value="{{ day.dish1_price if day.dish1_price is not none else '' }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
              <input type="text" name="dish2" placeholder="Món 2" value="{{ dishes[1] }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
              <input type="number" name="price2" placeholder="Giá" value="{{ day.dish2_price if day.dish2_price is not none else '' }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
              <input type="text" name="dish3" placeholder="Món 3" value="{{ dishes[2] }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
              <input type="number" name="price3" placeholder="Giá" value="{{ day.dish3_price if day.dish3_price is not none else '' }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
              <input type="text" name="dish4" placeholder="Món 4" value="{{ dishes[3] }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
              <input type="number" name="price4" placeholder="Giá" value="{{ day.dish4_price if day.dish4_price is not none else '' }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
            </div>
            <input type="number" name="ship_fee" placeholder="Ship (chia đều, để 0 nếu không)"
              value="{{ day.ship_fee if day.ship_fee is not none else '' }}"
              style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
            <button type="submit"
              style="align-self:flex-start;padding:6px 14px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:.82rem">
              💾 Lưu món + giá
            </button>
          </form>
```

- [ ] **Step 6: Kiểm tra template render (GET / → 200)**

Run: `python -m pytest tests/test_web.py -k "index_renders" -v`
Expected: PASS (smoke test GET / vẫn 200; `day.dish1_price` có sẵn từ get_week_data Task 2 → không lỗi Jinja).

- [ ] **Step 7: Commit**

```bash
git add web/app.py web/templates/index.html tests/test_web.py
git commit -m "feat: web nhập giá từng món + ship; bỏ ô đơn giá Giá/s

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Dọn hàm chết + full test + cập nhật docs

**Files:**
- Modify: `database.py` (gỡ `set_day_price`, `set_day_actual_price` nếu không còn caller)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Kiểm tra không còn caller của hàm cũ**

Run: `grep -rn "set_day_price\|set_day_actual_price" --include=*.py .`
Expected: chỉ còn định nghĩa trong `database.py` (không còn nơi gọi ở `web/app.py`/`scheduler.py`/tests). Nếu vậy → xoá 2 hàm `set_day_price` và `set_day_actual_price` khỏi `database.py`. (Nếu còn caller bất ngờ → dừng, báo lại.)

- [ ] **Step 2: Chạy full suite**

Run: `python -m pytest -q`
Expected: PASS toàn bộ, không regression.

- [ ] **Step 3: Cập nhật CLAUDE.md**

Trong `CLAUDE.md`, phần ngày bún đậu / tính tiền: ghi rõ ngày thứ 6 tính tiền **theo món** (mỗi món có giá riêng `dishN_price`; mỗi người = giá món + ship/số người); **15h snapshot** khoá tiền vào `vote_entries.cost`; admin nhập giá từng món + ship qua web tab "Tuần này" (đã bỏ ô "Giá/s" đơn giá; ngừng dùng `price_override`). Cập nhật mô tả schema `daily_votes` (thêm `dish1_price..dish4_price`) và `vote_entries` (thêm `cost`). Ghi chú công thức tổng kết: `per_person = ve.cost nếu đã chốt, else giá_món(hoặc giá_ngày) + ship/count`.

- [ ] **Step 4: Commit**

```bash
git add database.py CLAUDE.md
git commit -m "chore: gỡ hàm đơn giá chết + cập nhật CLAUDE.md giá theo món

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Giá theo món (dishN_price) → Task 1 (cột + setter), Task 4 (summary). ✓
- Mỗi người = giá món + ship/count → Task 3 (snapshot), Task 4 (summary live). ✓
- Snapshot khoá 15h → Task 3 (`snapshot_day_costs`), Task 5 (settle gọi). ✓
- Trước 15h live, sau 15h khoá → Task 4 (`ve.cost` ưu tiên; test `test_summary_uses_snapshot_when_locked`). ✓
- Bỏ ô "Giá/s", ship trực tiếp → Task 7 (endpoint + template). ✓
- Tổng kết per-dish (cả 2 hàm) → Task 4. ✓
- Ngừng dùng price_override (bỏ đọc khi tạo vote) → Task 6; gỡ hàm chết → Task 8. ✓
- Ngày cơm thường không đổi → Task 4 (`test_summary_com_single_price_unchanged`, fallback dv.price). ✓
- get_week_data prefill giá món → Task 2. ✓

**Placeholder scan:** Không có TBD/TODO; mọi step có code/cmd cụ thể. ✓

**Type consistency:** `set_day_dish_prices(date, prices:list)`, `set_day_ship(date, ship_fee:int)`, `snapshot_day_costs(date)->int` dùng nhất quán giữa Task 1/3/5/7. Cột `dish1_price..dish4_price` + `vote_entries.cost` đặt tên đồng nhất ở migration, setter, snapshot, summary, get_week_data, template. CASE khớp `ve.dish` → `dishN_price` giống nhau ở `get_monthly_summary` và `get_monthly_detail`. ✓

**Rủi ro đã xử lý:** `save_menu_items` dồn món rỗng → endpoint ghép cặp (món,giá) trước khi lưu (Task 7, có test align). `ve.cost` nullable → fallback live khi NULL. Ngày cơm/`✅❌` (dish NULL) → CASE ELSE NULL → fallback dv.price. Hàm cũ chỉ gỡ sau khi grep xác nhận hết caller (Task 8).
