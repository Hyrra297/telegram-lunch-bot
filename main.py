"""
Entry point: runs Telegram bot + FastAPI web server in the same asyncio event loop.
"""
import asyncio
import logging
import os

import uvicorn
from telegram.ext import Application

import config
import database as db
from handlers import vote, admin, summary, menu
from scheduler import build_scheduler
from web.app import app as web_app

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", 8080))


async def run_bot(tg_app: Application) -> None:
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)
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
