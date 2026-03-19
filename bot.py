
import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# =========================================
# НАСТРОЙКИ
# =========================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_BOT_TOKEN_HERE")

# Бот должен быть добавлен в приватную группу/канал и иметь права,
# чтобы проверять участие пользователя.
PRIVATE_GROUP_ID_RAW = os.getenv("PRIVATE_GROUP_ID", "")
PRIVATE_GROUP_LINK = os.getenv("PRIVATE_GROUP_LINK", "")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", "8080"))

DB_PATH = os.getenv("DB_PATH", "course_progress.db")

TEST_BOT_USERNAME = os.getenv("TEST_BOT_USERNAME", "your_test_bot")
TEST_BOT_START_PARAM = os.getenv("TEST_BOT_START_PARAM", "bd_course")
TEST_BOT_URL = os.getenv(
    "TEST_BOT_URL",
    f"https://t.me/{TEST_BOT_USERNAME}?start={TEST_BOT_START_PARAM}",
)

LESSONS: Dict[int, Dict[str, str]] = {
    1: {
        "title": "УРОК 1. КТО ТАКОЙ BD НА БИРЖЕ И ЗА ЧТО ЕГО РЕАЛЬНО ОЦЕНИВАЮТ",
        "text_url": "https://telegra.ph/UROK-1-KTO-TAKOJ-BD-NA-BIRZHE-I-ZA-CHTO-EGO-REALNO-OCENIVAYUT-03-19",
        "video_url": "",
    },
    2: {
        "title": "УРОК 2. BATTLE CARD BD: КАК ИЗУЧАТЬ СВОЮ БИРЖУ И ПРОДАВАТЬ ЕЕ ФАКТАМИ",
        "text_url": "https://telegra.ph/UROK-2-BATTLE-CARD-BD-KAK-IZUCHAT-SVOYU-BIRZHU-I-PRODAVAT-EE-FAKTAMI-03-19",
        "video_url": "",
    },
    3: {
        "title": "УРОК 3. ГДЕ ИСКАТЬ KOLS И КАК ПРОВЕРЯТЬ, ЧТО КОМЬЮНИТИ ЖИВОЕ",
        "text_url": "https://telegra.ph/UROK-3-GDE-ISKAT-KOLS-I-KAK-PROVERYAT-CHTO-KOMYUNITI-ZHIVOE-03-19",
        "video_url": "",
    },
    4: {
        "title": "УРОК 4. OUTREACH И ПЕРЕГОВОРЫ: КАК ВЫСТРАИВАТЬ ПЕРВЫЙ КОНТАКТ С KOL И ПАРТНЕРОМ",
        "text_url": "https://telegra.ph/UROK-4-OUTREACH-I-PEREGOVORY-KAK-VYSTRAIVAT-PERVYJ-KONTAKT-S-KOL-I-PARTNEROM-03-19",
        "video_url": "",
    },
    5: {
        "title": "УРОК 5. BROKER / VIP BD: КАК ПРОДАВАТЬ УСЛОВИЯМИ, ЦИФРАМИ И ОБЪЕМОМ",
        "text_url": "https://telegra.ph/UROK-5-BROKER--VIP-BD-KAK-PRODAVAT-USLOVIYAMI-CIFRAMI-I-OBEMOM-03-19",
        "video_url": "",
    },
    6: {
        "title": "УРОК 6. СИСТЕМА РАБОТЫ BD: PIPELINE, ОТЧЕТНОСТЬ, ВНУТРЕННЯЯ КУХНЯ И ПЛАН 30/60/90",
        "text_url": "https://telegra.ph/UROK-6-SISTEMA-RABOTY-BD-PIPELINE-OTCHETNOST-VNUTRENNYAYA-KUHNYA-I-PLAN-306090-03-19",
        "video_url": "",
    },
}

BONUSES = [
    ("БОНУС 1. BD PARTNER AUDIT CHECKLIST", "https://telegra.ph/BONUS-1-BD-PARTNER-AUDIT-CHECKLIST-03-19"),
    ("БОНУС 2. EXCHANGE BATTLE CARD TEMPLATE", "https://telegra.ph/BONUS-2-EXCHANGE-BATTLE-CARD-TEMPLATE-03-19"),
    ("БОНУС 3. BD WEEKLY REPORT & 30/60/90 PLANNER", "https://telegra.ph/BONUS-3-BD-WEEKLY-REPORT--306090-PLANNER-03-19"),
]

