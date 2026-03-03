import asyncio
import logging

from telegram.ext import Application

import config
import database as db
from handlers import vote, admin, summary
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
        "Scheduler started. Open: %s | Close: %s | TZ: %s",
        config.VOTE_OPEN_TIME,
        config.VOTE_CLOSE_TIME,
        config.TIMEZONE,
    )


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

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
