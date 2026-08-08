import asyncio
import logging
import sqlite3
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.exceptions import TelegramBadRequest

# ==================== SOZLAMALAR ====================
BOT_TOKEN = "8952379767:AAEFYcjaQf-d7fc1NjUBKD_rQPgVCHwjz-U"           # @BotFather dan olingan token
CHANNEL_USERNAME = "@trade_chanel_uz"           # majburiy obuna bo'ladigan kanal
CHANNEL_ID = "@trade_chanel_uz"                 # Battle posti shu yerga tashlanadi (o'sha kanal)
ADMIN_IDS = [8866852203]                         # admin(lar) Telegram ID raqami(lari)
DB_PATH = "contest.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

BOT_USERNAME: Optional[str] = None  # /start?=vote_ID deep-link havolasi uchun runtime'da olinadi


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
            message_id INTEGER
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
    rows = conn.execute("SELECT * FROM participants ORDER BY votes DESC, name ASC").fetchall()
    conn.close()
    return rows


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


def save_battle_post(chat_id: int, message_id: int):
    conn = db_connect()
    conn.execute("DELETE FROM battle_post")
    conn.execute("INSERT INTO battle_post (id, chat_id, message_id) VALUES (1, ?, ?)", (chat_id, message_id))
    conn.commit()
    conn.close()


def get_battle_post():
    conn = db_connect()
    row = conn.execute("SELECT * FROM battle_post WHERE id=1").fetchone()
    conn.close()
    return row


# ==================== FSM HOLATLARI ====================
class RegisterStates(StatesGroup):
    waiting_name = State()


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


def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🏆 Konkursda qatnashish", callback_data="register")],
    ]
    if is_admin(user_id):
        buttons.append([InlineKeyboardButton(text="⚙️ Admin panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qo'shish (Kanalga taklif posti)", callback_data="add_join_post")],
        [InlineKeyboardButton(text="📢 Kanalga Battle postini tashlash", callback_data="post_battle")],
        [InlineKeyboardButton(text="🔄 Ovozlarni yangilash", callback_data="refresh_battle")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")],
    ])


def skip_photo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Rasmsiz yuborish (Skip)", callback_data="skip_photo")],
    ])


def join_channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Qo'shilish", url=f"https://t.me/{BOT_USERNAME}?start=join")],
    ])


def build_battle_text_and_kb():
    """Kanalga tashlanadigan Battle postining matni va tugmalarini quradi."""
    participants = get_all_participants()
    if not participants:
        return None, None

    lines = ["🔥 <b>BATTLE / OVOZ BERISH</b> 🔥\n", "Ishtirokchiga ovoz berish uchun tugmani bosing:\n"]
    kb_rows = []
    for i, p in enumerate(participants, start=1):
        lines.append(f"{i}. <b>{p['name']}</b> — {p['votes']} ovoz")
        kb_rows.append([
            InlineKeyboardButton(
                text=f"🗳 {p['name']} ({p['votes']})",
                url=f"https://t.me/{BOT_USERNAME}?start=vote_{p['user_id']}",
            )
        ])
    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    return text, kb


# ==================== HANDLERLAR ====================

# --- 1) Deep-link orqali /start (masalan ovoz berish uchun) ---
@router.message(CommandStart(deep_link=True))
async def start_with_payload(message: Message, command: CommandObject, state: FSMContext):
    payload = command.args or ""

    if payload.startswith("vote_"):
        # ====== OVOZ BERISH SSENARIYSI: bosh menyu OCHILMAYDI ======
        try:
            candidate_id = int(payload.split("_", 1)[1])
        except (IndexError, ValueError):
            await message.answer("❌ Xato havola.")
            return

        voter_id = message.from_user.id

        # Majburiy obunani baribir tekshiramiz
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
        return

    if payload == "join":
        # ====== KANALDAGI TAKLIF POSTIDAN "✅ Qo'shilish" bosilganda ======
        user_id = message.from_user.id

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
            f"🎉 Tabriklaymiz, <b>{name}</b>! Siz konkurs ishtirokchisi sifatida avtomatik qo'shildingiz."
        )
        return

    # Boshqa turdagi payload bo'lsa — oddiy /start kabi ishlaymiz
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
        "👋 Xush kelibsiz!\n\nKonkursimizga xush kelibsiz. Pastdagi tugmalardan foydalaning:",
        reply_markup=main_menu_keyboard(user_id),
    )


@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.edit_text("✅ Obuna tasdiqlandi!")
        await callback.message.answer(
            "Bosh menyu:",
            reply_markup=main_menu_keyboard(callback.from_user.id),
        )
    else:
        await callback.answer("❌ Siz hali obuna bo'lmagansiz!", show_alert=True)


