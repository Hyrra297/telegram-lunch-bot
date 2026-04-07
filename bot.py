import asyncio
import logging

from telegram import BotCommand, BotCommandScopeChat
from telegram.ext import Application

import config
import database as db
from handlers import vote, admin, summary, payment, help, qr
from scheduler import build_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    await db.init_db()
    scheduler = build_scheduler(app)
    scheduler.start()
    logger.info(
        "Scheduler started. Open: %s | Close: %s | Announce: %s | TZ: %s",
        config.VOTE_OPEN_TIME,
        config.VOTE_CLOSE_TIME,
        config.ANNOUNCE_TIME,
        config.TIMEZONE,
    )

    # Lệnh hiện cho mọi người khi gõ /
    user_commands = [
        BotCommand("summary", "Xem tổng kết đặt cơm tháng này"),
        BotCommand("tien", "Xem tiền cơm của bạn tháng này"),
        BotCommand("dong_tien", "Báo đã đóng tiền tháng này"),
        BotCommand("qr", "Xem mã QR chuyển tiền"),
        BotCommand("help", "Xem danh sách lệnh"),
    ]
    await app.bot.set_my_commands(user_commands)

    # Lệnh admin — hiện thêm khi admin gõ /
    admin_commands = user_commands + [
        BotCommand("open_vote", "Mở vote đặt cơm hôm nay"),
        BotCommand("close_vote", "Đóng vote và chọn người lấy cơm"),
        BotCommand("add_member", "Thêm thành viên (reply vào tin nhắn của họ)"),
        BotCommand("remove_member", "Xoá thành viên (reply vào tin nhắn của họ)"),
        BotCommand("set_price", "Đổi giá mỗi suất cơm"),
        BotCommand("set_time", "Đổi giờ mở/đóng vote"),
        BotCommand("rotation", "Xem thứ tự lượt lấy cơm và trả hộp"),
        BotCommand("reset_vote", "Xoá vote hôm nay để mở lại"),
        BotCommand("assign", "Phân công lấy cơm/trả hộp thủ công"),
    ]
    for admin_id in config.ADMIN_IDS:
        try:
            await app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(admin_id))
        except Exception:
            pass


def main() -> None:
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    for handler in vote.get_handlers():
        app.add_handler(handler)
    for handler in admin.get_handlers():
        app.add_handler(handler)
    for handler in summary.get_handlers():
        app.add_handler(handler)
    for handler in payment.get_handlers():
        app.add_handler(handler)
    for handler in help.get_handlers():
        app.add_handler(handler)
    for handler in qr.get_handlers():
        app.add_handler(handler)

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
