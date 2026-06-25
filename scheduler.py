from __future__ import annotations
import logging
import pytz
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application

import config
import database as db
from image_summary import render_summary_image
from admin_notify import send_vote_digest, notify_admins

logger = logging.getLogger(__name__)


def _target_date(day_offset: int = 0) -> str:
    """Ngày đích dạng YYYY-MM-DD. day_offset=0 → hôm nay, 1 → ngày mai."""
    tz = pytz.timezone(config.TIMEZONE)
    return (datetime.now(tz) + timedelta(days=day_offset)).strftime("%Y-%m-%d")


def _is_friday(date_str: str) -> bool:
    """True nếu date_str (YYYY-MM-DD) là thứ 6."""
    return datetime.strptime(date_str, "%Y-%m-%d").weekday() == 4


def _open_vote_wording(day_offset: int, date_str: str | None = None) -> dict:
    """Chữ hiển thị tuỳ vote tạo cho hôm nay hay ngày mai; thứ 6 dùng wording bún đậu."""
    if date_str and _is_friday(date_str):
        return {
            "caption": "🍜 Thực đơn bún đậu hôm nay",
            "poll_question": "🥢 Hôm nay ăn bún đậu gì?",
            "day_label": "hôm nay",
        }
    if day_offset >= 1:
        return {
            "caption": "🍽️ Thực đơn ngày mai",
            "poll_question": "🍱 Ngày mai ăn gì?",
            "day_label": "ngày mai",
        }
    return {
        "caption": "🍽️ Thực đơn hôm nay",
        "poll_question": "🍱 Hôm nay ăn gì?",
        "day_label": "hôm nay",
    }


