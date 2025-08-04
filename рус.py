import asyncio
import logging
import random
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command

API_TOKEN = "8499852940:AAGlJ2Txa4rNkZ_3R2bgoPjfVZqA8BR8iYU"  # ← Замени на свой токен

from aiogram.client.default import DefaultBotProperties  # ДОБАВИТЬ импорт

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)


games = {}  # {chat_id: {...}}
last_bot_messages = {}  # chat_id -> message_id
DB_NAME = "roulette.db"

# ---------- Функция отправки с удалением прошлого сообщения ----------
async def send_and_cleanup(chat_id, text, reply_markup=None, delay=5):
    # Удалить предыдущее сообщение
    last_msg_id = last_bot_messages.get(chat_id)
    if last_msg_id:
        try:
            await bot.delete_message(chat_id, last_msg_id)
        except:
            pass

    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    last_bot_messages[chat_id] = msg.message_id

    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, msg.message_id)
        if last_bot_messages.get(chat_id) == msg.message_id:
            del last_bot_messages[chat_id]
    except:
        pass

# ---------- Клавиатуры ----------
def action_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔁 Крутить и выстрелить", callback_data="spin_shoot"),
            InlineKeyboardButton(text="🔫 Просто выстрел", callback_data="just_shoot")
        ]
    ])

def join_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Присоединиться", callback_data="join_game")]
    ])

# ---------- База данных ----------
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                balance INTEGER DEFAULT 0
            )
        ''')
        await db.commit()

# ---------- Команды ----------
dp = Dispatcher()
@dp.message(Command(commands=["рулетка", "игра", "начать"]))
async def start_game(msg: Message):
    if msg.chat.type not in {"group", "supergroup"}:
        await msg.reply("Эта команда работает только в группах.")
        return

    chat_id = msg.chat.id
    if chat_id in games:
        await send_and_cleanup(chat_id, "⚠️ Игра уже запущена.")
        return

    games[chat_id] = {
        "players": [],
        "alive": [],
        "current": 0,
        "bullet_index": random.randint(0, 5),
        "chamber_position": 0,
        "registration_msg": None
    }

    reg_msg = await msg.reply("🎯 Регистрация началась! Нажмите кнопку ниже. ⏳ 60 секунд", reply_markup=join_keyboard())
    games[chat_id]["registration_msg"] = reg_msg

    for remaining in [50, 40, 30, 20, 10]:
        await asyncio.sleep(10)
        if chat_id not in games:
            return
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=reg_msg.message_id,
                text=f"🎯 Регистрация продолжается! Осталось {remaining} секунд",
                reply_markup=join_keyboard()
            )
        except:
            pass

    await start_round(chat_id)

@dp.message(Command("cancelgame"))
async def cancel_game(msg: Message):
    chat_id = msg.chat.id
    if chat_id in games:
        del games[chat_id]
        await send_and_cleanup(chat_id, "🚫 Игра отменена.")
    else:
        await send_and_cleanup(chat_id, "Нет активной игры.")

@dp.message(Command("leaderboard"))
async def leaderboard(msg: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            SELECT username, games_won, balance FROM users
            ORDER BY balance DESC LIMIT 10
        ''')
        rows = await cursor.fetchall()

    if not rows:
        await send_and_cleanup(msg.chat.id, "Нет данных.")
        return

    text = "🏆 <b>Топ игроков:</b>\n"
    for i, (name, wins, balance) in enumerate(rows, 1):
        text += f"{i}. {name or 'Без имени'} — Побед: {wins}, 💰 ${balance}\n"

    await send_and_cleanup(msg.chat.id, text)

