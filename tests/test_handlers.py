"""Tests for handler helper functions (pure logic, no Telegram API calls)."""
import pytest

pytestmark = pytest.mark.asyncio


# ── handlers/vote.py ──────────────────────────────────────────────────────────

class TestBuildVoteText:
    def test_no_voters_no_menu(self):
        from handlers.vote import _build_vote_text
        text = _build_vote_text([])
        assert "Chưa có ai đặt" in text

    def test_with_voters(self):
        from handlers.vote import _build_vote_text
        voters = [{"full_name": "Nguyen A"}, {"full_name": "Tran B"}]
        text = _build_vote_text(voters)
        assert "Nguyen A" in text
        assert "Tran B" in text
        assert "2 người" in text

    def test_with_menu_description(self):
        from handlers.vote import _build_vote_text
        text = _build_vote_text([], menu_description="• Bún bò\n• Cơm gà")
        assert "Bún bò" in text
        assert "Cơm gà" in text

    def test_default_day_label_is_hom_nay(self):
        from handlers.vote import _build_vote_text
        text = _build_vote_text([])
        assert "Đặt cơm hôm nay" in text

    def test_day_label_ngay_mai(self):
        from handlers.vote import _build_vote_text
        text = _build_vote_text([], day_label="ngày mai")
        assert "Đặt cơm ngày mai" in text


class TestBuildKeyboard:
    """_build_keyboard() is the fallback inline keyboard (✅/❌).
    Dishes use native Telegram poll, not the keyboard."""

    def test_returns_checkin_buttons(self):
        from handlers.vote import _build_keyboard
        from telegram import InlineKeyboardMarkup
        kb = _build_keyboard()
        assert isinstance(kb, InlineKeyboardMarkup)
        buttons = kb.inline_keyboard[0]
        callbacks = [b.callback_data for b in buttons]
        assert "vote:in" in callbacks
        assert "vote:out" in callbacks

    def test_has_two_buttons(self):
        from handlers.vote import _build_keyboard
        kb = _build_keyboard()
        all_buttons = [b for row in kb.inline_keyboard for b in row]
        assert len(all_buttons) == 2


# ── handlers/help.py ─────────────────────────────────────────────────────────

class TestHelpText:
    # NOTE: slash commands use Markdown escaping e.g. /dong\_tien
    # so we search for the escaped form.

    def test_user_commands_present(self):
        from handlers.help import USER_COMMANDS
        assert "/tien" in USER_COMMANDS
        assert "dong" in USER_COMMANDS   # /dong\_tien (escaped)
        assert "/help" in USER_COMMANDS

    def test_admin_commands_present(self):
        from handlers.help import ADMIN_COMMANDS
        assert "summary" in ADMIN_COMMANDS  # /summary là lệnh admin
        assert "open" in ADMIN_COMMANDS   # /open\_vote
        assert "close" in ADMIN_COMMANDS  # /close\_vote
        assert "add" in ADMIN_COMMANDS    # /add\_member
        assert "reset" in ADMIN_COMMANDS  # /reset\_vote

    def test_user_and_admin_are_separate_strings(self):
        from handlers.help import USER_COMMANDS, ADMIN_COMMANDS
        # Admin block should not bleed into user block
        assert "open" not in USER_COMMANDS
        assert "summary" not in USER_COMMANDS  # /summary chỉ ở khối admin


# ── handlers/admin.py ─────────────────────────────────────────────────────────

class TestNextWorkingDay:
    def test_weekday_returns_tomorrow(self):
        from datetime import date
        from handlers.admin import _next_working_day
        # Thu 2026-06-11 -> Fri 2026-06-12
        assert _next_working_day(date(2026, 6, 11)) == date(2026, 6, 12)

    def test_friday_skips_to_monday(self):
        from datetime import date
        from handlers.admin import _next_working_day
        # Fri 2026-06-12 -> Mon 2026-06-15
        assert _next_working_day(date(2026, 6, 12)) == date(2026, 6, 15)

    def test_saturday_and_sunday_skip_to_monday(self):
        from datetime import date
        from handlers.admin import _next_working_day
        assert _next_working_day(date(2026, 6, 13)) == date(2026, 6, 15)  # Sat
        assert _next_working_day(date(2026, 6, 14)) == date(2026, 6, 15)  # Sun

    def test_result_is_never_weekend(self):
        from datetime import date, timedelta
        from handlers.admin import _next_working_day
        base = date(2026, 6, 8)  # Monday
        for i in range(14):
            assert _next_working_day(base + timedelta(days=i)).weekday() < 5


