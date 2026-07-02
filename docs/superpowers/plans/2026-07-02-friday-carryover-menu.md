# Thứ 6 tự kế thừa menu từ thứ 6 tuần trước — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thứ 6 (bún đậu) tự copy nguyên menu/giá/ship/ảnh của thứ 6 gần nhất có món — cho cả web preview lẫn poll bot 08:30; `friday_template` chỉ còn là fallback.

**Architecture:** Thêm `get_friday_source(date)` trong `database.py` làm nguồn menu thứ 6 duy nhất (lùi tối đa 8 tuần tìm thứ 6 có món; nếu không có → parse `friday_template`). `apply_friday_template` (bot, giữ tên) và một helper preview `_apply_friday_preview` (web) đều gọi hàm này → web và bot không lệch nhau.

**Tech Stack:** Python 3.8, aiosqlite, FastAPI, Jinja2, pytest + pytest-asyncio.

## Global Constraints

- Timezone Asia/Ho_Chi_Minh; ngày dạng ISO `YYYY-MM-DD`.
- `daily_votes` có sẵn cột: `dish1..dish4`, `dish1_price..dish4_price`, `ship_fee`, `menu_image` (migration try/except ALTER trong `init_db`).
- `web/app.py` import module DB bằng alias: `import database as db`.
- Test fixture `db` (conftest.py) = module `database` với DB temp đã `init_db()`; gọi `await db.<func>(...)`.
- Chạy test: `python -m pytest <path> -v` từ thư mục `d:/telegram-lunch-bot`.
- Chỉ áp cho thứ 6; caller đảm bảo `date` là thứ 6. `weekday` do `get_week_data` trả là chuỗi `"Thứ 6"`.
- Giữ nguyên guard "admin đã set món cho thứ 6 → không ghi đè".
- KHÔNG đụng: tính tiền, snapshot 15h (`friday_settle`), real-time notify, luồng T2–T5.

---

### Task 1: `get_friday_template` + `get_friday_source` trong database.py

**Files:**
- Modify: `database.py` (import dòng 2; thêm 2 hàm ngay TRƯỚC `apply_friday_template` ở dòng 305)
- Test: `tests/test_database.py` (thêm class `TestFridaySource`)

**Interfaces:**
- Consumes: `get_setting(key)`, `get_daily_vote(date)` (trả `dict` gồm các cột `daily_votes`).
- Produces:
  - `async def get_friday_template() -> Optional[dict]` → `{dishes:list, prices:list, ship_fee:int|None, menu_image:str|None}` hoặc `None`.
  - `async def get_friday_source(date: str) -> Optional[dict]` → cùng shape hoặc `None`.

- [ ] **Step 1: Thêm `timedelta` vào import**

Trong `database.py` dòng 2, đổi:
```python
from datetime import date as dt_date
```
thành:
```python
from datetime import date as dt_date, timedelta
```

- [ ] **Step 2: Viết failing tests**

Thêm vào cuối `tests/test_database.py`:
```python
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
```

- [ ] **Step 3: Chạy test — kỳ vọng FAIL**

Run: `python -m pytest tests/test_database.py::TestFridaySource -v`
Expected: FAIL — `AttributeError: module 'database' has no attribute 'get_friday_source'`.

- [ ] **Step 4: Cài đặt 2 hàm**

