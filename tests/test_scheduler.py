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
