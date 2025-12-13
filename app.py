# =========================
# استيراد المكتبات الأساسية
# =========================
import os
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

# =========================
# aiogram: إطار حديث لبوتات تيليجرام (Async + Webhook)
# =========================
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# =========================
# aiohttp: سيرفر بسيط لاستقبال Webhook
# =========================
from aiohttp import web

# =========================
# aiosqlite: قاعدة بيانات SQLite Async (أفضل من JSON للتزامن)
# =========================
import aiosqlite

# =========================
# dotenv: تحميل متغيرات البيئة من ملف .env (محليًا فقط)
# =========================
from dotenv import load_dotenv


# =========================
# إعداد Logging (مهم للتشخيص على الاستضافة)
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("support-bot")


# =========================
# تحميل متغيرات البيئة
# (في Render ستضعها في Environment Variables بدل .env)
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip())
BASE_URL = os.getenv("BASE_URL", "").strip()  # مثال: https://your-app.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret").strip()  # مسار سري إضافي
PORT = int(os.getenv("PORT", "10000").strip())

# =========================
# تحقق سريع من الإعدادات
# =========================
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN غير موجود. ضعه في Environment Variables.")
if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID غير صحيح. ضعه كرقم في Environment Variables.")
if not BASE_URL:
    raise RuntimeError("BASE_URL غير موجود. ضعه مثل: https://YOURAPP.onrender.com")


# =========================
# إعدادات قاعدة البيانات
# =========================
DB_PATH = os.getenv("DB_PATH", "bot.db").strip()


# =========================
# Router: مكان تجميع الـ handlers
# =========================
router = Router()


# =========================
# FSM States: حالات لإدارة إدخال الأدمن (مثل إضافة قناة/إذاعة/حظر)
# =========================
class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_add_channel = State()
    waiting_ban_user = State()
    waiting_unban_user = State()
    waiting_add_admin = State()
    waiting_remove_admin = State()
    waiting_reply_text = State()


# =========================
# هيكل بسيط لحفظ "من سيرد على من" للأدمن (مؤقت في الذاكرة)
# - لو الريستارت حصل، فقط "الوضع المؤقت" يضيع، لكن الباقي محفوظ في DB
# =========================
@dataclass
class PendingReply:
    target_user_id: int


PENDING_REPLIES: dict[int, PendingReply] = {}


# =========================
# إنشاء Bot و Dispatcher
# =========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(router)


