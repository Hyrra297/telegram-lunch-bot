from __future__ import annotations
import base64
import pytz
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, PollAnswerHandler

import anthropic
import config
import database as db
from admin_notify import notify_new_voter, notify_changed_dish, notify_retracted

CALLBACK_VOTE_IN = "vote:in"
CALLBACK_VOTE_OUT = "vote:out"


def _today(tz: str = config.TIMEZONE) -> str:
    return datetime.now(pytz.timezone(tz)).strftime("%Y-%m-%d")


def _past_evening_digest(date: str, tz: str = config.TIMEZONE) -> bool:
    """True nếu đã qua mốc digest tối (config.ADMIN_DIGEST_TIME, mặc định 20:00)
    của tối hôm trước ngày `date` — tức là admin đã được gửi danh sách "chốt".

    Sau mốc này, mọi thay đổi vote (đặt/đổi món/huỷ) cho ngày đó được nhắn riêng
    admin real-time, cho tới khi vote đóng lúc 10:30. Trước mốc này không báo."""
    zone = pytz.timezone(tz)
    vote_date = datetime.strptime(date, "%Y-%m-%d").date()
    h, m = map(int, config.ADMIN_DIGEST_TIME.split(":"))
    digest_dt = zone.localize(datetime.combine(vote_date - timedelta(days=1), dtime(h, m)))
    return datetime.now(zone) >= digest_dt


def _build_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Tôi đặt", callback_data=CALLBACK_VOTE_IN),
            InlineKeyboardButton("❌ Bỏ phiếu", callback_data=CALLBACK_VOTE_OUT),
        ]
    ])


def _build_vote_text(voters: list[dict], menu_description: str = "", day_label: str = "hôm nay") -> str:
    header = f"🍱 *Đặt cơm {day_label}*"
    if menu_description:
        header += f"\n\n{menu_description}"
    if voters:
        names = "\n".join(f"  • {v['full_name']}" for v in voters)
        header += f"\n\n👥 {len(voters)} người đặt:\n{names}"
    else:
        header += "\n\nChưa có ai đặt..."
    return header


async def _extract_menu_from_image(image_path: Path) -> str:
    """Dùng Claude vision để đọc nội dung thực đơn từ ảnh."""
    if not config.ANTHROPIC_API_KEY:
        return ""
    media_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
    }
    media_type = media_types.get(image_path.suffix.lower(), "image/jpeg")
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_data},
                },
                {
                    "type": "text",
                    "text": "Đây là ảnh thực đơn cơm trưa. Hãy liệt kê các món ăn trong ảnh, mỗi món một dòng bắt đầu bằng •. Chỉ liệt kê tên món, không giải thích thêm.",
                },
            ],
        }],
    )
    return response.content[0].text.strip()


