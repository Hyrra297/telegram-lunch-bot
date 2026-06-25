# Ngày thứ 6 = ngày bún đậu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Biến thứ 6 thành "ngày bún đậu" với luồng riêng — vote chỉ tạo lúc 8h30 sáng T6 (1 tin), wording bún đậu, giá/ship admin nhập tay qua web, phân công chỉ 1 người đi lấy (không trả hộp). Chỉ riêng thứ 6.

**Architecture:** Thêm helper `_is_friday(date_str)` trong `scheduler.py` để rẽ nhánh theo thứ 6. Bỏ thứ 5 khỏi 2 job tối (19h tạo vote + 20h digest) ⇒ job sáng 8h30 (lưới an toàn sẵn có) tự tạo vote T6 thành tin duy nhất. Giá/ship per-day lưu vào 2 cột override nullable mới trên `daily_votes`; admin nhập qua form tuần trong web; job tạo vote ưu tiên giá override nếu có. Notify real-time admin giữ nguyên (đã đúng tự nhiên cho T6).

**Tech Stack:** Python 3.8, python-telegram-bot 21.x, FastAPI, aiosqlite, APScheduler, pytest + pytest-asyncio, httpx (AsyncClient/ASGITransport), Jinja2.

## Global Constraints

- Python 3.8; `scheduler.py` và `database.py` đều có `from __future__ import annotations` (annotation kiểu `str | None` hợp lệ vì lazy).
- Timezone `Asia/Ho_Chi_Minh`; "thứ 6" = `datetime.fromisoformat(date_str).weekday() == 4`.
- Cột `daily_votes.price`/`ship_fee` là `NOT NULL DEFAULT 45000/20000` — KHÔNG được set NULL. Per-day override dùng cột riêng nullable.
- Test async: dùng fixture `db` (scheduler/database tests) và `web_app` + `admin_cookie` (web tests) đã có trong `tests/conftest.py` và `tests/test_web.py`.
- Migration cột mới: thêm dòng vào vòng lặp `try/except ALTER TABLE` trong `init_db()`.
- Ngày test cố định: `2026-01-02` là **thứ 6** (weekday 4), `2026-01-05` là **thứ 2** (weekday 0).
- Commit message tiếng Việt, kết thúc bằng dòng `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Branch hiện tại: `friday-bun-dau` (đã tạo, đã có 2 commit spec).

## File Structure

- `scheduler.py` — thêm `_is_friday`; sửa `_open_vote_wording` (wording bún đậu); sửa `_scheduled_open_vote` (ưu tiên giá override); sửa `_scheduled_announce_roles` (nhận `today` param + nhánh T6 chỉ picker); sửa `build_scheduler` (bỏ `thu` ở 2 job).
- `database.py` — thêm 2 cột migration `price_override`/`ship_fee_override`; thêm `set_day_price`; `get_week_data` trả thêm 2 field override.
- `web/app.py` — `/save-menu-items` nhận thêm `price`/`ship_fee`, gọi `set_day_price`.
- `web/templates/index.html` — thêm 2 ô input (price, ship_fee) vào form lưu món của mỗi ngày.
- `tests/test_scheduler.py` — test wording T6, trigger 2 job bỏ thu, nhánh announce T6, ưu tiên giá override; mở rộng `FakeBot`.
- `tests/test_database.py` — test `set_day_price` + `get_week_data` field override.
- `tests/test_web.py` — test `/save-menu-items` lưu override.

---

### Task 1: Helper `_is_friday` + wording bún đậu

**Files:**
- Modify: `scheduler.py` (thêm `_is_friday`; sửa `_open_vote_wording`; sửa call site trong `_scheduled_open_vote`)
- Test: `tests/test_scheduler.py` (class `TestIsFriday`, bổ sung `TestOpenVoteWording`)

**Interfaces:**
- Produces: `_is_friday(date_str: str) -> bool`; `_open_vote_wording(day_offset: int, date_str: str | None = None) -> dict` (thêm tham số `date_str`, mặc định `None` = không phải thứ 6 → giữ wording cũ).

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_scheduler.py` (sau class `TestOpenVoteWording`):

