# Tạo vote từ tối hôm trước — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép tạo vote cơm trưa của một ngày từ 19:00 tối hôm trước (T3→T6), thứ Hai vẫn tạo sáng 08:30; gộp tin nhắc vote vào job sáng và bỏ job reminder 09:30.

**Architecture:** Tham số hoá `_scheduled_open_vote` bằng `day_offset` (0 = hôm nay, 1 = ngày mai) để một hàm phục vụ cả job sáng lẫn job tối. Thêm job sáng `_scheduled_morning` vừa làm lưới an toàn (tạo vote nếu job tối lỡ) vừa gửi tin nhắc nếu vote đã tồn tại. Wording ("hôm nay" / "ngày mai") chọn theo `day_offset`.

**Tech Stack:** Python 3.11, APScheduler 3.10.4, python-telegram-bot 21.6, aiosqlite, pytest + pytest-asyncio (asyncio_mode = "auto").

**Spec:** [docs/superpowers/specs/2026-05-20-evening-vote-schedule-design.md](../specs/2026-05-20-evening-vote-schedule-design.md)

---

## File Structure

| File | Trách nhiệm | Thay đổi |
|---|---|---|
| `handlers/vote.py` | Helper dựng text vote | Thêm tham số `day_label` cho `_build_vote_text` |
| `scheduler.py` | Định nghĩa các job + `build_scheduler` | Helper `_target_date`/`_open_vote_wording`; `_scheduled_open_vote(day_offset)`; thêm `_send_vote_reminder` + `_scheduled_morning`; xoá `_scheduled_vote_reminder`; rewire `build_scheduler` |
| `config.py` | Đọc `.env` | Thêm `EVENING_OPEN_TIME`, gỡ `VOTE_CLOSE_TIME` |
| `.env`, `.env.example` | Cấu hình runtime | Thêm `EVENING_OPEN_TIME=19:00`, gỡ `VOTE_CLOSE_TIME` |
| `CLAUDE.md` | Tài liệu dự án | Cập nhật bảng "Lịch tự động (scheduler)" |
| `tests/test_handlers.py` | Test helper thuần | Thêm test `day_label` |
| `tests/test_scheduler.py` | **Mới** — test scheduler | Test helper, job bodies (FakeBot), `build_scheduler` |

**Thứ tự task được thiết kế để mỗi commit giữ app chạy được.** Việc cutover (xoá job 09:30, gỡ `VOTE_CLOSE_TIME`, rewire `build_scheduler`) gom hết vào Task 6 để tránh trạng thái nửa vời.

---

## Task 1: Thêm tham số `day_label` cho `_build_vote_text`

**Files:**
- Modify: `handlers/vote.py` (hàm `_build_vote_text`, hiện ở dòng 30-39)
- Test: `tests/test_handlers.py` (lớp `TestBuildVoteText`, dòng 9-27)

- [ ] **Step 1: Viết test thất bại**

Thêm 2 method vào cuối lớp `TestBuildVoteText` trong `tests/test_handlers.py` (ngay sau `test_with_menu_description`):

```python
    def test_default_day_label_is_hom_nay(self):
        from handlers.vote import _build_vote_text
        text = _build_vote_text([])
        assert "Đặt cơm hôm nay" in text

    def test_day_label_ngay_mai(self):
        from handlers.vote import _build_vote_text
        text = _build_vote_text([], day_label="ngày mai")
        assert "Đặt cơm ngày mai" in text
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_handlers.py::TestBuildVoteText::test_day_label_ngay_mai -v`
Expected: FAIL — `_build_vote_text() got an unexpected keyword argument 'day_label'`

- [ ] **Step 3: Viết code tối thiểu**

Trong `handlers/vote.py`, thay hàm `_build_vote_text` (dòng 30-39). Đổi signature và dòng `header`:

```python
def _build_vote_text(voters: list[dict], menu_description: str = "", day_label: str = "hôm nay") -> str:
    header = f"🍱 *Đặt cơm {day_label}*"
    if menu_description:
        header += f"\n\n{menu_description}"
    if voters:
        names = "\n".join(f"  • {v['full_name']}" for v in voters)
        header += f"\n\n👥 {len(voters)} người đặt:\n{names}"
    else:
        header += "\n\nChưa có ai đặt..."
    return header
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_handlers.py::TestBuildVoteText -v`
Expected: PASS (5 test, gồm 3 cũ + 2 mới)

