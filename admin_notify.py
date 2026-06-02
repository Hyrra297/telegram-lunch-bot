"""Thông báo vote riêng cho admin qua chat với bot (KHÔNG gửi vào nhóm).

- Digest buổi tối: tổng hợp ai đã đặt + số người.
- Real-time: báo ngay khi có người mới đặt.

Gửi tới từng id trong config.ADMIN_IDS (mỗi người 1 tin riêng).
"""
from __future__ import annotations
import logging

import config
import database as db

logger = logging.getLogger(__name__)


def _fmt_date(date: str) -> str:
    """YYYY-MM-DD → DD/MM."""
    try:
        y, m, d = date.split("-")
        return f"{d}/{m}"
    except ValueError:
        return date


def format_new_voter(name: str, count: int) -> str:
    return f"✅ {name} vừa đặt cơm — tổng {count} người."


def format_digest(date: str, voters: list) -> str:
    d = _fmt_date(date)
    if not voters:
        return f"📋 Vote ngày mai ({d}): chưa có ai đặt."
    names = "\n".join(f"  • {v['full_name']}" for v in voters)
    return f"📋 Vote ngày mai ({d}): {len(voters)} người đã đặt\n{names}"


async def notify_admins(bot, text: str, exclude_user_id=None) -> None:
    """Gửi tin riêng cho từng admin. Lỗi 1 người không chặn người khác."""
    for admin_id in config.ADMIN_IDS:
        if exclude_user_id is not None and admin_id == exclude_user_id:
            continue
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception as e:
            logger.warning("notify_admins: gửi admin %s thất bại: %s", admin_id, e)


async def notify_new_voter(bot, name: str, count: int, exclude_user_id=None) -> None:
    await notify_admins(bot, format_new_voter(name, count), exclude_user_id=exclude_user_id)


async def send_vote_digest(bot, date: str) -> None:
    voters = await db.get_voters(date)
    await notify_admins(bot, format_digest(date, voters))
