import asyncio
import logging
import os
import sqlite3
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from aiogram.exceptions import TelegramBadRequest
from aiohttp import web

# ==================== SOZLAMALAR ====================
# Bu qiymatlar endi kod ichida emas, balki ENVIRONMENT VARIABLES orqali olinadi.
# Render.com -> Dashboard -> Service -> Environment bo'limida quyidagilarni qo'shing:
#   BOT_TOKEN, CHANNEL_USERNAME, CHANNEL_ID, ADMIN_IDS, WEBAPP_URL, DB_PATH
BOT_TOKEN = os.getenv("BOT_TOKEN")                                   # @BotFather dan olingan token
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@trade_chanel_uz")  # majburiy obuna bo'ladigan kanal
CHANNEL_ID = os.getenv("CHANNEL_ID", "@trade_chanel_uz")              # post shu yerga tashlanadi (o'sha kanal)
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "8866852203").split(",") if x.strip()
]  # admin(lar) Telegram ID raqami(lari), vergul bilan ajratiladi: "111,222,333"
WEBAPP_URL = os.getenv(
    "WEBAPP_URL", "https://mukxabek-prog.github.io/nakurutkabot/"
)  # nakurutka/donat/stars/premium WebApp havolasi (https shart!)
DB_PATH = os.getenv("DB_PATH", "contest.db")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi! Render'da Environment bo'limiga BOT_TOKEN qiymatini qo'shing."
    )

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

BOT_USERNAME: Optional[str] = None  # deep-link havolalar uchun runtime'da olinadi


# ==================== DATABASE ====================
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            votes INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            voter_id INTEGER PRIMARY KEY,
            candidate_id INTEGER NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS battle_post (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            chat_id INTEGER,
            message_id INTEGER,
            intro_text TEXT,
            has_photo INTEGER DEFAULT 0,
            stopped INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def add_participant(user_id: int, name: str):
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO participants (user_id, name, votes) "
        "VALUES (?, ?, COALESCE((SELECT votes FROM participants WHERE user_id=?), 0))",
        (user_id, name, user_id),
    )
    conn.commit()
    conn.close()


def get_participant(user_id: int):
    conn = db_connect()
    row = conn.execute("SELECT * FROM participants WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def get_all_participants():
    conn = db_connect()
    # Adminlar hech qachon ishtirokchilar ro'yxatida ko'rinmaydi.
    # votes bo'yicha kamayish tartibida, teng ovozlar ichida ENG SO'NGGI qo'shilgan oldinda turadi
    if ADMIN_IDS:
        placeholders = ",".join("?" for _ in ADMIN_IDS)
        query = (
            f"SELECT * FROM participants WHERE user_id NOT IN ({placeholders}) "
            "ORDER BY votes DESC, user_id DESC"
        )
        rows = conn.execute(query, ADMIN_IDS).fetchall()
    else:
        rows = conn.execute("SELECT * FROM participants ORDER BY votes DESC, user_id DESC").fetchall()
    conn.close()
    return rows


def cleanup_admin_participants():
    """Agar admin oldin (test paytida) ishtirokchi sifatida qo'shilib qolgan bo'lsa, uni bazadan tozalaydi."""
    if not ADMIN_IDS:
        return
    conn = db_connect()
    placeholders = ",".join("?" for _ in ADMIN_IDS)
    conn.execute(f"DELETE FROM participants WHERE user_id IN ({placeholders})", ADMIN_IDS)
    conn.commit()
    conn.close()


def has_voted(voter_id: int) -> bool:
    conn = db_connect()
    row = conn.execute("SELECT 1 FROM votes WHERE voter_id=?", (voter_id,)).fetchone()
    conn.close()
    return row is not None


def add_vote(voter_id: int, candidate_id: int):
    conn = db_connect()
    conn.execute("INSERT INTO votes (voter_id, candidate_id) VALUES (?, ?)", (voter_id, candidate_id))
    conn.execute("UPDATE participants SET votes = votes + 1 WHERE user_id=?", (candidate_id,))
    conn.commit()
    conn.close()


def save_battle_post(chat_id: int, message_id: int, intro_text: str, has_photo: bool):
    conn = db_connect()
    conn.execute("DELETE FROM battle_post")
    conn.execute(
        "INSERT INTO battle_post (id, chat_id, message_id, intro_text, has_photo) VALUES (1, ?, ?, ?, ?)",
        (chat_id, message_id, intro_text, 1 if has_photo else 0),
    )
    conn.commit()
    conn.close()


def get_battle_post():
    conn = db_connect()
    row = conn.execute("SELECT * FROM battle_post WHERE id=1").fetchone()
    conn.close()
    return row


def stop_battle_in_db():
    conn = db_connect()
    conn.execute("UPDATE battle_post SET stopped = 1 WHERE id = 1")
    conn.commit()
    conn.close()


# ==================== FSM HOLATLARI ====================
class AdminPostStates(StatesGroup):
    waiting_text = State()
    waiting_photo = State()


# ==================== YORDAMCHI FUNKSIYALAR ====================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
    except TelegramBadRequest:
        return False


def subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📢 Kanalga obuna bo'lish",
            url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}",
        )],
        [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")],
    ])


