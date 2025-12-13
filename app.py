# =========================================================
# Telegram Support Bot (aiogram v3 + webhook)
# Works on Render (Free Tier)
# =========================================================

import os
import logging
import asyncio

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiohttp import web
from dotenv import load_dotenv

# =========================================================
# Load environment variables
# =========================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BASE_URL = os.getenv("BASE_URL")  # https://your-app.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
PORT = int(os.getenv("PORT", "10000"))

# =========================================================
# Validate env vars (important)
# =========================================================
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not BASE_URL:
    raise RuntimeError("BASE_URL is missing")

if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is missing")

# =========================================================
# Logging
# =========================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("support-bot")

# =========================================================
# Bot / Dispatcher / Router
# =========================================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# =========================================================
# Handlers
# =========================================================

@router.message(CommandStart())
async def start_handler(message: Message):
    """
    Handles /start command
    """
    await message.answer(
        "👋 أهلاً بك!\n"
        "هذا بوت تواصل.\n"
        "اكتب رسالتك وسيصل الرد من الإدارة."
    )

@router.message()
async def forward_to_admin(message: Message):
    """
    Forwards user messages to admin
    """
    if message.from_user.id == ADMIN_ID:
        return

    text = (
        f"📩 رسالة جديدة\n\n"
        f"👤 المستخدم: {message.from_user.full_name}\n"
        f"🆔 ID: {message.from_user.id}\n\n"
        f"{message.text}"
    )

    await bot.send_message(chat_id=ADMIN_ID, text=text)
    await message.answer("✅ تم استلام رسالتك، سيتم الرد عليك قريبًا.")

# =========================================================
# Webhook setup
# =========================================================
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

async def on_startup():
    """
    Set Telegram webhook on startup
    """
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

async def on_shutdown():
    """
    Proper shutdown
    """
    await bot.session.close()

# =========================================================
# Aiohttp app
# =========================================================
async def handle_webhook(request: web.Request):
    """
    Receives updates from Telegram
    """
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return web.Response(text="OK")

app = web.Application()
app.router.add_post(WEBHOOK_PATH, handle_webhook)

# =========================================================
# Main entry
# =========================================================
async def main():
    await on_startup()

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

    logger.info("Bot is running...")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