- [ ] **Step 5: Commit**

```bash
git add handlers/vote.py tests/test_handlers.py
git commit -m "Thêm tham số day_label cho _build_vote_text"
```

---

## Task 2: Helper `_target_date` và `_open_vote_wording`

**Files:**
- Modify: `scheduler.py` (thêm import + 2 helper, sau khối import dòng 1-12)
- Test: `tests/test_scheduler.py` (**tạo mới**)

- [ ] **Step 1: Viết test thất bại**

Tạo file mới `tests/test_scheduler.py`:

```python
"""Tests cho scheduler: helper thuần, job bodies (FakeBot), build_scheduler."""
from datetime import datetime, timedelta

import pytz

import config


# ── helper thuần ──────────────────────────────────────────────────────────────

class TestTargetDate:
    def test_offset_zero_is_today(self):
        from scheduler import _target_date
        expected = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
        assert _target_date(0) == expected

    def test_offset_one_is_tomorrow(self):
        from scheduler import _target_date
        expected = (datetime.now(pytz.timezone(config.TIMEZONE)) + timedelta(days=1)).strftime("%Y-%m-%d")
        assert _target_date(1) == expected

    def test_default_offset_is_today(self):
        from scheduler import _target_date
        expected = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
        assert _target_date() == expected


class TestOpenVoteWording:
    def test_today_wording(self):
        from scheduler import _open_vote_wording
        w = _open_vote_wording(0)
        assert w["day_label"] == "hôm nay"
        assert w["caption"] == "🍽️ Thực đơn hôm nay"
        assert w["poll_question"] == "🍱 Hôm nay ăn gì?"

    def test_tomorrow_wording(self):
        from scheduler import _open_vote_wording
        w = _open_vote_wording(1)
        assert w["day_label"] == "ngày mai"
        assert w["caption"] == "🍽️ Thực đơn ngày mai"
        assert w["poll_question"] == "🍱 Ngày mai ăn gì?"
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — `ImportError: cannot import name '_target_date' from 'scheduler'`

- [ ] **Step 3: Viết code tối thiểu**

Trong `scheduler.py`, thêm `datetime`/`timedelta` vào khối import đầu file (sau dòng `import pytz`):

```python
from datetime import datetime, timedelta
```

Rồi thêm 2 helper ngay sau dòng `logger = logging.getLogger(__name__)` (dòng 12), trước `async def _scheduled_open_vote`:

```python
def _target_date(day_offset: int = 0) -> str:
    """Ngày đích dạng YYYY-MM-DD. day_offset=0 → hôm nay, 1 → ngày mai."""
    tz = pytz.timezone(config.TIMEZONE)
    return (datetime.now(tz) + timedelta(days=day_offset)).strftime("%Y-%m-%d")


def _open_vote_wording(day_offset: int) -> dict:
    """Chữ hiển thị tuỳ vote tạo cho hôm nay hay cho ngày mai."""
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

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "Thêm helper _target_date và _open_vote_wording"
```

---

## Task 3: `_scheduled_open_vote` hỗ trợ `day_offset`

**Files:**
- Modify: `scheduler.py` (hàm `_scheduled_open_vote`, hiện ở dòng 15-68)
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_scheduler.py` — khối FakeBot dùng chung và test cho `_scheduled_open_vote`:

```python
# ── FakeBot dùng chung cho test job bodies ────────────────────────────────────

class _FakeMsg:
    def __init__(self, message_id, poll_id=None):
        self.message_id = message_id
        if poll_id is not None:
            self.poll = type("_Poll", (), {"id": poll_id})()


class FakeBot:
    def __init__(self):
        self.sent_messages = []   # list[str] — text các tin nhắn
        self.sent_polls = []      # list[dict] — {question, options}
        self.sent_photos = []     # list[str] — caption các ảnh

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append(text)
        return _FakeMsg(1001)

    async def send_poll(self, chat_id, question, options, **kwargs):
        self.sent_polls.append({"question": question, "options": options})
        return _FakeMsg(2002, poll_id="fake-poll-id")

    async def send_photo(self, chat_id, photo, caption=None, **kwargs):
        self.sent_photos.append(caption)


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


# ── _scheduled_open_vote ──────────────────────────────────────────────────────

class TestScheduledOpenVote:
    async def test_offset_one_creates_vote_for_tomorrow(self, db):
        from scheduler import _scheduled_open_vote, _target_date
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=1)

        tomorrow = _target_date(1)
        daily = await db.get_daily_vote(tomorrow)
        assert daily is not None
        assert daily["status"] == "open"

    async def test_offset_one_uses_ngay_mai_wording(self, db):
        from scheduler import _scheduled_open_vote
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=1)
        # Không có món ăn → fallback inline keyboard, text dùng "ngày mai"
        assert any("Đặt cơm ngày mai" in m for m in app.bot.sent_messages)

    async def test_offset_zero_uses_hom_nay_wording(self, db):
        from scheduler import _scheduled_open_vote
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=0)
        assert any("Đặt cơm hôm nay" in m for m in app.bot.sent_messages)

    async def test_skips_when_vote_already_open(self, db):
        from scheduler import _scheduled_open_vote, _target_date
        today = _target_date(0)
        await db.create_daily_vote(today, 999, 45000, 20000)  # status='open'
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=0)
        # Đã có vote → không gửi gì thêm
        assert app.bot.sent_messages == []
        assert app.bot.sent_polls == []
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestScheduledOpenVote -v`
Expected: FAIL — `_scheduled_open_vote()` chưa nhận `day_offset` (TypeError: unexpected keyword argument 'day_offset')

- [ ] **Step 3: Viết code tối thiểu**

Thay TOÀN BỘ hàm `_scheduled_open_vote` trong `scheduler.py` (dòng 15-68) bằng:

```python
async def _scheduled_open_vote(app: Application, day_offset: int = 0) -> None:
    """Tạo vote cho ngày đích. day_offset=0 → hôm nay, day_offset=1 → ngày mai."""
    target_str = _target_date(day_offset)
    wording = _open_vote_wording(day_offset)
    logger.info("⏰ Scheduler: open_vote triggered for %s (offset=%d)", target_str, day_offset)

    try:
        existing = await db.get_daily_vote(target_str)
        if existing and existing["status"] in ("open", "closed"):
            logger.info("Vote already %s for %s, skipping.", existing["status"], target_str)
            return

        price_str = await db.get_setting("price") or str(config.PRICE_PER_MEAL)
        price = int(price_str)
        ship_fee_str = await db.get_setting("ship_fee") or str(config.SHIP_FEE)
        ship_fee = int(ship_fee_str)

        # Send menu photo if available
        menu_image = existing["menu_image"] if existing else None
        if menu_image:
            photo_path = Path("static/menus") / menu_image
            if photo_path.exists():
                logger.info("Sending menu photo: %s", photo_path)
                with open(photo_path, "rb") as f:
                    await app.bot.send_photo(
                        chat_id=config.CHAT_ID,
                        photo=f,
                        caption=wording["caption"],
                    )

        from handlers.vote import _build_keyboard, _build_vote_text
        dishes = await db.get_menu_items(target_str)
        logger.info("Dishes for %s: %s", target_str, dishes)

        if dishes:
            poll_msg = await app.bot.send_poll(
                chat_id=config.CHAT_ID,
                question=wording["poll_question"],
                options=dishes,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            await db.create_daily_vote(target_str, poll_msg.message_id, price, ship_fee)
            await db.set_poll_id(target_str, poll_msg.poll.id)
            logger.info("✅ Poll sent for %s (msg_id=%s)", target_str, poll_msg.message_id)
        else:
            msg = await app.bot.send_message(
                chat_id=config.CHAT_ID,
                text=_build_vote_text([], day_label=wording["day_label"]),
                parse_mode="Markdown",
                reply_markup=_build_keyboard(),
            )
            await db.create_daily_vote(target_str, msg.message_id, price, ship_fee)
            logger.info("✅ Inline vote sent for %s (msg_id=%s)", target_str, msg.message_id)
    except Exception:
        logger.exception("❌ open_vote failed for %s", target_str)
```