def webapp_entry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Kirish", web_app=WebAppInfo(url=WEBAPP_URL))],
    ])


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Post qo'shish", callback_data="add_post")],
        [InlineKeyboardButton(text="🔄 Ovozlarni yangilash", callback_data="refresh_battle")],
        [InlineKeyboardButton(text="🛑 To'xtatish (g'olibni e'lon qilish)", callback_data="stop_battle")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")],
    ])


def skip_photo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Rasmsiz yuborish (Skip)", callback_data="skip_photo")],
    ])


def build_post_content(intro_text: str):
    """Kanalga tashlanadigan yagona postning matni va tugmalarini quradi:
    admin matni + ishtirokchilar ro'yxati (ovoz bilan) + Qo'shilish tugmasi."""
    participants = get_all_participants()

    lines = []
    if intro_text:
        lines.append(intro_text)
        lines.append("")
    lines.append("🔥 <b>BATTLE / OVOZ BERISH</b> 🔥")
    lines.append("Ishtirokchiga ovoz berish uchun tugmani bosing:\n")

    kb_rows = []
    if participants:
        for i, p in enumerate(participants, start=1):
            lines.append(f"{i}. {p['name']} — {p['votes']} ovoz")
            kb_rows.append([
                InlineKeyboardButton(
                    text=f"🗳 {p['name']} ({p['votes']})",
                    url=f"https://t.me/{BOT_USERNAME}?start=vote_{p['user_id']}",
                )
            ])
    else:
        lines.append("Hozircha ishtirokchilar yo'q.")

    kb_rows.append([InlineKeyboardButton(text="✅ Qo'shilish", url=f"https://t.me/{BOT_USERNAME}?start=join")])

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    return text, kb


