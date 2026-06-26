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

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None, **kwargs):
        pass

    async def stop_poll(self, chat_id, message_id, **kwargs):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


# ── _scheduled_open_vote ──────────────────────────────────────────────────────

class TestScheduledOpenVote:
    async def test_offset_one_creates_vote_for_tomorrow(self, db):
        from scheduler import _scheduled_open_vote, _target_date
        tomorrow = _target_date(1)
        await db.set_menu_image(tomorrow, "menu.jpg")
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=1)

        daily = await db.get_daily_vote(tomorrow)
        assert daily is not None
        assert daily["status"] == "open"

    async def test_offset_one_uses_ngay_mai_wording(self, db, monkeypatch):
        import scheduler
        # Pin ngày đích là thứ 2 (không phải thứ 6) để luôn kiểm tra wording "ngày mai"
        monday = "2026-01-05"
        monkeypatch.setattr(scheduler, "_target_date", lambda day_offset=0: monday)
        await db.set_menu_image(monday, "menu.jpg")
        app = FakeApp()
        await scheduler._scheduled_open_vote(app, day_offset=1)
        # Không có món ăn → fallback inline keyboard, text dùng "ngày mai"
        assert any("Đặt cơm ngày mai" in m for m in app.bot.sent_messages)

    async def test_offset_zero_uses_hom_nay_wording(self, db):
        from scheduler import _scheduled_open_vote, _target_date
        await db.set_menu_image(_target_date(0), "menu.jpg")
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

    async def test_offset_one_poll_uses_ngay_mai_question(self, db, monkeypatch):
        import scheduler
        # Pin ngày đích là thứ 2 (không phải thứ 6) để luôn kiểm tra question "ngày mai"
        monday = "2026-01-05"
        monkeypatch.setattr(scheduler, "_target_date", lambda day_offset=0: monday)
        await db.set_menu_image(monday, "menu.jpg")
        await db.save_menu_items(monday, ["Cơm gà", "Bún bò"])
        app = FakeApp()
        await scheduler._scheduled_open_vote(app, day_offset=1)
        assert len(app.bot.sent_polls) == 1
        assert app.bot.sent_polls[0]["question"] == "🍱 Ngày mai ăn gì?"
        assert app.bot.sent_polls[0]["options"] == ["Cơm gà", "Bún bò"]

    async def test_no_menu_image_skips_and_notifies(self, db):
        """Không có ảnh thực đơn → KHÔNG tạo vote, báo riêng admin."""
        from scheduler import _scheduled_open_vote, _target_date
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=1)
        tomorrow = _target_date(1)
        assert await db.get_daily_vote(tomorrow) is None
        assert app.bot.sent_polls == []
        assert any("Chưa có ảnh thực đơn" in m for m in app.bot.sent_messages)


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
        await db.set_menu_image(today, "menu.jpg")
        app = FakeApp()
        await _scheduled_morning(app)
        daily = await db.get_daily_vote(today)
        assert daily is not None
        assert daily["status"] == "open"
        # Tạo vote cùng ngày → wording "hôm nay"
        assert any("Đặt cơm hôm nay" in m for m in app.bot.sent_messages)

    async def test_morning_no_image_notifies_no_vote(self, db):
        """08:30 không có ảnh → không tạo vote, báo riêng admin."""
        from scheduler import _scheduled_morning, _target_date
        today = _target_date(0)
        app = FakeApp()
        await _scheduled_morning(app)
        assert await db.get_daily_vote(today) is None
        assert any("Chưa có ảnh thực đơn" in m for m in app.bot.sent_messages)

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

    async def test_creates_vote_when_status_is_none(self, db):
        from scheduler import _scheduled_morning, _target_date
        today = _target_date(0)
        await db.save_menu_items(today, ["Cơm tấm"])  # tạo row placeholder status='none'
        await db.set_menu_image(today, "menu.jpg")
        app = FakeApp()
        await _scheduled_morning(app)
        daily = await db.get_daily_vote(today)
        assert daily is not None
        assert daily["status"] == "open"
        # row 'none' có sẵn món → đi nhánh poll
        assert len(app.bot.sent_polls) == 1


# ── config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_evening_open_time_default(self):
        import importlib
        import config as config_mod
        importlib.reload(config_mod)
        assert config_mod.EVENING_OPEN_TIME == "19:00"


# ── build_scheduler ───────────────────────────────────────────────────────────

class TestBuildScheduler:
    def test_job_ids(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())  # app chỉ được lưu vào args, không gọi
        ids = {j.id for j in sched.get_jobs()}
        assert ids == {"open_vote_evening", "morning", "announce_roles", "monthly_summary", "admin_digest", "friday_settle"}
        assert "vote_reminder" not in ids
        assert "open_vote" not in ids

    def test_evening_job_trigger(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        trig = str(jobs["open_vote_evening"].trigger)
        assert "hour='19'" in trig
        assert "day_of_week='sun,mon,tue,wed'" in trig
        assert "thu" not in trig

    def test_digest_job_excludes_thursday(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        trig = str(jobs["admin_digest"].trigger)
        assert "hour='20'" in trig
        assert "day_of_week='sun,mon,tue,wed'" in trig
        assert "thu" not in trig

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

    def test_friday_settle_job(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        assert "friday_settle" in jobs
        trig = str(jobs["friday_settle"].trigger)
        assert "hour='15'" in trig
        assert "day_of_week='fri'" in trig


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
        # Thứ 6: KHÔNG tính tiền lúc 10h30 (đợi job 15h)
        assert daily["cost_per_person"] is None
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
        # Ngày thường: vẫn tính tiền lúc 10h30
        assert daily["cost_per_person"] is not None
        joined = " ".join(app.bot.sent_messages)
        assert "trả hộp" in joined


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
