from __future__ import annotations
import pytz
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
import aiosqlite

import config
import database as db


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def _require_admin(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_admin(update.effective_user.id):
            await update.message.reply_text("Chỉ admin mới dùng được lệnh này.")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


@_require_admin
async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Dùng: /set_price <số tiền>\nVí dụ: /set_price 35000")
        return
    try:
        price = int(context.args[0].replace(",", "").replace(".", ""))
    except ValueError:
        await update.message.reply_text("Giá không hợp lệ. Ví dụ: /set_price 35000")
        return
    await db.set_setting("price", str(price))
    await update.message.reply_text(f"Đã cập nhật giá mỗi suất: {price:,}đ")


@_require_admin
async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text(
            "Dùng: /set_time <giờ mở> <giờ đóng>\nVí dụ: /set_time 08:00 10:30"
        )
        return
    open_t, close_t = context.args[0], context.args[1]
    for t in (open_t, close_t):
        parts = t.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            await update.message.reply_text(f"Thời gian không hợp lệ: {t}. Dùng định dạng HH:MM")
            return
    await db.set_setting("open_time", open_t)
    await db.set_setting("close_time", close_t)
    await update.message.reply_text(
        f"Đã cập nhật:\n• Mở vote: {open_t}\n• Đóng vote: {close_t}\n\n"
        "Lịch mới sẽ có hiệu lực từ ngày hôm sau khi restart bot."
    )


@_require_admin
async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "Reply vào tin nhắn của người muốn thêm và dùng lệnh /add_member"
        )
        return
    target = update.message.reply_to_message.from_user
    await db.add_user(target.id, target.full_name, target.username)
    await update.message.reply_text(
        f"Đã thêm {target.full_name} vào danh sách đặt cơm."
    )


@_require_admin
async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "Reply vào tin nhắn của người muốn xoá và dùng lệnh /remove_member"
        )
        return
    target = update.message.reply_to_message.from_user
    removed = await db.deactivate_user(target.id)
    if removed:
        await update.message.reply_text(f"Đã xoá {target.full_name} khỏi danh sách đặt cơm.")
    else:
        await update.message.reply_text(f"Không tìm thấy {target.full_name} trong danh sách.")


@_require_admin
async def show_rotation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = await db.get_active_users()
    if not users:
        await update.message.reply_text("Chưa có thành viên nào.")
        return

    pick_dates = await db.get_last_pick_return_dates()

    lines = []
    for i, u in enumerate(sorted(users, key=lambda x: x["rotation_index"]), 1):
        picked = pick_dates.get(u["id"], {}).get("picked") or "—"
        returned = pick_dates.get(u["id"], {}).get("returned") or "—"
        lines.append(f"{i}. {u['full_name']}  🛵{picked}  📦{returned}")

    text = "🔄 *Vòng xoay phân công:*\n_(🛵 lấy cơm | 📦 trả hộp)_\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown")


@_require_admin
async def reset_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    async with aiosqlite.connect(config.DB_PATH) as db_conn:
        await db_conn.execute("DELETE FROM vote_entries WHERE date = ?", (today,))
        await db_conn.execute(
            """UPDATE daily_votes SET status = 'none',
               poll_message_id = NULL, poll_id = NULL,
               picker_user_id = NULL, returner_user_id = NULL,
               cost_per_person = NULL
               WHERE date = ?""",
            (today,),
        )
        await db_conn.commit()
    await update.message.reply_text(f"♻️ Đã reset vote ngày {today}. Dùng /open_vote để mở lại.")


@_require_admin
async def skip_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = pytz.timezone(config.TIMEZONE)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    async with aiosqlite.connect(db.DB_PATH) as db_conn:
        await db_conn.execute(
            """INSERT INTO daily_votes (date, price, ship_fee, status)
               VALUES (?, ?, ?, 'closed')
               ON CONFLICT(date) DO UPDATE SET status = 'closed'""",
            (today, config.PRICE_PER_MEAL, config.SHIP_FEE),
        )
        await db_conn.commit()
    await update.message.reply_text(f"⏭️ Đã bỏ qua ngày {today} — hôm nay không đặt cơm.")


def get_handlers():
    return [
        CommandHandler("set_price", set_price),
        CommandHandler("set_time", set_time),
        CommandHandler("add_member", add_member),
        CommandHandler("remove_member", remove_member),
        CommandHandler("rotation", show_rotation),
        CommandHandler("reset_vote", reset_vote),
        CommandHandler("skip_today", skip_today),
    ]
