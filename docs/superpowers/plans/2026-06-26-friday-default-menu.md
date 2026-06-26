# Menu bún đậu mặc định cho mọi thứ 6 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mỗi thứ 6 tự động tạo vote bún đậu từ 1 template cố định (4 món + giá + ship + ảnh `fri.jpg`), admin không cần thao tác.

**Architecture:** Lưu template ở `settings.friday_template` (JSON). Hàm `apply_friday_template(date)` áp template vào ngày đó nếu chưa có món. Móc vào `_scheduled_open_vote`: thứ 6 → áp template (rồi re-fetch) trước khi check ảnh → poll bún đậu tự tạo. Override (admin set món khác) và `/skip_today` vẫn hoạt động.

**Tech Stack:** Python 3.8, python-telegram-bot, aiosqlite, APScheduler, pytest + pytest-asyncio.

## Global Constraints

- Python 3.8; `scheduler.py`/`database.py` có `from __future__ import annotations`.
- Template = JSON ở `settings.friday_template`: keys `dishes` (list tên), `prices` (list int), `ship_fee` (int), `menu_image` (str).
- `apply_friday_template` KHÔNG ghi đè nếu ngày đó đã có món (admin override thắng); return `False` nếu thiếu setting / JSON lỗi / đã có món; `True` nếu áp.
- Chỉ áp cho **thứ 6** (`_is_friday`); ngày khác không đổi hành vi.
- Test async: fixture `db` (test_database/test_scheduler). Chạy `python -m pytest` (KHÔNG `pytest` trần). Bash = Git Bash trên Windows.
- Ngày test: `2026-01-02` = thứ 6, `2026-01-05` = thứ 2.
- Commit tiếng Việt, kết thúc bằng `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Branch: `friday-default-menu` (đã tạo, đã commit spec). Baseline test: chạy `python -m pytest -q` để biết số hiện tại trước khi bắt đầu.

## File Structure

- `database.py` — thêm `import json` (nếu chưa có); thêm `apply_friday_template(date) -> bool`.
- `scheduler.py` — trong `_scheduled_open_vote`, sau early-return, nhánh thứ 6 áp template + re-fetch `existing`.
- `tests/test_database.py` — class `TestFridayTemplate`.
- `tests/test_scheduler.py` — test áp template khi tạo vote thứ 6.
- `CLAUDE.md` — ghi chú template thứ 6.

---

### Task 1: `apply_friday_template(date)` (database.py)

**Files:**
- Modify: `database.py` (thêm `import json` ở đầu nếu chưa có; thêm hàm `apply_friday_template`)
- Test: `tests/test_database.py` (class `TestFridayTemplate`)

**Interfaces:**
- Consumes: `get_setting`, `get_menu_items`, `save_menu_items`, `set_day_dish_prices`, `set_day_ship`, `set_menu_image` (đã có).
- Produces: `apply_friday_template(date: str) -> bool` — đọc `settings.friday_template` (JSON); nếu ngày đó chưa có món thì áp dishes/prices/ship/image, return `True`; ngược lại return `False`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_database.py` (cuối file):

```python
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

    async def test_returns_false_when_no_template(self, db):
        assert await db.apply_friday_template("2026-01-02") is False

    async def test_returns_false_when_bad_json(self, db):
        await db.set_setting("friday_template", "{not json")
        assert await db.apply_friday_template("2026-01-02") is False
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_database.py::TestFridayTemplate -v`
Expected: FAIL — `AttributeError: module 'database' has no attribute 'apply_friday_template'`.

- [ ] **Step 3: Thêm `apply_friday_template`**

Trong `database.py`, đảm bảo có `import json` ở đầu file (thêm dòng `import json` cạnh các import khác nếu chưa có).

Thêm hàm (đặt gần các hàm settings/menu, ví dụ sau `set_day_ship`):

