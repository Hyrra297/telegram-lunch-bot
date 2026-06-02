"""Test thông báo vote riêng cho admin (admin_notify.py)."""
import config
from admin_notify import (
    format_new_voter,
    format_digest,
    notify_admins,
    notify_new_voter,
)


class FakeBot:
    def __init__(self, fail_for=None):
        self.sent = []          # list[(chat_id, text)]
        self.fail_for = fail_for or set()

    async def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.fail_for:
            raise RuntimeError("boom")
        self.sent.append((chat_id, text))


class TestFormatters:
    def test_new_voter_text(self):
        assert format_new_voter("Hưng", 3) == "✅ Hưng vừa đặt cơm — tổng 3 người."

    def test_digest_with_voters(self):
        voters = [{"full_name": "An"}, {"full_name": "Bình"}]
        text = format_digest("2026-06-03", voters)
        assert "2 người" in text
        assert "• An" in text
        assert "• Bình" in text
        assert "03/06" in text  # định dạng ngày DD/MM

    def test_digest_empty(self):
        text = format_digest("2026-06-03", [])
        assert "chưa có ai" in text.lower()
        assert "03/06" in text


class TestNotify:
    async def test_notify_admins_sends_to_all(self, monkeypatch):
        monkeypatch.setattr(config, "ADMIN_IDS", {1001, 1002})
        bot = FakeBot()
        await notify_admins(bot, "hi")
        assert {c for c, _ in bot.sent} == {1001, 1002}
        assert all(t == "hi" for _, t in bot.sent)

    async def test_notify_admins_excludes_user(self, monkeypatch):
        monkeypatch.setattr(config, "ADMIN_IDS", {1001, 1002})
        bot = FakeBot()
        await notify_admins(bot, "hi", exclude_user_id=1002)
        assert {c for c, _ in bot.sent} == {1001}

    async def test_notify_admins_one_failure_does_not_block_others(self, monkeypatch):
        monkeypatch.setattr(config, "ADMIN_IDS", {1001, 1002})
        bot = FakeBot(fail_for={1001})
        await notify_admins(bot, "hi")  # không được raise
        assert {c for c, _ in bot.sent} == {1002}

    async def test_notify_new_voter_composes_and_sends(self, monkeypatch):
        monkeypatch.setattr(config, "ADMIN_IDS", {1001})
        bot = FakeBot()
        await notify_new_voter(bot, "Nam", 5)
        assert bot.sent == [(1001, "✅ Nam vừa đặt cơm — tổng 5 người.")]