```python
class TestIsFriday:
    def test_friday_true(self):
        from scheduler import _is_friday
        assert _is_friday("2026-01-02") is True  # thứ 6

    def test_monday_false(self):
        from scheduler import _is_friday
        assert _is_friday("2026-01-05") is False  # thứ 2


class TestFridayWording:
    def test_friday_uses_bun_dau_wording(self):
        from scheduler import _open_vote_wording
        w = _open_vote_wording(0, "2026-01-02")  # thứ 6
        assert w["day_label"] == "hôm nay"
        assert w["caption"] == "🍜 Thực đơn bún đậu hôm nay"
        assert w["poll_question"] == "🥢 Hôm nay ăn bún đậu gì?"

    def test_non_friday_keeps_default(self):
        from scheduler import _open_vote_wording
        w = _open_vote_wording(0, "2026-01-05")  # thứ 2
        assert w["caption"] == "🍽️ Thực đơn hôm nay"
        assert w["poll_question"] == "🍱 Hôm nay ăn gì?"

    def test_no_date_keeps_default(self):
        from scheduler import _open_vote_wording
        w = _open_vote_wording(0)  # backward-compat: không truyền date
        assert w["caption"] == "🍽️ Thực đơn hôm nay"
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestIsFriday tests/test_scheduler.py::TestFridayWording -v`
Expected: FAIL — `ImportError: cannot import name '_is_friday'` và/hoặc `TypeError` do `_open_vote_wording` chưa nhận `date_str`.

- [ ] **Step 3: Cài đặt `_is_friday` + sửa `_open_vote_wording`**

Trong `scheduler.py`, thêm helper ngay sau `_target_date` (sau dòng `return (datetime.now(tz) + timedelta(days=day_offset)).strftime("%Y-%m-%d")`):

```python
def _is_friday(date_str: str) -> bool:
    """True nếu date_str (YYYY-MM-DD) là thứ 6."""
    return datetime.strptime(date_str, "%Y-%m-%d").weekday() == 4
```

Thay toàn bộ hàm `_open_vote_wording` bằng:

```python
def _open_vote_wording(day_offset: int, date_str: str | None = None) -> dict:
    """Chữ hiển thị tuỳ vote tạo cho hôm nay hay ngày mai; thứ 6 dùng wording bún đậu."""
    if date_str and _is_friday(date_str):
        return {
            "caption": "🍜 Thực đơn bún đậu hôm nay",
            "poll_question": "🥢 Hôm nay ăn bún đậu gì?",
            "day_label": "hôm nay",
        }
    if day_offset >= 1:
        return {
            "caption": "🍽️ Thực đơn ngày mai",
            "poll_question": "🍱 Ngày mai ăn gì?",
            "day_label": "ngày mai",
        }
    return {
        "caption": "🍽️ Thực đơn hôm nay",
        "poll_question": "🍱 Hôm nay ăn gì?",
        "day_label": "hôm nay",
    }
```

Trong `_scheduled_open_vote`, sửa dòng `wording = _open_vote_wording(day_offset)` thành:

```python
    wording = _open_vote_wording(day_offset, target_str)
```