```python
async def apply_friday_template(date: str) -> bool:
    """Áp menu bún đậu mặc định (settings.friday_template, JSON) vào `date`.
    Chỉ áp khi ngày đó CHƯA có món (admin override thắng).
    Trả True nếu đã áp; False nếu thiếu template / JSON lỗi / đã có món."""
    raw = await get_setting("friday_template")
    if not raw:
        return False
    try:
        tpl = json.loads(raw)
    except (ValueError, TypeError):
        return False
    dishes = tpl.get("dishes") or []
    if not dishes:
        return False
    if await get_menu_items(date):
        return False  # admin đã set món → không ghi đè
    await save_menu_items(date, dishes)
    await set_day_dish_prices(date, tpl.get("prices") or [])
    ship = tpl.get("ship_fee")
    if ship is not None:
        await set_day_ship(date, int(ship))
    image = tpl.get("menu_image")
    if image:
        await set_menu_image(date, image)
    return True
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_database.py::TestFridayTemplate -v`
Expected: PASS cả 4 test.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: apply_friday_template — áp menu bún đậu mặc định từ settings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Móc template vào tạo vote thứ 6 (scheduler.py)

**Files:**
- Modify: `scheduler.py::_scheduled_open_vote` (nhánh thứ 6 áp template + re-fetch)
- Test: `tests/test_scheduler.py` (class `TestFridayTemplateOpenVote`)

**Interfaces:**
- Consumes: `db.apply_friday_template` (Task 1); `_is_friday`; `db.get_daily_vote`.
- Produces: `_scheduled_open_vote` — khi `_is_friday(target_str)` và ngày đó chưa có món, tự áp template trước khi check ảnh → tạo poll bún đậu.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_scheduler.py` (cuối file):

```python
class TestFridayTemplateOpenVote:
    async def test_friday_applies_default_template(self, db, monkeypatch):
        import json, scheduler
        friday = "2026-01-02"
        monkeypatch.setattr(scheduler, "_target_date", lambda day_offset=0: friday)
        tpl = {"dishes": ["Bún đậu(35k)", "Bún đậu(40k)"], "prices": [35000, 40000],
               "ship_fee": 20000, "menu_image": "fri.jpg"}
        await db.set_setting("friday_template", json.dumps(tpl))
        app = FakeApp()
        await scheduler._scheduled_open_vote(app, day_offset=0)
        assert len(app.bot.sent_polls) == 1
        assert app.bot.sent_polls[0]["options"] == ["Bún đậu(35k)", "Bún đậu(40k)"]
        daily = await db.get_daily_vote(friday)
        assert daily["status"] == "open"
        assert daily["dish1_price"] == 35000

    async def test_friday_keeps_admin_menu(self, db, monkeypatch):
        import json, scheduler
        friday = "2026-01-02"
        monkeypatch.setattr(scheduler, "_target_date", lambda day_offset=0: friday)
        await db.set_setting("friday_template", json.dumps(
            {"dishes": ["Template món"], "prices": [99000], "ship_fee": 20000, "menu_image": "fri.jpg"}))
        await db.save_menu_items(friday, ["Món admin"])
        await db.set_menu_image(friday, "admin.jpg")
        app = FakeApp()
        await scheduler._scheduled_open_vote(app, day_offset=0)
        assert app.bot.sent_polls[0]["options"] == ["Món admin"]  # template KHÔNG áp

    async def test_non_friday_ignores_template(self, db, monkeypatch):
        import json, scheduler
        monday = "2026-01-05"
        monkeypatch.setattr(scheduler, "_target_date", lambda day_offset=0: monday)
        await db.set_setting("friday_template", json.dumps(
            {"dishes": ["X"], "prices": [1], "ship_fee": 0, "menu_image": "fri.jpg"}))
        await db.set_menu_image(monday, "menu.jpg")
        app = FakeApp()
        await scheduler._scheduled_open_vote(app, day_offset=0)
        assert await db.get_menu_items(monday) == []   # template không áp cho thứ 2
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestFridayTemplateOpenVote -v`
Expected: FAIL ở `test_friday_applies_default_template` — chưa áp template (không có ảnh → notify admin, không tạo poll).

- [ ] **Step 3: Sửa `_scheduled_open_vote`**

Trong `scheduler.py::_scheduled_open_vote`, ngay SAU khối early-return:

```python
        existing = await db.get_daily_vote(target_str)
        if existing and existing["status"] in ("open", "closed"):
            logger.info("Vote already %s for %s, skipping.", existing["status"], target_str)
            return
