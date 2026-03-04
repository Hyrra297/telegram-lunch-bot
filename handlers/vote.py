from __future__ import annotations
import base64
import pytz
from datetime import datetime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

import anthropic
import config
import database as db

CALLBACK_VOTE_IN = "vote:in"
CALLBACK_VOTE_OUT = "vote:out"


def _today(tz: str = config.TIMEZONE) -> str:
    return datetime.now(pytz.timezone(tz)).strftime("%Y-%m-%d")


def _build_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Tôi đặt", callback_data=CALLBACK_VOTE_IN),
            InlineKeyboardButton("❌ Bỏ phiếu", callback_data=CALLBACK_VOTE_OUT),
        ]
    ])


def _build_vote_text(voters: list[dict], menu_description: str = "") -> str:
    header = "🍱 *Đặt cơm hôm nay*"
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

    # Send menu photo if available, then extract menu description
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

    msg = await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text=_build_vote_text([], menu_description),
        parse_mode="Markdown",
        reply_markup=_build_keyboard(),
    )
    await db.create_daily_vote(today, msg.message_id, price, ship_fee)
    if menu_description:
        await db.set_menu_description(today, menu_description)


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
    await db.close_daily_vote(today, picker["id"])

    voter_names = ", ".join(f"@{v['username']}" if v["username"] else v["full_name"] for v in voters)
    picker_mention = f"@{picker['username']}" if picker["username"] else f"*{picker['full_name']}*"

    await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text=(
            f"🔒 Vote đã đóng! {len(voters)} người đặt cơm.\n\n"
            f"🛵 {picker_mention} sẽ đi lấy cơm và trả hộp hôm nay!\n\n"
            f"Danh sách: {voter_names}"
        ),
        parse_mode="Markdown",
    )

    # Disable buttons on the poll message
    if daily["poll_message_id"]:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=config.CHAT_ID,
                message_id=daily["poll_message_id"],
                reply_markup=None,
            )
        except Exception:
            pass


async def handle_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user = query.from_user
    today = _today()

    daily = await db.get_daily_vote(today)
    if not daily or daily["status"] == "closed":
        await query.answer("Vote hôm nay đã đóng rồi!", show_alert=True)
        return

    member = await db.get_user(user.id)
    if not member or not member["active"]:
        await query.answer("Bạn chưa được thêm vào danh sách đặt cơm.", show_alert=True)
        return

    if query.data == CALLBACK_VOTE_IN:
        voted_in = await db.toggle_vote(today, user.id)
        if not voted_in:
            await query.answer("Đã huỷ đặt cơm.")
        else:
            await query.answer("Đã đăng ký đặt cơm!")
    elif query.data == CALLBACK_VOTE_OUT:
        await db.toggle_vote(today, user.id)
        await query.answer("Đã bỏ phiếu (không đặt).")

    voters = await db.get_voters(today)
    menu_description = daily.get("menu_description") or ""
    try:
        await query.edit_message_text(
            text=_build_vote_text(voters, menu_description),
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
    ]