async def _scheduled_open_vote(app: Application, day_offset: int = 0) -> None:
    """Tạo vote cho ngày đích. day_offset=0 → hôm nay, day_offset=1 → ngày mai."""
    target_str = _target_date(day_offset)
    wording = _open_vote_wording(day_offset, target_str)
    logger.info("⏰ Scheduler: open_vote triggered for %s (offset=%d)", target_str, day_offset)

    try:
        existing = await db.get_daily_vote(target_str)
        if existing and existing["status"] in ("open", "closed"):
            logger.info("Vote already %s for %s, skipping.", existing["status"], target_str)
            return

        price_str = await db.get_setting("price") or str(config.PRICE_PER_MEAL)
        price = int(price_str)
        ship_fee_str = await db.get_setting("ship_fee") or str(config.SHIP_FEE)
        ship_fee = int(ship_fee_str)

        # Giá/ship admin nhập tay cho ngày này (override) — ưu tiên nếu có
        if existing:
            if existing["price_override"] is not None:
                price = existing["price_override"]
            if existing["ship_fee_override"] is not None:
                ship_fee = existing["ship_fee_override"]

        # Bắt buộc có ảnh thực đơn mới tạo vote — thiếu thì báo riêng admin
        menu_image = existing["menu_image"] if existing else None
        if not menu_image:
            await notify_admins(
                app.bot,
                f"⚠️ Chưa có ảnh thực đơn cho {wording['day_label']} ({target_str}) — "
                f"bot chưa tạo vote. Hãy upload menu để mở vote nhé!",
            )
            logger.info("No menu image for %s — skip vote, admin notified.", target_str)
            return

        # Send menu photo if available
        if menu_image:
            photo_path = Path("static/menus") / menu_image
            if photo_path.exists():
                logger.info("Sending menu photo: %s", photo_path)
                with open(photo_path, "rb") as f:
                    await app.bot.send_photo(
                        chat_id=config.CHAT_ID,
                        photo=f,
                        caption=wording["caption"],
                    )

        from handlers.vote import _build_keyboard, _build_vote_text
        dishes = await db.get_menu_items(target_str)
        logger.info("Dishes for %s: %s", target_str, dishes)

        if dishes:
            poll_msg = await app.bot.send_poll(
                chat_id=config.CHAT_ID,
                question=wording["poll_question"],
                options=dishes,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            await db.create_daily_vote(target_str, poll_msg.message_id, price, ship_fee)
            await db.set_poll_id(target_str, poll_msg.poll.id)
            logger.info("✅ Poll sent for %s (msg_id=%s)", target_str, poll_msg.message_id)
        else:
            msg = await app.bot.send_message(
                chat_id=config.CHAT_ID,
                text=_build_vote_text([], day_label=wording["day_label"]),
                parse_mode="Markdown",
                reply_markup=_build_keyboard(),
            )
            await db.create_daily_vote(target_str, msg.message_id, price, ship_fee)
            logger.info("✅ Inline vote sent for %s (msg_id=%s)", target_str, msg.message_id)
    except Exception:
        logger.exception("❌ open_vote failed for %s", target_str)


async def _send_vote_reminder(app: Application, date: str) -> None:
    """Gửi tin nhắc số người đã vote (vote vẫn mở)."""
    voters = await db.get_voters(date)
    if voters:
        text = f"⏰ Đã có *{len(voters)} người* đặt cơm. Ai chưa vote thì vote nhanh nhé!"
    else:
        text = "⏰ Chưa có ai đặt cơm hôm nay. Vote nhanh nhé!"
    await app.bot.send_message(chat_id=config.CHAT_ID, text=text, parse_mode="Markdown")
    logger.info("✅ Vote reminder sent for %s, %d voters", date, len(voters))


async def _scheduled_morning(app: Application) -> None:
    """08:30 — vote đã tạo từ tối hôm trước thì nhắc số người vote;
    chưa có thì tạo vote cho hôm nay (lưới an toàn khi job 19:00 lỡ)."""
    today = _target_date(0)
    logger.info("⏰ Scheduler: morning triggered for %s", today)

    try:
        daily = await db.get_daily_vote(today)
        if daily and daily["status"] == "open":
            await _send_vote_reminder(app, today)
        elif daily and daily["status"] == "closed":
            logger.info("Vote already closed for %s, skipping morning job.", today)
        else:
            await _scheduled_open_vote(app, day_offset=0)
    except Exception:
        logger.exception("❌ morning job failed for %s", today)


async def _scheduled_announce_roles(app: Application, today: str | None = None) -> None:
    """10:30 — Đóng vote + chọn và thông báo người lấy cơm + trả hộp.
    Thứ 6 (bún đậu): chỉ chọn 1 người đi lấy, không trả hộp."""
    if today is None:
        today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    logger.info("⏰ Scheduler: announce_roles triggered for %s", today)

    try:
        daily = await db.get_daily_vote(today)
        if not daily:
            logger.info("No vote for %s, skipping announce.", today)
            return

        # Ngày đã skip (status=closed + chưa từng có poll) → bỏ qua, không gửi gì
        if daily["status"] == "closed" and not daily.get("poll_message_id"):
            logger.info("Day %s was skipped (no poll), silent return.", today)
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

        def _esc(s: str) -> str:
            return s.replace("_", "\\_")

        picker = await db.pick_next_fetcher(today)
        picker_mention = f"@{_esc(picker['username'])}" if picker["username"] else _esc(picker["full_name"])

        if _is_friday(today):
            # Ngày bún đậu: chỉ 1 người đi lấy, không trả hộp
            await db.close_daily_vote(today, picker["id"], None)
            roles_text = f"🛵 {picker_mention} đi lấy bún đậu"
        else:
            returner = await db.pick_next_returner(today, picker["id"])
            await db.close_daily_vote(today, picker["id"], returner["id"] if returner else None)
            if returner and returner["id"] != picker["id"]:
                returner_mention = f"@{_esc(returner['username'])}" if returner["username"] else _esc(returner["full_name"])
                roles_text = f"🛵 {picker_mention} đi lấy cơm\n📦 {returner_mention} trả hộp"
            else:
                roles_text = f"🛵 {picker_mention} đi lấy cơm và trả hộp"

        # Tính chi phí mỗi người — thứ 6 (bún đậu) đợi job 15h, KHÔNG tính lúc 10h30
        if not _is_friday(today):
            price = daily.get("price") or config.PRICE_PER_MEAL
            ship_fee = daily.get("ship_fee") or config.SHIP_FEE
            cost_per_person = price + round(ship_fee / len(voters))
            await db.set_cost_per_person(today, cost_per_person)

        await app.bot.send_message(
            chat_id=config.CHAT_ID,
            text=f"📋 *Chốt sổ!* Tổng có *{len(voters)} người* đặt cơm.\n\n🍱 *Phân công hôm nay:*\n{roles_text}",
            parse_mode="Markdown",
        )
        logger.info("✅ Roles assigned for %s, picker=%s", today, picker["username"])
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
        image = render_summary_image(rows, paid_ids, year_month)
        await app.bot.send_photo(
            chat_id=config.CHAT_ID,
            photo=BytesIO(image),
            caption=f"📊 Tổng kết tháng {int(month)}/{year}",
        )
        logger.info("✅ Monthly summary sent for %s", year_month)
    except Exception:
        logger.exception("❌ monthly_summary failed for %s", year_month)


async def _scheduled_admin_digest(app: Application) -> None:
    """20:00 T2-T5 — gửi riêng admin tổng hợp ai đã đặt cho vote ngày mai."""
    tomorrow = _target_date(1)
    logger.info("⏰ Scheduler: admin_digest triggered for %s", tomorrow)
    try:
        daily = await db.get_daily_vote(tomorrow)
        if not daily or daily["status"] != "open":
            return
        await send_vote_digest(app.bot, tomorrow)
        logger.info("✅ Admin digest sent for %s", tomorrow)
    except Exception:
        logger.exception("❌ admin_digest failed for %s", tomorrow)


def build_scheduler(app: Application) -> AsyncIOScheduler:
    tz = pytz.timezone(config.TIMEZONE)

    def _hm(t: str):
        h, m = map(int, t.split(":"))
        return h, m

    morning_h, morning_m = _hm(config.VOTE_OPEN_TIME)      # 08:30
    evening_h, evening_m = _hm(config.EVENING_OPEN_TIME)   # 19:00
    announce_h, announce_m = _hm(config.ANNOUNCE_TIME)     # 10:30
    digest_h, digest_m = _hm(config.ADMIN_DIGEST_TIME)     # 20:00

    scheduler = AsyncIOScheduler(timezone=tz)
    # 19:00 CN-T4: tạo vote cho ngày mai (T2-T5) — gồm CN tạo vote cho thứ 2; T6 do job 08:30 tạo
    scheduler.add_job(
        _scheduled_open_vote,
        trigger=CronTrigger(hour=evening_h, minute=evening_m, day_of_week="sun,mon,tue,wed", timezone=tz),
        args=[app, 1], id="open_vote_evening", replace_existing=True, misfire_grace_time=300,
    )
    # 08:30 T2-T6: có vote → nhắc; chưa có → tạo vote (lưới an toàn)
    scheduler.add_job(
        _scheduled_morning,
        trigger=CronTrigger(hour=morning_h, minute=morning_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="morning", replace_existing=True, misfire_grace_time=300,
    )
    # 10:30 T2-T6: đóng vote + chốt sổ
    scheduler.add_job(
        _scheduled_announce_roles,
        trigger=CronTrigger(hour=announce_h, minute=announce_m, day_of_week="mon-fri", timezone=tz),
        args=[app], id="announce_roles", replace_existing=True, misfire_grace_time=300,
    )
    # 20:00 CN-T4: digest vote gửi riêng admin (cho vote ngày mai, gồm CN cho thứ 2; bỏ T5 vì T6 không tạo vote tối)
    scheduler.add_job(
        _scheduled_admin_digest,
        trigger=CronTrigger(hour=digest_h, minute=digest_m, day_of_week="sun,mon,tue,wed", timezone=tz),
        args=[app], id="admin_digest", replace_existing=True, misfire_grace_time=300,
    )
    # 14:00 hằng ngày: tổng kết tháng (tự thoát nếu không phải ngày cuối tháng)
    scheduler.add_job(
        _scheduled_monthly_summary,
        trigger=CronTrigger(hour=14, minute=0, day_of_week="mon-sun", timezone=tz),
        args=[app], id="monthly_summary", replace_existing=True, misfire_grace_time=300,
    )
    return scheduler