```

thêm:

```python
        # Thứ 6: áp menu bún đậu mặc định nếu chưa có món, rồi đọc lại
        if _is_friday(target_str):
            applied = await db.apply_friday_template(target_str)
            if applied:
                existing = await db.get_daily_vote(target_str)
                logger.info("Áp menu bún đậu mặc định cho %s", target_str)
```

(Phần dưới giữ nguyên: lấy price/ship toàn cục, check `existing["menu_image"]` — giờ là `fri.jpg`, gửi ảnh, `get_menu_items` → 4 món template, tạo poll.)

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py::TestFridayTemplateOpenVote tests/test_scheduler.py -q`
Expected: PASS (gồm các test open_vote cũ vẫn xanh — ngày không phải thứ 6 hoặc không có `friday_template` → không áp).

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: thứ 6 tự áp menu bún đậu mặc định khi tạo vote

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Full test + cập nhật CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Chạy full suite**

Run: `python -m pytest -q`
Expected: PASS toàn bộ, không regression.

- [ ] **Step 2: Cập nhật CLAUDE.md**

Trong `CLAUDE.md`, phần ngày bún đậu / thứ 6: ghi rõ có **template bún đậu mặc định** lưu ở `settings.friday_template` (JSON: dishes/prices/ship_fee/menu_image). Mỗi thứ 6 lúc 8h30, `_scheduled_open_vote` gọi `db.apply_friday_template(date)` áp template nếu ngày đó chưa có món (admin set món khác / `/skip_today` thì không áp). Đổi menu mặc định → cập nhật setting `friday_template` (không cần deploy). Ảnh dùng lại `fri.jpg`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: ghi chú template menu bún đậu mặc định thứ 6

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Template cố định ở settings → Task 1 (`apply_friday_template` đọc `settings.friday_template`). ✓
- Tự áp vào thứ 6 8h30, admin không cần làm gì → Task 2 (móc vào `_scheduled_open_vote`). ✓
- Override (admin set món) không bị ghi đè → Task 1 (`get_menu_items` non-empty → return False); test `test_friday_keeps_admin_menu`. ✓
- `/skip_today` vẫn skip → không thuộc task (early-return status=closed trong `_scheduled_open_vote` đã chặn; morning job cũng skip status closed) — hành vi sẵn có, đúng chủ đích. ✓
- Ảnh dùng lại fri.jpg → template `menu_image="fri.jpg"`; check ảnh pass sau khi áp. ✓
- Thiếu/lỗi template → return False, không vỡ → Task 1 (test bad_json / no_template). ✓
- Ngày thường không đổi → Task 2 (`_is_friday` gate; test `test_non_friday_ignores_template`). ✓

**Placeholder scan:** Không có TBD/TODO; mọi step có code/cmd. ✓

**Type consistency:** `apply_friday_template(date)->bool` dùng nhất quán giữa Task 1 (định nghĩa) và Task 2 (gọi). Keys JSON (`dishes`/`prices`/`ship_fee`/`menu_image`) khớp giữa test, hàm, và setup prod. ✓

**Lưu ý:** Setting `settings.friday_template` trên prod chưa được set bởi plan này — set ở bước finishing (deploy) qua `set_setting`, giá trị = menu tuần này. Template `ship_fee=20000` = ship toàn cục nên `create_daily_vote` ghi đè cùng giá (không lệch); nếu sau này đổi template ship khác global cần xử lý thêm (ngoài phạm vi).