Ghi chú: `build_scheduler` hiện gọi `_scheduled_open_vote` với `args=[app]` → `day_offset` mặc định 0 → hành vi job sáng cũ không đổi. App vẫn chạy được sau task này.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS (10 test)

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "_scheduled_open_vote: hỗ trợ day_offset để tạo vote ngày mai"
```

---

## Task 4: Job sáng gộp `_scheduled_morning` + helper `_send_vote_reminder`

**Files:**
- Modify: `scheduler.py` (thêm 2 hàm sau `_scheduled_open_vote`)
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_scheduler.py` (FakeBot/FakeApp đã định nghĩa ở Task 3, dùng lại):

```python
# ── _scheduled_morning ────────────────────────────────────────────────────────

class TestScheduledMorning:
    async def test_reminds_when_vote_already_open(self, db):
        from scheduler import _scheduled_morning, _target_date
        today = _target_date(0)
        await db.create_daily_vote(today, 555, 45000, 20000)  # status='open'
        app = FakeApp()
        await _scheduled_morning(app)
        # Gửi đúng 1 tin nhắc, không tạo poll mới
        assert len(app.bot.sent_messages) == 1
        assert "Vote nhanh" in app.bot.sent_messages[0]
        assert app.bot.sent_polls == []

    async def test_creates_vote_when_none_exists(self, db):
        from scheduler import _scheduled_morning, _target_date
        today = _target_date(0)
        app = FakeApp()
        await _scheduled_morning(app)
        daily = await db.get_daily_vote(today)
        assert daily is not None
        assert daily["status"] == "open"
        # Tạo vote cùng ngày → wording "hôm nay"
        assert any("Đặt cơm hôm nay" in m for m in app.bot.sent_messages)

    async def test_skips_when_vote_closed(self, db):
        from scheduler import _scheduled_morning, _target_date
        today = _target_date(0)
        await db.create_daily_vote(today, 777, 45000, 20000)
        await db.set_vote_closed(today)  # status='closed' (vd ngày /skip_today)
        app = FakeApp()
        await _scheduled_morning(app)
        # status='closed' → không nhắc, không tạo
        assert app.bot.sent_messages == []
        assert app.bot.sent_polls == []
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestScheduledMorning -v`
Expected: FAIL — `ImportError: cannot import name '_scheduled_morning' from 'scheduler'`

- [ ] **Step 3: Viết code tối thiểu**

Trong `scheduler.py`, thêm 2 hàm này ngay SAU hàm `_scheduled_open_vote` (trước `_scheduled_vote_reminder` hiện có):

```python
async def _send_vote_reminder(app: Application, date: str) -> None:
    """Gửi tin nhắc số người đã vote (vote vẫn mở)."""
    voters = await db.get_voters(date)
    if voters:
        text = f"⏰ Đã có *{len(voters)} người* đặt cơm. Ai chưa vote thì vote nhanh nhé!"
    else:
        text = "⏰ Chưa có ai đặt cơm hôm nay. Vote nhanh nhé!"
    await app.bot.send_message(chat_id=config.CHAT_ID, text=text, parse_mode="Markdown")
    logger.info("✅ Vote reminder sent for %s, %d voters", date, len(voters))


async def _scheduled_morning(app: Application) -> None:
    """08:30 — vote đã tạo từ tối hôm trước thì nhắc số người vote;
    chưa có thì tạo vote cho hôm nay (lưới an toàn khi job 19:00 lỡ)."""
    today = _target_date(0)
    logger.info("⏰ Scheduler: morning triggered for %s", today)

    try:
        daily = await db.get_daily_vote(today)
        if daily and daily["status"] == "open":
            await _send_vote_reminder(app, today)
        elif daily and daily["status"] == "closed":
            logger.info("Vote already closed for %s, skipping morning job.", today)
        else:
            await _scheduled_open_vote(app, day_offset=0)
    except Exception:
        logger.exception("❌ morning job failed for %s", today)
```

