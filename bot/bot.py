import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from dotenv import load_dotenv

# Загружаем переменные из файла .env
load_dotenv()

# Достаём токен
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Токен не найден! Проверь файл .env")

# Достаём список разрешённых ID (пока оставим пустым или своим)
ALLOWED_IDS = os.getenv("ALLOWED_USER_IDS", "").split(",")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    # Проверка доступа (если список ID не пустой)
    user_id = str(message.from_user.id)
    if ALLOWED_IDS and ALLOWED_IDS[0] != "" and user_id not in ALLOWED_IDS:
        await message.answer("У тебя нет доступа к этому боту.")
        return

    await message.answer(
        "Привет! Я PlanHub Bot.\n"
        "Каркас успешно запущен!\n\n"
        "Скоро здесь появятся:\n"
        "📂 Мои категории\n"
        "📅 Расписание\n"
        "⏰ Дедлайны\n"
        "🔔 Уведомления"
    )

async def main():
    print("Бот запущен и ждёт сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
