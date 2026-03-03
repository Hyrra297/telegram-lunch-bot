from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

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
    lines = []
    for i, u in enumerate(users, 1):
        last = u["last_picked_at"] or "chưa lần nào"
        name = u["full_name"]
        lines.append(f"{i}. {name} (lần cuối lấy: {last})")
    await update.message.reply_text("📋 Thứ tự luân phiên:\n\n" + "\n".join(lines))


def get_handlers():
    return [
        CommandHandler("set_price", set_price),
        CommandHandler("set_time", set_time),
        CommandHandler("add_member", add_member),
        CommandHandler("remove_member", remove_member),
        CommandHandler("rotation", show_rotation),
    ]
