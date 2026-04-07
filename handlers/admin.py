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

    # Sort by last duty date ASC (who goes next first), tiebreak rotation_index
    def _last_duty(u):
        lp = u.get("last_picked_at") or ""
        lr = u.get("last_returned_at") or ""
        return max(lp, lr)

    sorted_users = sorted(users, key=lambda u: (_last_duty(u), u["rotation_index"]))

    lines = []
    for i, u in enumerate(sorted_users, 1):
        picked = u.get("last_picked_at") or "—"
        returned = u.get("last_returned_at") or "—"
        last = _last_duty(u) or "chưa làm"
        lines.append(f"{i}. {u['full_name']}  🛵{picked}  📦{returned}")

    text = "🔄 *Vòng xoay phân công:*\n_(ưu tiên từ trên xuống — ai lâu nhất đi trước)_\n" + "\n".join(lines)
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


@_require_admin
async def assign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Phân công thủ công khi vote đã đóng nhưng chưa có picker/returner."""
    today = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    daily = await db.get_daily_vote(today)
    if not daily:
        await update.message.reply_text("❌ Hôm nay chưa có vote nào.")
        return
    if daily["status"] != "closed":
        await update.message.reply_text("❌ Vote chưa đóng. Đóng vote trước rồi mới phân công.")
        return
    if daily.get("picker_user_id"):
        await update.message.reply_text("ℹ️ Đã phân công rồi. Dùng /reset_vote nếu muốn làm lại.")
        return

    voters = await db.get_voters(today)
    if not voters:
        await update.message.reply_text("❌ Hôm nay không có ai vote.")
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

    price = daily.get("price") or config.PRICE_PER_MEAL
    ship_fee = daily.get("ship_fee") or config.SHIP_FEE
    cost_per_person = price + round(ship_fee / len(voters))
    await db.set_cost_per_person(today, cost_per_person)

    await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text=f"📋 *Chốt sổ!* Tổng có *{len(voters)} người* đặt cơm.\n\n🍱 *Phân công hôm nay:*\n{roles_text}",
        parse_mode="Markdown",
    )



def get_handlers():
    return [
        CommandHandler("set_price", set_price),
        CommandHandler("set_time", set_time),
        CommandHandler("add_member", add_member),
        CommandHandler("remove_member", remove_member),
        CommandHandler("rotation", show_rotation),
        CommandHandler("reset_vote", reset_vote),
        CommandHandler("skip_today", skip_today),
        CommandHandler("assign", assign),
    ]