# ── handlers/payment.py ───────────────────────────────────────────────────────

class TestMonthLabel:
    def test_format(self):
        from handlers.payment import _month_label
        assert _month_label("2026-03") == "tháng 3/2026"
        assert _month_label("2026-12") == "tháng 12/2026"

    def test_strips_leading_zero(self):
        from handlers.payment import _month_label
        assert _month_label("2026-01") == "tháng 1/2026"


class TestCurrentMonth:
    def test_returns_yyyy_mm_format(self):
        from handlers.payment import _current_month
        month = _current_month()
        parts = month.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4  # YYYY
        assert len(parts[1]) == 2  # MM


class TestPreviousMonth:
    def test_returns_month_before_current(self):
        from datetime import datetime
        import pytz
        from handlers.payment import _current_month, _previous_month

        now = datetime.now(pytz.timezone("Asia/Ho_Chi_Minh"))
        prev = _previous_month()

        if now.month == 1:
            assert prev == f"{now.year - 1}-12"
        else:
            assert prev == f"{now.year}-{now.month - 1:02d}"

        # Luôn khác tháng hiện tại
        assert prev != _current_month()


class TestBillingMonth:
    """_billing_month: ngày cuối tháng → tháng hiện tại; ngày khác → tháng trước.
    Khớp với job tổng kết 14:00 (gửi bảng tháng hiện tại đúng ngày cuối tháng)."""

    def test_last_day_of_month_returns_current_month(self):
        from datetime import datetime
        from handlers.payment import _billing_month
        # 30/06/2026 là ngày cuối tháng 6 → trả tháng 6
        assert _billing_month(datetime(2026, 6, 30, 14, 11)) == "2026-06"

    def test_normal_day_returns_previous_month(self):
        from datetime import datetime
        from handlers.payment import _billing_month
        # 15/06/2026 → vẫn trỏ tháng 5 (tháng đã ăn xong)
        assert _billing_month(datetime(2026, 6, 15, 9, 0)) == "2026-05"

    def test_first_day_of_month_returns_previous_month(self):
        from datetime import datetime
        from handlers.payment import _billing_month
        # 01/07/2026 → trả tháng 6
        assert _billing_month(datetime(2026, 7, 1, 9, 0)) == "2026-06"

    def test_last_day_january_returns_january(self):
        from datetime import datetime
        from handlers.payment import _billing_month
        assert _billing_month(datetime(2026, 1, 31, 14, 0)) == "2026-01"

    def test_mid_january_returns_previous_december(self):
        from datetime import datetime
        from handlers.payment import _billing_month
        # 15/01/2026 → tháng 12/2025 (qua năm)
        assert _billing_month(datetime(2026, 1, 15, 9, 0)) == "2025-12"

    def test_last_day_february_leap_year(self):
        from datetime import datetime
        from handlers.payment import _billing_month
        # 2028 nhuận: 29/02 là ngày cuối → trả tháng 2
        assert _billing_month(datetime(2028, 2, 29, 14, 0)) == "2028-02"
        # 28/02/2028 chưa phải cuối tháng → trả tháng 1
        assert _billing_month(datetime(2028, 2, 28, 14, 0)) == "2028-01"

    def test_summary_billing_month_matches_payment(self):
        from datetime import datetime
        from handlers.summary import _billing_month as sb
        from handlers.payment import _billing_month as pb
        for d in [datetime(2026, 6, 30, 14, 0), datetime(2026, 6, 15, 9, 0),
                  datetime(2026, 1, 15, 9, 0)]:
            assert sb(d) == pb(d)


# ── handlers/vote.py — handle_vote_callback ───────────────────────────────────

class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class _FakeMessage:
    def __init__(self, message_id):
        self.message_id = message_id


class FakeCallbackQuery:
    def __init__(self, message_id, user_id, data):
        self.message = _FakeMessage(message_id)
        self.from_user = _FakeUser(user_id)
        self.data = data
        self.answers = []
        self.edited_text = None

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text=None, parse_mode=None, reply_markup=None):
        self.edited_text = text


class FakeUpdate:
    def __init__(self, callback_query):
        self.callback_query = callback_query