@dp.message(Command("mystats"))
async def mystats(msg: Message):
    user_id = msg.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            SELECT games_played, games_won, balance FROM users
            WHERE user_id = ?
        ''', (user_id,))
        row = await cursor.fetchone()

    if not row:
        await send_and_cleanup(msg.chat.id, "Вы ещё не играли.")
        return

    played, won, balance = row
    await send_and_cleanup(
        msg.chat.id,
        f"🎲 <b>Ваши статистики:</b>\nИгр сыграно: {played}\nПобед: {won}\n💰 Баланс: ${balance}"
    )

@dp.callback_query(lambda c: c.data == "join_game")
async def join_game(callback: CallbackQuery):
    user = callback.from_user
    chat_id = callback.message.chat.id

    game = games.get(chat_id)
    if not game:
        await callback.answer("⛔ Регистрация завершена.")
        return

    user_data = (user.id, user.username or user.full_name)
    if user_data in game["players"]:
        await callback.answer("Вы уже зарегистрированы.")
        return

    game["players"].append(user_data)
    await callback.answer("Вы зарегистрированы!")
    await send_and_cleanup(chat_id, f"👤 {user_data[1]} присоединился к игре.")

# ---------- Игра ----------
async def start_round(chat_id):
    game = games.get(chat_id)
    if not game or len(game["players"]) < 2:
        await send_and_cleanup(chat_id, "Недостаточно игроков. Игра отменена.")
        games.pop(chat_id, None)
        return

    game["alive"] = game["players"][:]
    game["current"] = 0
    game["bullet_index"] = random.randint(0, 5)
    game["chamber_position"] = 0

    await send_and_cleanup(chat_id, f"🔫 Игра начинается!\nИгроков: {len(game['alive'])}")
    await next_turn(chat_id)

async def next_turn(chat_id):
    game = games.get(chat_id)
    if not game or len(game["alive"]) < 2:
        if game and len(game["alive"]) == 1:
            winner = game["alive"][0]
            await send_and_cleanup(chat_id, f"🏆 Победитель: <b>{winner[1]}</b>! Он получает $10.")
            await update_stats(winner[0], winner[1], win=True)
        games.pop(chat_id, None)
        return

    current = game["alive"][game["current"]]
    msg = await bot.send_message(
        chat_id,
        f"👉 Ходит <b>{current[1]}</b>\nВыберите действие:",
        reply_markup=action_keyboard()
    )
    last_bot_messages[chat_id] = msg.message_id  # сохраняем

@dp.callback_query(lambda c: c.data in {"spin_shoot", "just_shoot"})
async def handle_shot(callback: CallbackQuery):
    user = callback.from_user
    chat_id = callback.message.chat.id
    game = games.get(chat_id)

    if not game:
        await callback.answer("Игра завершена.")
        return

    current_player = game["alive"][game["current"]]
    if user.id != current_player[0]:
        await callback.answer("⛔ Сейчас не ваш ход.")
        return

    spin = callback.data == "spin_shoot"
    if spin:
        game["chamber_position"] = random.randint(0, 5)

    fired = game["chamber_position"] == game["bullet_index"]

    if fired:
        await callback.message.edit_text(f"💥 <b>{current_player[1]}</b> выстрелил... и проиграл!")
        game["alive"].pop(game["current"])
        await update_stats(user.id, user.username or user.full_name, win=False)
        game["bullet_index"] = random.randint(0, 5)
        game["chamber_position"] = 0
        if game["current"] >= len(game["alive"]):
            game["current"] = 0
    else:
        await callback.message.edit_text(f"😅 <b>{current_player[1]}</b> выстрелил и выжил.")
        game["chamber_position"] = (game["chamber_position"] + 1) % 6
        game["current"] = (game["current"] + 1) % len(game["alive"])

    await next_turn(chat_id)

# ---------- Статистика ----------
async def update_stats(user_id, username, win=False):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT INTO users (user_id, username)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO NOTHING
        ''', (user_id, username))
        await db.execute('''
            UPDATE users
            SET games_played = games_played + 1
            WHERE user_id = ?
        ''', (user_id,))
        if win:
            await db.execute('''
                UPDATE users
                SET games_won = games_won + 1, balance = balance + 10
                WHERE user_id = ?
            ''', (user_id,))
        await db.commit()

# ---------- Запуск ----------
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
