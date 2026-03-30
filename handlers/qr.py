from __future__ import annotations
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

QR_DIR = Path("static/qr")
ALLOWED_EXT = [".jpg", ".jpeg", ".png", ".webp", ".gif"]


def _find_qr_files():
    """Tìm tất cả file QR trong thư mục static/qr/."""
    files = []
    for ext in ALLOWED_EXT:
        for f in QR_DIR.glob(f"*{ext}"):
            files.append(f)
    return files


async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    qr_files = _find_qr_files()

    if not qr_files:
        await update.message.reply_text("Chưa có mã QR nào. Admin upload trên web nhé.")
        return

    for qr_file in qr_files:
        name = qr_file.stem.replace("_", " ").title()
        with open(qr_file, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"💳 {name}",
            )


def get_handlers():
    return [
        CommandHandler("qr", qr_command),
    ]