# =========================
# دوال مساعدة للتعامل مع قاعدة البيانات
# =========================
async def db_init():
    # تعليق: إنشاء الجداول الأساسية إن لم تكن موجودة
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS banned (
                user_id INTEGER PRIMARY KEY
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS force_channels (
                username TEXT PRIMARY KEY
            )
            """
        )

        # تعليق: ضمان وجود الأدمن الرئيسي ضمن جدول الأدمن
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (ADMIN_ID,))

        # تعليق: إعداد افتراضي لحالة البوت (on)
        await db.execute(
            "INSERT OR IGNORE INTO config (key, value) VALUES ('bot_status', 'on')"
        )

        await db.commit()


async def db_get_config(key: str) -> Optional[str]:
    # تعليق: جلب قيمة إعداد من جدول config
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None


async def db_set_config(key: str, value: str) -> None:
    # تعليق: تحديث/إضافة إعداد في جدول config
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


async def db_is_admin(user_id: int) -> bool:
    # تعليق: التحقق هل المستخدم أدمن
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return (await cur.fetchone()) is not None


async def db_add_admin(user_id: int) -> None:
    # تعليق: إضافة أدمن
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        await db.commit()


async def db_remove_admin(user_id: int) -> bool:
    # تعليق: حذف أدمن (مع منع حذف الأدمن الرئيسي)
    if user_id == ADMIN_ID:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()
    return True


async def db_is_banned(user_id: int) -> bool:
    # تعليق: التحقق هل المستخدم محظور
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM banned WHERE user_id = ?", (user_id,))
        return (await cur.fetchone()) is not None


async def db_ban_user(user_id: int) -> None:
    # تعليق: حظر مستخدم
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (user_id,))
        await db.commit()


async def db_unban_user(user_id: int) -> None:
    # تعليق: فك حظر مستخدم
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM banned WHERE user_id = ?", (user_id,))
        await db.commit()


async def db_add_user(user_id: int) -> None:
    # تعليق: تسجيل مستخدم (عند /start أو أول رسالة)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()


async def db_get_users_count() -> int:
    # تعليق: عدد المستخدمين
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        return int(row[0])


async def db_get_force_channels() -> list[str]:
    # تعليق: جلب قائمة قنوات الاشتراك الإجباري
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username FROM force_channels ORDER BY username")
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def db_add_force_channel(username: str) -> None:
    # تعليق: إضافة قناة للاشتراك الإجباري
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO force_channels (username) VALUES (?)", (username,)
        )
        await db.commit()


async def db_delete_force_channel(username: str) -> None:
    # تعليق: حذف قناة من الاشتراك الإجباري
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM force_channels WHERE username = ?", (username,))
        await db.commit()


async def db_iter_users(batch_size: int = 200):
    # تعليق: جلب المستخدمين على دفعات (مفيد للإذاعة)
    offset = 0
    while True:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM users ORDER BY user_id LIMIT ? OFFSET ?",
                (batch_size, offset),
            )
            rows = await cur.fetchall()
        if not rows:
            break
        for r in rows:
            yield int(r[0])
        offset += batch_size


# =========================
# لوحة الأدمن (أزرار)
# =========================
def kb_admin_panel() -> InlineKeyboardMarkup:
    # تعليق: كيبورد لوحة التحكم للأدمن
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👥 إدارة المستخدمين", callback_data="adm:users"),
                InlineKeyboardButton(text="📢 إذاعة", callback_data="adm:broadcast"),
            ],
            [
                InlineKeyboardButton(text="📊 إحصائيات", callback_data="adm:stats"),
                InlineKeyboardButton(text="🔗 اشتراك إجباري", callback_data="adm:force"),
            ],
            [
                InlineKeyboardButton(text="❌ إيقاف البوت", callback_data="adm:off"),
                InlineKeyboardButton(text="✅ تشغيل البوت", callback_data="adm:on"),
            ],
        ]
    )


def kb_users_menu() -> InlineKeyboardMarkup:
    # تعليق: كيبورد إدارة المستخدمين
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔒 حظر", callback_data="adm:ban"),
                InlineKeyboardButton(text="🔓 فك حظر", callback_data="adm:unban"),
            ],
            [
                InlineKeyboardButton(text="➕ إضافة أدمن", callback_data="adm:add_admin"),
                InlineKeyboardButton(text="🗑️ حذف أدمن", callback_data="adm:remove_admin"),
            ],
            [
                InlineKeyboardButton(text="↩️ رجوع", callback_data="adm:back"),
            ],
        ]
    )


def kb_force_menu() -> InlineKeyboardMarkup:
    # تعليق: كيبورد إدارة الاشتراك الإجباري
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ إضافة قناة", callback_data="adm:add_ch"),
                InlineKeyboardButton(text="📋 عرض القنوات", callback_data="adm:list_ch"),
            ],
            [
                InlineKeyboardButton(text="↩️ رجوع", callback_data="adm:back"),
            ],
        ]
    )


def kb_user_message_actions(target_user_id: int) -> InlineKeyboardMarkup:
    # تعليق: كيبورد يظهر للأدمن تحت كل رسالة مستخدم (رد + حظر)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✉️ رد على المستخدم",
                    callback_data=f"usr:reply:{target_user_id}",
                ),
                InlineKeyboardButton(
                    text="🔒 حظر المستخدم",
                    callback_data=f"usr:ban:{target_user_id}",
                ),
            ]
        ]
    )


def kb_force_subscribe(channels: list[str]) -> InlineKeyboardMarkup:
    # تعليق: كيبورد الاشتراك الإجباري للمستخدم (روابط + تحقق)
    buttons = []
    for ch in channels:
        clean = ch.replace("@", "")
        buttons.append(
            [InlineKeyboardButton(text=f"📢 اشترك في {ch}", url=f"https://t.me/{clean}")]
        )
    buttons.append([InlineKeyboardButton(text="✅ تحقق", callback_data="usr:check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =========================
# التحقق من الاشتراك الإجباري
# =========================
async def user_not_subscribed(user_id: int) -> list[str]:
    # تعليق: يرجع قائمة القنوات التي لم يشترك فيها المستخدم
    channels = await db_get_force_channels()
    not_ok = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status not in ("member", "administrator", "creator"):
                not_ok.append(ch)
        except Exception:
            # تعليق: لو القناة غير صحيحة أو البوت ليس أدمن فيها أو خطأ API
            not_ok.append(ch)
    return not_ok


# =========================
# /start: بداية استخدام البوت
# =========================
@router.message(CommandStart())
async def cmd_start(message: Message):
    # تعليق: حفظ المستخدم في DB
    await db_add_user(message.from_user.id)

    # تعليق: منع المحظورين
    if await db_is_banned(message.from_user.id):
        await message.answer("🚫 تم حظرك من استخدام البوت.")
        return

    # تعليق: إذا البوت متوقف، نسمح فقط للأدمن
    bot_status = await db_get_config("bot_status")
    if bot_status != "on" and not await db_is_admin(message.from_user.id):
        await message.answer("🚫 البوت متوقف حاليًا.")
        return

    # تعليق: التحقق من الاشتراك الإجباري
    not_ok = await user_not_subscribed(message.from_user.id)
    if not_ok:
        await message.answer(
            "🔒 يجب عليك الاشتراك في القنوات التالية لاستخدام البوت:",
            reply_markup=kb_force_subscribe(not_ok),
        )
        return

    # تعليق: رسالة ترحيب
    name = message.from_user.first_name or "صديقي"
    await message.answer(f"أهلًا {name}.\nأرسل رسالتك الآن وسيتم تحويلها للإدارة.")


# =========================
# /admin: لوحة تحكم الأدمن
# =========================
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    # تعليق: تحقق صلاحيات الأدمن
    if not await db_is_admin(message.from_user.id):
        await message.answer("هذا الأمر مخصص للأدمن فقط.")
        return

    # تعليق: عرض لوحة التحكم
    await message.answer("✨ لوحة تحكم الأدمن ✨", reply_markup=kb_admin_panel())


# =========================
# استقبال أي رسالة من المستخدم (كل الأنواع)
# =========================
@router.message()
async def handle_any_user_message(message: Message):
    # تعليق: تجاهل رسائل الأدمن هنا (لأن له منطق خاص للرد)
    if await db_is_admin(message.from_user.id):
        # تعليق: إذا الأدمن في وضع "الرد على مستخدم" نطبّق منطق الرد
        pending = PENDING_REPLIES.get(message.from_user.id)
        if pending:
            # تعليق: إرسال رسالة الأدمن إلى المستخدم (بنسخ نفس نوع الرسالة)
            try:
                await message.copy_to(chat_id=pending.target_user_id)
                await message.answer("✅ تم إرسال الرد للمستخدم.")
            except Exception as e:
                await message.answer(f"❌ فشل إرسال الرد: {e}")

            # تعليق: إنهاء وضع الرد
            PENDING_REPLIES.pop(message.from_user.id, None)
        return

    # تعليق: تسجيل المستخدم (لو بدأ يرسل بدون /start)
    await db_add_user(message.from_user.id)

    # تعليق: منع المحظورين
    if await db_is_banned(message.from_user.id):
        return

    # تعليق: إذا البوت متوقف، نمنع غير الأدمن
    bot_status = await db_get_config("bot_status")
    if bot_status != "on":
        await message.answer("🚫 البوت متوقف حاليًا.")
        return

    # تعليق: التحقق من الاشتراك الإجباري
    not_ok = await user_not_subscribed(message.from_user.id)
    if not_ok:
        await message.answer(
            "🔒 يجب عليك الاشتراك في القنوات التالية لاستخدام البوت:",
            reply_markup=kb_force_subscribe(not_ok),
        )
        return

    # تعليق: تجهيز معلومات المستخدم للإدارة
    user_id = message.from_user.id
    username = message.from_user.username or "بدون_معرف"
    name = message.from_user.full_name or "بدون اسم"

    header = (
        f"📩 رسالة جديدة\n"
        f"👤 الاسم: {name}\n"
        f"🔗 المعرف: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"—\n"
        f"اضغط زر (رد) للرد مباشرة بدون أخطاء."
    )

    # تعليق: إرسال الهيدر كنص للأدمن
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=header,
        reply_markup=kb_user_message_actions(user_id),
    )

    # تعليق: إرسال الرسالة نفسها للأدمن (Copy = يدعم كل الأنواع)
    try:
        await message.copy_to(chat_id=ADMIN_ID)
    except Exception as e:
        # تعليق: لو فشل نسخ نوع معين (نادر)، نرسل fallback نصي
        await bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ لم أتمكن من نسخ الرسالة: {e}")

    # تعليق: تأكيد للمستخدم
    await message.answer("✅ تم إرسال رسالتك للإدارة. سيتم الرد عليك قريبًا.")


# =========================
# CallbackQuery: معالجة ضغط الأزرار
# =========================
@router.callback_query()
async def callbacks(call: CallbackQuery, state: FSMContext):
    data = call.data or ""
    user_id = call.from_user.id

    # -------------------------
    # أزرار المستخدم: تحقق اشتراك
    # -------------------------
    if data == "usr:check_sub":
        not_ok = await user_not_subscribed(user_id)
        if not_ok:
            await call.answer("❗ لم تشترك في جميع القنوات بعد.", show_alert=True)
        else:
            await call.answer("✅ تم التحقق بنجاح!", show_alert=True)
            await bot.send_message(chat_id=call.message.chat.id, text="🎉 يمكنك الآن استخدام البوت.")
        return

    # -------------------------
    # أزرار على رسالة المستخدم عند الأدمن: Reply/Ban
    # -------------------------
    if data.startswith("usr:reply:"):
        # تعليق: السماح فقط للأدمن
        if not await db_is_admin(user_id):
            await call.answer("❌ هذا الخيار للأدمن فقط.", show_alert=True)
            return

        # تعليق: استخراج user_id الهدف من callback_data
        target_user_id = int(data.split(":")[-1])

        # تعليق: تفعيل وضع الرد (الرسالة التالية من الأدمن تُرسل للمستخدم)
        PENDING_REPLIES[user_id] = PendingReply(target_user_id=target_user_id)

        await call.answer("اكتب ردّك الآن وسيتم إرساله للمستخدم.", show_alert=True)
        return

    if data.startswith("usr:ban:"):
        # تعليق: السماح فقط للأدمن
        if not await db_is_admin(user_id):
            await call.answer("❌ هذا الخيار للأدمن فقط.", show_alert=True)
            return

        # تعليق: استخراج user_id الهدف
        target_user_id = int(data.split(":")[-1])
        await db_ban_user(target_user_id)

        await call.answer("✅ تم حظر المستخدم.", show_alert=True)
        try:
            await bot.send_message(chat_id=target_user_id, text="🚫 تم حظرك من استخدام البوت.")
        except Exception:
            pass
        return

    # -------------------------
    # لوحة الأدمن العامة
    # -------------------------
    if data.startswith("adm:"):
        # تعليق: تحقق صلاحيات الأدمن
        if not await db_is_admin(user_id):
            await call.answer("❌ هذا الخيار للأدمن فقط.", show_alert=True)
            return

        action = data.split(":", 1)[1]

        # تعليق: رجوع للوحة التحكم
        if action == "back":
            await call.message.edit_text("✨ لوحة تحكم الأدمن ✨", reply_markup=kb_admin_panel())
            await call.answer()
            return

        # تعليق: إدارة المستخدمين
        if action == "users":
            await call.message.edit_text("👥 إدارة المستخدمين:", reply_markup=kb_users_menu())
            await call.answer()
            return

        # تعليق: قائمة الاشتراك الإجباري
        if action == "force":
            await call.message.edit_text("🔗 إدارة الاشتراك الإجباري:", reply_markup=kb_force_menu())
            await call.answer()
            return

        # تعليق: إحصائيات
        if action == "stats":
            users_count = await db_get_users_count()
            channels = await db_get_force_channels()
            bot_status = await db_get_config("bot_status")
            await call.message.answer(
                f"📊 الإحصائيات\n\n"
                f"👥 المستخدمون: {users_count}\n"
                f"📢 قنوات الاشتراك: {len(channels)}\n"
                f"⚙️ الحالة: {'✅ يعمل' if bot_status == 'on' else '❌ متوقف'}"
            )
            await call.answer()
            return

        # تعليق: تشغيل/إيقاف
        if action == "off":
            await db_set_config("bot_status", "off")
            await call.message.answer("❌ تم إيقاف البوت.")
            await call.answer()
            return

        if action == "on":
            await db_set_config("bot_status", "on")
            await call.message.answer("✅ تم تشغيل البوت.")
            await call.answer()
            return

        # تعليق: إذاعة
        if action == "broadcast":
            await call.message.answer("📝 أرسل الآن نص الإذاعة:")
            await state.set_state(AdminStates.waiting_broadcast)
            await call.answer()
            return

        # تعليق: إضافة قناة اشتراك
        if action == "add_ch":
            await call.message.answer("📝 أرسل يوزر القناة مثل: @channel")
            await state.set_state(AdminStates.waiting_add_channel)
            await call.answer()
            return

        # تعليق: عرض القنوات + حذف
        if action == "list_ch":
            channels = await db_get_force_channels()
            if not channels:
                await call.message.answer("📭 لا توجد قنوات.")
            else:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"🗑️ حذف {ch}", callback_data=f"adm:del_ch:{ch}")]
                        for ch in channels
                    ] + [[InlineKeyboardButton(text="↩️ رجوع", callback_data="adm:force")]]
                )
                await call.message.answer("📋 القنوات الحالية:", reply_markup=kb)
            await call.answer()
            return

        # تعليق: حذف قناة
        if action.startswith("del_ch:"):
            ch = action.split("del_ch:", 1)[1]
            await db_delete_force_channel(ch)
            await call.answer("✅ تم حذف القناة.", show_alert=True)
            return

        # تعليق: حظر/فك حظر
        if action == "ban":
            await call.message.answer("🔒 أرسل ID المستخدم الذي تريد حظره:")
            await state.set_state(AdminStates.waiting_ban_user)
            await call.answer()
            return

        if action == "unban":
            await call.message.answer("🔓 أرسل ID المستخدم الذي تريد فك حظره:")
            await state.set_state(AdminStates.waiting_unban_user)
            await call.answer()
            return

        # تعليق: إضافة/حذف أدمن
        if action == "add_admin":
            await call.message.answer("➕ أرسل ID المستخدم الذي تريد إضافته كأدمن:")
            await state.set_state(AdminStates.waiting_add_admin)
            await call.answer()
            return

        if action == "remove_admin":
            await call.message.answer("🗑️ أرسل ID الأدمن الذي تريد حذفه:")
            await state.set_state(AdminStates.waiting_remove_admin)
            await call.answer()
            return

    # تعليق: إذا لم يطابق أي شيء
    await call.answer()


# =========================
# استقبال نص الإذاعة من الأدمن
# =========================
@router.message(AdminStates.waiting_broadcast)
async def on_broadcast_text(message: Message, state: FSMContext):
    # تعليق: تحقق أدمن
    if not await db_is_admin(message.from_user.id):
        await state.clear()
        return

    text = message.text or ""
    if not text.strip():
        await message.answer("❗ أرسل نصًا فقط للإذاعة.")
        return

    # تعليق: إرسال الإذاعة لكل المستخدمين (Copy أفضل للوسائط، لكن هنا نص فقط)
    sent = 0
    failed = 0
    async for uid in db_iter_users():
        try:
            await bot.send_message(chat_id=uid, text=text)
            sent += 1
        except Exception:
            failed += 1

    await message.answer(f"✅ تمت الإذاعة.\nنجح: {sent}\nفشل: {failed}")
    await state.clear()


# =========================
# إضافة قناة اشتراك إجباري
# =========================
@router.message(AdminStates.waiting_add_channel)
async def on_add_channel(message: Message, state: FSMContext):
    # تعليق: تحقق أدمن
    if not await db_is_admin(message.from_user.id):
        await state.clear()
        return

    ch = (message.text or "").strip()
    if not ch.startswith("@"):
        await message.answer("❗ لازم يبدأ بـ @ مثل: @channel")
        return

    await db_add_force_channel(ch)
    await message.answer(f"✅ تمت إضافة القناة {ch}")
    await state.clear()


# =========================
# حظر مستخدم
# =========================
@router.message(AdminStates.waiting_ban_user)
async def on_ban_user(message: Message, state: FSMContext):
    # تعليق: تحقق أدمن
    if not await db_is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        uid = int((message.text or "").strip())
        await db_ban_user(uid)
        await message.answer(f"✅ تم حظر المستخدم {uid}")
        try:
            await bot.send_message(chat_id=uid, text="🚫 تم حظرك من استخدام البوت.")
        except Exception:
            pass
    except Exception:
        await message.answer("❗ أدخل ID صحيح (أرقام فقط).")

    await state.clear()


# =========================
# فك حظر مستخدم
# =========================
@router.message(AdminStates.waiting_unban_user)
async def on_unban_user(message: Message, state: FSMContext):
    # تعليق: تحقق أدمن
    if not await db_is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        uid = int((message.text or "").strip())
        await db_unban_user(uid)
        await message.answer(f"✅ تم فك الحظر عن {uid}")
    except Exception:
        await message.answer("❗ أدخل ID صحيح (أرقام فقط).")

    await state.clear()


# =========================
# إضافة أدمن
# =========================
@router.message(AdminStates.waiting_add_admin)
async def on_add_admin(message: Message, state: FSMContext):
    # تعليق: تحقق أدمن
    if not await db_is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        uid = int((message.text or "").strip())
        await db_add_admin(uid)
        await message.answer(f"✅ تم إضافة الأدمن {uid}")
    except Exception:
        await message.answer("❗ أدخل ID صحيح (أرقام فقط).")

    await state.clear()


# =========================
# حذف أدمن
# =========================
@router.message(AdminStates.waiting_remove_admin)
async def on_remove_admin(message: Message, state: FSMContext):
    # تعليق: تحقق أدمن
    if not await db_is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        uid = int((message.text or "").strip())
        ok = await db_remove_admin(uid)
        if not ok:
            await message.answer("❌ لا يمكن حذف الأدمن الرئيسي.")
        else:
            await message.answer(f"✅ تم حذف الأدمن {uid}")
    except Exception:
        await message.answer("❗ أدخل ID صحيح (أرقام فقط).")

    await state.clear()


# =========================
# Webhook server باستخدام aiohttp
# =========================
async def on_startup(app: web.Application):
    # تعليق: تهيئة DB
    await db_init()

    # تعليق: إعداد Webhook في تيليجرام
    webhook_path = f"/webhook/{WEBHOOK_SECRET}"
    webhook_url = f"{BASE_URL}{webhook_path}"

    # تعليق: ضبط Webhook (remove + set لضمان التحديث)
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(webhook_url)

    logger.info(f"Webhook set to: {webhook_url}")


async def on_shutdown(app: web.Application):
    # تعليق: حذف Webhook عند إغلاق السيرفر (اختياري)
    await bot.delete_webhook(drop_pending_updates=False)
    logger.info("Webhook deleted.")


async def handle_webhook(request: web.Request):
    # تعليق: استقبال JSON من تيليجرام وتحويله إلى Update يعالجه aiogram
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="Invalid JSON", status=400)

    # تعليق: تمرير التحديث للـ Dispatcher
    await dp.feed_raw_update(bot, data)

    # تعليق: تيليجرام يحتاج 200 OK سريعًا
    return web.Response(text="OK")


def build_app() -> web.Application:
    # تعليق: إنشاء تطبيق aiohttp وربط المسارات
    app = web.Application()

    # تعليق: مسار Webhook السري
    app.router.add_post(f"/webhook/{WEBHOOK_SECRET}", handle_webhook)

    # تعليق: مسار صحة بسيط للتأكد أن السيرفر شغال
    app.router.add_get("/", lambda r: web.Response(text="Support bot is running."))

    # تعليق: أحداث بدء/إغلاق
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


# =========================
# تشغيل السيرفر
# =========================
if __name__ == "__main__":
    # تعليق: تشغيل aiohttp web server على PORT (Render يحدد PORT تلقائيًا)
    web.run_app(build_app(), host="0.0.0.0", port=PORT)