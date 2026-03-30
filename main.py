"""
Entry point: runs Telegram bot + FastAPI web server in the same asyncio event loop.
"""
import asyncio
import logging
import os
from pathlib import Path

import uvicorn
from telegram.ext import Application

import config
import database as db
from handlers import vote, admin, summary, menu, payment, help, qr
from scheduler import build_scheduler
from web.app import app as web_app

# Symlink static dirs to persistent volume so uploads survive restarts
import shutil
for name in ("menus", "qr"):
    vol = Path(f"/data/{name}")
    link = Path(f"static/{name}")
    vol.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.resolve() != vol.resolve():
            link.unlink()
            link.symlink_to(vol)
    elif link.is_dir():
        shutil.rmtree(link)
        link.symlink_to(vol)
    else:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(vol)
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeChatMember

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
# Suppress noisy httpx logs (getUpdates every 10s floods the log buffer)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", 8080))


async def run_bot(tg_app: Application) -> None:
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "poll_answer", "poll"],
    )

    # Xóa sạch lệnh cũ ở mọi scope trước
    from telegram import (
        BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats,
        BotCommandScopeAllChatAdministrators,
    )
    for scope in [
        None,  # default
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ]:
        try:
            if scope is None:
                await tg_app.bot.delete_my_commands()
            else:
                await tg_app.bot.delete_my_commands(scope=scope)
        except Exception:
            pass
    for admin_id in config.ADMIN_IDS:
        for scope in [
            BotCommandScopeChat(admin_id),
            BotCommandScopeChatMember(chat_id=config.CHAT_ID, user_id=admin_id),
        ]:
            try:
                await tg_app.bot.delete_my_commands(scope=scope)
            except Exception:
                pass  # delete cả ChatMember để clear cache cũ

    # Đăng ký lệnh mới
    user_commands = [
        BotCommand("summary", "Xem tổng tiền cơm phải đóng tháng này"),
        BotCommand("tien", "Xem tiền cơm của bạn tháng này"),
        BotCommand("dong_tien", "Báo đã đóng tiền tháng này"),
        BotCommand("qr", "Xem mã QR chuyển tiền"),
        BotCommand("help", "Xem danh sách lệnh"),
    ]
    admin_commands = user_commands + [
        BotCommand("open_vote", "Mở vote đặt cơm hôm nay"),
        BotCommand("close_vote", "Đóng vote, chốt đơn cơm hôm nay"),
        BotCommand("add_member", "Thêm thành viên (reply vào tin nhắn của họ)"),
        BotCommand("remove_member", "Xoá thành viên (reply vào tin nhắn của họ)"),
        BotCommand("set_price", "Đổi giá mỗi suất cơm"),
        BotCommand("set_time", "Đổi giờ mở/đóng vote"),
        BotCommand("rotation", "Xem thứ tự lượt lấy cơm và trả hộp"),
        BotCommand("reset_vote", "Xoá vote hôm nay để mở lại"),
        BotCommand("skip_today", "Hôm nay không đặt cơm"),
    ]
    await tg_app.bot.set_my_commands(user_commands)
    for admin_id in config.ADMIN_IDS:
        try:
            await tg_app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(admin_id))
        except Exception:
            pass

    logger.info("Telegram bot started.")
    # Keep running until cancelled
    try:
        await asyncio.Event().wait()
    finally:
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()


async def run_web() -> None:
    uvi_config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=PORT,
        log_level="warning",
    )
    server = uvicorn.Server(uvi_config)
    logger.info("Web dashboard starting on http://0.0.0.0:%d", PORT)
    await server.serve()


async def main() -> None:
    await db.init_db()

    tg_app = Application.builder().token(config.BOT_TOKEN).build()

    for handler in vote.get_handlers():
        tg_app.add_handler(handler)
    for handler in admin.get_handlers():
        tg_app.add_handler(handler)
    for handler in summary.get_handlers():
        tg_app.add_handler(handler)
    for handler in menu.get_handlers():
        tg_app.add_handler(handler)
    for handler in payment.get_handlers():
        tg_app.add_handler(handler)
    for handler in help.get_handlers():
        tg_app.add_handler(handler)
    for handler in qr.get_handlers():
        tg_app.add_handler(handler)

    scheduler = build_scheduler(tg_app)
    scheduler.start()
    logger.info(
        "Scheduler: open=%s close=%s tz=%s",
        config.VOTE_OPEN_TIME, config.VOTE_CLOSE_TIME, config.TIMEZONE,
    )

    await asyncio.gather(
        run_bot(tg_app),
        run_web(),
    )


if __name__ == "__main__":
    asyncio.run(main())