class TestHandleVoteCallback:
    async def test_vote_lands_on_message_date_not_today(self, db):
        """Vote tạo cho ngày khác hôm nay: phiếu phải vào đúng ngày của tin nhắn."""
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN, _today
        future = "2099-12-31"
        assert future != _today()
        await db.create_daily_vote(future, 5000, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        query = FakeCallbackQuery(message_id=5000, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), None)
        assert len(await db.get_voters(future)) == 1
        assert len(await db.get_voters(_today())) == 0

    async def test_edit_text_wording_future_date(self, db):
        """Tin nhắn vote cho ngày tương lai → text dùng 'ngày mai'."""
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN
        await db.create_daily_vote("2099-12-31", 5001, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        query = FakeCallbackQuery(message_id=5001, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), None)
        assert query.edited_text and "Đặt cơm ngày mai" in query.edited_text


class _FakeBot:
    def __init__(self):
        self.sent = []  # list[(chat_id, text)]

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


class _FakeContext:
    def __init__(self, bot):
        self.bot = bot


def _force_after_digest(monkeypatch, value=True):
    """Ép cổng thời gian _past_evening_digest trả về giá trị mong muốn."""
    import handlers.vote as votemod
    monkeypatch.setattr(votemod, "_past_evening_digest", lambda *a, **k: value)


class TestPastEveningDigest:
    """Cổng thời gian: báo real-time sau digest tối 20:00 hôm trước (ADMIN_DIGEST_TIME)."""

    def test_true_for_today_vote(self):
        """Vote hôm nay: digest tối hôm qua chắc chắn đã qua → True."""
        import handlers.vote as votemod
        from handlers.vote import _today
        assert votemod._past_evening_digest(_today()) is True

    def test_false_for_far_future_vote(self):
        """Vote ngày xa: digest tối hôm trước chưa tới → False."""
        import handlers.vote as votemod
        assert votemod._past_evening_digest("2099-12-31") is False

    def test_true_for_tomorrow_vote_after_digest_time(self, monkeypatch):
        """Vote ngày mai, digest đặt 00:00 → mốc digest (00:00 hôm nay) đã qua → True."""
        import config
        import handlers.vote as votemod
        from datetime import datetime, timedelta
        import pytz
        monkeypatch.setattr(config, "ADMIN_DIGEST_TIME", "00:00")
        tz = pytz.timezone(config.TIMEZONE)
        tomorrow = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")
        assert votemod._past_evening_digest(tomorrow) is True


class TestVoteNotifiesAdmin:
    """Đường inline keyboard (fallback, không có món)."""

    async def test_notifies_admin_on_new_voter_after_digest(self, db, monkeypatch):
        """Người mới đặt sau digest tối → nhắn riêng admin."""
        import config
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN, _today
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        _force_after_digest(monkeypatch, True)
        today = _today()
        await db.create_daily_vote(today, 6000, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        bot = _FakeBot()
        query = FakeCallbackQuery(message_id=6000, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), _FakeContext(bot))
        assert bot.sent == [(1001, "✅ Người Test vừa đặt cơm — tổng 1 người.")]

    async def test_no_notify_before_digest(self, db, monkeypatch):
        """Đặt trước digest tối 20:00 → KHÔNG báo real-time."""
        import config
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN, _today
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        _force_after_digest(monkeypatch, False)
        today = _today()
        await db.create_daily_vote(today, 6001, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        bot = _FakeBot()
        query = FakeCallbackQuery(message_id=6001, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), _FakeContext(bot))
        assert bot.sent == []

    async def test_notifies_admin_on_leaving_after_digest(self, db, monkeypatch):
        """Huỷ vote sau digest tối → báo admin với tin huỷ + số người còn lại."""
        import config
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN, _today
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        _force_after_digest(monkeypatch, True)
        today = _today()
        await db.create_daily_vote(today, 6002, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        await db.toggle_vote(today, 42)  # đã vote sẵn
        bot = _FakeBot()
        query = FakeCallbackQuery(message_id=6002, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), _FakeContext(bot))  # tap → rời
        assert bot.sent == [(1001, "❌ Người Test vừa huỷ cơm — còn 0 người.")]

    async def test_notifies_for_next_day_vote_after_digest(self, db, monkeypatch):
        """Vote cho ngày mai sau digest tối (chưa tới ngày ăn) → VẪN báo real-time."""
        import config
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN, _today
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        _force_after_digest(monkeypatch, True)
        future = "2099-12-31"
        assert future != _today()
        await db.create_daily_vote(future, 6003, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        bot = _FakeBot()
        query = FakeCallbackQuery(message_id=6003, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), _FakeContext(bot))
        assert bot.sent == [(1001, "✅ Người Test vừa đặt cơm — tổng 1 người.")]


