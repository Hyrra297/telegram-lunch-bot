# Friday Picker Threshold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chỉ phân công hai người đi lấy bún đậu thứ 6 khi có từ 8 người đặt; từ 1 đến 7 người chỉ phân công một người.

**Architecture:** Giữ nguyên schema và luồng phân công hiện tại. `_scheduled_announce_roles` dùng độ dài danh sách `voters` đã đọc lúc 10:30 làm số suất; người lấy thứ hai vẫn được chọn bằng `pick_next_returner` và lưu trong `returner_user_id`, nhưng chỉ khi `len(voters) >= 8`.

**Tech Stack:** Python 3.8, pytest, pytest-asyncio, python-telegram-bot 21.x, aiosqlite

## Global Constraints

- Mỗi voter tại thời điểm chốt vote 10:30 được tính là một suất.
- Thứ 6 có từ 1 đến 7 suất phải có đúng một người lấy bún đậu.
- Thứ 6 có từ 8 suất trở lên phải có hai người lấy bún đậu khác nhau.
- Người lấy thứ hai tiếp tục được lưu trong `daily_votes.returner_user_id`; không thêm migration.
- Thứ 6 không phân công trả hộp và không chốt chi phí lúc 10:30.
- Luồng thứ 2 đến thứ 5 không thay đổi.

---

## File Structure

- `tests/test_scheduler.py`: kiểm thử hồi quy hai biên 7 và 8 suất, cùng hành vi ngày thường.
- `scheduler.py`: áp ngưỡng 8 suất trong nhánh phân công thứ 6 và cập nhật mô tả/comment cho đúng hành vi.

### Task 1: Áp ngưỡng 8 suất cho hai người lấy bún đậu

**Files:**
- Modify: `tests/test_scheduler.py:322-375`
- Modify: `scheduler.py:166-241`

**Interfaces:**
- Consumes: `db.get_voters(date: str) -> list[dict]`, `db.pick_next_fetcher(date: str) -> Optional[dict]`, `db.pick_next_returner(date: str, picker_user_id: int) -> Optional[dict]`, `db.close_daily_vote(date: str, picker_user_id: int, returner_user_id: Optional[int]) -> None`.
- Produces: `_scheduled_announce_roles(app: Application, today: Optional[str] = None) -> None` với điều kiện phân công người thứ hai là ngày thứ 6 và `len(voters) >= 8`.

- [ ] **Step 1: Viết test biên 7 và 8 suất**

Trong `TestAnnounceRoles`, thay helper hai người bằng helper nhận số lượng:

```python
async def _setup_voters(self, db, date, count):
    for user_id in range(1, count + 1):
        await db.add_user(user_id, f"User {user_id}", f"user{user_id}")
    await db.create_daily_vote(date, 100, 45000, 20000)
    for user_id in range(1, count + 1):
        await db.toggle_vote(date, user_id)
```

Thay test thứ 6 cũ bằng hai test biên:

```python
async def test_friday_seven_orders_assigns_one_picker(self, db):
    from scheduler import _scheduled_announce_roles
    friday = "2026-01-02"
    await self._setup_voters(db, friday, 7)
    app = FakeApp()

    await _scheduled_announce_roles(app, today=friday)

    daily = await db.get_daily_vote(friday)
    assert daily["status"] == "closed"
    assert daily["picker_user_id"] is not None
    assert daily["returner_user_id"] is None
    assert daily["cost_per_person"] is None
    joined = " ".join(app.bot.sent_messages)
    assert "đi lấy bún đậu" in joined
    assert " và " not in joined
    assert "trả hộp" not in joined

async def test_friday_eight_orders_assigns_two_pickers(self, db):
    from scheduler import _scheduled_announce_roles
    friday = "2026-01-02"
    await self._setup_voters(db, friday, 8)
    app = FakeApp()

    await _scheduled_announce_roles(app, today=friday)

    daily = await db.get_daily_vote(friday)
    assert daily["status"] == "closed"
    assert daily["picker_user_id"] is not None
    assert daily["returner_user_id"] is not None
    assert daily["returner_user_id"] != daily["picker_user_id"]
    assert daily["cost_per_person"] is None
    joined = " ".join(app.bot.sent_messages)
    assert " và " in joined
    assert "đi lấy bún đậu" in joined
    assert "trả hộp" not in joined
```

Đổi test ngày thường sang `await self._setup_voters(db, monday, 2)`. Giữ test một voter hiện có để bảo vệ trường hợp tối thiểu.

- [ ] **Step 2: Chạy test để xác nhận trạng thái RED**

Run:

```powershell
python -m pytest tests/test_scheduler.py::TestAnnounceRoles -v
```

Expected: `test_friday_seven_orders_assigns_one_picker` FAIL vì code hiện tại điền `returner_user_id` cho mọi thứ 6 có ít nhất hai voter; test 8 suất và các test còn lại PASS.

- [ ] **Step 3: Cài đặt điều kiện tối thiểu**

Trong `scheduler.py`, cập nhật docstring và nhánh thứ 6:

```python
async def _scheduled_announce_roles(app: Application, today: str | None = None) -> None:
    """10:30 — Đóng vote + chọn và thông báo người lấy cơm + trả hộp.
    Thứ 6 (bún đậu): từ 8 suất chọn 2 người đi lấy, dưới 8 suất chọn 1 người;
    không trả hộp.
    """
```

```python
if _is_friday(today):
    # Ngày bún đậu: từ 8 suất chọn 2 người đi lấy; dưới 8 suất chọn 1 người.
    # Người thứ 2 lưu tạm vào cột returner_user_id (không dùng cho trả hộp T6).
    if len(voters) >= 8:
        picker2 = await db.pick_next_returner(today, picker["id"])
    else:
        picker2 = None

    if picker2 and picker2["id"] != picker["id"]:
        picker2_mention = f"@{_esc(picker2['username'])}" if picker2["username"] else _esc(picker2["full_name"])
        await db.close_daily_vote(today, picker["id"], picker2["id"])
        roles_text = f"🛵 {picker_mention} và {picker2_mention} đi lấy bún đậu"
    else:
        await db.close_daily_vote(today, picker["id"], None)
        roles_text = f"🛵 {picker_mention} đi lấy bún đậu"
```

- [ ] **Step 4: Chạy test scheduler để xác nhận GREEN**

Run:

```powershell
python -m pytest tests/test_scheduler.py -v
```

Expected: toàn bộ test trong `tests/test_scheduler.py` PASS, bao gồm test 7 suất, 8 suất, một suất và ngày thường.

- [ ] **Step 5: Chạy toàn bộ test suite và kiểm tra diff**

Run:

```powershell
python -m pytest -v
git diff --check
git diff -- scheduler.py tests/test_scheduler.py
```

Expected: toàn bộ test PASS; `git diff --check` không báo lỗi; diff chỉ chứa điều kiện ngưỡng, comment/docstring và test liên quan.

- [ ] **Step 6: Commit thay đổi**

```powershell
git add -- scheduler.py tests/test_scheduler.py docs/superpowers/plans/2026-07-17-friday-picker-threshold.md
git commit -m "feat: require eight Friday orders for two pickers"
```
