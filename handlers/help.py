from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

import config

USER_COMMANDS = """
*📋 Lệnh dành cho mọi người:*
/summary — Xem tổng tiền cơm phải đóng tháng này
/dong\\_tien — Báo đã đóng tiền tháng này
/help — Xem danh sách lệnh
""".strip()

ADMIN_COMMANDS = """

*🔧 Lệnh dành cho admin:*
/open\\_vote — Mở vote đặt cơm hôm nay
/close\\_vote — Đóng vote, chốt đơn cơm hôm nay
/add\\_member — Thêm thành viên (reply vào tin nhắn của họ)
/remove\\_member — Xoá thành viên (reply vào tin nhắn của họ)
/set\\_price <số> — Đổi giá mỗi suất cơm
/set\\_time <mở> <đóng> — Đổi giờ mở/đóng vote (VD: 08:00 10:30)
/rotation — Xem thứ tự lượt lấy cơm và trả hộp
/reset\\_vote — Xoá vote hôm nay để mở lại
/skip\\_today — Hôm nay không đặt cơm
""".strip()


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = USER_COMMANDS
    if update.effective_user.id in config.ADMIN_IDS:
        text += "\n\n" + ADMIN_COMMANDS
    await update.message.reply_text(text, parse_mode="Markdown")


def get_handlers():
    return [CommandHandler("help", help_command)]
