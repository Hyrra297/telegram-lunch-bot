from __future__ import annotations
import asyncio
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

import config

AUTO_DELETE_SECONDS = 10


async def _auto_delete(message, delay=AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

USER_COMMANDS = """
*📋 Lệnh dành cho mọi người:*
/tien — Xem tiền cơm của bạn tháng này
/dong\\_tien — Báo đã đóng tiền tháng này
/qr — Xem mã QR chuyển tiền
/help — Xem danh sách lệnh
""".strip()

ADMIN_COMMANDS = """

*🔧 Lệnh dành cho admin:*
/summary — Xem tổng kết đặt cơm tháng này
/open\\_vote — Mở vote đặt cơm hôm nay
/close\\_vote — Đóng vote, chốt đơn cơm hôm nay
/add\\_member — Thêm thành viên (reply vào tin nhắn của họ)
/remove\\_member — Xoá thành viên (reply vào tin nhắn của họ)
/set\\_price <số> — Đổi giá mỗi suất cơm
/set\\_time <mở> <đóng> — Đổi giờ mở/đóng vote (VD: 08:00 10:30)
/rotation — Xem thứ tự lượt lấy cơm và trả hộp
/reset\\_vote — Xoá vote hôm nay để mở lại
/skip\\_today — Hôm nay không đặt cơm
/reopen\\_vote — Mở lại vote sau khi đã đóng
""".strip()


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = USER_COMMANDS
    if update.effective_user.id in config.ADMIN_IDS:
        text += "\n\n" + ADMIN_COMMANDS
    reply = await update.message.reply_text(text, parse_mode="Markdown")

    if update.effective_chat.type != "private":
        asyncio.create_task(_auto_delete(reply))


def get_handlers():
    return [CommandHandler("help", help_command)]
