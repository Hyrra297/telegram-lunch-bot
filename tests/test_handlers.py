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
        assert "/summary" in USER_COMMANDS
        assert "dong" in USER_COMMANDS   # /dong\_tien (escaped)
        assert "/help" in USER_COMMANDS

    def test_admin_commands_present(self):
        from handlers.help import ADMIN_COMMANDS
        assert "open" in ADMIN_COMMANDS   # /open\_vote
        assert "close" in ADMIN_COMMANDS  # /close\_vote
        assert "add" in ADMIN_COMMANDS    # /add\_member
        assert "reset" in ADMIN_COMMANDS  # /reset\_vote

    def test_user_and_admin_are_separate_strings(self):
        from handlers.help import USER_COMMANDS, ADMIN_COMMANDS
        # Admin block should not bleed into user block
        assert "open" not in USER_COMMANDS


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
