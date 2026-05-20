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

    async def test_offset_one_poll_uses_ngay_mai_question(self, db):
        from scheduler import _scheduled_open_vote, _target_date
        tomorrow = _target_date(1)
        await db.save_menu_items(tomorrow, ["Cơm gà", "Bún bò"])
        app = FakeApp()
        await _scheduled_open_vote(app, day_offset=1)
        assert len(app.bot.sent_polls) == 1
        assert app.bot.sent_polls[0]["question"] == "🍱 Ngày mai ăn gì?"
        assert app.bot.sent_polls[0]["options"] == ["Cơm gà", "Bún bò"]


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

    async def test_creates_vote_when_status_is_none(self, db):
        from scheduler import _scheduled_morning, _target_date
        today = _target_date(0)
        await db.save_menu_items(today, ["Cơm tấm"])  # tạo row placeholder status='none'
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
