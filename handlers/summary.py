from __future__ import annotations
import re
import pytz
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

import config
import database as db


def _current_month(tz: str = config.TIMEZONE) -> str:
    return datetime.now(pytz.timezone(tz)).strftime("%Y-%m")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    lines = []
    for r in rows:
        name = r["full_name"]
        count = r["meal_count"]
        total = r["total"]
        lines.append(f"👤 {name:<16}: {count} suất = *{total:,}đ*")

    text = f"{header}\n\n" + "\n".join(lines) + f"\n{'─' * 28}"

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
    my_row = next((r for r in rows if r["full_name"] == user.full_name), None)

    # Fallback: tìm theo user_id nếu full_name không khớp
    if not my_row:
        detail = await db.get_monthly_detail(year_month)
        for m in detail.get("members", []):
            if m.get("user_id") == user.id:
                my_row = m
                break

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

    await update.message.reply_text(text, parse_mode="Markdown")


def get_handlers():
    return [
        CommandHandler("summary", summary),
        CommandHandler("tien", my_money),
    ]