# ── handlers/vote.py — handle_poll_answer (native poll) ───────────────────────

class _FakePollUser:
    def __init__(self, user_id, first_name="", last_name="", username=None):
        self.id = user_id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username


class _FakePollAnswer:
    def __init__(self, poll_id, user, option_ids):
        self.poll_id = poll_id
        self.user = user
        self.option_ids = option_ids


class _FakePollUpdate:
    def __init__(self, poll_answer):
        self.poll_answer = poll_answer


class TestPollAnswerNotifiesAdmin:
    """Đường native poll (có món)."""

    async def _setup_poll(self, db, message_id=7000, poll_id="pollA"):
        from handlers.vote import _today
        today = _today()
        await db.create_daily_vote(today, message_id, 45000, 20000)
        await db.set_poll_id(today, poll_id)
        await db.save_menu_items(today, ["Cơm gà", "Bún bò"])
        return today, poll_id

    async def test_poll_notifies_new_voter_after_digest(self, db, monkeypatch):
        import config
        from handlers.vote import handle_poll_answer
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        _force_after_digest(monkeypatch, True)
        _, poll_id = await self._setup_poll(db)
        bot = _FakeBot()
        user = _FakePollUser(42, first_name="Người", last_name="Test")
        update = _FakePollUpdate(_FakePollAnswer(poll_id, user, [0]))
        await handle_poll_answer(update, _FakeContext(bot))
        assert bot.sent == [(1001, "✅ Người Test vừa đặt cơm — tổng 1 người.")]

    async def test_poll_notifies_changed_dish_after_digest(self, db, monkeypatch):
        import config
        from handlers.vote import handle_poll_answer, _today
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        _force_after_digest(monkeypatch, True)
        today, poll_id = await self._setup_poll(db)
        await db.add_user(42, "Người Test", "tester")
        await db.vote_for_dish(today, 42, "Cơm gà")  # đã đặt món 0
        bot = _FakeBot()
        user = _FakePollUser(42, first_name="Người", last_name="Test", username="tester")
        update = _FakePollUpdate(_FakePollAnswer(poll_id, user, [1]))  # đổi sang món 1
        await handle_poll_answer(update, _FakeContext(bot))
        assert bot.sent == [(1001, "🔄 Người Test đổi món — tổng 1 người.")]

    async def test_poll_notifies_retract_after_digest(self, db, monkeypatch):
        import config
        from handlers.vote import handle_poll_answer, _today
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        _force_after_digest(monkeypatch, True)
        today, poll_id = await self._setup_poll(db)
        await db.add_user(42, "Người Test", "tester")
        await db.vote_for_dish(today, 42, "Cơm gà")
        bot = _FakeBot()
        user = _FakePollUser(42, first_name="Người", last_name="Test", username="tester")
        update = _FakePollUpdate(_FakePollAnswer(poll_id, user, []))  # bỏ chọn
        await handle_poll_answer(update, _FakeContext(bot))
        assert bot.sent == [(1001, "❌ Người Test vừa huỷ cơm — còn 0 người.")]

    async def test_poll_no_notify_before_digest(self, db, monkeypatch):
        import config
        from handlers.vote import handle_poll_answer
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        _force_after_digest(monkeypatch, False)
        _, poll_id = await self._setup_poll(db)
        bot = _FakeBot()
        user = _FakePollUser(42, first_name="Người", last_name="Test")
        update = _FakePollUpdate(_FakePollAnswer(poll_id, user, [0]))
        await handle_poll_answer(update, _FakeContext(bot))
        assert bot.sent == []


# ── admin_notify.py — mẫu tin ─────────────────────────────────────────────────

class TestAdminNotifyFormats:
    def test_new_voter(self):
        from admin_notify import format_new_voter
        assert format_new_voter("An", 3) == "✅ An vừa đặt cơm — tổng 3 người."

    def test_changed_dish(self):
        from admin_notify import format_changed_dish
        assert format_changed_dish("An", 3) == "🔄 An đổi món — tổng 3 người."

    def test_retracted(self):
        from admin_notify import format_retracted
        assert format_retracted("An", 2) == "❌ An vừa huỷ cơm — còn 2 người."