def build_final_results_text(intro_text: str) -> str:
    """Konkurs to'xtatilgandan keyingi yakuniy natijalar matnini quradi (tugmalarsiz)."""
    participants = get_all_participants()

    lines = []
    if intro_text:
        lines.append(intro_text)
        lines.append("")
    lines.append("🏁 <b>KONKURS YAKUNLANDI!</b> 🏁\n")

    if participants:
        winner = participants[0]
        lines.append(f"🏆 <b>G'olib:</b> {winner['name']} — {winner['votes']} ovoz\n")
        lines.append("📊 <b>Yakuniy natijalar:</b>")
        for i, p in enumerate(participants, start=1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"
            lines.append(f"{medal} {i}. {p['name']} — {p['votes']} ovoz")
    else:
        lines.append("Ishtirokchilar bo'lmadi.")

    return "\n".join(lines)


async def update_battle_message():
    """Kanaldagi postni JORIY ovoz/ishtirokchi ma'lumotlari bilan joyida (edit) yangilaydi.
    Konkurs to'xtatilgan bo'lsa — yakuniy natijalar (tugmasiz) ko'rsatiladi.
    Har safar yangi qo'shilish/ovoz berish yoki to'xtatishdan keyin avtomatik chaqiriladi."""
    post = get_battle_post()
    if post is None:
        return  # hali post yuborilmagan bo'lsa, yangilanadigan narsa yo'q

    if post["stopped"]:
        text = build_final_results_text(post["intro_text"] or "")
        kb = None
    else:
        text, kb = build_post_content(post["intro_text"] or "")

    try:
        if post["has_photo"]:
            await bot.edit_message_caption(
                chat_id=post["chat_id"], message_id=post["message_id"], caption=text, reply_markup=kb
            )
        else:
            await bot.edit_message_text(
                chat_id=post["chat_id"], message_id=post["message_id"], text=text, reply_markup=kb
            )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(f"Battle postini avtomatik yangilashda xatolik: {e}")


# ==================== HANDLERLAR ====================

# --- 1) Deep-link orqali /start (ovoz berish / qo'shilish) ---
@router.message(CommandStart(deep_link=True))
async def start_with_payload(message: Message, command: CommandObject, state: FSMContext):
    payload = command.args or ""

    if payload.startswith("vote_"):
        # ====== OVOZ BERISH: bosh menyu OCHILMAYDI, darhol ovoz qo'shiladi ======
        try:
            candidate_id = int(payload.split("_", 1)[1])
        except (IndexError, ValueError):
            await message.answer("❌ Xato havola.")
            return

        voter_id = message.from_user.id

        post = get_battle_post()
        if post and post["stopped"]:
            await message.answer("🏁 Konkurs allaqachon yakunlangan. Endi ovoz berish mumkin emas.")
            return

        if not await check_subscription(voter_id):
            await message.answer(
                "❌ Ovoz berish uchun avval kanalga obuna bo'ling:",
                reply_markup=subscribe_keyboard(),
            )
            return

        candidate = get_participant(candidate_id)
        if candidate is None:
            await message.answer("❌ Bunday ishtirokchi topilmadi.")
            return

        if voter_id == candidate_id:
            await message.answer("🚫 Siz o'zingizga ovoz bera olmaysiz!")
            return

        if has_voted(voter_id):
            await message.answer("⚠️ Siz allaqachon ovoz bergansiz. Faqat 1 marta ovoz berish mumkin.")
            return

        add_vote(voter_id, candidate_id)
        await message.answer(
            f"✅ Ovozingiz qabul qilindi!\nSiz <b>{candidate['name']}</b>ga ovoz berdingiz."
        )
        await update_battle_message()
        return

    if payload == "join":
        # ====== KANALDAGI "✅ Qo'shilish" bosilganda: darhol, avtomatik nik bilan qo'shiladi ======
        user_id = message.from_user.id

        if is_admin(user_id):
            await message.answer("⛔ Adminlar konkursda ishtirokchi sifatida qatnasha olmaydi.")
            return

        post = get_battle_post()
        if post and post["stopped"]:
            await message.answer("🏁 Konkurs allaqachon yakunlangan. Endi qatnashish mumkin emas.")
            return

        if not await check_subscription(user_id):
            await message.answer(
                "❌ Qatnashish uchun avval kanalga obuna bo'ling:",
                reply_markup=subscribe_keyboard(),
            )
            return

        if get_participant(user_id):
            await message.answer("✅ Siz allaqachon konkurs ishtirokchisi sifatida ro'yxatdan o'tgansiz.")
            return

        name = message.from_user.full_name or message.from_user.username or f"User{user_id}"
        add_participant(user_id, name)
        await message.answer(
            f"🎉 Tabriklaymiz, <b>{name}</b>! Siz konkurs ishtirokchisi sifatida qo'shildingiz."
        )
        await update_battle_message()
        return

    await cmd_start(message, state)


# --- 2) Oddiy /start (payload'siz) ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    if not await check_subscription(user_id):
        await message.answer(
            "👋 Assalomu alaykum!\n\n"
            "Botdan foydalanish uchun avval quyidagi kanalga obuna bo'ling:",
            reply_markup=subscribe_keyboard(),
        )
        return

    await message.answer(
        "🤖 <b>Botga xush kelibsiz!</b>\n\n"
        "✅ Nakrutka\n"
        "💎 Donat\n"
        "⭐ Stars\n"
        "👑 Premium\n\n"
        "xizmatlaridan foydalanish uchun pastdagi tugmani bosing 👇",
        reply_markup=webapp_entry_keyboard(),
    )


@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.edit_text("✅ Obuna tasdiqlandi!")
        await callback.message.answer(
            "🤖 <b>Botga xush kelibsiz!</b>\n\n"
            "✅ Nakrutka\n"
            "💎 Donat\n"
            "⭐ Stars\n"
            "👑 Premium\n\n"
            "xizmatlaridan foydalanish uchun pastdagi tugmani bosing 👇",
            reply_markup=webapp_entry_keyboard(),
        )
    else:
        await callback.answer("❌ Siz hali obuna bo'lmagansiz!", show_alert=True)


@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    await callback.message.edit_text("⚙️ Admin panel yopildi. Qayta ochish uchun /admin buyrug'ini yuboring.")
    await callback.answer()


# --- 3) Admin panel: FAQAT /admin buyrug'i orqali ochiladi ---
@router.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return  # oddiy foydalanuvchilarga hech qanday javob berilmaydi
    await message.answer("⚙️ Admin panel:", reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "add_post")
async def add_post(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Sizga ruxsat yo'q.", show_alert=True)
        return

    await callback.message.answer("✏️ Post uchun matnni yuboring:")
    await state.set_state(AdminPostStates.waiting_text)
    await callback.answer()


@router.message(AdminPostStates.waiting_text)
async def add_post_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Iltimos, matn ko'rinishida yuboring.")
        return

    await state.update_data(intro_text=text)
    await message.answer(
        "🖼 Endi rasm yuboring.\n\nRasmsiz yubormoqchi bo'lsangiz, pastdagi tugmani bosing:",
        reply_markup=skip_photo_keyboard(),
    )
    await state.set_state(AdminPostStates.waiting_photo)


@router.message(AdminPostStates.waiting_photo, F.photo)
async def add_post_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    intro_text = data.get("intro_text", "")
    photo_id = message.photo[-1].file_id

    text, kb = build_post_content(intro_text)
    sent = await bot.send_photo(chat_id=CHANNEL_ID, photo=photo_id, caption=text, reply_markup=kb)
    save_battle_post(sent.chat.id, sent.message_id, intro_text, has_photo=True)

    await state.clear()
    await message.answer("✅ Post rasm bilan kanalga joylandi!", reply_markup=admin_panel_keyboard())


@router.message(AdminPostStates.waiting_photo)
async def add_post_wrong_content(message: Message):
    await message.answer(
        "❌ Iltimos, rasm yuboring yoki 'Skip' tugmasini bosing.",
        reply_markup=skip_photo_keyboard(),
    )


@router.callback_query(AdminPostStates.waiting_photo, F.data == "skip_photo")
async def add_post_skip(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    intro_text = data.get("intro_text", "")

    text, kb = build_post_content(intro_text)
    sent = await bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=kb)
    save_battle_post(sent.chat.id, sent.message_id, intro_text, has_photo=False)

    await state.clear()
    await callback.message.answer("✅ Post (rasmsiz) kanalga joylandi!", reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "refresh_battle")
async def refresh_battle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Sizga ruxsat yo'q.", show_alert=True)
        return

    post = get_battle_post()
    if post is None:
        await callback.answer("❌ Hali post yuborilmagan.", show_alert=True)
        return

    await update_battle_message()
    await callback.answer("✅ Ovozlar yangilandi!", show_alert=True)


@router.callback_query(F.data == "stop_battle")
async def stop_battle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Sizga ruxsat yo'q.", show_alert=True)
        return

    post = get_battle_post()
    if post is None:
        await callback.answer("❌ Hali post yuborilmagan.", show_alert=True)
        return

    if post["stopped"]:
        await callback.answer("ℹ️ Konkurs allaqachon to'xtatilgan.", show_alert=True)
        return

    stop_battle_in_db()
    await update_battle_message()

    participants = get_all_participants()
    if participants:
        winner = participants[0]
        await callback.message.answer(
            f"🏁 Konkurs to'xtatildi!\n\n🏆 <b>G'olib:</b> {winner['name']} — {winner['votes']} ovoz",
            reply_markup=admin_panel_keyboard(),
        )
    else:
        await callback.message.answer(
            "🏁 Konkurs to'xtatildi. Ishtirokchilar bo'lmagani uchun g'olib yo'q.",
            reply_markup=admin_panel_keyboard(),
        )
    await callback.answer()


# ==================== SOXTA WEB-SERVER (faqat Render "Web Service" uchun) ====================
# Render "Web Service" turi doim biror portni tinglashni talab qiladi, aks holda
# xizmatni "timed out" deb o'chirib qo'yadi. Bot esa polling rejimida ishlagani
# uchun hech qanday portni o'zi ochmaydi - shu sababli shu yerda juda oddiy
# HTTP server ochib qo'yamiz, u faqat Render tekshiruvidan o'tish uchun kerak.
async def start_dummy_webserver():
    async def health(request):
        return web.Response(text="Bot ishlayapti ✅")

    app = web.Application()
    app.router.add_get("/", health)

    port = int(os.getenv("PORT", "10000"))  # Render PORT'ni o'zi beradi
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info(f"Dummy web-server {port}-portda ishga tushdi (Render uchun).")


# ==================== ISHGA TUSHIRISH ====================
async def main():
    global BOT_USERNAME
    init_db()
    cleanup_admin_participants()
    me = await bot.get_me()
    BOT_USERNAME = me.username
    logging.info(f"Bot ishga tushdi: @{BOT_USERNAME}")

    await start_dummy_webserver()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
