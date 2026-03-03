from __future__ import annotations
import pytz
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

import config
import database as db

MENU_DIR = Path("static/menus")
MENU_DIR.mkdir(parents=True, exist_ok=True)


def _today() -> str:
    return datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")


async def handle_menu_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Triggered when someone sends a photo with caption /menu (or /menu@botname).
    Only works in the configured group, only for admins.
    """
    msg = update.message
    if not msg:
        return
    if msg.chat.id != config.CHAT_ID:
        return
    if msg.from_user.id not in config.ADMIN_IDS:
        await msg.reply_text("Chỉ admin mới dùng được lệnh này.")
        return

    # Pick the largest photo size
    photo = msg.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)

    today = _today()
    filename = f"{today}.jpg"
    dest = MENU_DIR / filename

    await tg_file.download_to_drive(dest)
    await db.set_menu_image(today, filename)

    await msg.reply_text(f"✅ Đã lưu thực đơn ngày {today}!")


def get_handlers():
    # Match messages in the group that have a photo AND caption starting with /menu
    return [
        MessageHandler(
            filters.PHOTO & filters.Caption(["/menu"]) & filters.Chat(config.CHAT_ID),
            handle_menu_photo,
        )
    ]
