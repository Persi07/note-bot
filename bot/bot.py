import os
import logging
import sqlite3
import asyncio
from datetime import datetime, date

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_IDS_STR = os.getenv("ALLOWED_USER_IDS", "")

if not BOT_TOKEN:
    print("Error: BOT_TOKEN is missing in .env file.")
    exit(1)

# Parse allowed user IDs
allowed_ids = set()
if ALLOWED_USER_IDS_STR.strip():
    for uid in ALLOWED_USER_IDS_STR.split(","):
        uid = uid.strip()
        if uid:
            try:
                allowed_ids.add(int(uid))
            except ValueError:
                pass

# Database setup
DB_PATH = "data/database.db"
os.makedirs("data", exist_ok=True)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                title TEXT DEFAULT '',
                text TEXT,
                created_at TEXT
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                title TEXT,
                description TEXT,
                due_date TEXT,
                is_done INTEGER DEFAULT 0
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                title TEXT,
                url TEXT
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                weekday INTEGER,
                time_start TEXT,
                title TEXT,
                event_type TEXT,
                location TEXT,
                category_id INTEGER
            )
        """)
        
        conn.commit()

def migrate_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(notes)")
            columns = [row[1] for row in cur.fetchall()]
            if 'title' not in columns:
                cur.execute("ALTER TABLE notes ADD COLUMN title TEXT DEFAULT ''")
                conn.commit()
                logging.info("Added title column to notes table")
        except Exception as e:
            logging.exception("Error during database migration")

init_db()
migrate_db()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot and Dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# States
class CategoryStates(StatesGroup):
    waiting_for_name = State()
    renaming_category = State()

class NoteStates(StatesGroup):
    adding_title = State()
    adding_text = State()
    editing_title = State()
    editing_text = State()

class TaskStates(StatesGroup):
    adding_title = State()
    adding_description = State()
    adding_due_date = State()
    editing_title = State()
    editing_description = State()
    editing_due_date = State()

class LinkStates(StatesGroup):
    adding_title = State()
    adding_url = State()
    editing_title = State()
    editing_url = State()

class ScheduleStates(StatesGroup):
    adding_title = State()
    adding_weekday = State()
    adding_time = State()
    adding_event_type = State()
    adding_location = State()
    adding_category = State()
    editing_title = State()
    editing_time = State()
    editing_event_type = State()
    editing_location = State()
    editing_category = State()

# Helper functions
def check_access(user_id: int) -> bool:
    if not allowed_ids:
        return True
    return user_id in allowed_ids

def save_user(telegram_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (telegram_id,))
        conn.commit()

def get_user_id_by_telegram_id(telegram_id: int) -> int | None:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cur.fetchone()
        return row[0] if row else None

def format_date(iso_str: str | None) -> str:
    if not iso_str:
        return "Не указан"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d.%m.%Y")
    except:
        return "Не указана"

def parse_date(date_str: str) -> str | None:
    try:
        dt = datetime.strptime(date_str, "%d.%m.%Y")
        return dt.isoformat()
    except:
        return None

def get_weekday_name(weekday: int) -> str:
    names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return names[weekday] if 0 <= weekday <= 6 else ""

# Keyboards
def main_menu_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="📂 Мои категории")
    kb.button(text="📅 Расписание")
    kb.button(text="⏰ Дедлайны")
    kb.button(text="❓ Помощь")
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

def category_list_kb(categories: list, has_categories: bool):
    kb = InlineKeyboardBuilder()
    if has_categories:
        for cat in categories:
            kb.button(text=f"{cat[2]}", callback_data=f"cat_{cat[0]}")
        kb.adjust(1)
    kb.button(text="➕ Создать категорию", callback_data="create_cat")
    kb.button(text="⬅️ Главное меню", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()

def category_card_kb(cat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Заметки", callback_data=f"notes_{cat_id}")
    kb.button(text="✅ Задачи", callback_data=f"tasks_{cat_id}")
    kb.button(text="🔗 Ссылки", callback_data=f"links_{cat_id}")
    kb.button(text="✏️ Переименовать", callback_data=f"rename_cat_{cat_id}")
    kb.button(text="🗑 Удалить", callback_data=f"del_cat_confirm_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data="back_to_categories")
    kb.adjust(2, 2, 2)
    return kb.as_markup()

def notes_list_kb(notes: list, cat_id: int):
    kb = InlineKeyboardBuilder()
    for note in notes:
        display_text = note[2] if note[2] else (note[3][:30] + "..." if len(note[3]) > 30 else note[3])
        kb.button(text=display_text, callback_data=f"note_{note[0]}")
    kb.adjust(1)
    kb.button(text="➕ Добавить заметку", callback_data=f"add_note_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
    kb.adjust(1)
    return kb.as_markup()

def note_card_kb(note_id: int, cat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить", callback_data=f"edit_note_menu_{note_id}_{cat_id}")
    kb.button(text="🗑 Удалить", callback_data=f"del_note_{note_id}_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"back_to_notes_{cat_id}")
    kb.adjust(1)
    return kb.as_markup()

def edit_note_menu_kb(note_id: int, cat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить название", callback_data=f"edit_note_title_{note_id}_{cat_id}")
    kb.button(text="Изменить описание", callback_data=f"edit_note_text_{note_id}_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"note_{note_id}")
    kb.adjust(1)
    return kb.as_markup()

def tasks_list_kb(tasks: list, cat_id: int):
    kb = InlineKeyboardBuilder()
    for task in tasks:
        status = "выполнена" if task[5] else "активна"
        kb.button(text=f"{task[2]} — {status}", callback_data=f"task_{task[0]}")
    kb.adjust(1)
    kb.button(text="➕ Добавить задачу", callback_data=f"add_task_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
    kb.adjust(1)
    return kb.as_markup()

def task_card_kb(task_id: int, cat_id: int, is_done: bool):
    kb = InlineKeyboardBuilder()
    if is_done:
        kb.button(text="↩️ Вернуть в работу", callback_data=f"toggle_task_{task_id}_{cat_id}")
    else:
        kb.button(text="✅ Отметить выполненной", callback_data=f"toggle_task_{task_id}_{cat_id}")
    kb.button(text="✏️ Изменить", callback_data=f"edit_task_menu_{task_id}_{cat_id}")
    kb.button(text="🗑 Удалить", callback_data=f"del_task_{task_id}_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"back_to_tasks_{cat_id}")
    kb.adjust(1)
    return kb.as_markup()

def edit_task_menu_kb(task_id: int, cat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить название", callback_data=f"edit_task_title_{task_id}_{cat_id}")
    kb.button(text="Изменить описание", callback_data=f"edit_task_desc_{task_id}_{cat_id}")
    kb.button(text="Изменить дедлайн", callback_data=f"edit_task_date_{task_id}_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"task_{task_id}")
    kb.adjust(1)
    return kb.as_markup()

def links_list_kb(links: list, cat_id: int):
    kb = InlineKeyboardBuilder()
    for link in links:
        kb.button(text=link[2], callback_data=f"link_{link[0]}")
    kb.adjust(1)
    kb.button(text="➕ Добавить ссылку", callback_data=f"add_link_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
    kb.adjust(1)
    return kb.as_markup()

def link_card_kb(link_id: int, cat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить", callback_data=f"edit_link_menu_{link_id}_{cat_id}")
    kb.button(text="🗑 Удалить", callback_data=f"del_link_{link_id}_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"back_to_links_{cat_id}")
    kb.adjust(1)
    return kb.as_markup()

def edit_link_menu_kb(link_id: int, cat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить название", callback_data=f"edit_link_title_{link_id}_{cat_id}")
    kb.button(text="Изменить ссылку", callback_data=f"edit_link_url_{link_id}_{cat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"link_{link_id}")
    kb.adjust(1)
    return kb.as_markup()

def deadlines_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🧹 Удалить просроченные", callback_data="delete_overdue")
    kb.button(text="⬅️ Главное меню", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()

def schedule_main_kb(counts: dict):
    kb = InlineKeyboardBuilder()
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i, day in enumerate(days):
        count = counts.get(i, 0)
        kb.button(text=f"{day} ({count})", callback_data=f"schedule_day_{i}")
    kb.adjust(2, 2, 2, 1)
    kb.button(text="📆 Вся неделя", callback_data="schedule_week")
    kb.button(text="➕ Добавить событие", callback_data="schedule_add")
    kb.button(text="⬅️ Назад", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()

def schedule_day_kb(events: list, weekday: int):
    kb = InlineKeyboardBuilder()
    for event in events:
        kb.button(text=f"{event[3]} {event[4]}", callback_data=f"schedule_event_{event[0]}")
    kb.adjust(1)
    kb.button(text="➕ Добавить событие", callback_data="schedule_add")
    kb.button(text="⬅️ Назад", callback_data="schedule_main")
    kb.adjust(1)
    return kb.as_markup()

def schedule_event_kb(event_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить", callback_data=f"schedule_edit_menu_{event_id}")
    kb.button(text="🗑 Удалить", callback_data=f"schedule_del_confirm_{event_id}")
    kb.button(text="⬅️ Назад", callback_data=f"schedule_day_{0}")
    kb.adjust(1)
    return kb.as_markup()

def schedule_edit_menu_kb(event_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить название", callback_data=f"schedule_edit_title_{event_id}")
    kb.button(text="Изменить время", callback_data=f"schedule_edit_time_{event_id}")
    kb.button(text="Изменить тип", callback_data=f"schedule_edit_type_{event_id}")
    kb.button(text="Изменить место", callback_data=f"schedule_edit_location_{event_id}")
    kb.button(text="Изменить категорию", callback_data=f"schedule_edit_category_{event_id}")
    kb.button(text="⬅️ Назад", callback_data=f"schedule_event_{event_id}")
    kb.adjust(1)
    return kb.as_markup()

def schedule_weekday_select_kb():
    kb = InlineKeyboardBuilder()
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i, day in enumerate(days):
        kb.button(text=day, callback_data=f"schedule_add_wd_{i}")
    kb.adjust(4, 3)
    kb.button(text="⬅️ Отмена", callback_data="schedule_cancel")
    kb.adjust(1)
    return kb.as_markup()

def schedule_event_type_kb():
    kb = InlineKeyboardBuilder()
    types = ["занятие", "встреча", "работа", "личное"]
    for t in types:
        kb.button(text=t, callback_data=f"schedule_add_type_{t}")
    kb.adjust(2)
    kb.button(text="⬅️ Отмена", callback_data="schedule_cancel")
    kb.adjust(1)
    return kb.as_markup()

def schedule_category_select_kb(categories: list):
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat[2], callback_data=f"schedule_add_cat_{cat[0]}")
    kb.button(text="Без категории", callback_data="schedule_add_cat_none")
    kb.adjust(1)
    kb.button(text="⬅️ Отмена", callback_data="schedule_cancel")
    kb.adjust(1)
    return kb.as_markup()

def schedule_edit_category_select_kb(categories: list, event_id: int):
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat[2], callback_data=f"schedule_edit_cat_{event_id}_{cat[0]}")
    kb.button(text="Без категории", callback_data=f"schedule_edit_cat_{event_id}_none")
    kb.adjust(1)
    kb.button(text="⬅️ Назад", callback_data=f"schedule_edit_menu_{event_id}")
    kb.adjust(1)
    return kb.as_markup()

# Handlers

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    await state.clear()
    save_user(message.from_user.id)
    await message.answer(
        "Привет! Я твой помощник для заметок и задач.",
        reply_markup=main_menu_kb()
    )

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_kb())

@dp.message(F.text == "📅 Расписание")
async def show_schedule(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    await state.clear()
    user_db_id = get_user_id_by_telegram_id(message.from_user.id)
    if not user_db_id:
        save_user(message.from_user.id)
        user_db_id = get_user_id_by_telegram_id(message.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT weekday, COUNT(*) FROM schedule WHERE user_id = ? GROUP BY weekday", (user_db_id,))
        rows = cur.fetchall()
    
    counts = {row[0]: row[1] for row in rows}
    
    await message.answer("Расписание:", reply_markup=schedule_main_kb(counts))

@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: Message):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    text = """Это бот для хранения заметок, задач, дедлайнов и ссылок.
Разделы:
📂 Мои категории — управление категориями, заметками, задачами и ссылками.
📅 Расписание — управление событиями по дням недели.
⏰ Дедлайны — список ближайших задач."""
    await message.answer(text, reply_markup=main_menu_kb())

@dp.message(F.text == "📂 Мои категории")
async def show_categories(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    await state.clear()
    user_db_id = get_user_id_by_telegram_id(message.from_user.id)
    if not user_db_id:
        save_user(message.from_user.id)
        user_db_id = get_user_id_by_telegram_id(message.from_user.id)
        
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM categories WHERE user_id = ?", (user_db_id,))
        categories = cur.fetchall()
        
    if not categories:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Создать категорию", callback_data="create_cat")
        kb.button(text="⬅️ Главное меню", callback_data="main_menu")
        kb.adjust(1)
        await message.answer("У тебя пока нет категорий.\nДобавить первую категорию.", reply_markup=kb.as_markup())
    else:
        await message.answer("Выберите категорию:", reply_markup=category_list_kb(categories, True))

@dp.message(F.text == "⏰ Дедлайны")
async def show_deadlines(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
        
    await state.clear()
    user_db_id = get_user_id_by_telegram_id(message.from_user.id)
    if not user_db_id:
        save_user(message.from_user.id)
        user_db_id = get_user_id_by_telegram_id(message.from_user.id)
        
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        query = """
            SELECT t.*, c.name as category_name 
            FROM tasks t
            JOIN categories c ON t.category_id = c.id
            WHERE c.user_id = ? AND t.is_done = 0 AND t.due_date IS NOT NULL
            ORDER BY t.due_date ASC
        """
        cur.execute(query, (user_db_id,))
        tasks = cur.fetchall()
        
    if not tasks:
        await message.answer("Активных задач с дедлайнами пока нет.", reply_markup=deadlines_kb())
    else:
        lines = []
        for task in tasks:
            status = "Выполнена" if task[5] else "Активна"
            lines.append(f"Категория: {task[6]}\nНазвание: {task[2]}\nДедлайн: {format_date(task[4])}\nСтатус: {status}\n---")
        await message.answer("\n".join(lines), reply_markup=deadlines_kb())

# ============================================================================
# STATE HANDLERS - MUST BE BEFORE CATCH-ALL HANDLER
# ============================================================================

@dp.message(CategoryStates.waiting_for_name)
async def handle_new_category_name(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received category name from user {message.from_user.id}: {message.text}")
    name = message.text.strip()
    if not name:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
        
    user_db_id = get_user_id_by_telegram_id(message.from_user.id)
    if not user_db_id:
        save_user(message.from_user.id)
        user_db_id = get_user_id_by_telegram_id(message.from_user.id)
        
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (user_db_id, name))
            conn.commit()
        except Exception as e:
            logging.exception("Database error while creating category")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM categories WHERE user_id = ?", (user_db_id,))
        categories = cur.fetchall()
        
    await message.answer("Категория создана!", reply_markup=category_list_kb(categories, True))

@dp.message(CategoryStates.renaming_category)
async def handle_rename_category(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received new category name from user {message.from_user.id}: {message.text}")
    data = await state.get_data()
    cat_id = data.get("cat_id")
    new_name = message.text.strip()
    
    if not new_name:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
    
    user_db_id = get_user_id_by_telegram_id(message.from_user.id)
        
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE categories SET name = ? WHERE id = ? AND user_id = ?", (new_name, cat_id, user_db_id))
            conn.commit()
            cur.execute("SELECT * FROM categories WHERE id = ?", (cat_id,))
            category = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while renaming category")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    if category:
        await message.answer(f"Категория переименована в: {category[2]}", reply_markup=category_card_kb(cat_id))
    else:
        await message.answer("Запись не найдена.")

@dp.message(NoteStates.adding_title)
async def handle_new_note_title(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received note title from user {message.from_user.id}: {message.text}")
    title = message.text.strip()
    
    await state.update_data(title=title)
    await state.set_state(NoteStates.adding_text)
    await message.answer("Введите текст/описание заметки:")

@dp.message(NoteStates.adding_text)
async def handle_new_note_text(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received note text from user {message.from_user.id}")
    data = await state.get_data()
    cat_id = data.get("cat_id")
    title = data.get("title")
    text = message.text.strip()
    
    if not text:
        await message.answer("Текст не может быть пустым. Попробуйте снова:")
        return
        
    now = datetime.now().isoformat()
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO notes (category_id, title, text, created_at) VALUES (?, ?, ?, ?)", (cat_id, title, text, now))
            conn.commit()
            cur.execute("SELECT * FROM notes WHERE category_id = ?", (cat_id,))
            notes = cur.fetchall()
        except Exception as e:
            logging.exception("Database error while creating note")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    await message.answer("Заметка добавлена!", reply_markup=notes_list_kb(notes, cat_id))

@dp.message(NoteStates.editing_title)
async def handle_edit_note_title(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Editing note title from user {message.from_user.id}")
    data = await state.get_data()
    note_id = data.get("note_id")
    cat_id = data.get("cat_id")
    new_title = message.text.strip()
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE notes SET title = ? WHERE id = ?", (new_title, note_id))
            conn.commit()
            cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            note = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while updating note title")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    if note:
        title_display = note[2] if note[2] else "Без названия"
        text_display = note[3] if note[3] else "Без описания"
        logger.info(f"Note {note_id} title updated successfully")
        await message.answer(f"Название: {title_display}\n\n{text_display}", reply_markup=note_card_kb(note_id, cat_id))
    else:
        await message.answer("Запись не найдена.")

@dp.message(NoteStates.editing_text)
async def handle_edit_note_text(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Editing note text from user {message.from_user.id}")
    data = await state.get_data()
    note_id = data.get("note_id")
    cat_id = data.get("cat_id")
    new_text = message.text.strip()
    
    if not new_text:
        await message.answer("Текст не может быть пустым. Попробуйте снова:")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE notes SET text = ? WHERE id = ?", (new_text, note_id))
            conn.commit()
            cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            note = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while updating note text")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    if note:
        title_display = note[2] if note[2] else "Без названия"
        text_display = note[3] if note[3] else "Без описания"
        logger.info(f"Note {note_id} text updated successfully")
        await message.answer(f"Название: {title_display}\n\n{text_display}", reply_markup=note_card_kb(note_id, cat_id))
    else:
        await message.answer("Запись не найдена.")

@dp.message(TaskStates.adding_title)
async def handle_task_title(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received task title from user {message.from_user.id}")
    title = message.text.strip()
    if not title:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
        
    await state.update_data(title=title)
    await state.set_state(TaskStates.adding_description)
    await message.answer("Введите описание задачи (или '-' если нет описания):")

@dp.message(TaskStates.adding_description)
async def handle_task_description(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received task description from user {message.from_user.id}")
    desc = message.text.strip()
    if desc == "-":
        desc = ""
        
    await state.update_data(description=desc)
    await state.set_state(TaskStates.adding_due_date)
    await message.answer("Введите дедлайн в формате ДД.ММ.ГГГГ:")

@dp.message(TaskStates.adding_due_date)
async def handle_task_due_date(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received task due date from user {message.from_user.id}: {message.text}")
    date_str = message.text.strip()
    iso_date = parse_date(date_str)
    
    if not iso_date:
        await message.answer("Неверный формат даты. Пожалуйста, введите в формате ДД.ММ.ГГГГ:")
        return
        
    data = await state.get_data()
    cat_id = data.get("cat_id")
    title = data.get("title")
    description = data.get("description")
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tasks (category_id, title, description, due_date) VALUES (?, ?, ?, ?)",
                (cat_id, title, description, iso_date)
            )
            conn.commit()
            cur.execute("SELECT * FROM tasks WHERE category_id = ?", (cat_id,))
            tasks = cur.fetchall()
        except Exception as e:
            logging.exception("Database error while creating task")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    await message.answer("Задача добавлена!", reply_markup=tasks_list_kb(tasks, cat_id))

@dp.message(TaskStates.editing_title)
async def handle_edit_task_title(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Editing task title from user {message.from_user.id}")
    data = await state.get_data()
    task_id = data.get("task_id")
    cat_id = data.get("cat_id")
    new_title = message.text.strip()
    
    if not new_title:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE tasks SET title = ? WHERE id = ?", (new_title, task_id))
            conn.commit()
            cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            task = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while updating task title")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    if task:
        desc_text = task[3] if task[3] else "Нет описания"
        logger.info(f"Task {task_id} title updated successfully")
        text = f"Название: {task[2]}\nОписание: {desc_text}\nДедлайн: {format_date(task[4])}\nСтатус: {'Выполнена' if task[5] else 'Активна'}"
        await message.answer(text, reply_markup=task_card_kb(task_id, cat_id, task[5]))
    else:
        await message.answer("Запись не найдена.")

@dp.message(TaskStates.editing_description)
async def handle_edit_task_description(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Editing task description from user {message.from_user.id}")
    data = await state.get_data()
    task_id = data.get("task_id")
    cat_id = data.get("cat_id")
    new_desc = message.text.strip()
    
    if new_desc == "-":
        new_desc = ""
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE tasks SET description = ? WHERE id = ?", (new_desc, task_id))
            conn.commit()
            cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            task = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while updating task description")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    if task:
        desc_text = task[3] if task[3] else "Нет описания"
        logger.info(f"Task {task_id} description updated successfully")
        text = f"Название: {task[2]}\nОписание: {desc_text}\nДедлайн: {format_date(task[4])}\nСтатус: {'Выполнена' if task[5] else 'Активна'}"
        await message.answer(text, reply_markup=task_card_kb(task_id, cat_id, task[5]))
    else:
        await message.answer("Запись не найдена.")

@dp.message(TaskStates.editing_due_date)
async def handle_edit_task_due_date(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Editing task due date from user {message.from_user.id}")
    data = await state.get_data()
    task_id = data.get("task_id")
    cat_id = data.get("cat_id")
    date_str = message.text.strip()
    iso_date = parse_date(date_str)
    
    if not iso_date:
        await message.answer("Неверный формат даты. Введите в формате ДД.ММ.ГГГГ:")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (iso_date, task_id))
            conn.commit()
            cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            task = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while updating task due date")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    if task:
        desc_text = task[3] if task[3] else "Нет описания"
        logger.info(f"Task {task_id} due date updated successfully")
        text = f"Название: {task[2]}\nОписание: {desc_text}\nДедлайн: {format_date(task[4])}\nСтатус: {'Выполнена' if task[5] else 'Активна'}"
        await message.answer(text, reply_markup=task_card_kb(task_id, cat_id, task[5]))
    else:
        await message.answer("Запись не найдена.")

@dp.message(LinkStates.adding_title)
async def handle_link_title(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received link title from user {message.from_user.id}")
    title = message.text.strip()
    if not title:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
        
    await state.update_data(title=title)
    await state.set_state(LinkStates.adding_url)
    await message.answer("Введите URL (http://, https:// или t.me):")

@dp.message(LinkStates.adding_url)
async def handle_link_url(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Received link URL from user {message.from_user.id}")
    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("t.me")):
        await message.answer("Неверный формат URL. Должен начинаться с http://, https:// или t.me. Попробуйте снова:")
        return
        
    data = await state.get_data()
    cat_id = data.get("cat_id")
    title = data.get("title")
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO links (category_id, title, url) VALUES (?, ?, ?)", (cat_id, title, url))
            conn.commit()
            cur.execute("SELECT * FROM links WHERE category_id = ?", (cat_id,))
            links = cur.fetchall()
        except Exception as e:
            logging.exception("Database error while creating link")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    await message.answer("Ссылка добавлена!", reply_markup=links_list_kb(links, cat_id))

@dp.message(LinkStates.editing_title)
async def handle_edit_link_title(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Editing link title from user {message.from_user.id}")
    data = await state.get_data()
    link_id = data.get("link_id")
    cat_id = data.get("cat_id")
    new_title = message.text.strip()
    
    if not new_title:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE links SET title = ? WHERE id = ?", (new_title, link_id))
            conn.commit()
            cur.execute("SELECT * FROM links WHERE id = ?", (link_id,))
            link = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while updating link title")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    if link:
        logger.info(f"Link {link_id} title updated successfully")
        await message.answer(f"Название: {link[2]}\nURL: {link[3]}", reply_markup=link_card_kb(link_id, cat_id))
    else:
        await message.answer("Запись не найдена.")

@dp.message(LinkStates.editing_url)
async def handle_edit_link_url(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Editing link URL from user {message.from_user.id}")
    data = await state.get_data()
    link_id = data.get("link_id")
    cat_id = data.get("cat_id")
    new_url = message.text.strip()
    
    if not (new_url.startswith("http://") or new_url.startswith("https://") or new_url.startswith("t.me")):
        await message.answer("Неверный формат URL. Попробуйте снова:")
        return
    
    if not new_url:
        await message.answer("Значение не может быть пустым. Попробуйте снова:")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE links SET url = ? WHERE id = ?", (new_url, link_id))
            conn.commit()
            cur.execute("SELECT * FROM links WHERE id = ?", (link_id,))
            link = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while updating link URL")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
        
    await state.clear()
    
    if link:
        logger.info(f"Link {link_id} URL updated successfully")
        await message.answer(f"Название: {link[2]}\nURL: {link[3]}", reply_markup=link_card_kb(link_id, cat_id))
    else:
        await message.answer("Запись не найдена.")

# Schedule FSM handlers
@dp.message(ScheduleStates.adding_title)
async def handle_schedule_add_title(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Schedule add: received title from user {message.from_user.id}")
    title = message.text.strip()
    if not title:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
    
    await state.update_data(title=title)
    await state.set_state(ScheduleStates.adding_weekday)
    await message.answer("Выберите день недели:", reply_markup=schedule_weekday_select_kb())

@dp.message(ScheduleStates.adding_time)
async def handle_schedule_add_time(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Schedule add: received time from user {message.from_user.id}")
    time_str = message.text.strip()
    
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await message.answer("Неверный формат времени. Введите в формате ЧЧ:ММ (например, 09:30):")
        return
    
    await state.update_data(time_start=time_str)
    await state.set_state(ScheduleStates.adding_event_type)
    await message.answer("Выберите тип события:", reply_markup=schedule_event_type_kb())

@dp.message(ScheduleStates.adding_location)
async def handle_schedule_add_location(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Schedule add: received location from user {message.from_user.id}")
    location = message.text.strip()
    if location == "-":
        location = ""
    
    await state.update_data(location=location)
    await state.set_state(ScheduleStates.adding_category)
    
    user_db_id = get_user_id_by_telegram_id(message.from_user.id)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM categories WHERE user_id = ?", (user_db_id,))
        categories = cur.fetchall()
    
    await message.answer("Выберите категорию:", reply_markup=schedule_category_select_kb(categories))

# Schedule edit FSM handlers
@dp.message(ScheduleStates.editing_title)
async def handle_schedule_edit_title(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Schedule edit: updating title from user {message.from_user.id}")
    data = await state.get_data()
    event_id = data.get("event_id")
    new_title = message.text.strip()
    
    if not new_title:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE schedule SET title = ? WHERE id = ?", (new_title, event_id))
            conn.commit()
        except Exception as e:
            logging.exception("Database error while updating schedule title")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
    
    await state.clear()
    await message.answer("Название обновлено!")
    await show_schedule_event_card(message, event_id)

@dp.message(ScheduleStates.editing_time)
async def handle_schedule_edit_time(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Schedule edit: updating time from user {message.from_user.id}")
    data = await state.get_data()
    event_id = data.get("event_id")
    time_str = message.text.strip()
    
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await message.answer("Неверный формат времени. Введите в формате ЧЧ:ММ (например, 09:30):")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE schedule SET time_start = ? WHERE id = ?", (time_str, event_id))
            conn.commit()
        except Exception as e:
            logging.exception("Database error while updating schedule time")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
    
    await state.clear()
    await message.answer("Время обновлено!")
    await show_schedule_event_card(message, event_id)

@dp.message(ScheduleStates.editing_location)
async def handle_schedule_edit_location(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
    
    logger.info(f"Schedule edit: updating location from user {message.from_user.id}")
    data = await state.get_data()
    event_id = data.get("event_id")
    location = message.text.strip()
    
    if location == "-":
        location = ""
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE schedule SET location = ? WHERE id = ?", (location, event_id))
            conn.commit()
        except Exception as e:
            logging.exception("Database error while updating schedule location")
            await message.answer("Произошла ошибка при работе с базой данных.")
            return
    
    await state.clear()
    await message.answer("Место обновлено!")
    await show_schedule_event_card(message, event_id)

# ============================================================================
# CATCH-ALL HANDLER - MUST BE AFTER ALL STATE HANDLERS
# ============================================================================

@dp.message()
async def catch_all(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.answer("У тебя нет доступа к этому боту.")
        return
        
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Используй меню или команду /start.", reply_markup=main_menu_kb())

# ============================================================================
# CALLBACK HANDLERS
# ============================================================================

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=None)
    await callback.message.answer("Возврат в главное меню.", reply_markup=main_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "create_cat")
async def cb_create_cat(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CategoryStates.waiting_for_name)
    await callback.message.answer("Введите название новой категории:")
    await callback.answer()

@dp.callback_query(F.data.startswith("cat_"))
async def cb_open_category(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[1])
    await state.clear()
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM categories WHERE id = ?", (cat_id,))
        category = cur.fetchone()
        
    if not category or category[1] != get_user_id_by_telegram_id(callback.from_user.id):
         await callback.answer("Запись не найдена.", show_alert=True)
         return

    await callback.message.edit_text(f"Категория: {category[2]}", reply_markup=category_card_kb(cat_id))
    await callback.answer()

@dp.callback_query(F.data == "back_to_categories")
async def cb_back_to_categories(callback: CallbackQuery):
    logger.info(f"User {callback.from_user.id} clicked back to categories list")
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM categories WHERE user_id = ?", (user_db_id,))
        categories = cur.fetchall()
        
    if not categories:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Создать категорию", callback_data="create_cat")
        kb.button(text="⬅️ Главное меню", callback_data="main_menu")
        kb.adjust(1)
        await callback.message.edit_text("У тебя пока нет категорий.\nДобавить первую категорию.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Выберите категорию:", reply_markup=category_list_kb(categories, True))
    await callback.answer()

@dp.callback_query(F.data.startswith("rename_cat_"))
async def cb_rename_cat(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.set_state(CategoryStates.renaming_category)
    await state.update_data(cat_id=cat_id)
    await callback.message.answer("Введите новое название категории:")
    await callback.answer()

@dp.callback_query(F.data.startswith("del_cat_confirm_"))
async def cb_del_cat_confirm(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[3])
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data=f"del_cat_yes_{cat_id}")
    kb.button(text="Нет, отмена", callback_data=f"back_to_category_{cat_id}")
    kb.adjust(2)
    await callback.message.edit_text("Вы уверены, что хотите удалить эту категорию?\nВсе данные внутри будут удалены.", reply_markup=kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("del_cat_yes_"))
async def cb_del_cat_yes(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[3])
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM categories WHERE id = ?", (cat_id,))
            cat = cur.fetchone()
            if not cat or cat[0] != user_db_id:
                await callback.answer("Запись не найдена.", show_alert=True)
                return
                
            cur.execute("DELETE FROM notes WHERE category_id = ?", (cat_id,))
            cur.execute("DELETE FROM tasks WHERE category_id = ?", (cat_id,))
            cur.execute("DELETE FROM links WHERE category_id = ?", (cat_id,))
            cur.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
            conn.commit()
        except Exception as e:
            logging.exception("Database error while deleting category")
            await callback.answer("Произошла ошибка при работе с базой данных.", show_alert=True)
            return
        
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM categories WHERE user_id = ?", (user_db_id,))
        categories = cur.fetchall()
        
    if not categories:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Создать категорию", callback_data="create_cat")
        kb.button(text="⬅️ Главное меню", callback_data="main_menu")
        kb.adjust(1)
        await callback.message.edit_text("Категория удалена.\nУ тебя пока нет категорий.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Категория удалена.\nВыберите категорию:", reply_markup=category_list_kb(categories, True))
    await callback.answer()

@dp.callback_query(F.data.startswith("back_to_category_"))
async def cb_back_to_category(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[-1])
    logger.info(f"User {callback.from_user.id} clicked back to category {cat_id}")
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM categories WHERE id = ?", (cat_id,))
        category = cur.fetchone()
        
    if not category or category[1] != get_user_id_by_telegram_id(callback.from_user.id):
        await callback.answer("Запись не найдена.", show_alert=True)
        return
        
    await callback.message.edit_text(f"Категория: {category[2]}", reply_markup=category_card_kb(cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("notes_"))
async def cb_show_notes(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM notes WHERE category_id = ?", (cat_id,))
        notes = cur.fetchall()
        
    if not notes:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить заметку", callback_data=f"add_note_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет заметок.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Заметки:", reply_markup=notes_list_kb(notes, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("add_note_"))
async def cb_add_note(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.set_state(NoteStates.adding_title)
    await state.update_data(cat_id=cat_id)
    await callback.message.answer("Введите название заметки:")
    await callback.answer()

@dp.callback_query(F.data.startswith("note_"))
async def cb_show_note(callback: CallbackQuery):
    logger.info(f"Opening note from user {callback.from_user.id}")
    note_id = int(callback.data.split("_")[1])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
        note = cur.fetchone()
        
    if not note:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
        
    cat_id = note[1]
    
    title_display = note[2] if note[2] else "Без названия"
    text_display = note[3] if note[3] else "Без описания"
    
    await callback.message.edit_text(f"Название: {title_display}\n\n{text_display}", reply_markup=note_card_kb(note_id, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("back_to_notes_"))
async def cb_back_to_notes(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[-1])
    logger.info(f"User {callback.from_user.id} clicked back to notes list")
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM notes WHERE category_id = ?", (cat_id,))
        notes = cur.fetchall()
        
    if not notes:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить заметку", callback_data=f"add_note_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет заметок.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Заметки:", reply_markup=notes_list_kb(notes, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_note_menu_"))
async def cb_edit_note_menu(callback: CallbackQuery):
    parts = callback.data.split("_")
    note_id = int(parts[3])
    cat_id = int(parts[4])
    
    await callback.message.edit_text("Что изменить?", reply_markup=edit_note_menu_kb(note_id, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_note_title_"))
async def cb_edit_note_title(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    note_id = int(parts[3])
    cat_id = int(parts[4])
    
    await state.set_state(NoteStates.editing_title)
    await state.update_data(note_id=note_id, cat_id=cat_id)
    await callback.message.answer("Введите новое название заметки:")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_note_text_"))
async def cb_edit_note_text(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    note_id = int(parts[3])
    cat_id = int(parts[4])
    
    await state.set_state(NoteStates.editing_text)
    await state.update_data(note_id=note_id, cat_id=cat_id)
    await callback.message.answer("Введите новый текст заметки:")
    await callback.answer()

@dp.callback_query(F.data.startswith("del_note_"))
async def cb_del_note(callback: CallbackQuery):
    logger.info(f"Deleting note from user {callback.from_user.id}")
    parts = callback.data.split("_")
    note_id = int(parts[2])
    cat_id = int(parts[3])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()
            cur.execute("SELECT * FROM notes WHERE category_id = ?", (cat_id,))
            notes = cur.fetchall()
        except Exception as e:
            logging.exception("Database error while deleting note")
            await callback.answer("Произошла ошибка при работе с базой данных.", show_alert=True)
            return
        
    if not notes:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить заметку", callback_data=f"add_note_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет заметок.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Заметки:", reply_markup=notes_list_kb(notes, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("tasks_"))
async def cb_show_tasks(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE category_id = ?", (cat_id,))
        tasks = cur.fetchall()
        
    if not tasks:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить задачу", callback_data=f"add_task_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет задач.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Задачи:", reply_markup=tasks_list_kb(tasks, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("add_task_"))
async def cb_add_task(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.set_state(TaskStates.adding_title)
    await state.update_data(cat_id=cat_id)
    await callback.message.answer("Введите название задачи:")
    await callback.answer()

@dp.callback_query(F.data.startswith("task_"))
async def cb_show_task(callback: CallbackQuery):
    logger.info(f"Opening task from user {callback.from_user.id}")
    task_id = int(callback.data.split("_")[1])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task = cur.fetchone()
        
    if not task:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
        
    cat_id = task[1]
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM categories WHERE id = ?", (cat_id,))
        cat = cur.fetchone()
        if not cat or cat[0] != user_db_id:
             await callback.answer("Запись не найдена.", show_alert=True)
             return

    desc_text = task[3] if task[3] else "Нет описания"
    text = f"Название: {task[2]}\nОписание: {desc_text}\nДедлайн: {format_date(task[4])}\nСтатус: {'Выполнена' if task[5] else 'Активна'}"
    
    await callback.message.edit_text(text, reply_markup=task_card_kb(task_id, cat_id, task[5]))
    await callback.answer()

@dp.callback_query(F.data.startswith("back_to_tasks_"))
async def cb_back_to_tasks(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[-1])
    logger.info(f"User {callback.from_user.id} clicked back to tasks list")
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE category_id = ?", (cat_id,))
        tasks = cur.fetchall()
        
    if not tasks:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить задачу", callback_data=f"add_task_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет задач.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Задачи:", reply_markup=tasks_list_kb(tasks, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_task_"))
async def cb_toggle_task(callback: CallbackQuery):
    parts = callback.data.split("_")
    task_id = int(parts[2])
    cat_id = int(parts[3])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT is_done FROM tasks WHERE id = ?", (task_id,))
            task = cur.fetchone()
            if not task:
                await callback.answer("Запись не найдена.", show_alert=True)
                return
                
            new_status = 1 if task[0] == 0 else 0
            cur.execute("UPDATE tasks SET is_done = ? WHERE id = ?", (new_status, task_id))
            conn.commit()
            cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            updated_task = cur.fetchone()
        except Exception as e:
            logging.exception("Database error while toggling task")
            await callback.answer("Произошла ошибка при работе с базой данных.", show_alert=True)
            return
        
    desc_text = updated_task[3] if updated_task[3] else "Нет описания"
    text = f"Название: {updated_task[2]}\nОписание: {desc_text}\nДедлайн: {format_date(updated_task[4])}\nСтатус: {'Выполнена' if updated_task[5] else 'Активна'}"
    
    await callback.message.edit_text(text, reply_markup=task_card_kb(task_id, cat_id, updated_task[5]))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_task_menu_"))
async def cb_edit_task_menu(callback: CallbackQuery):
    parts = callback.data.split("_")
    task_id = int(parts[3])
    cat_id = int(parts[4])
    
    await callback.message.edit_text("Что изменить?", reply_markup=edit_task_menu_kb(task_id, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_task_title_"))
async def cb_edit_task_title(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    task_id = int(parts[3])
    cat_id = int(parts[4])
    
    await state.set_state(TaskStates.editing_title)
    await state.update_data(task_id=task_id, cat_id=cat_id)
    await callback.message.answer("Введите новое название задачи:")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_task_desc_"))
async def cb_edit_task_desc(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    task_id = int(parts[3])
    cat_id = int(parts[4])
    
    await state.set_state(TaskStates.editing_description)
    await state.update_data(task_id=task_id, cat_id=cat_id)
    await callback.message.answer("Введите новое описание задачи (или '-'):")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_task_date_"))
async def cb_edit_task_date(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    task_id = int(parts[3])
    cat_id = int(parts[4])
    
    await state.set_state(TaskStates.editing_due_date)
    await state.update_data(task_id=task_id, cat_id=cat_id)
    await callback.message.answer("Введите новый дедлайн в формате ДД.ММ.ГГГГ:")
    await callback.answer()

@dp.callback_query(F.data.startswith("del_task_"))
async def cb_del_task(callback: CallbackQuery):
    logger.info(f"Deleting task from user {callback.from_user.id}")
    parts = callback.data.split("_")
    task_id = int(parts[2])
    cat_id = int(parts[3])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            cur.execute("SELECT * FROM tasks WHERE category_id = ?", (cat_id,))
            tasks = cur.fetchall()
        except Exception as e:
            logging.exception("Database error while deleting task")
            await callback.answer("Произошла ошибка при работе с базой данных.", show_alert=True)
            return
        
    if not tasks:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить задачу", callback_data=f"add_task_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет задач.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Задачи:", reply_markup=tasks_list_kb(tasks, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("links_"))
async def cb_show_links(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM links WHERE category_id = ?", (cat_id,))
        links = cur.fetchall()
        
    if not links:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить ссылку", callback_data=f"add_link_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет ссылок.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Ссылки:", reply_markup=links_list_kb(links, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("add_link_"))
async def cb_add_link(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.set_state(LinkStates.adding_title)
    await state.update_data(cat_id=cat_id)
    await callback.message.answer("Введите название ссылки:")
    await callback.answer()

@dp.callback_query(F.data.startswith("link_"))
async def cb_show_link(callback: CallbackQuery):
    link_id = int(callback.data.split("_")[1])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM links WHERE id = ?", (link_id,))
        link = cur.fetchone()
        
    if not link:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
        
    cat_id = link[1]
    await callback.message.edit_text(f"Название: {link[2]}\nURL: {link[3]}", reply_markup=link_card_kb(link_id, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("back_to_links_"))
async def cb_back_to_links(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[-1])
    logger.info(f"User {callback.from_user.id} clicked back to links list")
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM links WHERE category_id = ?", (cat_id,))
        links = cur.fetchall()
        
    if not links:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить ссылку", callback_data=f"add_link_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет ссылок.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Ссылки:", reply_markup=links_list_kb(links, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_link_menu_"))
async def cb_edit_link_menu(callback: CallbackQuery):
    parts = callback.data.split("_")
    link_id = int(parts[3])
    cat_id = int(parts[4])
    
    await callback.message.edit_text("Что изменить?", reply_markup=edit_link_menu_kb(link_id, cat_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_link_title_"))
async def cb_edit_link_title(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    link_id = int(parts[3])
    cat_id = int(parts[4])
    
    await state.set_state(LinkStates.editing_title)
    await state.update_data(link_id=link_id, cat_id=cat_id)
    await callback.message.answer("Введите новое название ссылки:")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_link_url_"))
async def cb_edit_link_url(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    link_id = int(parts[3])
    cat_id = int(parts[4])
    
    await state.set_state(LinkStates.editing_url)
    await state.update_data(link_id=link_id, cat_id=cat_id)
    await callback.message.answer("Введите новый URL (http://, https:// или t.me):")
    await callback.answer()

@dp.callback_query(F.data.startswith("del_link_"))
async def cb_del_link(callback: CallbackQuery):
    parts = callback.data.split("_")
    link_id = int(parts[2])
    cat_id = int(parts[3])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM links WHERE id = ?", (link_id,))
            conn.commit()
            cur.execute("SELECT * FROM links WHERE category_id = ?", (cat_id,))
            links = cur.fetchall()
        except Exception as e:
            logging.exception("Database error while deleting link")
            await callback.answer("Произошла ошибка при работе с базой данных.", show_alert=True)
            return
        
    if not links:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить ссылку", callback_data=f"add_link_{cat_id}")
        kb.button(text="⬅️ Назад", callback_data=f"back_to_category_{cat_id}")
        kb.adjust(1)
        await callback.message.edit_text("В этой категории пока нет ссылок.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text("Ссылки:", reply_markup=links_list_kb(links, cat_id))
    await callback.answer()

@dp.callback_query(F.data == "delete_overdue")
async def cb_delete_overdue(callback: CallbackQuery):
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    today_iso = date.today().isoformat()
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            query = """
                DELETE FROM tasks 
                WHERE category_id IN (SELECT id FROM categories WHERE user_id = ?)
                AND is_done = 0
                AND due_date < ?
            """
            cur.execute(query, (user_db_id, today_iso))
            deleted_count = cur.rowcount
            conn.commit()
        except Exception as e:
            logging.exception("Database error while deleting overdue tasks")
            await callback.answer("Произошла ошибка при работе с базой данных.", show_alert=True)
            return
        
    if deleted_count > 0:
        msg = f"Удалено просроченных задач: {deleted_count}"
    else:
        msg = "Просроченных задач нет."
        
    await callback.message.edit_text(msg, reply_markup=deadlines_kb())
    await callback.answer()

# Schedule callbacks
@dp.callback_query(F.data == "schedule_main")
async def cb_schedule_main(callback: CallbackQuery):
    logger.info(f"User {callback.from_user.id} opened schedule main")
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT weekday, COUNT(*) FROM schedule WHERE user_id = ? GROUP BY weekday", (user_db_id,))
        rows = cur.fetchall()
    
    counts = {row[0]: row[1] for row in rows}
    
    await callback.message.edit_text("Расписание:", reply_markup=schedule_main_kb(counts))
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_day_"))
async def cb_schedule_day(callback: CallbackQuery):
    weekday = int(callback.data.split("_")[2])
    logger.info(f"User {callback.from_user.id} opened schedule day {weekday}")
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM schedule WHERE user_id = ? AND weekday = ? ORDER BY time_start", (user_db_id, weekday))
        events = cur.fetchall()
    
    day_name = get_weekday_name(weekday)
    
    if not events:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить событие", callback_data="schedule_add")
        kb.button(text="⬅️ Назад", callback_data="schedule_main")
        kb.adjust(1)
        await callback.message.edit_text(f"{day_name}\n\nНет событий в этот день.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text(f"{day_name}", reply_markup=schedule_day_kb(events, weekday))
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_event_"))
async def cb_schedule_event(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    logger.info(f"User {callback.from_user.id} opened schedule event {event_id}")
    await show_schedule_event_card_callback(callback, event_id)
    await callback.answer()

@dp.callback_query(F.data == "schedule_add")
async def cb_schedule_add(callback: CallbackQuery, state: FSMContext):
    logger.info(f"User {callback.from_user.id} started adding schedule event")
    await state.set_state(ScheduleStates.adding_title)
    await callback.message.answer("Введите название события:")
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_add_wd_"))
async def cb_schedule_add_weekday(callback: CallbackQuery, state: FSMContext):
    weekday = int(callback.data.split("_")[3])
    logger.info(f"User {callback.from_user.id} selected weekday {weekday}")
    await state.update_data(weekday=weekday)
    await state.set_state(ScheduleStates.adding_time)
    await callback.message.answer("Введите время в формате ЧЧ:ММ (например, 09:30):")
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_add_type_"))
async def cb_schedule_add_type(callback: CallbackQuery, state: FSMContext):
    event_type = callback.data.split("_")[3]
    logger.info(f"User {callback.from_user.id} selected event type {event_type}")
    await state.update_data(event_type=event_type)
    await state.set_state(ScheduleStates.adding_location)
    await callback.message.answer("Введите место проведения (или '-' если не указано):")
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_add_cat_"))
async def cb_schedule_add_category(callback: CallbackQuery, state: FSMContext):
    logger.info(f"User {callback.from_user.id} selected category for schedule event")
    parts = callback.data.split("_")
    cat_part = parts[3]
    
    if cat_part == "none":
        category_id = None
    else:
        category_id = int(cat_part)
    
    data = await state.get_data()
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO schedule (user_id, weekday, time_start, title, event_type, location, category_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_db_id, data["weekday"], data["time_start"], data["title"], data["event_type"], data["location"], category_id)
            )
            conn.commit()
            event_id = cur.lastrowid
        except Exception as e:
            logging.exception("Database error while creating schedule event")
            await callback.message.answer("Произошла ошибка при работе с базой данных.")
            await callback.answer()
            return
    
    await state.clear()
    await callback.message.answer("Событие добавлено!")
    await show_schedule_event_card_callback(callback, event_id)
    await callback.answer()

@dp.callback_query(F.data == "schedule_cancel")
async def cb_schedule_cancel(callback: CallbackQuery, state: FSMContext):
    logger.info(f"User {callback.from_user.id} cancelled schedule event creation")
    await state.clear()
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT weekday, COUNT(*) FROM schedule WHERE user_id = ? GROUP BY weekday", (user_db_id,))
        rows = cur.fetchall()
    
    counts = {row[0]: row[1] for row in rows}
    
    await callback.message.edit_text("Расписание:", reply_markup=schedule_main_kb(counts))
    await callback.answer()

@dp.callback_query(F.data == "schedule_week")
async def cb_schedule_week(callback: CallbackQuery):
    logger.info(f"User {callback.from_user.id} opened schedule week view")
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM schedule WHERE user_id = ? ORDER BY weekday, time_start", (user_db_id,))
        events = cur.fetchall()
    
    if not events:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="schedule_main")
        kb.adjust(1)
        await callback.message.edit_text("На неделе нет событий.", reply_markup=kb.as_markup())
        await callback.answer()
        return
    
    grouped = {}
    for event in events:
        weekday = event[2]
        if weekday not in grouped:
            grouped[weekday] = []
        grouped[weekday].append(event)
    
    lines = []
    for weekday in range(7):
        if weekday in grouped:
            lines.append(f"{get_weekday_name(weekday)}:")
            for event in grouped[weekday]:
                lines.append(f"{event[3]} — {event[4]} ({event[5]})")
            lines.append("")
    
    text = "\n".join(lines).strip()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="schedule_main")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_edit_menu_"))
async def cb_schedule_edit_menu(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[3])
    await callback.message.edit_text("Что изменить?", reply_markup=schedule_edit_menu_kb(event_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_edit_title_"))
async def cb_schedule_edit_title(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[3])
    await state.set_state(ScheduleStates.editing_title)
    await state.update_data(event_id=event_id)
    await callback.message.answer("Введите новое название:")
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_edit_time_"))
async def cb_schedule_edit_time(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[3])
    await state.set_state(ScheduleStates.editing_time)
    await state.update_data(event_id=event_id)
    await callback.message.answer("Введите новое время в формате ЧЧ:ММ:")
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_edit_type_"))
async def cb_schedule_edit_type(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[3])
    await state.set_state(ScheduleStates.editing_event_type)
    await state.update_data(event_id=event_id)
    await callback.message.answer("Выберите новый тип:", reply_markup=schedule_event_type_kb())
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_edit_location_"))
async def cb_schedule_edit_location(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[3])
    await state.set_state(ScheduleStates.editing_location)
    await state.update_data(event_id=event_id)
    await callback.message.answer("Введите новое место (или '-' если не указано):")
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_edit_category_"))
async def cb_schedule_edit_category(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[3])
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM categories WHERE user_id = ?", (user_db_id,))
        categories = cur.fetchall()
    
    await callback.message.edit_text("Выберите категорию:", reply_markup=schedule_edit_category_select_kb(categories, event_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_edit_cat_"))
async def cb_schedule_edit_category_select(callback: CallbackQuery):
    logger.info(f"User {callback.from_user.id} updating schedule event category")
    parts = callback.data.split("_")
    event_id = int(parts[3])
    cat_part = parts[4]
    
    if cat_part == "none":
        category_id = None
    else:
        category_id = int(cat_part)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE schedule SET category_id = ? WHERE id = ?", (category_id, event_id))
            conn.commit()
        except Exception as e:
            logging.exception("Database error while updating schedule category")
            await callback.answer("Произошла ошибка при работе с базой данных.", show_alert=True)
            return
    
    await callback.message.answer("Категория обновлена!")
    await show_schedule_event_card_callback(callback, event_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_del_confirm_"))
async def cb_schedule_del_confirm(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[3])
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data=f"schedule_del_yes_{event_id}")
    kb.button(text="Нет, назад", callback_data=f"schedule_event_{event_id}")
    kb.adjust(2)
    await callback.message.edit_text("Вы уверены, что хотите удалить это событие?", reply_markup=kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("schedule_del_yes_"))
async def cb_schedule_del_yes(callback: CallbackQuery):
    logger.info(f"User {callback.from_user.id} deleting schedule event")
    event_id = int(callback.data.split("_")[3])
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT weekday FROM schedule WHERE id = ?", (event_id,))
            row = cur.fetchone()
            if not row:
                await callback.answer("Запись не найдена.", show_alert=True)
                return
            weekday = row[0]
            
            cur.execute("DELETE FROM schedule WHERE id = ?", (event_id,))
            conn.commit()
        except Exception as e:
            logging.exception("Database error while deleting schedule event")
            await callback.answer("Произошла ошибка при работе с базой данных.", show_alert=True)
            return
    
    user_db_id = get_user_id_by_telegram_id(callback.from_user.id)
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM schedule WHERE user_id = ? AND weekday = ? ORDER BY time_start", (user_db_id, weekday))
        events = cur.fetchall()
    
    day_name = get_weekday_name(weekday)
    
    if not events:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить событие", callback_data="schedule_add")
        kb.button(text="⬅️ Назад", callback_data="schedule_main")
        kb.adjust(1)
        await callback.message.edit_text(f"{day_name}\n\nНет событий в этот день.", reply_markup=kb.as_markup())
    else:
        await callback.message.edit_text(f"{day_name}", reply_markup=schedule_day_kb(events, weekday))
    await callback.answer()

# Helper function to show schedule event card
async def show_schedule_event_card(message: Message, event_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM schedule WHERE id = ?", (event_id,))
        event = cur.fetchone()
    
    if not event:
        await message.answer("Запись не найдена.")
        return
    
    weekday_name = get_weekday_name(event[2])
    location = event[6] if event[6] else "не указано"
    
    category_name = "Без категории"
    if event[7]:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM categories WHERE id = ?", (event[7],))
            cat_row = cur.fetchone()
            if cat_row:
                category_name = cat_row[0]
    
    text = f"Название: {event[4]}\nВремя: {event[3]}\nДень: {weekday_name}\nТип: {event[5]}\nМесто: {location}\nКатегория: {category_name}"
    
    await message.answer(text, reply_markup=schedule_event_kb(event_id))

async def show_schedule_event_card_callback(callback: CallbackQuery, event_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM schedule WHERE id = ?", (event_id,))
        event = cur.fetchone()
    
    if not event:
        await callback.message.answer("Запись не найдена.")
        return
    
    weekday_name = get_weekday_name(event[2])
    location = event[6] if event[6] else "не указано"
    
    category_name = "Без категории"
    if event[7]:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM categories WHERE id = ?", (event[7],))
            cat_row = cur.fetchone()
            if cat_row:
                category_name = cat_row[0]
    
    text = f"Название: {event[4]}\nВремя: {event[3]}\nДень: {weekday_name}\nТип: {event[5]}\nМесто: {location}\nКатегория: {category_name}"
    
    await callback.message.edit_text(text, reply_markup=schedule_event_kb(event_id))

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())