Thêm vào `database.py` ngay TRƯỚC `async def apply_friday_template` (dòng 305):
```python
async def get_friday_template() -> Optional[dict]:
    """Parse settings.friday_template (JSON) → dict hoặc None (thiếu/hỏng/không có món)."""
    raw = await get_setting("friday_template")
    if not raw:
        return None
    try:
        tpl = json.loads(raw)
    except (ValueError, TypeError):
        return None
    dishes = tpl.get("dishes") or []
    if not dishes:
        return None
    return {
        "dishes": list(dishes),
        "prices": list(tpl.get("prices") or []),
        "ship_fee": tpl.get("ship_fee"),
        "menu_image": tpl.get("menu_image"),
    }


async def get_friday_source(date: str) -> Optional[dict]:
    """Menu bún đậu cho `date` (giả định là thứ 6): ưu tiên thứ 6 gần nhất TRƯỚC
    `date` có món (copy dishes/prices/ship/ảnh); nếu không có → friday_template.
    Ghép cặp (dishN, dishN_price) theo slot rồi lọc slot món rỗng để giá khỏi lệch.
    Trả {dishes, prices, ship_fee, menu_image} hoặc None."""
    d = dt_date.fromisoformat(date)
    for k in range(1, 9):  # lùi tối đa 8 tuần → luôn trúng thứ 6
        cand = (d - timedelta(days=7 * k)).isoformat()
        row = await get_daily_vote(cand)
        if row and row.get("dish1"):
            pairs = [
                (row[f"dish{i}"], row[f"dish{i}_price"])
                for i in range(1, 5)
                if row.get(f"dish{i}")
            ]
            return {
                "dishes": [dish for dish, _ in pairs],
                "prices": [price for _, price in pairs],
                "ship_fee": row.get("ship_fee"),
                "menu_image": row.get("menu_image"),
            }
    return await get_friday_template()
```

- [ ] **Step 5: Chạy test — kỳ vọng PASS**

Run: `python -m pytest tests/test_database.py::TestFridaySource -v`
Expected: PASS (5 test).

- [ ] **Step 6: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: get_friday_source — copy menu thứ 6 gần nhất, fallback template

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `apply_friday_template` dùng `get_friday_source`

**Files:**
- Modify: `database.py:305-329` (thân hàm `apply_friday_template`)
- Test: `tests/test_database.py` (thêm 1 test carryover vào class `TestFridayTemplate` sẵn có, dòng ~468)

**Interfaces:**
- Consumes: `get_friday_source(date)` (Task 1), `get_menu_items`, `save_menu_items`, `set_day_dish_prices`, `set_day_ship`, `set_menu_image`.
- Produces: `apply_friday_template(date) -> bool` giữ nguyên chữ ký (scheduler.py:65 gọi).

- [ ] **Step 1: Viết failing test**

Thêm vào class `TestFridayTemplate` trong `tests/test_database.py`:
```python
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
```

- [ ] **Step 2: Chạy test — kỳ vọng FAIL**

Run: `python -m pytest "tests/test_database.py::TestFridayTemplate::test_apply_copies_previous_friday_not_template" -v`
Expected: FAIL — hiện tại `apply_friday_template` chỉ đọc template ("TPL"), nên `get_menu_items` trả `["TPL"]` ≠ `["Prev1","Prev2"]`.

- [ ] **Step 3: Đổi thân `apply_friday_template`**

Thay toàn bộ hàm `apply_friday_template` (dòng 305–329) bằng:
```python
async def apply_friday_template(date: str) -> bool:
    """Áp menu bún đậu cho thứ 6 (`date`): ưu tiên copy thứ 6 gần nhất có món,
    fallback settings.friday_template (xem get_friday_source). Chỉ áp khi ngày đó
    CHƯA có món (admin override thắng). Trả True nếu đã áp; False nếu đã có món /
    không có nguồn."""
    if await get_menu_items(date):
        return False  # admin đã set món → không ghi đè
    src = await get_friday_source(date)
    if not src or not src.get("dishes"):
        return False
    await save_menu_items(date, src["dishes"])
    await set_day_dish_prices(date, src.get("prices") or [])
    ship = src.get("ship_fee")
    if ship is not None:
        await set_day_ship(date, int(ship))
    image = src.get("menu_image")
    if image:
        await set_menu_image(date, image)
    return True
```

- [ ] **Step 4: Chạy test — kỳ vọng PASS (mới + toàn bộ cũ)**