# =========================================
# ЛОГИ
# =========================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# =========================================
# DB
# =========================================

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS lesson_progress (
            chat_id INTEGER NOT NULL,
            lesson_id INTEGER NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT,
            PRIMARY KEY (chat_id, lesson_id)
        )
        """
    )

    conn.commit()
    conn.close()


def ensure_user(chat_id: int) -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO users(chat_id, created_at) VALUES(?, ?)",
        (chat_id, datetime.utcnow().isoformat()),
    )

    for lesson_id in LESSONS.keys():
        cur.execute(
            """
            INSERT OR IGNORE INTO lesson_progress(chat_id, lesson_id, completed, completed_at)
            VALUES(?, ?, 0, NULL)
            """,
            (chat_id, lesson_id),
        )

    conn.commit()
    conn.close()


def mark_lesson_completed(chat_id: int, lesson_id: int) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE lesson_progress
        SET completed = 1, completed_at = ?
        WHERE chat_id = ? AND lesson_id = ?
        """,
        (datetime.utcnow().isoformat(), chat_id, lesson_id),
    )
    conn.commit()
    conn.close()


def is_lesson_completed(chat_id: int, lesson_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT completed
        FROM lesson_progress
        WHERE chat_id = ? AND lesson_id = ?
        """,
        (chat_id, lesson_id),
    ).fetchone()
    conn.close()
    return bool(row and row["completed"] == 1)


def completed_count(chat_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM lesson_progress
        WHERE chat_id = ? AND completed = 1
        """,
        (chat_id,),
    ).fetchone()
    conn.close()
    return int(row["cnt"]) if row else 0


def all_lessons_completed(chat_id: int) -> bool:
    return completed_count(chat_id) >= len(LESSONS)


# =========================================
# ВСПОМОГАТЕЛЬНОЕ
# =========================================

def parse_group_id(value: str) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


PRIVATE_GROUP_ID = parse_group_id(PRIVATE_GROUP_ID_RAW)


