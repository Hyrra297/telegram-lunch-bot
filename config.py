from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
CHAT_ID: int = int(os.environ["CHAT_ID"])
ADMIN_IDS: set = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
VOTE_OPEN_TIME: str = os.getenv("VOTE_OPEN_TIME", "08:00")   # HH:MM
VOTE_CLOSE_TIME: str = os.getenv("VOTE_CLOSE_TIME", "10:30") # HH:MM
PRICE_PER_MEAL: int = int(os.getenv("PRICE_PER_MEAL", "45000"))
SHIP_FEE: int = int(os.getenv("SHIP_FEE", "20000"))
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
DB_PATH: str = os.getenv("DB_PATH", "lunch_bot.db")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