(biến `target_str` đã được tính ở dòng `target_str = _target_date(day_offset)` ngay trên đó.)

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py::TestIsFriday tests/test_scheduler.py::TestFridayWording tests/test_scheduler.py::TestOpenVoteWording -v`
Expected: PASS toàn bộ (gồm cả 2 test wording cũ vẫn xanh).

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: wording bún đậu cho thứ 6 + helper _is_friday

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Bỏ thứ 5 khỏi job 19h (tạo vote) và 20h (digest)

**Files:**
- Modify: `scheduler.py::build_scheduler` (2 job `open_vote_evening`, `admin_digest`)
- Test: `tests/test_scheduler.py::TestBuildScheduler` (sửa `test_evening_job_trigger`, thêm test digest)

**Interfaces:**
- Consumes: `_is_friday` (không trực tiếp; thay đổi ở cron `day_of_week`).
- Produces: job `open_vote_evening` và `admin_digest` có `day_of_week='sun,mon,tue,wed'` (bỏ `thu`).

- [ ] **Step 1: Sửa/Thêm test thất bại**

Trong `tests/test_scheduler.py::TestBuildScheduler`, sửa `test_evening_job_trigger` — đổi assertion ngày:

```python
    def test_evening_job_trigger(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        trig = str(jobs["open_vote_evening"].trigger)
        assert "hour='19'" in trig
        assert "day_of_week='sun,mon,tue,wed'" in trig
        assert "thu" not in trig
```

Thêm test mới cho digest trong cùng class:

```python
    def test_digest_job_excludes_thursday(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        trig = str(jobs["admin_digest"].trigger)
        assert "hour='20'" in trig
        assert "day_of_week='sun,mon,tue,wed'" in trig
        assert "thu" not in trig
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestBuildScheduler::test_evening_job_trigger tests/test_scheduler.py::TestBuildScheduler::test_digest_job_excludes_thursday -v`
Expected: FAIL — trigger hiện vẫn là `sun,mon,tue,wed,thu`.

- [ ] **Step 3: Sửa `build_scheduler`**

Trong `scheduler.py::build_scheduler`, đổi `day_of_week` của job `open_vote_evening` từ `"sun,mon,tue,wed,thu"` thành `"sun,mon,tue,wed"`:

```python
    scheduler.add_job(
        _scheduled_open_vote,
        trigger=CronTrigger(hour=evening_h, minute=evening_m, day_of_week="sun,mon,tue,wed", timezone=tz),
        args=[app, 1], id="open_vote_evening", replace_existing=True, misfire_grace_time=300,
    )
```

Và job `admin_digest` từ `"sun,mon,tue,wed,thu"` thành `"sun,mon,tue,wed"`:

```python
    scheduler.add_job(
        _scheduled_admin_digest,
        trigger=CronTrigger(hour=digest_h, minute=digest_m, day_of_week="sun,mon,tue,wed", timezone=tz),
        args=[app], id="admin_digest", replace_existing=True, misfire_grace_time=300,
    )
```

Cập nhật comment phía trên 2 job cho khớp (bỏ chữ "T5"/"thu" nếu có).

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py::TestBuildScheduler -v`
Expected: PASS toàn bộ (gồm `test_job_ids`, `test_morning_job_trigger`, `test_evening_job_passes_day_offset_one`).

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: bỏ thứ 5 khỏi job tạo vote 19h và digest 20h (T6 tạo vote 8h30)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Phân công thứ 6 — chỉ 1 người đi lấy, không trả hộp

**Files:**
- Modify: `scheduler.py::_scheduled_announce_roles` (thêm tham số `today`; nhánh T6)
- Test: `tests/test_scheduler.py` (mở rộng `FakeBot`; class `TestAnnounceRoles`)

**Interfaces:**
- Consumes: `_is_friday`; `db.pick_next_fetcher`, `db.pick_next_returner`, `db.close_daily_vote(date, picker_id, returner_id)` (returner None → chỉ bump `last_picked_at`).
- Produces: `_scheduled_announce_roles(app, today: str | None = None)` — nếu `today is None` thì tính từ giờ hiện tại; thứ 6 chỉ chọn picker, gọi `close_daily_vote(today, picker_id, None)`, tin `🛵 @X đi lấy bún đậu`.

- [ ] **Step 1: Mở rộng FakeBot + viết test thất bại**

Trong `tests/test_scheduler.py`, thêm 2 method no-op vào class `FakeBot` (để nhánh đóng poll không lỗi):

```python
    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None, **kwargs):
        pass

    async def stop_poll(self, chat_id, message_id, **kwargs):
        pass
```

Thêm class test mới (cuối file `tests/test_scheduler.py`):

```python
class TestAnnounceRoles:
    async def _setup_two_voters(self, db, date):
        await db.add_user(1, "An", "an")
        await db.add_user(2, "Binh", "binh")
        await db.create_daily_vote(date, 100, 45000, 20000)  # status='open'
        await db.toggle_vote(date, 1)
        await db.toggle_vote(date, 2)

    async def test_friday_only_picker_no_returner(self, db):
        from scheduler import _scheduled_announce_roles
        friday = "2026-01-02"
        await self._setup_two_voters(db, friday)
        app = FakeApp()
        await _scheduled_announce_roles(app, today=friday)

        daily = await db.get_daily_vote(friday)
        assert daily["status"] == "closed"
        assert daily["picker_user_id"] is not None
        assert daily["returner_user_id"] is None
        joined = " ".join(app.bot.sent_messages)
        assert "đi lấy bún đậu" in joined
        assert "trả hộp" not in joined

    async def test_non_friday_assigns_returner(self, db):
        from scheduler import _scheduled_announce_roles
        monday = "2026-01-05"
        await self._setup_two_voters(db, monday)
        app = FakeApp()
        await _scheduled_announce_roles(app, today=monday)

        daily = await db.get_daily_vote(monday)
        assert daily["returner_user_id"] is not None
        joined = " ".join(app.bot.sent_messages)
        assert "trả hộp" in joined
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestAnnounceRoles -v`
Expected: FAIL — `_scheduled_announce_roles` chưa nhận `today` (TypeError) hoặc thứ 6 vẫn gán returner.

- [ ] **Step 3: Sửa `_scheduled_announce_roles`**

Thay phần đầu hàm (chữ ký + tính `today`):

```python
async def _scheduled_announce_roles(app: Application, today: str | None = None) -> None:
    """10:30 — Đóng vote + chọn và thông báo người lấy cơm + trả hộp.
    Thứ 6 (bún đậu): chỉ chọn 1 người đi lấy, không trả hộp."""
    if today is None:
        today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    logger.info("⏰ Scheduler: announce_roles triggered for %s", today)
```

(xoá dòng `from datetime import datetime` cục bộ trong hàm — `datetime` đã import ở đầu module dòng `from datetime import datetime, timedelta`.)

Thay khối chọn người + dựng `roles_text` (từ `picker = await db.pick_next_fetcher(today)` tới hết nhánh `else: roles_text = ... "đi lấy cơm và trả hộp"`) bằng:

```python
        def _esc(s: str) -> str:
            return s.replace("_", "\\_")

        picker = await db.pick_next_fetcher(today)
        picker_mention = f"@{_esc(picker['username'])}" if picker["username"] else _esc(picker["full_name"])

        if _is_friday(today):
            # Ngày bún đậu: chỉ 1 người đi lấy, không trả hộp
            await db.close_daily_vote(today, picker["id"], None)
            roles_text = f"🛵 {picker_mention} đi lấy bún đậu"
        else:
            returner = await db.pick_next_returner(today, picker["id"])
            await db.close_daily_vote(today, picker["id"], returner["id"] if returner else None)
            if returner and returner["id"] != picker["id"]:
                returner_mention = f"@{_esc(returner['username'])}" if returner["username"] else _esc(returner["full_name"])
                roles_text = f"🛵 {picker_mention} đi lấy cơm\n📦 {returner_mention} trả hộp"
            else:
                roles_text = f"🛵 {picker_mention} đi lấy cơm và trả hộp"
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py::TestAnnounceRoles -v`
Expected: PASS cả 2 test.

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: thứ 6 chỉ phân công 1 người đi lấy bún đậu, không trả hộp

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Cột override giá/ship + `set_day_price` + `get_week_data`

**Files:**
- Modify: `database.py` (migration trong `init_db`; hàm `set_day_price`; `get_week_data`)
- Test: `tests/test_database.py` (class `TestDayPrice`)

**Interfaces:**
- Produces:
  - 2 cột nullable trên `daily_votes`: `price_override INTEGER`, `ship_fee_override INTEGER` (NULL = admin chưa nhập).
  - `set_day_price(date: str, price_override: Optional[int], ship_fee_override: Optional[int]) -> None` — tạo placeholder row nếu chưa có, set 2 cột override (None → NULL).
  - `get_week_data(...)` trả thêm key `price_override`, `ship_fee_override` cho mỗi ngày (None nếu không có row hoặc chưa nhập).

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_database.py` (cuối file):

```python
class TestDayPrice:
    async def test_set_day_price_stores_override(self, db):
        await db.set_day_price("2026-01-02", 30000, 0)
        dv = await db.get_daily_vote("2026-01-02")
        assert dv["price_override"] == 30000
        assert dv["ship_fee_override"] == 0

    async def test_set_day_price_none_clears(self, db):
        await db.set_day_price("2026-01-02", 30000, 0)
        await db.set_day_price("2026-01-02", None, None)
        dv = await db.get_daily_vote("2026-01-02")
        assert dv["price_override"] is None
        assert dv["ship_fee_override"] is None

    async def test_get_week_data_includes_override(self, db):
        await db.set_day_price("2026-01-02", 30000, 0)
        rows = await db.get_week_data(["2026-01-02"])
        assert rows[0]["price_override"] == 30000
        assert rows[0]["ship_fee_override"] == 0

    async def test_get_week_data_no_row_override_none(self, db):
        rows = await db.get_week_data(["2026-01-02"])
        assert rows[0]["price_override"] is None
        assert rows[0]["ship_fee_override"] is None
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_database.py::TestDayPrice -v`
Expected: FAIL — `AttributeError: module 'database' has no attribute 'set_day_price'` / thiếu key `price_override`.

- [ ] **Step 3: Thêm migration + `set_day_price` + sửa `get_week_data`**

Trong `database.py::init_db`, thêm 2 dòng vào danh sách `col_sql` (cuối list, trước `]`):

```python
            "ALTER TABLE daily_votes ADD COLUMN price_override INTEGER",
            "ALTER TABLE daily_votes ADD COLUMN ship_fee_override INTEGER",
```

Thêm hàm `set_day_price` (đặt ngay sau `set_menu_image`):

```python
async def set_day_price(date: str, price_override: Optional[int], ship_fee_override: Optional[int]) -> None:
    """Lưu giá/ship admin nhập tay cho 1 ngày (override). None = bỏ override, dùng giá toàn cục."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Tạo placeholder row nếu chưa có (price/ship_fee dùng default cột)
        await db.execute(
            "INSERT OR IGNORE INTO daily_votes (date, status) VALUES (?, 'none')",
            (date,),
        )
        await db.execute(
            "UPDATE daily_votes SET price_override = ?, ship_fee_override = ? WHERE date = ?",
            (price_override, ship_fee_override, date),
        )
        await db.commit()
```

Trong `get_week_data`, thêm `price_override`/`ship_fee_override` vào CẢ HAI dict trả về:

Nhánh không có row (`if not dv:`), thêm 2 key:

```python
                results.append({
                    "date": date_str,
                    "date_display": date_display,
                    "weekday": WEEKDAYS[d.weekday()],
                    "status": "none",
                    "voters": [],
                    "picker_name": None,
                    "menu_image": None,
                    "price_override": None,
                    "ship_fee_override": None,
                })
                continue
```

Nhánh có row (`results.append({...})` cuối hàm), thêm 2 key:

```python
            results.append({
                "date": date_str,
                "date_display": date_display,
                "weekday": WEEKDAYS[d.weekday()],
                "status": status,
                "voters": voters,
                "picker_name": picker_name,
                "menu_image": dv["menu_image"],
                "price_override": dv["price_override"],
                "ship_fee_override": dv["ship_fee_override"],
            })
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_database.py::TestDayPrice -v`
Expected: PASS cả 4 test.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: cột override giá/ship theo ngày + set_day_price + get_week_data

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Tạo vote ưu tiên giá override (không ghi đè giá admin)

**Files:**
- Modify: `scheduler.py::_scheduled_open_vote` (resolve giá/ship từ override)
- Test: `tests/test_scheduler.py` (class `TestOpenVotePriceOverride`)

**Interfaces:**
- Consumes: `existing = await db.get_daily_vote(target_str)` (đã có sẵn trong hàm); `existing["price_override"]`, `existing["ship_fee_override"]` (từ Task 4).
- Produces: `_scheduled_open_vote` truyền giá đã resolve (override nếu có, else toàn cục) vào `create_daily_vote`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_scheduler.py` (cuối file):

```python
class TestOpenVotePriceOverride:
    async def test_uses_price_override(self, db):
        from scheduler import _scheduled_open_vote, _target_date
        today = _target_date(0)
        await db.set_menu_image(today, "menu.jpg")
        await db.set_day_price(today, 30000, 0)
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=0)
        daily = await db.get_daily_vote(today)
        assert daily["price"] == 30000
        assert daily["ship_fee"] == 0

    async def test_no_override_uses_global(self, db):
        from scheduler import _scheduled_open_vote, _target_date
        today = _target_date(0)
        await db.set_menu_image(today, "menu.jpg")
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=0)
        daily = await db.get_daily_vote(today)
        assert daily["price"] == config.PRICE_PER_MEAL   # 45000
        assert daily["ship_fee"] == config.SHIP_FEE      # 20000
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestOpenVotePriceOverride -v`
Expected: FAIL ở `test_uses_price_override` — giá vẫn bị ghi đè thành 45000/20000.

- [ ] **Step 3: Sửa `_scheduled_open_vote`**

Trong `scheduler.py::_scheduled_open_vote`, ngay sau khối lấy giá toàn cục:

```python
        price_str = await db.get_setting("price") or str(config.PRICE_PER_MEAL)
        price = int(price_str)
        ship_fee_str = await db.get_setting("ship_fee") or str(config.SHIP_FEE)
        ship_fee = int(ship_fee_str)
```

thêm ngay bên dưới:

```python
        # Giá/ship admin nhập tay cho ngày này (override) — ưu tiên nếu có
        if existing:
            if existing["price_override"] is not None:
                price = existing["price_override"]
            if existing["ship_fee_override"] is not None:
                ship_fee = existing["ship_fee_override"]
```

(`existing` đã được fetch ở đầu hàm bằng `existing = await db.get_daily_vote(target_str)`.)

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py::TestOpenVotePriceOverride -v`
Expected: PASS cả 2 test.

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: tạo vote ưu tiên giá/ship override admin nhập, không ghi đè

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Web — ô nhập giá/ship + endpoint lưu override

**Files:**
- Modify: `web/app.py::save_menu_items_endpoint` (nhận `price`/`ship_fee`)
- Modify: `web/templates/index.html` (2 input trong form lưu món)
- Test: `tests/test_web.py` (test lưu override)

**Interfaces:**
- Consumes: `db.set_day_price(date, price_override, ship_fee_override)` (Task 4); `week_days[i].price_override`/`ship_fee_override` từ `get_week_data` (Task 4) để prefill.
- Produces: `/save-menu-items` chấp nhận form `price`, `ship_fee` (chuỗi; rỗng/không phải số → None).

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_web.py` (sau `test_save_menu_items_success`):

```python
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
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_web.py::test_save_menu_items_with_price_override tests/test_web.py::test_save_menu_items_empty_price_no_override -v`
Expected: FAIL — endpoint chưa lưu override (`price_override` vẫn None ở test 1).

- [ ] **Step 3: Sửa endpoint `save_menu_items_endpoint`**

Trong `web/app.py`, thay toàn bộ hàm `save_menu_items_endpoint` bằng:

```python
@app.post("/save-menu-items")
async def save_menu_items_endpoint(
    request: Request,
    date: str = Form(...),
    dish1: str = Form(""),
    dish2: str = Form(""),
    dish3: str = Form(""),
    dish4: str = Form(""),
    price: str = Form(""),
    ship_fee: str = Form(""),
):
    if not _is_admin(request):
        return JSONResponse({"ok": False, "error": "Không có quyền"}, status_code=403)
    dishes = [d.strip() for d in [dish1, dish2, dish3, dish4] if d.strip()]
    await db.save_menu_items(date, dishes)

    def _parse_int(s: str):
        s = s.strip()
        return int(s) if s.isdigit() else None

    await db.set_day_price(date, _parse_int(price), _parse_int(ship_fee))
    return JSONResponse({"ok": True})
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_web.py::test_save_menu_items_with_price_override tests/test_web.py::test_save_menu_items_empty_price_no_override tests/test_web.py::test_save_menu_items_success -v`
Expected: PASS cả 3 (test cũ vẫn xanh).

- [ ] **Step 5: Thêm ô input vào template**

Trong `web/templates/index.html`, trong form lưu món (sau `</div>` đóng grid 4 món, trước `<button type="submit">`), thêm:

```html
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
              <input type="number" name="price" placeholder="Giá/suất (vd 40000)"
                value="{{ day.price_override if day.price_override is not none else '' }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
              <input type="number" name="ship_fee" placeholder="Ship (để 0 nếu không)"
                value="{{ day.ship_fee_override if day.ship_fee_override is not none else '' }}"
                style="padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;min-width:0">
            </div>
```

(Form đã dùng `new FormData(event.target)` nên 2 input này tự được gửi kèm. `day` là biến lặp `week_days` chứa `price_override`/`ship_fee_override` từ Task 4.)

- [ ] **Step 6: Kiểm tra template render không lỗi**

Run: `python -m pytest tests/test_web.py -k "index or health" -v` (nếu có test render index) — nếu không có, chạy nhanh app để mắt thường kiểm tra:
`python -m uvicorn web.app:app --port 8080` → mở `http://localhost:8080`, tab "Tuần này" thấy 2 ô Giá/Ship dưới 4 ô món; nhập giá cho thứ 6, bấm Lưu → "✅ Đã lưu!". Tắt uvicorn sau khi xong.
Expected: trang render bình thường, 2 ô hiển thị, lưu OK.

- [ ] **Step 7: Commit**

```bash
git add web/app.py web/templates/index.html tests/test_web.py
git commit -m "feat: web nhập giá/ship theo ngày cho bún đậu (tab Tuần này)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Chạy full test suite + cập nhật tài liệu

**Files:**
- Modify: `CLAUDE.md` (mô tả lịch thứ 6); `C:\Users\CPU60361_LOCAL\.claude\projects\d--telegram-lunch-bot\memory\MEMORY.md` (nếu cần ghi nhớ)

- [ ] **Step 1: Chạy toàn bộ test**

Run: `python -m pytest -q`
Expected: PASS toàn bộ, không regression.

- [ ] **Step 2: Cập nhật CLAUDE.md**

Trong `CLAUDE.md`, bảng "Lịch tự động": thêm/ghi chú thứ 6 là ngày bún đậu — vote chỉ tạo 8h30 (không tạo tối T5, không digest cho T6), wording bún đậu, phân công chỉ 1 người đi lấy (không trả hộp), giá/ship admin nhập tay qua web. Sửa dòng job 19h/20h ghi rõ `day_of_week=sun,mon,tue,wed` (CN–T4, không gồm T5).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: cập nhật CLAUDE.md cho lịch thứ 6 ngày bún đậu

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Vote chỉ tạo 8h30 T6, không tạo tối T5 + không digest → Task 2 (bỏ `thu` ở 2 job); job sáng sẵn có tạo vote (đã test ở `TestScheduledMorning`). ✓
- Wording bún đậu → Task 1. ✓
- Giá/ship admin nhập tay, không ghi đè → Task 4 (cột override + set_day_price) + Task 5 (resolve khi tạo) + Task 6 (web nhập). ✓
- 1 người đi lấy, không trả hộp → Task 3. ✓
- Notify real-time admin giữ nguyên → không sửa code (spec mục 5); không có task — đúng chủ đích. ✓
- Chỉ riêng thứ 6 → mọi nhánh đều rẽ qua `_is_friday`; các ngày khác giữ hành vi (test `test_non_friday_*`). ✓

**Placeholder scan:** Không có TBD/TODO; mọi step có code/cmd cụ thể. ✓

**Type consistency:** `_is_friday(date_str)->bool`, `_open_vote_wording(day_offset, date_str=None)`, `_scheduled_announce_roles(app, today=None)`, `set_day_price(date, price_override, ship_fee_override)` dùng nhất quán giữa các task. Cột `price_override`/`ship_fee_override` đặt tên đồng nhất ở migration, `set_day_price`, `get_week_data`, `_scheduled_open_vote`, endpoint web. ✓

**Lưu ý rủi ro:** Cột `daily_votes.price`/`ship_fee` là NOT NULL — đã tránh bằng cột override nullable riêng (không đụng NULL vào price/ship). `_open_vote_wording` thêm tham số có default nên 2 test wording cũ vẫn pass.
