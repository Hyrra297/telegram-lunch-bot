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


class TestVoteNotifiesAdmin:
    async def test_notifies_admin_on_new_voter_today(self, db, monkeypatch):
        """Người mới đặt vào đúng ngày hôm nay → bot nhắn riêng admin."""
        import config
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN, _today
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        today = _today()
        await db.create_daily_vote(today, 6000, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        bot = _FakeBot()
        query = FakeCallbackQuery(message_id=6000, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), _FakeContext(bot))
        assert bot.sent == [(1001, "✅ Người Test vừa đặt cơm — tổng 1 người.")]

    async def test_no_notify_when_leaving(self, db, monkeypatch):
        """Bỏ vote (toggle off) → KHÔNG nhắn admin."""
        import config
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN, _today
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        today = _today()
        await db.create_daily_vote(today, 6001, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        await db.toggle_vote(today, 42)  # đã vote sẵn
        bot = _FakeBot()
        query = FakeCallbackQuery(message_id=6001, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), _FakeContext(bot))  # tap → rời
        assert bot.sent == []

    async def test_no_notify_when_not_today(self, db, monkeypatch):
        """Vote cho ngày mai (chưa tới ngày ăn) → KHÔNG real-time."""
        import config
        from handlers.vote import handle_vote_callback, CALLBACK_VOTE_IN
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        await db.create_daily_vote("2099-12-31", 6002, 45000, 20000)
        await db.add_user(42, "Người Test", "tester")
        bot = _FakeBot()
        query = FakeCallbackQuery(message_id=6002, user_id=42, data=CALLBACK_VOTE_IN)
        await handle_vote_callback(FakeUpdate(query), _FakeContext(bot))
        assert bot.sent == []
