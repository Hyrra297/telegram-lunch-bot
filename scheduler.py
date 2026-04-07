from __future__ import annotations
import logging
import pytz
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application

import config
import database as db

logger = logging.getLogger(__name__)


async def _scheduled_open_vote(app: Application) -> None:
    today_str = __import__("datetime").datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    logger.info("⏰ Scheduler: open_vote triggered for %s", today_str)

    try:
        existing = await db.get_daily_vote(today_str)
        if existing and existing["status"] in ("open", "closed"):
            logger.info("Vote already %s for %s, skipping.", existing["status"], today_str)
            return

        price_str = await db.get_setting("price") or str(config.PRICE_PER_MEAL)
        price = int(price_str)
        ship_fee_str = await db.get_setting("ship_fee") or str(config.SHIP_FEE)
        ship_fee = int(ship_fee_str)

        # Send menu photo if available
        menu_image = existing["menu_image"] if existing else None
        if menu_image:
            photo_path = Path("static/menus") / menu_image
            if photo_path.exists():
                logger.info("Sending menu photo: %s", photo_path)
                with open(photo_path, "rb") as f:
                    await app.bot.send_photo(
                        chat_id=config.CHAT_ID,
                        photo=f,
                        caption="🍽️ Thực đơn hôm nay",
                    )

        from handlers.vote import _build_keyboard, _build_vote_text
        dishes = await db.get_menu_items(today_str)
        logger.info("Dishes for %s: %s", today_str, dishes)

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
            logger.info("✅ Poll sent for %s (msg_id=%s)", today_str, poll_msg.message_id)
        else:
            msg = await app.bot.send_message(
                chat_id=config.CHAT_ID,
                text=_build_vote_text([]),
                parse_mode="Markdown",
                reply_markup=_build_keyboard(),
            )
            await db.create_daily_vote(today_str, msg.message_id, price, ship_fee)
            logger.info("✅ Inline vote sent for %s (msg_id=%s)", today_str, msg.message_id)
    except Exception:
        logger.exception("❌ open_vote failed for %s", today_str)


