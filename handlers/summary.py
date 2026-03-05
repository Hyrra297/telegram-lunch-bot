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


def get_handlers():
    return [
        CommandHandler("summary", summary),
    ]