Ghi chú: hàm `_scheduled_vote_reminder` cũ vẫn giữ nguyên ở task này (sẽ xoá ở Task 6). App vẫn chạy được.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS (13 test)

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "Thêm job sáng gộp: nhắc vote hoặc tạo vote"
```

---

## Task 5: Thêm cấu hình `EVENING_OPEN_TIME`

**Files:**
- Modify: `config.py` (dòng 10-13)
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_scheduler.py`:

```python
# ── config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_evening_open_time_default(self):
        import importlib
        import config as config_mod
        importlib.reload(config_mod)
        assert config_mod.EVENING_OPEN_TIME == "19:00"
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestConfig -v`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'EVENING_OPEN_TIME'`

- [ ] **Step 3: Viết code tối thiểu**

Trong `config.py`, thêm dòng `EVENING_OPEN_TIME` ngay sau dòng `VOTE_CLOSE_TIME` (dòng 11). KHÔNG xoá `VOTE_CLOSE_TIME` ở task này (`build_scheduler` cũ còn dùng — sẽ xoá ở Task 6). Sau khi sửa, các dòng 10-13 thành:

```python
VOTE_OPEN_TIME: str = os.getenv("VOTE_OPEN_TIME", "08:30")    # HH:MM — job sáng (thứ 2 - thứ 6)
VOTE_CLOSE_TIME: str = os.getenv("VOTE_CLOSE_TIME", "09:30")  # HH:MM — (deprecated, xoá ở Task 6)
EVENING_OPEN_TIME: str = os.getenv("EVENING_OPEN_TIME", "19:00")  # HH:MM — tạo vote cho ngày mai (T2-T5)
ANNOUNCE_TIME: str = os.getenv("ANNOUNCE_TIME", "10:30")      # HH:MM — thông báo phân công
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py::TestConfig -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_scheduler.py
git commit -m "Thêm cấu hình EVENING_OPEN_TIME"
```

---

## Task 6: Cutover — rewire `build_scheduler`, xoá job 09:30 + `VOTE_CLOSE_TIME`

**Files:**
- Modify: `scheduler.py` (xoá `_scheduled_vote_reminder`, thay `build_scheduler`)
- Modify: `config.py` (xoá `VOTE_CLOSE_TIME`)
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_scheduler.py`:

```python
# ── build_scheduler ───────────────────────────────────────────────────────────

class TestBuildScheduler:
    def test_job_ids(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())  # app chỉ được lưu vào args, không gọi
        ids = {j.id for j in sched.get_jobs()}
        assert ids == {"open_vote_evening", "morning", "announce_roles", "monthly_summary"}
        assert "vote_reminder" not in ids
        assert "open_vote" not in ids

    def test_evening_job_trigger(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        trig = str(jobs["open_vote_evening"].trigger)
        assert "hour='19'" in trig
        assert "day_of_week='mon-thu'" in trig

    def test_morning_job_trigger(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        trig = str(jobs["morning"].trigger)
        assert "hour='8'" in trig
        assert "minute='30'" in trig
        assert "day_of_week='mon-fri'" in trig

    def test_evening_job_passes_day_offset_one(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        # args = [app, day_offset]; job tối phải truyền day_offset=1
        assert jobs["open_vote_evening"].args[1] == 1
```

- [ ] **Step 2: Chạy test để xác nhận thất bại**

Run: `python -m pytest tests/test_scheduler.py::TestBuildScheduler -v`
Expected: FAIL — hiện có job `open_vote`/`vote_reminder` nên `test_job_ids` sai (assert set mismatch).

- [ ] **Step 3a: Xoá hàm `_scheduled_vote_reminder` trong `scheduler.py`**

Xoá TOÀN BỘ hàm `_scheduled_vote_reminder` (hàm có docstring `"""09:30 — Nhắc nhở số người đã vote, vote vẫn mở."""`, dài ~26 dòng). Logic của nó đã được thay bằng `_send_vote_reminder` (Task 4).

Trước khi xoá, xác nhận không nơi nào khác dùng:
Run: `grep -rn "_scheduled_vote_reminder" --include=*.py .`
Expected: chỉ xuất hiện trong `scheduler.py` (định nghĩa hàm + lời gọi trong `build_scheduler`). Không có file khác.

