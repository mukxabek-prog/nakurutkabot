import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = "8952379767:AAEFYcjaQf-d7fc1NjUBKD_rQPgVCHwjz-U"
ADMIN_ID = 8866852203
CHANNEL_ID = "@Chanel_trade"  
CHANNEL_USERNAME = "trade_chanel_uz" 

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Ishtirokchilarni va ovozlarni saqlash uchun bazalar
# participants = {user_id: {"name": "Ism", "votes": 0}}
participants = {}
# voted_users = {voter_user_id: candidate_user_id} (Kim kimga ovoz bergani)
voted_users = {}

class CreatePoll(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()


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
    
    # Agar start orqali ovoz berish uchun kelgan bo'lsa (masalan: ?start=vote_12345)
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("vote_"):
        candidate_id = int(args[1].split("_")[1])
        
        # Obunani tekshiramiz
        if not await check_subscription(user_id):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_USERNAME}")],
                [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data=f"check_vote_{candidate_id}")]
            ])
            await message.answer("⚠️ Ovoz berish uchun avval kanalimizga obuna bo'ling:", reply_markup=kb)
            return
        
        await process_vote(message, user_id, candidate_id)
        return

    # Oddiy start
    if not await check_subscription(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_USERNAME}")],
            [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")]
        ])
        await message.answer("⚠️ Botdan foydalanish uchun avval kanalimizga obuna bo'ling:", reply_markup=kb)
        return

    kb = []
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton(text="⚙️ Admin Panel", callback_data="admin_panel")])
    
    kb.append([InlineKeyboardButton(text="🏆 Konkursga ishtirokchi qo'shish (Nik yuborish)", callback_data="add_participant")])
    
    await message.answer("🎉 Xush kelibsiz! Konkurs botidasiz.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# Ishtirokchi o'z nikini yuboradi
@dp.callback_query(F.data == "add_participant")
async def ask_participant_name(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Konkursda qatnashish uchun o'zingizning nik yoki ismingizni yuboring:")
    await state.set_state("waiting_for_name")
    await callback.answer()

@dp.message(F.state == "waiting_for_name")
async def save_participant(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    name = message.text
    participants[user_id] = {"name": name, "votes": 0}
    await state.clear()
    await message.answer(f"✅ Tabriklayman, **{name}**! Siz konkurs ro'yxatiga qo'shildingiz.")


# Obunani tekshirib ovozni qabul qilish
@dp.callback_query(F.data.startswith("check_vote_"))
async def process_check_vote(callback: types.CallbackQuery):
    candidate_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if await check_subscription(user_id):
        await callback.message.delete()
        await process_vote(callback.message, user_id, candidate_id)
    else:
        await callback.answer("Siz hali kanalga obuna bo'lmadingiz!", show_alert=True)


async def process_vote(message: types.Message, user_id: int, candidate_id: int):
    if user_id in voted_users:
        await message.answer("⚠️ Siz allaqachon ovoz bergansiz! Bir kishi faqat 1 marta ovoz berishi mumkin.")
        return
    
    if candidate_id not in participants:
        await message.answer("❌ Bu ishtirokchi topilmadi yoki konkurs tugagan.")
        return
        
    if user_id == candidate_id:
        await message.answer("❌ O'zingizga o'zingiz ovoz bera olmaysiz!")
        return

    # Ovozni qo'shamiz
    voted_users[user_id] = candidate_id
    participants[candidate_id]["votes"] += 1
    
    candidate_name = participants[candidate_id]["name"]
    votes_count = participants[candidate_id]["votes"]
    
    await message.answer(f"✅ Ovozingiz muvaffaqiyatli qabul qilindi!\n\n🏆 Ishtirokchi: <b>{candidate_name}</b>\n⭐ Jami ovozlar: {votes_count} ta\n\nRahmat! Rahmat!")


# --- ADMIN PANEL ---
@dp.callback_query(F.data == "admin_panel", F.from_user.id == ADMIN_ID)
async def admin_panel(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga Battle (Ovoz) postini tashlash", callback_data="publish_battle")],
        [InlineKeyboardButton(text="❌ Chiqish", callback_data="close_menu")]
    ])
    await callback.message.edit_text("🔧 Admin panel:", reply_markup=kb)


@dp.callback_query(F.data == "publish_battle", F.from_user.id == ADMIN_ID)
async def publish_battle_post(callback: types.CallbackQuery):
    if not participants:
        await callback.answer("Hozircha ishtirokchilar yo'q!", show_alert=True)
        return

    bot_info = await bot.get_me()
    
    # Har bir ishtirokchi uchun alohida ovoz berish tugmasini yasaymiz
    keyboard_buttons = []
    for u_id, data in participants.items():
        btn_text = f"{data['name']} — {data['votes']} 🗳"
        btn_url = f"https://t.me/{bot_info.username}?start=vote_{u_id}"
        keyboard_buttons.append([InlineKeyboardButton(text=btn_text, url=btn_url)])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    text = "🏆 **BATL BOSHLANDI!** 🥳\n\nQuyidagi ishtirokchilardan biriga ovoz bering:"
    
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.message.answer("✅ Battle posti kanalga yuborildi!")
    except Exception as e:
        await callback.message.answer(f"❌ Xatolik: {e}")


@dp.callback_query(F.data == "close_menu")
async def close_menu(callback: types.CallbackQuery):
    await callback.message.delete()


async def main():
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
