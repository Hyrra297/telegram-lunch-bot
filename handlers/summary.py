from __future__ import annotations
import asyncio
import calendar
import logging
import re
import pytz
from io import BytesIO
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

import config
import database as db
from image_summary import render_summary_image

logger = logging.getLogger(__name__)

AUTO_DELETE_SECONDS = 10


async def _auto_delete(message, delay=AUTO_DELETE_SECONDS):
    """Xóa tin nhắn sau delay giây."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
        logger.info(f"Auto-deleted message {message.message_id}")
    except Exception as e:
        logger.warning(f"Auto-delete failed for message {message.message_id}: {e}")


def _current_month(tz: str = config.TIMEZONE) -> str:
    return datetime.now(pytz.timezone(tz)).strftime("%Y-%m")


def _previous_month(tz: str = config.TIMEZONE) -> str:
    """Tháng dương lịch liền trước (xử lý đúng năm, vd tháng 1 → tháng 12 năm trước)."""
    now = datetime.now(pytz.timezone(tz))
    last_day_prev = now.replace(day=1) - timedelta(days=1)
    return last_day_prev.strftime("%Y-%m")


def _billing_month(now: datetime | None = None, tz: str = config.TIMEZONE) -> str:
    """Tháng đang được chốt tiền — xem handlers/payment._billing_month.

    Ngày cuối tháng → tháng hiện tại; các ngày khác → tháng liền trước.
    """
    if now is None:
        now = datetime.now(pytz.timezone(tz))
    last_day = calendar.monthrange(now.year, now.month)[1]
    if now.day == last_day:
        return now.strftime("%Y-%m")
    last_day_prev = now.replace(day=1) - timedelta(days=1)
    return last_day_prev.strftime("%Y-%m")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        return

    if context.args:
        m = re.match(r"^(\d{2})-(\d{4})$", context.args[0])
        if not m or not (1 <= int(m.group(1)) <= 12):
            await update.message.reply_text(
                "Định dạng không đúng. Dùng: /summary MM-YYYY\nVí dụ: /summary 03-2026"
            )
            return
        year_month = f"{m.group(2)}-{m.group(1)}"
    else:
        year_month = _billing_month()

    rows = await db.get_monthly_summary(year_month)

    year, month = year_month.split("-")

    if not rows:
        await update.message.reply_text(
            f"📊 Tổng kết tháng {int(month)}/{year}\n\nKhông có dữ liệu cho tháng này.",
        )
        return

    # Sắp xếp theo tổng tiền giảm dần
    rows.sort(key=lambda r: r["total"], reverse=True)
    paid_ids = await db.get_paid_user_ids(year_month)

    image = render_summary_image(rows, paid_ids, year_month)
    await update.message.reply_photo(
        photo=BytesIO(image),
        caption=f"📊 Tổng kết tháng {int(month)}/{year}",
    )


async def my_money(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if context.args:
        m = re.match(r"^(\d{2})-(\d{4})$", context.args[0])
        if not m or not (1 <= int(m.group(1)) <= 12):
            await update.message.reply_text(
                "Định dạng không đúng. Dùng: /tien MM-YYYY\nVí dụ: /tien 03-2026"
            )
            return
        year_month = f"{m.group(2)}-{m.group(1)}"
    else:
        year_month = _billing_month()

    rows = await db.get_monthly_summary(year_month)

    year, month = year_month.split("-")
    my_row = next((r for r in rows if r.get("user_id") == user.id), None)

    if not my_row:
        reply = await update.message.reply_text(
            f"📊 Tháng {int(month)}/{year}: Bạn chưa có dữ liệu đặt cơm.",
            parse_mode="Markdown",
        )
        if update.effective_chat.type != "private":
            asyncio.create_task(_auto_delete(reply))
        return

    count = my_row["meal_count"]
    total = my_row["total"]
    paid_ids = await db.get_paid_user_ids(year_month)
    is_paid = user.id in paid_ids

    status = "✅ Đã đóng" if is_paid else "❌ Chưa đóng"

    text = (
        f"💰 *Tiền cơm tháng {int(month)}/{year}*\n"
        f"{'─' * 28}\n"
        f"👤 {user.full_name}\n"
        f"🍚 Số suất: *{count}*\n"
        f"💵 Tổng tiền: *{total:,}đ*\n"
        f"📋 Trạng thái: {status}\n"
        f"{'─' * 28}"
    )

    reply = await update.message.reply_text(text, parse_mode="Markdown")

    # Xóa reply bot trong nhóm sau 10s, giữ lệnh user
    if update.effective_chat.type != "private":
        asyncio.create_task(_auto_delete(reply))


def get_handlers():
    return [
        CommandHandler("summary", summary),
        CommandHandler("tien", my_money),
    ]
