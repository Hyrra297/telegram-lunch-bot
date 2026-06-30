from __future__ import annotations
import asyncio
import calendar
import logging
import pytz
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

import config
import database as db

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "pay:confirm:"
AUTO_DELETE_SECONDS = 10


async def _auto_delete(message, delay=AUTO_DELETE_SECONDS):
    """Xóa tin nhắn sau delay giây."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


def _current_month(tz: str = config.TIMEZONE) -> str:
    return datetime.now(pytz.timezone(tz)).strftime("%Y-%m")


def _previous_month(tz: str = config.TIMEZONE) -> str:
    """Tháng dương lịch liền trước — đóng tiền là trả cho tháng đã ăn xong."""
    now = datetime.now(pytz.timezone(tz))
    last_day_prev = now.replace(day=1) - timedelta(days=1)
    return last_day_prev.strftime("%Y-%m")


def _billing_month(now: datetime | None = None, tz: str = config.TIMEZONE) -> str:
    """Tháng đang được chốt tiền.

    Ngày cuối tháng (job tổng kết 14:00 gửi bảng *tháng hiện tại*) → tháng hiện tại;
    các ngày khác → tháng dương lịch liền trước (đang trả cho tháng đã ăn xong).
    Nhờ vậy /dong_tien và /summary khớp đúng tháng mà nhóm vừa nhận tổng kết.
    """
    if now is None:
        now = datetime.now(pytz.timezone(tz))
    last_day = calendar.monthrange(now.year, now.month)[1]
    if now.day == last_day:
        return now.strftime("%Y-%m")
    last_day_prev = now.replace(day=1) - timedelta(days=1)
    return last_day_prev.strftime("%Y-%m")


def _month_label(year_month: str) -> str:
    year, m = year_month.split("-")
    return f"tháng {int(m)}/{year}"


async def dong_tien(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    year_month = _billing_month()
    paid_ids = await db.get_paid_user_ids(year_month)
    is_private = update.effective_chat.type == "private"

    if user.id in paid_ids:
        reply = await update.message.reply_text(
            f"✅ {_month_label(year_month).capitalize()} của bạn đã được xác nhận rồi!"
        )
        if not is_private:
            asyncio.create_task(_auto_delete(reply))
        return

    def _esc(s: str) -> str:
        return s.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")

    mention = f"@{_esc(user.username)}" if user.username else f"*{_esc(user.full_name)}*"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Xác nhận đã nhận tiền",
            callback_data=f"{CALLBACK_PREFIX}{user.id}:{year_month}",
        )
    ]])

    # Phản hồi cho user
    reply = await update.message.reply_text(
        f"💰 Đã ghi nhận bạn báo đóng tiền {_month_label(year_month)}.\nChờ admin xác nhận nhé!",
        parse_mode="Markdown",
    )

    # Xóa reply bot trong nhóm sau 10s, giữ lệnh user
    if not is_private:
        asyncio.create_task(_auto_delete(reply))

    # Gửi nút xác nhận cho admin (có retry nếu rate limit)
    admin_text = f"💰 {mention} báo đã đóng tiền {_month_label(year_month)}.\n\nNhấn nút bên dưới để xác nhận."
    for admin_id in config.ADMIN_IDS:
        if is_private and user.id == admin_id:
            await update.message.reply_text(
                admin_text, parse_mode="Markdown", reply_markup=keyboard,
            )
        else:
            for attempt in range(3):
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_text,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                    break
                except Exception as e:
                    logger.warning(f"dong_tien: gửi admin {admin_id} thất bại (lần {attempt+1}): {e}")
                    if attempt < 2:
                        await asyncio.sleep(1)


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

    def _esc(s: str) -> str:
        return s.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")

    paid_ids = await db.get_paid_user_ids(year_month)
    if user_id in paid_ids:
        try:
            await query.edit_message_text(
                text=query.message.text + "\n\n✅ (Đã xác nhận trước đó)",
                reply_markup=None,
            )
        except Exception:
            pass
        return

    # Lưu DB trước — quan trọng nhất
    await db.toggle_monthly_paid(year_month, user_id)

    member = await db.get_user(user_id)
    name = member["full_name"] if member else str(user_id)
    admin_name = query.from_user.full_name

    # Xoá nút khỏi tin nhắn cũ — plain text, không dùng Markdown
    try:
        await query.edit_message_text(
            text=query.message.text + f"\n\n✅ Đã xác nhận bởi {admin_name}.",
            reply_markup=None,
        )
    except Exception as e:
        logger.warning(f"Edit confirm message failed: {e}")

    # Thông báo công khai vào nhóm — plain text, không dùng Markdown
    try:
        group_msg = await context.bot.send_message(
            chat_id=config.CHAT_ID,
            text=f"✅ {name} đã đóng tiền {_month_label(year_month)} — xác nhận bởi {admin_name}.",
        )
        asyncio.create_task(_auto_delete(group_msg))
    except Exception as e:
        logger.warning(f"Send group confirm failed: {e}")

    # Thông báo private cho user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Tiền {_month_label(year_month)} của bạn đã được xác nhận bởi {admin_name}!",
        )
    except Exception as e:
        logger.warning(f"dong_tien: gửi private user {user_id} thất bại: {e}")


def get_handlers():
    return [
        CommandHandler("dong_tien", dong_tien),
        CallbackQueryHandler(handle_confirm_callback, pattern=f"^{CALLBACK_PREFIX}"),
    ]