- [ ] **Step 3b: Thay hàm `build_scheduler` trong `scheduler.py`**

Thay TOÀN BỘ hàm `build_scheduler` bằng:

```python
def build_scheduler(app: Application) -> AsyncIOScheduler:
    tz = pytz.timezone(config.TIMEZONE)

    def _hm(t: str):
        h, m = map(int, t.split(":"))
        return h, m

    morning_h, morning_m = _hm(config.VOTE_OPEN_TIME)      # 08:30
    evening_h, evening_m = _hm(config.EVENING_OPEN_TIME)   # 19:00
    announce_h, announce_m = _hm(config.ANNOUNCE_TIME)     # 10:30

    scheduler = AsyncIOScheduler(timezone=tz)
    # 19:00 T2-T5: tạo vote cho ngày mai (T3-T6)
    scheduler.add_job(
        _scheduled_open_vote,
        trigger=CronTrigger(hour=evening_h, minute=evening_m, day_of_week="mon-thu", timezone=tz),
        args=[app, 1], id="open_vote_evening", replace_existing=True, misfire_grace_time=300,
    )
    # 08:30 T2-T6: có vote → nhắc; chưa có → tạo vote (lưới an toàn)
    scheduler.add_job(
        _scheduled_morning,
        trigger=CronTrigger(hour=morning_h, minute=morning_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="morning", replace_existing=True, misfire_grace_time=300,
    )
    # 10:30 T2-T6: đóng vote + chốt sổ
    scheduler.add_job(
        _scheduled_announce_roles,
        trigger=CronTrigger(hour=announce_h, minute=announce_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="announce_roles", replace_existing=True, misfire_grace_time=300,
    )
    # 14:00 hằng ngày: tổng kết tháng (tự thoát nếu không phải ngày cuối tháng)
    scheduler.add_job(
        _scheduled_monthly_summary,
        trigger=CronTrigger(hour=14, minute=0, day_of_week="mon-sun", timezone=tz),
        args=[app], id="monthly_summary", replace_existing=True, misfire_grace_time=300,
    )
    return scheduler
```

- [ ] **Step 3c: Xoá `VOTE_CLOSE_TIME` trong `config.py`**

Xoá dòng `VOTE_CLOSE_TIME: str = os.getenv("VOTE_CLOSE_TIME", "09:30")  # HH:MM — (deprecated, xoá ở Task 6)`.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS (toàn bộ test scheduler, gồm 4 test `TestBuildScheduler` mới)

- [ ] **Step 5: Commit**

```bash
git add scheduler.py config.py tests/test_scheduler.py
git commit -m "Đổi lịch: tạo vote 19:00 hôm trước, gỡ reminder 9:30"
```

---

## Task 7: Cập nhật `.env`, `.env.example`, `CLAUDE.md`

**Files:**
- Modify: `.env`
- Modify: `.env.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Sửa `.env`**

Trong `.env`, thay khối (dòng ~12-15):

```
# Giờ mở/đóng vote và thông báo người lấy cơm (múi giờ Việt Nam)
VOTE_OPEN_TIME=08:30
VOTE_CLOSE_TIME=09:30
ANNOUNCE_TIME=10:30
```

thành:

```
# Giờ tạo vote và thông báo người lấy cơm (múi giờ Việt Nam)
VOTE_OPEN_TIME=08:30
EVENING_OPEN_TIME=19:00
ANNOUNCE_TIME=10:30
```

- [ ] **Step 2: Sửa `.env.example`**

Trong `.env.example`, thay khối (dòng ~4-6):

```
VOTE_OPEN_TIME=08:30
VOTE_CLOSE_TIME=10:00
ANNOUNCE_TIME=10:30
```

thành:

```
VOTE_OPEN_TIME=08:30
EVENING_OPEN_TIME=19:00
ANNOUNCE_TIME=10:30
```

- [ ] **Step 3: Sửa `CLAUDE.md`**

Đọc `CLAUDE.md`, tìm mục `## Lịch tự động (scheduler)`. Thay TOÀN BỘ mục đó (bảng + dòng "Cấu hình trong `.env`") bằng:

```markdown
## Lịch tự động (scheduler)
| Giờ | Ngày | Hành động |
|---|---|---|
| 19:00 | T2–T5 | Tạo vote cho ngày hôm sau (T3–T6), wording "ngày mai" |
| 08:30 | T2–T6 | Đã có vote → nhắc số người vote; chưa có → tạo vote (lưới an toàn) |
| 10:30 | T2–T6 | Đóng vote + chốt sổ + phân công lấy cơm/trả hộp |
| 14:00 | Cuối tháng | Gửi tổng kết tiền cơm cả tháng |

Vote T3→T6 tạo từ 19:00 tối hôm trước; vote T2 tạo sáng 08:30. Job 08:30 vừa
là lưới an toàn (tạo bù nếu job tối lỡ) vừa gửi tin nhắc nếu vote đã có.

Cấu hình trong `.env`: `VOTE_OPEN_TIME` (08:30), `EVENING_OPEN_TIME` (19:00), `ANNOUNCE_TIME` (10:30)
```

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "Cập nhật .env.example và CLAUDE.md cho lịch mới"
```

Ghi chú: `.env` chứa token thật và không được commit (`.gitignore`) — chỉ sửa file cục bộ, không `git add .env`.

---

## Task 8: Kiểm tra cuối

**Files:** không sửa code.

- [ ] **Step 1: Chạy toàn bộ test suite**

Run: `python -m pytest -v`
Expected: PASS toàn bộ (test cũ ở `test_database.py`, `test_handlers.py`, `test_web.py` + test mới ở `test_scheduler.py`). Không có test FAIL/ERROR.

- [ ] **Step 2: Kiểm tra `build_scheduler` đăng ký đúng job**

Run:
```bash
python -c "import scheduler; s = scheduler.build_scheduler(object()); [print(j.id, '|', j.trigger) for j in s.get_jobs()]"
```
Expected (4 dòng, đúng giờ/ngày):
```
open_vote_evening | cron[day_of_week='mon-thu', hour='19', minute='0']
morning | cron[day_of_week='mon-fri', hour='8', minute='30']
announce_roles | cron[day_of_week='mon-fri', hour='10', minute='30']
monthly_summary | cron[day_of_week='mon-sun', hour='14', minute='0']
```

- [ ] **Step 3: Kiểm tra bot khởi động sạch**

Dùng skill `/kill-bot` để restart bot, rồi xem log khởi động: không có traceback, scheduler start thành công, có 4 job trên. Sau khi xác nhận log sạch thì dừng bot (hoặc để chạy nếu muốn).

Lưu ý: không thể chờ tới 19:00 để test thật. Nếu muốn xác nhận hành vi ngay, admin gõ `/open_vote` trong private chat (luôn tạo vote cho hôm nay, wording "hôm nay" — không đổi) để chắc đường tạo vote thủ công vẫn hoạt động.

---

## Self-Review (đã thực hiện khi viết plan)

**Spec coverage:**
- Job 19:00 T2–T5 tạo vote ngày mai → Task 3 + Task 6.
- Job 08:30 gộp nhắc/tạo → Task 4 + Task 6.
- Xoá job `vote_reminder` 09:30 → Task 6.
- Wording "ngày mai"/"hôm nay" (3 chỗ: caption, poll, text vote) → Task 1 (`_build_vote_text`) + Task 2 (`_open_vote_wording`) + Task 3 (wiring).
- Lưới an toàn 08:30 → Task 4 (nhánh `else` của `_scheduled_morning`).
- `/open_vote` thủ công giữ "hôm nay" → mặc định `day_label="hôm nay"` (Task 1), không sửa lệnh.
- Config `EVENING_OPEN_TIME` thêm, `VOTE_CLOSE_TIME` gỡ → Task 5 + Task 6.
- Cập nhật CLAUDE.md → Task 7.

**Placeholder scan:** không có TBD/TODO; mọi step có code/command cụ thể.

**Type consistency:** `day_offset: int` xuyên suốt; `_open_vote_wording` trả dict với key `caption`/`poll_question`/`day_label` — dùng nhất quán ở Task 2 và Task 3; `_build_vote_text(..., day_label=...)` khớp giữa Task 1 và Task 3.
