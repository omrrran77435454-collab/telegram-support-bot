# ======================================================
# Telegram Support Bot (aiogram v3 + webhook)
# Stable version for Render Free
# ======================================================

import os
import asyncio
import logging

from aiohttp import web
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from aiogram.filters import CommandStart

# ======================================================
# Load environment variables
# ======================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BASE_URL = os.getenv("BASE_URL")  # https://your-app.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
PORT = int(os.getenv("PORT", "10000"))

# ======================================================
# Validate env vars
# ======================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not BASE_URL:
    raise RuntimeError("BASE_URL is missing")

if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is missing")

# ======================================================
# Logging
# ======================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("support-bot")

# ======================================================
# Bot / Dispatcher
# ======================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ======================================================
# Handlers
# ======================================================

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "👋 مرحبًا بك في بوت التواصل\n\n"
        "✍️ أرسل رسالتك وسيتم تحويلها للإدارة."
    )

@router.message()
async def forward_to_admin(message: Message):
    if message.from_user.id == ADMIN_ID:
        return

    await bot.send_message(
        ADMIN_ID,
        f"📩 رسالة جديدة من:\n"
        f"👤 {message.from_user.full_name}\n"
        f"🆔 {message.from_user.id}\n\n"
        f"{message.text}"
    )

    await message.answer("✅ تم إرسال رسالتك للإدارة.")

# ======================================================
# Webhook setup
# ======================================================

async def on_startup(app: web.Application):
    webhook_url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
    await bot.set_webhook(webhook_url)
    logger.info(f"Webhook set to: {webhook_url}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Bot session closed")

# ======================================================
# Web server
# ======================================================

async def handle_webhook(request: web.Request):
    secret = request.match_info.get("secret")
    if secret != WEBHOOK_SECRET:
        return web.Response(status=403)

    data = await request.json()
    await dp.feed_webhook_update(bot, data)
    return web.Response(text="OK")

def main():
    app = web.Application()
    app.router.add_post("/webhook/{secret}", handle_webhook)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)

# ======================================================
# Entry point
# ======================================================

if __name__ == "__main__":
    main()    Proper shutdown
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
