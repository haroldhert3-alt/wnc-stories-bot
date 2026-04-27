import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, PhotoSize
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

class BotStates(StatesGroup):
    waiting_for_photo = State()
    waiting_for_details = State()
    waiting_for_choice = State()
    waiting_for_approval = State()

def load_prompt():
    with open("system_prompt.txt", "r", encoding="utf-8") as f:
        return f.read().strip()

@dp.message(F.text == "/start")
async def start(message: Message, state: FSMContext):
    await message.answer(
        "Привет! Я бот для генерации сторитейлов.\n\n"
        "Отправь фото, а потом напиши данные:\n\n"
        "ГЕО (2 буквы)\n"
        "Название приложения\n"
        "Сумма выигрыша\n"
        "Доп. контекст (опционально)"
    )
    await state.set_state(BotStates.waiting_for_photo)

@dp.message(BotStates.waiting_for_photo, F.photo)
async def handle_photo(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    
    await state.update_data(photo_url=photo_url)
    await message.answer("Фото получил! Теперь пришли данные в формате:\nГЕО\nПриложение\nСумма\nДоп. контекст")
    await state.set_state(BotStates.waiting_for_details)

@dp.message(BotStates.waiting_for_details)
async def process_details(message: Message, state: FSMContext):
    lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
    
    if len(lines) < 3:
        await message.answer("Нужно минимум 3 строки")
        return

    geo = lines[0].upper()
    app_name = lines[1]
    win_amount = lines[2]
    extra = '\n'.join(lines[3:]) if len(lines) > 3 else ""

    data = await state.get_data()
    photo_url = data["photo_url"]

    vision = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Опиши фото подробно: кто на фото, эмоции, обстановка."},
                {"type": "image_url", "image_url": {"url": photo_url}}
            ]
        }],
        max_tokens=500
    )
    photo_desc = vision.choices[0].message.content.strip()

    await state.update_data(geo=geo, app_name=app_name, win_amount=win_amount, extra=extra, photo_desc=photo_desc)

    prompt = f"""Создай ровно 3 коротких варианта (по 3-5 предложений).

ГЕО: {geo}
Приложение: {app_name}
Сумма: {win_amount}
Описание фото: {photo_desc}
Доп. контекст: {extra}"""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": load_prompt()},
            {"role": "user", "content": prompt}
        ],
        temperature=0.85
    )

    variants = response.choices[0].message.content.strip()
    await message.answer(f"Вот 3 варианта:\n\n{variants}\n\nНапиши номер (1-3)")
    await state.set_state(BotStates.waiting_for_choice)

@dp.message(BotStates.waiting_for_choice)
async def generate_full_story(message: Message, state: FSMContext):
    choice = message.text.strip()
    data = await state.get_data()

    prompt = f"""Напиши ПОЛНУЮ историю на русском (500-650 слов).

ГЕО: {data['geo']}
Приложение: {data['app_name']}
Сумма: {data['win_amount']}
Описание фото: {data['photo_desc']}
Доп. контекст: {data['extra']}
Вариант: {choice}"""

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": load_prompt()},
            {"role": "user", "content": prompt}
        ],
        temperature=0.75,
        max_tokens=2800
    )

    full_story = response.choices[0].message.content.strip()
    await message.answer(full_story + "\n\nНапиши 'ОК' или пришли правки.")
    await state.update_data(full_story=full_story)
    await state.set_state(BotStates.waiting_for_approval)

@dp.message(BotStates.waiting_for_approval)
async def handle_approval(message: Message, state: FSMContext):
    if message.text.strip().upper() == "ОК":
        data = await state.get_data()
        prompt = f"Переведи на язык {data['geo']}:\n\n{data['full_story']}"

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        await message.answer("Готово!\n\n" + response.choices[0].message.content.strip())
        await state.clear()
    else:
        data = await state.get_data()
        prompt = f"Улучши историю с учётом: {message.text}\n\n{data['full_story']}"

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2800
        )
        await message.answer(response.choices[0].message.content.strip() + "\n\n'ОК' для перевода или новые правки.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())