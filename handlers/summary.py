from __future__ import annotations
import asyncio
import re
import pytz
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

import config
import database as db

AUTO_DELETE_SECONDS = 10


async def _auto_delete(message, delay=AUTO_DELETE_SECONDS):
    """Xóa tin nhắn sau delay giây. Bỏ qua lỗi nếu không xóa được."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


def _current_month(tz: str = config.TIMEZONE) -> str:
    return datetime.now(pytz.timezone(tz)).strftime("%Y-%m")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        return

    if context.args:
        year_month = context.args[0]
        if not re.match(r"^\d{4}-\d{2}$", year_month):
            await update.message.reply_text(
                "Định dạng không đúng. Dùng: /summary YYYY-MM\nVí dụ: /summary 2026-03"
            )
            return
    else:
        year_month = _current_month()

    rows = await db.get_monthly_summary(year_month)

    year, month = year_month.split("-")
    header = f"📊 *Tổng kết tháng {int(month)}/{year}*\n{'─' * 28}"

    if not rows:
        await update.message.reply_text(
            f"{header}\n\nKhông có dữ liệu cho tháng này.",
            parse_mode="Markdown",
        )
        return

    # Sắp xếp theo tổng tiền giảm dần
    rows.sort(key=lambda r: r["total"], reverse=True)

    paid_ids = await db.get_paid_user_ids(year_month)

    lines = []
    max_name_len = max(len(r["full_name"]) for r in rows)
    for i, r in enumerate(rows, 1):
        name = r["full_name"].ljust(max_name_len)
        count = r["meal_count"]
        total = f"{r['total']:>10,}đ"
        status = "✅" if r.get("user_id") in paid_ids else "❌"
        lines.append(f"{i:>2}. {name}  {count:>2} suất  {total}  {status}")

    table = "\n".join(lines)
    text = f"{header}\n\n```\n{table}\n```"

    await update.message.reply_text(text, parse_mode="Markdown")


async def my_money(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if context.args:
        year_month = context.args[0]
        if not re.match(r"^\d{4}-\d{2}$", year_month):
            await update.message.reply_text(
                "Định dạng không đúng. Dùng: /tien YYYY-MM\nVí dụ: /tien 2026-03"
            )
            return
    else:
        year_month = _current_month()

    rows = await db.get_monthly_summary(year_month)

    year, month = year_month.split("-")
    my_row = next((r for r in rows if r.get("user_id") == user.id), None)

    if not my_row:
        await update.message.reply_text(
            f"📊 Tháng {int(month)}/{year}: Bạn chưa có dữ liệu đặt cơm.",
            parse_mode="Markdown",
        )
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

    # Auto-delete cả lệnh và reply trong nhóm
    if update.effective_chat.type != "private":
        asyncio.create_task(_auto_delete(update.message))
        asyncio.create_task(_auto_delete(reply))


def get_handlers():
    return [
        CommandHandler("summary", summary),
        CommandHandler("tien", my_money),
    ]