Run: `python -m pytest tests/test_database.py tests/test_scheduler.py -v`
Expected: PASS toàn bộ. Test cũ (`TestFridayTemplate`, `TestFridayTemplateOpenVote`) vẫn xanh vì DB test không có thứ 6 trước → `get_friday_source` fallback template → hành vi như cũ.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: apply_friday_template ưu tiên copy thứ 6 trước (template = fallback)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Web preview thứ 6 + nhãn

**Files:**
- Modify: `web/app.py` (thêm helper `_apply_friday_preview`; gọi trong route `index` sau dòng 120)
- Modify: `web/templates/index.html` (nhãn preview quanh badge trạng thái, sau dòng 503)
- Test: `tests/test_web.py` (thêm 2 test helper)

**Interfaces:**
- Consumes: `db.get_friday_source(date)` (Task 1); `week_days` (list dict từ `get_week_data`, có keys `weekday,date,dish1_price..dish4_price,ship_fee,menu_image,status`); `week_menu` (dict `date -> list[str]` pad 4).
- Produces: `async def _apply_friday_preview(week_days, week_menu) -> None` (mutate tại chỗ; set `day["is_template_preview"]=True` khi overlay).

- [ ] **Step 1: Viết failing tests**

Thêm vào `tests/test_web.py`:
```python
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
        "dish4_price": None, "ship_fee": None, "menu_image": None,
    }]
    week_menu = {"2026-07-03": ["", "", "", ""]}
    await _apply_friday_preview(week_days, week_menu)
    assert week_menu["2026-07-03"][:2] == ["Bún đậu(35k)", "Bún đậu(40k)"]
    assert week_days[0]["dish1_price"] == 35000
    assert week_days[0]["dish2_price"] == 40000
    assert week_days[0]["ship_fee"] == 20000
    assert week_days[0]["menu_image"] == "fri.jpg"
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
```

- [ ] **Step 2: Chạy test — kỳ vọng FAIL**

Run: `python -m pytest tests/test_web.py -k friday_preview -v`
Expected: FAIL — `ImportError: cannot import name '_apply_friday_preview' from 'web.app'`.

- [ ] **Step 3: Thêm helper vào `web/app.py`**

Thêm hàm này ngay TRƯỚC `@app.get("/", ...)` (dòng 103):
```python
async def _apply_friday_preview(week_days: list, week_menu: dict) -> None:
    """Overlay menu bún đậu (thứ 6 gần nhất / template) vào ô Thứ 6 chưa có món.
    Chỉ để HIỂN THỊ preview trên web — không ghi DB. Mutate tại chỗ."""
    for day in week_days:
        if day.get("weekday") != "Thứ 6":
            continue
        date = day["date"]
        if any(week_menu.get(date, [])):
            continue  # thứ 6 đã có món (admin set / đã materialize) → không preview
        src = await db.get_friday_source(date)
        if not src or not src.get("dishes"):
            continue
        dishes = (list(src["dishes"]) + ["", "", "", ""])[:4]
        prices = (list(src.get("prices") or []) + [None, None, None, None])[:4]
        week_menu[date] = dishes
        (day["dish1_price"], day["dish2_price"],
         day["dish3_price"], day["dish4_price"]) = prices
        day["ship_fee"] = src.get("ship_fee")
        day["menu_image"] = src.get("menu_image")
        day["is_template_preview"] = True
```

- [ ] **Step 4: Gọi helper trong route `index`**

Trong `web/app.py`, ngay SAU vòng lặp build `week_menu` (sau dòng 120 `week_menu[d] = items + [""] * (4 - len(items))`), thêm:
```python
    await _apply_friday_preview(week_days, week_menu)
```

- [ ] **Step 5: Thêm nhãn preview vào `index.html`**

Trong `web/templates/index.html`, ngay SAU block badge trạng thái (sau dòng 503 `{% endif %}` của `day.status`), thêm:
```html
          {% if day.is_template_preview %}
            <span class="status-badge" style="background:#fff7ed;color:#c2410c">🍜 Bún đậu (theo tuần trước)</span>
          {% endif %}
```