async def _scheduled_vote_reminder(app: Application) -> None:
    """09:30 — Nhắc nhở số người đã vote, vote vẫn mở."""
    from datetime import datetime
    today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    logger.info("⏰ Scheduler: vote_reminder triggered for %s", today)

    try:
        daily = await db.get_daily_vote(today)
        if not daily or daily["status"] != "open":
            logger.info("Vote not open for %s, skipping reminder.", today)
            return

        voters = await db.get_voters(today)
        if voters:
            text = f"⏰ Đã có *{len(voters)} người* đặt cơm. Ai chưa vote thì vote nhanh nhé!"
        else:
            text = "⏰ Chưa có ai đặt cơm hôm nay. Vote nhanh nhé!"

        await app.bot.send_message(
            chat_id=config.CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("✅ Vote reminder sent for %s, %d voters", today, len(voters))
    except Exception:
        logger.exception("❌ vote_reminder failed for %s", today)


async def _scheduled_announce_roles(app: Application) -> None:
    """10:30 — Đóng vote + chọn và thông báo người lấy cơm + trả hộp."""
    from datetime import datetime
    today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    logger.info("⏰ Scheduler: announce_roles triggered for %s", today)

    try:
        daily = await db.get_daily_vote(today)
        if not daily:
            logger.info("No vote for %s, skipping announce.", today)
            return

        # Đã chọn người rồi thì skip
        if daily.get("picker_user_id"):
            logger.info("Already assigned for %s, skipping.", today)
            return

        # Đóng vote nếu đang mở
        if daily["status"] == "open":
            # Đóng poll / keyboard trên Telegram
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
            logger.info("Vote closed for %s at announce time.", today)

        if daily["status"] not in ("open", "closed"):
            logger.info("Vote status is %s for %s, skipping.", daily["status"], today)
            return

        voters = await db.get_voters(today)
        if not voters:
            await app.bot.send_message(
                chat_id=config.CHAT_ID,
                text="📢 Hôm nay không có ai đặt cơm.",
            )
            return

        picker = await db.pick_next_fetcher(today)
        returner = await db.pick_next_returner(today, picker["id"])
        await db.close_daily_vote(today, picker["id"], returner["id"] if returner else None)

        def _esc(s: str) -> str:
            return s.replace("_", "\\_")

        picker_mention = f"@{_esc(picker['username'])}" if picker["username"] else _esc(picker["full_name"])
        if returner and returner["id"] != picker["id"]:
            returner_mention = f"@{_esc(returner['username'])}" if returner["username"] else _esc(returner["full_name"])
            roles_text = f"🛵 {picker_mention} đi lấy cơm\n📦 {returner_mention} trả hộp"
        else:
            roles_text = f"🛵 {picker_mention} đi lấy cơm và trả hộp"

        # Tính chi phí mỗi người
        price = daily.get("price") or config.PRICE_PER_MEAL
        ship_fee = daily.get("ship_fee") or config.SHIP_FEE
        cost_per_person = price + round(ship_fee / len(voters))
        await db.set_cost_per_person(today, cost_per_person)

        await app.bot.send_message(
            chat_id=config.CHAT_ID,
            text=f"📋 *Chốt sổ!* Tổng có *{len(voters)} người* đặt cơm.\n\n🍱 *Phân công hôm nay:*\n{roles_text}",
            parse_mode="Markdown",
        )
        logger.info("✅ Roles assigned for %s, picker=%s, cost=%s", today, picker["username"], cost_per_person)
    except Exception:
        logger.exception("❌ announce_roles failed for %s", today)


async def _scheduled_monthly_summary(app: Application) -> None:
    """14:00 ngày cuối tháng — gửi tổng kết tiền cơm vào nhóm."""
    from datetime import datetime
    now = datetime.now(pytz.timezone(config.TIMEZONE))

    # Kiểm tra có phải ngày cuối tháng không
    import calendar
    last_day = calendar.monthrange(now.year, now.month)[1]
    if now.day != last_day:
        return

    year_month = now.strftime("%Y-%m")
    logger.info("⏰ Scheduler: monthly_summary triggered for %s", year_month)

    try:
        rows = await db.get_monthly_summary(year_month)
        if not rows:
            return

        rows.sort(key=lambda r: r["total"], reverse=True)
        paid_ids = await db.get_paid_user_ids(year_month)

        year, month = year_month.split("-")
        header = f"📊 *Tổng kết tháng {int(month)}/{year}*\n{'─' * 28}"

        lines = []
        for i, r in enumerate(rows, 1):
            status = "✅" if r.get("user_id") in paid_ids else "❌"
            lines.append(f"{i}. {status} *{r['full_name']}*: {r['meal_count']} suất = *{r['total']:,}đ*")

        text = f"{header}\n\n" + "\n".join(lines) + f"\n{'─' * 28}\n✅ = Đã đóng  ❌ = Chưa đóng"

        await app.bot.send_message(
            chat_id=config.CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("✅ Monthly summary sent for %s", year_month)
    except Exception:
        logger.exception("❌ monthly_summary failed for %s", year_month)


def build_scheduler(app: Application) -> AsyncIOScheduler:
    tz = pytz.timezone(config.TIMEZONE)

    def _hm(t: str):
        h, m = map(int, t.split(":"))
        return h, m

    open_h, open_m = _hm(config.VOTE_OPEN_TIME)       # 08:30
    close_h, close_m = _hm(config.VOTE_CLOSE_TIME)   # 09:30
    announce_h, announce_m = _hm(config.ANNOUNCE_TIME)  # 10:30

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        _scheduled_open_vote,
        trigger=CronTrigger(hour=open_h, minute=open_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="open_vote", replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        _scheduled_vote_reminder,
        trigger=CronTrigger(hour=close_h, minute=close_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="vote_reminder", replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        _scheduled_announce_roles,
        trigger=CronTrigger(hour=announce_h, minute=announce_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="announce_roles", replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        _scheduled_monthly_summary,
        trigger=CronTrigger(hour=14, minute=0, day_of_week="mon-sun", timezone=tz),
        args=[app], id="monthly_summary", replace_existing=True, misfire_grace_time=300,
    )
    return scheduler
