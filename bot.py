import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = "8952379767:AAEFYcjaQf-d7fc1NjUBKD_rQPgVCHwjz-U"
ADMIN_ID = 8866852203
CHANNEL_ID = "@trade_chanel_uz"  # Post yuboriladigan kanal (yoki kanal username/id si)
CHANNEL_USERNAME = "trade_chanel_uz" # Majburiy obuna kanali

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# FSM holatlari (So'rovnoma yaratish uchun)
class CreatePoll(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()
    preview = State()


# Majburiy obunani tekshirish
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=f"@{CHANNEL_USERNAME}", user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
    except Exception:
        pass
    return False


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    
    # Majburiy obunani tekshiramiz
    if not await check_subscription(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_USERNAME}")],
            [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")]
        ])
        await message.answer("⚠️ Botdan foydalanish uchun avval kanalimizga obuna bo'ling:", reply_markup=kb)
        return

    await send_main_menu(message)


async def send_main_menu(message: types.Message):
    user_id = message.from_user.id
    kb = []
    
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton(text="⚙️ Admin Panel", callback_data="admin_panel")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=kb) if kb else None
    await message.answer("Xush kelibsiz! Asosiy menyudasiz.", reply_markup=keyboard)


@dp.callback_query(F.data == "check_sub")
async def process_check_sub(callback: types.CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer("Rahmat! Obuna tasdiqlandi.")
        await send_main_menu(callback.message)
    else:
        await callback.answer("Siz hali kanalga obuna bo'lmadingiz!", show_alert=True)


# --- ADMIN PANEL ---
@dp.callback_query(F.data == "admin_panel", F.from_user.id == ADMIN_ID)
async def admin_panel(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ So'rovnoma qo'shish", callback_data="add_poll")],
        [InlineKeyboardButton(text="❌ Chiqish", callback_data="close_menu")]
    ])
    await callback.message.edit_text("🔧 Admin panelga xush kelibsiz:", reply_markup=kb)


@dp.callback_query(F.data == "add_poll", F.from_user.id == ADMIN_ID)
async def start_add_poll(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="cancel_poll")]
    ])
    await callback.message.answer("📝 So'rovnoma matnini (nomini) kiriting:", reply_markup=kb)
    await state.set_state(CreatePoll.waiting_for_text)
    await callback.answer()


@dp.callback_query(F.data == "cancel_poll")
async def cancel_poll(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Amaliyot bekor qilindi.")
    await send_main_menu(callback.message)


@dp.message(CreatePoll.waiting_for_text, F.from_user.id == ADMIN_ID)
async def process_poll_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Skip (Rasm tashlab yuborish)", callback_data="skip_photo")],
        [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="cancel_poll")]
    ])
    await message.answer("🖼 Endi rasm yuboring yoki 'Skip' tugmasini bosing:", reply_markup=kb)
    await state.set_state(CreatePoll.waiting_for_photo)


@dp.callback_query(CreatePoll.waiting_for_photo, F.data == "skip_photo", F.from_user.id == ADMIN_ID)
async def skip_photo(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(photo=None)
    await show_preview(callback.message, state)
    await callback.answer()


@dp.message(CreatePoll.waiting_for_photo, F.from_user.id == ADMIN_ID, F.photo)
async def process_poll_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo=photo_id)
    await show_preview(message, state)


async def show_preview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text")
    photo = data.get("photo")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga yuborish", callback_data="publish_poll")],
        [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="cancel_poll")]
    ])
    
    preview_text = f"<b>Oldindan ko'rinish (Preview):</b>\n\n{text}"
    
    if photo:
        await message.answer_photo(photo=photo, caption=preview_text, parse_html=True, reply_markup=kb)
    else:
        await message.answer(text=preview_text, parse_html=True, reply_markup=kb)
    
    await state.set_state(CreatePoll.preview)


@dp.callback_query(CreatePoll.preview, F.data == "publish_poll", F.from_user.id == ADMIN_ID)
async def publish_poll(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get("text")
    photo = data.get("photo")
    
    # Kanalga tashlash uchun pastki "Qo'shilish" tugmasi
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qo'shilish", url=f"https://t.me/{bot.username}?start=join")]
    ])
    
    try:
        if photo:
            await bot.send_photo(chat_id=CHANNEL_ID, photo=photo, caption=text, reply_markup=kb)
        else:
            await bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=kb)
            
        await callback.message.answer("✅ So'rovnoma muvaffaqiyatli kanalga yuborildi!")
    except Exception as e:
        await callback.message.answer(f"❌ Xatolik yuz berdi: {e}")
        
    await state.clear()
    await send_main_menu(callback.message)


@dp.callback_query(F.data == "close_menu")
async def close_menu(callback: types.CallbackQuery):
    await callback.message.delete()


async def main():
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