@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    await callback.message.edit_text("Bosh menyu:")
    await callback.message.edit_reply_markup(reply_markup=main_menu_keyboard(callback.from_user.id))


# --- 3) Ro'yxatdan o'tish ---
@router.callback_query(F.data == "register")
async def register_start(callback: CallbackQuery, state: FSMContext):
    existing = get_participant(callback.from_user.id)
    if existing:
        await callback.answer("Siz allaqachon ro'yxatdan o'tgansiz ✅", show_alert=True)
        return

    await callback.message.answer("✏️ Konkursda ishtirok etish uchun ism/nikingizni yuboring:")
    await state.set_state(RegisterStates.waiting_name)
    await callback.answer()


@router.message(RegisterStates.waiting_name)
async def register_finish(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("❌ Iltimos, matn ko'rinishida ism yuboring.")
        return

    add_participant(message.from_user.id, name)
    await state.clear()
    await message.answer(
        f"🎉 Tabriklaymiz, <b>{name}</b>! Siz konkurs ishtirokchisi sifatida ro'yxatdan o'tdingiz."
    )


# --- 4) Admin panel ---
@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Sizga ruxsat yo'q.", show_alert=True)
        return
    await callback.message.edit_text("⚙️ Admin panel:", reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "post_battle")
async def post_battle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Sizga ruxsat yo'q.", show_alert=True)
        return

    text, kb = build_battle_text_and_kb()
    if text is None:
        await callback.answer("❌ Hozircha ishtirokchilar yo'q.", show_alert=True)
        return

    sent = await bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=kb)
    save_battle_post(sent.chat.id, sent.message_id)
    await callback.answer("✅ Battle posti kanalga joylandi!", show_alert=True)


@router.callback_query(F.data == "refresh_battle")
async def refresh_battle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Sizga ruxsat yo'q.", show_alert=True)
        return

    post = get_battle_post()
    if post is None:
        await callback.answer("❌ Hali battle posti yuborilmagan.", show_alert=True)
        return

    text, kb = build_battle_text_and_kb()
    if text is None:
        await callback.answer("❌ Ishtirokchilar yo'q.", show_alert=True)
        return

    try:
        await bot.edit_message_text(
            chat_id=post["chat_id"], message_id=post["message_id"], text=text, reply_markup=kb
        )
        await callback.answer("✅ Ovozlar yangilandi!", show_alert=True)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("Hech narsa o'zgarmadi.", show_alert=True)
        else:
            await callback.answer(f"❌ Xatolik: {e}", show_alert=True)


@router.callback_query(F.data == "add_join_post")
async def add_join_post(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Sizga ruxsat yo'q.", show_alert=True)
        return

    await callback.message.answer("✏️ Kanalga tashlanadigan taklif posti uchun matnni yuboring:")
    await state.set_state(AdminPostStates.waiting_text)
    await callback.answer()


@router.message(AdminPostStates.waiting_text)
async def add_join_post_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Iltimos, matn ko'rinishida yuboring.")
        return

    await state.update_data(post_text=text)
    await message.answer(
        "🖼 Endi rasm yuboring.\n\nAgar rasmsiz yubormoqchi bo'lsangiz, pastdagi tugmani bosing:",
        reply_markup=skip_photo_keyboard(),
    )
    await state.set_state(AdminPostStates.waiting_photo)


@router.message(AdminPostStates.waiting_photo, F.photo)
async def add_join_post_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("post_text", "")
    photo_id = message.photo[-1].file_id

    await bot.send_photo(
        chat_id=CHANNEL_ID, photo=photo_id, caption=text, reply_markup=join_channel_keyboard()
    )
    await state.clear()
    await message.answer("✅ Post rasm bilan kanalga joylandi!")


@router.message(AdminPostStates.waiting_photo)
async def add_join_post_wrong_content(message: Message):
    await message.answer(
        "❌ Iltimos, rasm yuboring yoki 'Skip' tugmasini bosing.",
        reply_markup=skip_photo_keyboard(),
    )


@router.callback_query(AdminPostStates.waiting_photo, F.data == "skip_photo")
async def add_join_post_skip(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get("post_text", "")

    await bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=join_channel_keyboard())
    await state.clear()
    await callback.message.answer("✅ Post (rasmsiz) kanalga joylandi!")
    await callback.answer()


# ==================== ISHGA TUSHIRISH ====================
async def main():
    global BOT_USERNAME
    init_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username
    logging.info(f"Bot ishga tushdi: @{BOT_USERNAME}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