- [ ] **Step 6: Chạy test — kỳ vọng PASS**

Run: `python -m pytest tests/test_web.py -v`
Expected: PASS toàn bộ (2 test mới + smoke `test_index_renders_ok`, `test_price_inputs_only_on_friday` vẫn xanh).

- [ ] **Step 7: Commit**

```bash
git add web/app.py web/templates/index.html tests/test_web.py
git commit -m "feat: web tab Tuần này preview menu bún đậu thứ 6 từ tuần trước

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Cập nhật CLAUDE.md + verify toàn bộ

**Files:**
- Modify: `CLAUDE.md` (đoạn "Template bún đậu mặc định")

- [ ] **Step 1: Cập nhật CLAUDE.md**

Tìm đoạn bắt đầu bằng `**Template bún đậu mặc định**:` trong `CLAUDE.md`. Thêm/điều chỉnh để phản ánh cơ chế mới. Chèn câu sau vào cuối đoạn đó:
```
Từ 2026-07-02: nguồn menu thứ 6 ưu tiên **copy nguyên thứ 6 gần nhất có món** (`get_friday_source(date)` — lùi tối đa 8 tuần), `friday_template` chỉ còn là **fallback** khi chưa từng có thứ 6 nào có món. Web tab "Tuần này" cũng preview thứ 6 sắp tới bằng chính nguồn này (`_apply_friday_preview`) nên hiện sẵn món/giá/ảnh cả tuần, kèm nhãn "🍜 Bún đậu (theo tuần trước)". Sửa menu một thứ 6 → thứ 6 sau tự kế thừa.
```

- [ ] **Step 2: Chạy toàn bộ test suite**

Run: `python -m pytest -v`
Expected: PASS toàn bộ (không regression).

- [ ] **Step 3: Verify thủ công web local**

Run:
```bash
python -c "import sqlite3" && echo ok
python -m uvicorn web.app:app --port 8080
```
Mở `http://localhost:8080` (đăng nhập admin) → tab "Tuần này". Nếu DB local có thứ 6 trước có món (hoặc `friday_template`) → cột Thứ 6 hiện sẵn món/giá/ảnh + nhãn "🍜 Bún đậu (theo tuần trước)". Dừng uvicorn (Ctrl+C).

Ghi chú: DB local hiện đang cũ (thiếu cột `dish1_price`) — nếu cần verify sát prod, dùng skill `verify` / seed một thứ 6 mẫu, hoặc chạy trên nhóm test trước khi deploy (theo memory [[preview-changes-test-group]]).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: cơ chế thứ 6 copy menu tuần trước (get_friday_source)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Mục tiêu 1 (thứ 6 kế thừa thứ 6 trước) → Task 1 `get_friday_source`. ✓
- Mục tiêu 2 (cả web + bot dùng chung nguồn) → Task 2 (bot) + Task 3 (web). ✓
- Mục tiêu 3 (template = fallback) → Task 1 nhánh cuối + Task 2. ✓
- Mục tiêu 4 (không đụng tính tiền/snapshot/notify/T2–T5) → không task nào chạm; nhãn preview chỉ thêm khi `is_template_preview`. ✓
- Ghép cặp giá/món tránh lệch → Task 1 Step 4 (pairs). ✓
- Nhãn preview UI → Task 3 Step 5. ✓
- Test carryover + fallback + skip-empty → Task 1/2/3. ✓

**Placeholder scan:** Không có TBD/TODO; mọi step có code/command cụ thể. ✓

**Type consistency:** `get_friday_source`/`get_friday_template` trả cùng shape `{dishes,prices,ship_fee,menu_image}`; `apply_friday_template(date)->bool` giữ chữ ký (scheduler.py:65); `_apply_friday_preview(week_days, week_menu)` khớp keys `get_week_data` trả (`weekday="Thứ 6"`, `dish1_price..4`, `ship_fee`, `menu_image`). ✓
