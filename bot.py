import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = "SIZNING_BOT_TOKENINGIZ"
CHANNEL_USERNAME = "@smm_veko"  # Majburiy obuna kanali

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Vaqtinchalik baza (real loyihada SQLite yoki PostgreSQL ishlatiladi)
# votes = {voter_id: candidate_id}
votes = {}
# participants = [user_id1, user_id2, ...]
participants = []


# Kanaga obuna bo'lganligini tekshirish funksiyasi
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        # Agar a'zo bo'lsa (creator, administrator, member)
        if member.status in ["creator", "administrator", "member"]:
            return True
    except Exception:
        pass
    return False


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    
    # Obunani tekshiramiz
    is_subscribed = await check_subscription(user_id)
    
    if not is_subscribed:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")]
        ])
        await message.answer(
            "⚠️ Ovoz berish uchun avval quyidagi kanalga obuna bo'lishingiz kerak:",
            reply_markup=keyboard
        )
        return

    await show_main_menu(message)


async def show_main_menu(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Konkursga qo'shilish (Nik qo'shish)", callback_data="join_contest")],
        [InlineKeyboardButton(text="🏆 Ovoz berish sahifasi", callback_data="vote_page")]
    ])
    await message.answer("Xush kelibsiz! Kerakli bo'limni tanlang:", reply_markup=keyboard)


# Obunani tekshirish tugmasi
@dp.callback_query(F.data == "check_sub")
async def process_check_sub(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await callback.message.delete()
        await callback.message.answer("Rahmat! Endi davom etishingiz mumkin.")
        await show_main_menu(callback.message)
    else:
        await callback.answer("Siz hali kanalga obuna bo'lmadingiz!", show_alert=True)


# Konkursga qo'shilish (Nik qo'shish)
@dp.callback_query(F.data == "join_contest")
async def join_contest(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in participants:
        participants.append(user_id)
        await callback.answer("Siz muvaffaqiyatli ro'yxatga qo'shildingiz!", show_alert=True)
    else:
        await callback.answer("Siz allaqachon ro'yxatdasiz!", show_alert=True)


# Kanal tark etganda ovozni avtof qilib tashlash (Chat Member Update)
@dp.chat_member()
async def on_user_leave(event: types.ChatMemberUpdated):
    if event.chat.username == CHANNEL_USERNAME.replace("@", ""):
        # Agar foydalanuvchi kanaldan chiqqan bo'lsa
        if event.old_chat_member.status in ["member", "administrator"] and event.new_chat_member.status == "left":
            user_id = event.from_user.id
            # Agar u ovoz bergan bo'lsa, ovozini o'chiramiz
            if user_id in votes:
                candidate_id = votes[user_id]
                del votes[user_id]
                # Bu yerda bazadan ham ovozni ayirib tashlash logikasini yozasiz
                print(f"Foydalanuvchi {user_id} kanaldan chiqqani uchun uning ovozi bekor qilindi.")


async def main():
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
