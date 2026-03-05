from __future__ import annotations
import pytz
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

import config
import database as db

CALLBACK_PREFIX = "pay:confirm:"


def _current_month(tz: str = config.TIMEZONE) -> str:
    return datetime.now(pytz.timezone(tz)).strftime("%Y-%m")


def _month_label(year_month: str) -> str:
    year, m = year_month.split("-")
    return f"tháng {int(m)}/{year}"


async def dong_tien(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    year_month = _current_month()
    paid_ids = await db.get_paid_user_ids(year_month)
    if user.id in paid_ids:
        await update.message.reply_text(
            f"✅ {_month_label(year_month).capitalize()} của bạn đã được xác nhận rồi!"
        )
        return

    mention = f"@{user.username}" if user.username else f"*{user.full_name}*"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Xác nhận đã nhận tiền",
            callback_data=f"{CALLBACK_PREFIX}{user.id}:{year_month}",
        )
    ]])
    await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text=f"💰 {mention} báo đã đóng tiền {_month_label(year_month)}.\n\nAdmin vui lòng xác nhận.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def handle_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in config.ADMIN_IDS:
        await query.answer("Chỉ admin mới xác nhận được.", show_alert=True)
        return

    # Parse callback data: pay:confirm:{user_id}:{year_month}
    payload = query.data[len(CALLBACK_PREFIX):]
    user_id_str, year_month = payload.rsplit(":", 1)
    user_id = int(user_id_str)

    paid_ids = await db.get_paid_user_ids(year_month)
    if user_id in paid_ids:
        await query.edit_message_text(
            query.message.text + "\n\n✅ *(Đã xác nhận trước đó)*",
            parse_mode="Markdown",
        )
        return

    await db.toggle_monthly_paid(year_month, user_id)

    member = await db.get_user(user_id)
    name = member["full_name"] if member else str(user_id)
    mention = f"@{member['username']}" if member and member["username"] else f"*{name}*"
    admin_name = query.from_user.full_name

    # Xoá nút khỏi tin nhắn cũ
    await query.edit_message_reply_markup(reply_markup=None)

    # Thông báo công khai
    await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text=f"✅ {mention} đã đóng tiền {_month_label(year_month)} — xác nhận bởi {admin_name}.",
        parse_mode="Markdown",
    )


def get_handlers():
    return [
        CommandHandler("dong_tien", dong_tien),
        CallbackQueryHandler(handle_confirm_callback, pattern=f"^{CALLBACK_PREFIX}"),
    ]
