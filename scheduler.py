from __future__ import annotations
import pytz
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application

import config
import database as db


async def _scheduled_open_vote(app: Application) -> None:
    today_str = __import__("datetime").datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    existing = await db.get_daily_vote(today_str)
    if existing and existing["status"] == "open":
        return  # Already opened

    price_str = await db.get_setting("price") or str(config.PRICE_PER_MEAL)
    price = int(price_str)
    ship_fee_str = await db.get_setting("ship_fee") or str(config.SHIP_FEE)
    ship_fee = int(ship_fee_str)

    # Send menu photo if available
    menu_image = existing["menu_image"] if existing else None
    if menu_image:
        photo_path = Path("static/menus") / menu_image
        if photo_path.exists():
            with open(photo_path, "rb") as f:
                await app.bot.send_photo(
                    chat_id=config.CHAT_ID,
                    photo=f,
                    caption="🍽️ Thực đơn hôm nay",
                )

    from handlers.vote import _build_keyboard, _build_vote_text
    dishes = await db.get_menu_items(today_str)

    if dishes:
        poll_msg = await app.bot.send_poll(
            chat_id=config.CHAT_ID,
            question="🍱 Hôm nay ăn gì?",
            options=dishes,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        await db.create_daily_vote(today_str, poll_msg.message_id, price, ship_fee)
        await db.set_poll_id(today_str, poll_msg.poll.id)
    else:
        msg = await app.bot.send_message(
            chat_id=config.CHAT_ID,
            text=_build_vote_text([]),
            parse_mode="Markdown",
            reply_markup=_build_keyboard(),
        )
        await db.create_daily_vote(today_str, msg.message_id, price, ship_fee)


async def _scheduled_close_and_announce(app: Application) -> None:
    """10:30 — Đóng vote + chọn và thông báo người lấy cơm + trả hộp."""
    from datetime import datetime
    today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    daily = await db.get_daily_vote(today)
    if not daily or daily["status"] != "open":
        return

    voters = await db.get_voters(today)

    # Đóng poll / keyboard
    if daily.get("poll_id") and daily.get("poll_message_id"):
        try:
            await app.bot.stop_poll(
                chat_id=config.CHAT_ID,
                message_id=daily["poll_message_id"],
            )
        except Exception:
            pass
    elif daily.get("poll_message_id"):
        try:
            await app.bot.edit_message_reply_markup(
                chat_id=config.CHAT_ID,
                message_id=daily["poll_message_id"],
                reply_markup=None,
            )
        except Exception:
            pass

    await db.set_vote_closed(today)

    if not voters:
        await app.bot.send_message(
            chat_id=config.CHAT_ID,
            text="🔒 Vote đã đóng. Hôm nay không có ai đặt cơm.",
        )
        return

    picker = await db.pick_next_fetcher(today)
    returner = await db.pick_next_returner(today, picker["id"])
    await db.close_daily_vote(today, picker["id"], returner["id"] if returner else None)

    picker_mention = f"@{picker['username']}" if picker["username"] else f"*{picker['full_name']}*"
    if returner and returner["id"] != picker["id"]:
        returner_mention = f"@{returner['username']}" if returner["username"] else f"*{returner['full_name']}*"
        roles_text = f"🛵 {picker_mention} đi lấy cơm\n📦 {returner_mention} trả hộp"
    else:
        roles_text = f"🛵 {picker_mention} đi lấy cơm và trả hộp"

    await app.bot.send_message(
        chat_id=config.CHAT_ID,
        text=f"🔒 Vote đã đóng! *{len(voters)} người* đặt cơm hôm nay.\n\n🍱 Phân công:\n{roles_text}",
        parse_mode="Markdown",
    )


async def _scheduled_daily_summary(_app) -> None:
    """12:00 — Tính chi phí mỗi người và ghi vào daily_votes.cost_per_person."""
    from datetime import datetime
    today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    daily = await db.get_daily_vote(today)
    if not daily or daily["status"] != "closed":
        return

    voters = await db.get_voters(today)
    if not voters:
        return

    price = daily.get("price") or config.PRICE_PER_MEAL
    ship_fee = daily.get("ship_fee") or config.SHIP_FEE
    cost_per_person = price + round(ship_fee / len(voters))

    await db.set_cost_per_person(today, cost_per_person)


def build_scheduler(app: Application) -> AsyncIOScheduler:
    tz = pytz.timezone(config.TIMEZONE)

    def _hm(t: str):
        h, m = map(int, t.split(":"))
        return h, m

    open_h, open_m = _hm(config.VOTE_OPEN_TIME)
    close_h, close_m = _hm(config.VOTE_CLOSE_TIME)
    summary_h, summary_m = _hm(config.SUMMARY_TIME)

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        _scheduled_open_vote,
        trigger=CronTrigger(hour=open_h, minute=open_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="open_vote", replace_existing=True,
    )
    scheduler.add_job(
        _scheduled_close_and_announce,
        trigger=CronTrigger(hour=close_h, minute=close_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="close_vote", replace_existing=True,
    )
    scheduler.add_job(
        _scheduled_daily_summary,
        trigger=CronTrigger(hour=summary_h, minute=summary_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="daily_summary", replace_existing=True,
    )
    return scheduler