async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not PRIVATE_GROUP_ID:
        return True

    try:
        member = await context.bot.get_chat_member(PRIVATE_GROUP_ID, user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception as e:
        logger.warning("Не удалось проверить подписку user_id=%s: %s", user_id, e)
        return False


def subscription_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    if PRIVATE_GROUP_LINK:
        buttons.append([InlineKeyboardButton("🔐 Вступить в группу", url=PRIVATE_GROUP_LINK)])
    buttons.append([InlineKeyboardButton("✅ Я вступил, проверить", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)


def lessons_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    rows = []
    for lesson_id, lesson in LESSONS.items():
        done = "✅" if is_lesson_completed(chat_id, lesson_id) else "▫️"
        rows.append([
            InlineKeyboardButton(
                f"{done} Урок {lesson_id}",
                callback_data=f"open_lesson:{lesson_id}",
            )
        ])

    rows.append([InlineKeyboardButton("📊 Мой прогресс", callback_data="show_progress")])
    return InlineKeyboardMarkup(rows)


def lesson_keyboard(chat_id: int, lesson_id: int) -> InlineKeyboardMarkup:
    lesson = LESSONS[lesson_id]
    rows = []

    # 1-я строка: текст / видео
    first_row = [InlineKeyboardButton("📖 Текстовый урок", url=lesson["text_url"])]
    if lesson["video_url"]:
        first_row.append(InlineKeyboardButton("🎬 Видео урок", url=lesson["video_url"]))
    else:
        first_row.append(InlineKeyboardButton("🎬 Видео урок", callback_data=f"video_placeholder:{lesson_id}"))
    rows.append(first_row)

    # 2-я строка: подтверждение изучения
    if is_lesson_completed(chat_id, lesson_id):
        rows.append([InlineKeyboardButton("✅ Урок подтвержден", callback_data="noop")])
    else:
        rows.append([InlineKeyboardButton("✅ Подтвердить изучение", callback_data=f"complete:{lesson_id}")])

    # 3-я строка: навигация
    nav_row = []
    if lesson_id > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"open_lesson:{lesson_id - 1}"))
    nav_row.append(InlineKeyboardButton("📚 К урокам", callback_data="menu"))
    if lesson_id < len(LESSONS):
        nav_row.append(InlineKeyboardButton("➡️ Вперед", callback_data=f"open_lesson:{lesson_id + 1}"))
    rows.append(nav_row)

    return InlineKeyboardMarkup(rows)


def completion_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for title, url in BONUSES:
        rows.append([InlineKeyboardButton(title, url=url)])
    rows.append([InlineKeyboardButton("🧪 Перейти в бот с тестом", url=TEST_BOT_URL)])
    rows.append([InlineKeyboardButton("📚 Вернуться к урокам", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def lesson_text(chat_id: int, lesson_id: int) -> str:
    total = len(LESSONS)
    done = completed_count(chat_id)
    lesson = LESSONS[lesson_id]
    status = "✅ Изучение подтверждено" if is_lesson_completed(chat_id, lesson_id) else "▫️ Ожидает подтверждения"

    return (
        f"{lesson['title']}\n\n"
        f"Прогресс: {done}/{total}\n"
        f"Статус урока: {status}\n\n"
        "Выберите формат:\n"
        "• Текстовый урок — открывает страницу Telegra.ph\n"
        "• Видео урок — пока заглушка, добавим позже\n\n"
        "После изучения нажмите «Подтвердить изучение»."
    )


def main_menu_text(chat_id: int) -> str:
    done = completed_count(chat_id)
    total = len(LESSONS)
    return (
        "Курс: Business Development в Web3 и CEX\n\n"
        f"Твой прогресс: {done}/{total}\n\n"
        "Как проходить курс:\n"
        "1. Открой урок\n"
        "2. Выбери формат: текстовый или видео\n"
        "3. После изучения нажми «Подтвердить изучение»\n"
        "4. После 6 уроков получишь бонусы и переход в бот с тестом"
    )


def progress_text(chat_id: int) -> str:
    done = completed_count(chat_id)
    total = len(LESSONS)
    left = total - done
    return (
        f"Текущий прогресс: {done}/{total}\n"
        f"Осталось уроков: {left}"
    )


def completion_text() -> str:
    return (
        "Поздравляю! Ты завершил все уроки курса.\n\n"
        "Тебе открыты 3 бонуса:\n"
        "• BD Partner Audit Checklist\n"
        "• Exchange Battle Card Template\n"
        "• BD Weekly Report & 30/60/90 Planner\n\n"
        "Следующий шаг — перейти в бот с тестом.\n"
        "При успешной сдаче ты сможешь получить:\n\n"
        "🛡 Proof of Competency — база курса для подтверждения HR\n"
        "✅ Verified Certificate of Completion — именной PDF-сертификат"
    )


# =========================================
# HANDLERS
# =========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    ensure_user(chat_id)

    if not await check_membership(user_id, context):
        await update.message.reply_text(
            "Чтобы получить доступ к курсу, сначала вступи в приватную группу.\n\n"
            "После вступления нажми «Я вступил, проверить».",
            reply_markup=subscription_keyboard(),
        )
        return

    await update.message.reply_text(
        main_menu_text(chat_id),
        reply_markup=lessons_menu_keyboard(chat_id),
    )


async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    ensure_user(chat_id)

    if not await check_membership(user_id, context):
        await update.message.reply_text(
            "Доступ к курсу открыт только участникам приватной группы.",
            reply_markup=subscription_keyboard(),
        )
        return

    await update.message.reply_text(
        main_menu_text(chat_id),
        reply_markup=lessons_menu_keyboard(chat_id),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return

    await query.answer()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    ensure_user(chat_id)

    # Перед доступом ко всем экранам перепроверяем участие
    if query.data not in {"check_sub", "noop"} and not await check_membership(user_id, context):
        await query.edit_message_text(
            "Сначала вступи в приватную группу, затем нажми проверку.",
            reply_markup=subscription_keyboard(),
        )
        return

    data = query.data or ""

    if data == "check_sub":
        if await check_membership(user_id, context):
            await query.edit_message_text(
                main_menu_text(chat_id),
                reply_markup=lessons_menu_keyboard(chat_id),
            )
        else:
            await query.edit_message_text(
                "Я пока не вижу тебя в приватной группе.\n\n"
                "Вступи в группу и нажми проверку еще раз.",
                reply_markup=subscription_keyboard(),
            )
        return

    if data == "menu":
        await query.edit_message_text(
            main_menu_text(chat_id),
            reply_markup=lessons_menu_keyboard(chat_id),
        )
        return

    if data == "show_progress":
        await query.edit_message_text(
            progress_text(chat_id),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📚 Назад к урокам", callback_data="menu")]]
            ),
        )
        return

    if data.startswith("open_lesson:"):
        lesson_id = int(data.split(":")[1])
        await query.edit_message_text(
            lesson_text(chat_id, lesson_id),
            reply_markup=lesson_keyboard(chat_id, lesson_id),
        )
        return

    if data.startswith("video_placeholder:"):
        lesson_id = int(data.split(":")[1])
        await query.answer(
            f"Видео к уроку {lesson_id} добавим позже.",
            show_alert=True,
        )
        return

    if data.startswith("complete:"):
        lesson_id = int(data.split(":")[1])
        mark_lesson_completed(chat_id, lesson_id)

        if all_lessons_completed(chat_id):
            await query.edit_message_text(
                completion_text(),
                reply_markup=completion_keyboard(),
            )
            return

        await query.edit_message_text(
            lesson_text(chat_id, lesson_id),
            reply_markup=lesson_keyboard(chat_id, lesson_id),
        )

        done = completed_count(chat_id)
        left = len(LESSONS) - done
        await query.answer(f"Урок подтвержден. Осталось: {left}", show_alert=False)
        return

    if data == "noop":
        return


# =========================================
# MAIN
# =========================================

def build_application() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lessons", lessons_command))
    app.add_handler(CallbackQueryHandler(on_callback))

    return app


def main() -> None:
    if BOT_TOKEN == "PASTE_BOT_TOKEN_HERE":
        raise RuntimeError("Укажи BOT_TOKEN в переменных окружения.")

    init_db()
    app = build_application()

    if WEBHOOK_URL:
        logger.info("Запуск через webhook")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
            webhook_url=f"{WEBHOOK_URL.rstrip('/')}/{WEBHOOK_PATH}",
        )
    else:
        logger.info("Запуск через polling")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