async def open_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.effective_user.id not in config.ADMIN_IDS:
        await update.message.reply_text("Chỉ admin mới dùng được lệnh này.")
        return

    today = _today()
    existing = await db.get_daily_vote(today)
    if existing and existing["status"] == "open":
        await update.message.reply_text("Hôm nay đã có vote rồi!")
        return

    price_str = await db.get_setting("price") or str(config.PRICE_PER_MEAL)
    price = int(price_str)
    ship_fee_str = await db.get_setting("ship_fee") or str(config.SHIP_FEE)
    ship_fee = int(ship_fee_str)

    # Send menu photo if available
    menu_image = existing["menu_image"] if existing else None
    menu_description = ""
    if menu_image:
        photo_path = Path("static/menus") / menu_image
        if photo_path.exists():
            with open(photo_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=config.CHAT_ID,
                    photo=f,
                    caption="🍽️ Thực đơn hôm nay",
                )
            try:
                menu_description = await _extract_menu_from_image(photo_path)
            except Exception:
                menu_description = ""

    dishes = await db.get_menu_items(today)

    if dishes:
        # Native Telegram poll
        poll_msg = await context.bot.send_poll(
            chat_id=config.CHAT_ID,
            question="🍱 Hôm nay ăn gì?",
            options=dishes,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        await db.create_daily_vote(today, poll_msg.message_id, price, ship_fee)
        await db.set_poll_id(today, poll_msg.poll.id)
    else:
        # Fallback: inline keyboard
        msg = await context.bot.send_message(
            chat_id=config.CHAT_ID,
            text=_build_vote_text([], menu_description),
            parse_mode="Markdown",
            reply_markup=_build_keyboard(),
        )
        await db.create_daily_vote(today, msg.message_id, price, ship_fee)
        if menu_description:
            await db.set_menu_description(today, menu_description)


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý khi user vote trong native Telegram poll."""
    answer = update.poll_answer
    poll_id = answer.poll_id
    user_id = answer.user.id
    option_ids = answer.option_ids  # [] nếu user bỏ vote

    daily = await db.get_daily_vote_by_poll_id(poll_id)
    if not daily or daily["status"] != "open":
        return

    date = daily["date"]
    dishes = await db.get_menu_items(date)
    user = answer.user
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username or str(user_id)
    was_voter = await db.is_voter(date, user_id)

    if not option_ids:
        # User retracted vote
        import aiosqlite
        async with aiosqlite.connect(config.DB_PATH) as db_conn:
            await db_conn.execute(
                "DELETE FROM vote_entries WHERE date=? AND user_id=?", (date, user_id)
            )
            await db_conn.commit()
        # Báo riêng admin khi huỷ — chỉ sau digest tối 20:00 hôm trước
        if was_voter and _past_evening_digest(date):
            voters = await db.get_voters(date)
            await notify_retracted(context.bot, full_name, len(voters), exclude_user_id=user_id)
    else:
        # Tự động thêm user vào bảng users nếu chưa có
        await db.ensure_user(user_id, user.username, full_name)

        idx = option_ids[0]
        dish = dishes[idx] if idx < len(dishes) else dishes[0]
        await db.vote_for_dish(date, user_id, dish)

        # Báo riêng admin mọi thay đổi sau digest tối 20:00 hôm trước
        if _past_evening_digest(date):
            voters = await db.get_voters(date)
            if was_voter:
                await notify_changed_dish(context.bot, full_name, len(voters), exclude_user_id=user_id)
            else:
                await notify_new_voter(context.bot, full_name, len(voters), exclude_user_id=user_id)


async def close_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.effective_user.id not in config.ADMIN_IDS:
        await update.message.reply_text("Chỉ admin mới dùng được lệnh này.")
        return

    today = _today()
    daily = await db.get_daily_vote(today)
    if not daily:
        await update.message.reply_text("Chưa có vote nào hôm nay.")
        return
    if daily["status"] == "closed":
        await update.message.reply_text("Vote hôm nay đã đóng rồi.")
        return

    voters = await db.get_voters(today)
    if not voters:
        await context.bot.send_message(
            chat_id=config.CHAT_ID,
            text="Hôm nay không có ai đặt cơm.",
        )
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

    await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text=f"🔒 Vote đã đóng! *{len(voters)} người* đặt cơm.\n\n{roles_text}",
        parse_mode="Markdown",
    )

    # Đóng native poll nếu có
    if daily.get("poll_id") and daily.get("poll_message_id"):
        try:
            await context.bot.stop_poll(
                chat_id=config.CHAT_ID,
                message_id=daily["poll_message_id"],
            )
        except Exception:
            pass
    # Đóng inline keyboard nếu có (fallback mode)
    elif daily.get("poll_message_id") and not daily.get("poll_id"):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=config.CHAT_ID,
                message_id=daily["poll_message_id"],
                reply_markup=None,
            )
        except Exception:
            pass


async def handle_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fallback handler cho inline keyboard (khi không có dishes)."""
    query = update.callback_query
    await query.answer()

    user = query.from_user

    # Tra vote theo tin nhắn chứa nút — không dùng _today() vì vote có thể
    # được tạo từ tối hôm trước (cho ngày mai).
    daily = await db.get_daily_vote_by_message_id(query.message.message_id)
    if not daily or daily["status"] == "closed":
        await query.answer("Vote này đã đóng rồi!", show_alert=True)
        return
    date = daily["date"]

    member = await db.get_user(user.id)
    if not member or not member["active"]:
        await query.answer("Bạn chưa được thêm vào danh sách đặt cơm.", show_alert=True)
        return

    was_in = await db.is_voter(date, user.id)
    now_in = was_in
    if query.data == CALLBACK_VOTE_IN:
        now_in = await db.toggle_vote(date, user.id)
        await query.answer("Đã đăng ký đặt cơm!" if now_in else "Đã huỷ đặt cơm.")
    elif query.data == CALLBACK_VOTE_OUT:
        now_in = await db.toggle_vote(date, user.id)
        await query.answer("Đã bỏ phiếu (không đặt).")

    voters = await db.get_voters(date)

    # Báo riêng admin mọi thay đổi sau digest tối 20:00 hôm trước
    if now_in != was_in and _past_evening_digest(date):
        if now_in:
            await notify_new_voter(context.bot, member["full_name"], len(voters), exclude_user_id=user.id)
        else:
            await notify_retracted(context.bot, member["full_name"], len(voters), exclude_user_id=user.id)

    menu_description = daily.get("menu_description") or ""
    day_label = "hôm nay" if date == _today() else "ngày mai"
    try:
        await query.edit_message_text(
            text=_build_vote_text(voters, menu_description, day_label=day_label),
            parse_mode="Markdown",
            reply_markup=_build_keyboard(),
        )
    except Exception:
        pass


def get_handlers():
    return [
        CommandHandler("open_vote", open_vote),
        CommandHandler("close_vote", close_vote),
        CallbackQueryHandler(handle_vote_callback, pattern=r"^vote:"),
        PollAnswerHandler(handle_poll_answer),
    ]
