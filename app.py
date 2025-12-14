import os
import asyncio
import logging

from dotenv import load_dotenv
from aiohttp import web

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("support-bot")

# ----------------------------
# Env
# ----------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip())  # لو ما تستخدمه اتركه
BASE_URL = os.getenv("BASE_URL", "").strip()        # https://your-service.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not BASE_URL:
    raise RuntimeError("BASE_URL is missing (e.g. https://your-app.onrender.com)")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is missing")

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

# ----------------------------
# Bot setup
# ----------------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("مرحباً! ارسل رسالتك وسيتم التعامل معها.")

@router.message()
async def echo_handler(message: Message):
    # مؤقتاً: رد بسيط للتأكد أن البوت شغال
    await message.answer("تم الاستلام ✅")

# ----------------------------
# Webhook HTTP handler
# ----------------------------
async def handle_webhook(request: web.Request):
    secret = request.match_info.get("secret")
    if secret != WEBHOOK_SECRET:
        return web.Response(status=403, text="Forbidden")

    update = await request.json()
    await dp.feed_webhook_update(bot, update)
    return web.Response(text="OK")

# ----------------------------
# Startup / Shutdown
# ----------------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to: {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()
    logger.info("Bot session closed")

# ----------------------------
# App factory
# ----------------------------
def create_app() -> web.Application:
    async def health(request):
    return web.Response(text="OK")

app.router.add_get("/", health)
    app = web.Application()
    app.router.add_post("/webhook/{secret}", handle_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

# ----------------------------
# Entry
# ----------------------------
if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
