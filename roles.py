"""Luật chốt sổ dùng chung cho mọi đường đóng vote: job 10:30, lệnh /close_vote
và nút 🔒 Đóng vote dưới poll. Giữ ở một chỗ để ba đường không lệch nhau."""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

import config
import database as db

logger = logging.getLogger(__name__)


def is_friday(date_str: str) -> bool:
    """True nếu date_str (YYYY-MM-DD) là thứ 6 — ngày bún đậu."""
    return datetime.strptime(date_str, "%Y-%m-%d").weekday() == 4


def meal_name(date_str: str) -> str:
    return "bún đậu" if is_friday(date_str) else "cơm"


def cost_per_person(daily: dict, voter_count: int) -> int:
    """Tiền mỗi người: giá suất + ship chia đều.
    Ngày cơm tòa nhà / freeship → không cộng ship."""
    price = daily.get("price") or config.PRICE_PER_MEAL
    if daily.get("building_order") or daily.get("freeship"):
        return price
    ship_fee = daily.get("ship_fee") or config.SHIP_FEE
    return price + round(ship_fee / voter_count)


def _esc(s: str) -> str:
    return s.replace("_", "\\_")


def _mention(user: dict) -> str:
    return f"@{_esc(user['username'])}" if user["username"] else _esc(user["full_name"])


async def assign_and_settle(date: str, daily: dict, voters: list) -> Optional[str]:
    """Phân công người lấy/trả + khoá tiền theo loại ngày.

    Trả về dòng phân công để ghép vào tin nhắn, hoặc None nếu ngày cơm tòa nhà
    (không phân công ai). Quy tắc:
    - Cơm tòa nhà: không phân công, không tính ship, round-robin giữ nguyên
    - Thứ 6 (bún đậu): luôn 1 người đi lấy, không trả hộp, tiền đợi job 15:00
    - Ngày thường: 1 người lấy + 1 người trả hộp
    """
    # Thứ 6 (bún đậu) tính tiền theo món ở job 15:00 — không chốt tiền tại đây
    if not is_friday(date):
        await db.set_cost_per_person(date, cost_per_person(daily, len(voters)))

    if daily.get("building_order"):
        await db.set_vote_closed(date)
        logger.info("Building-order day %s: closed, no roles assigned.", date)
        return None

    picker = await db.pick_next_fetcher(date)
    picker_mention = _mention(picker)

    if is_friday(date):
        await db.close_daily_vote(date, picker["id"], None)
        return f"🛵 {picker_mention} đi lấy bún đậu"

    returner = await db.pick_next_returner(date, picker["id"])
    await db.close_daily_vote(date, picker["id"], returner["id"] if returner else None)
    if returner and returner["id"] != picker["id"]:
        return f"🛵 {picker_mention} đi lấy cơm\n📦 {_mention(returner)} trả hộp"
    return f"🛵 {picker_mention} đi lấy cơm và trả hộp"
