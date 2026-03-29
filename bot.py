import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Dict, Optional, Set

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================
# НАСТРОЙКИ
# =========================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_BOT_TOKEN_HERE")

# Канал/группа, наличие в котором открывает доступ к курсу
PRIVATE_GROUP_ID_RAW = os.getenv("PRIVATE_GROUP_ID", "")

# Закрытый канал, где лежат видео уроков
# Пример: -1003723306059
VIDEO_CHANNEL_ID_RAW = os.getenv("VIDEO_CHANNEL_ID", "-1003723306059")

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

# ID админов, которым разрешены команды /setvideo и /videos
# Формат: ADMIN_IDS=123456789,987654321
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")

LESSONS: Dict[int, Dict[str, str]] = {
    1: {
        "title": "УРОК 1. КТО ТАКОЙ BD НА БИРЖЕ И ЗА ЧТО ЕГО РЕАЛЬНО ОЦЕНИВАЮТ",
        "text_url": "https://telegra.ph/UROK-1-KTO-TAKOJ-BD-NA-BIRZHE-I-ZA-CHTO-EGO-REALNO-OCENIVAYUT-03-19",
    },
    2: {
        "title": "УРОК 2. BATTLE CARD BD: КАК ИЗУЧАТЬ СВОЮ БИРЖУ И ПРОДАВАТЬ ЕЕ ФАКТАМИ",
        "text_url": "https://telegra.ph/UROK-2-BATTLE-CARD-BD-KAK-IZUCHAT-SVOYU-BIRZHU-I-PRODAVAT-EE-FAKTAMI-03-19",
    },
    3: {
        "title": "УРОК 3. ГДЕ ИСКАТЬ KOLS И КАК ПРОВЕРЯТЬ, ЧТО КОМЬЮНИТИ ЖИВОЕ",
        "text_url": "https://telegra.ph/UROK-3-GDE-ISKAT-KOLS-I-KAK-PROVERYAT-CHTO-KOMYUNITI-ZHIVOE-03-19",
    },
    4: {
        "title": "УРОК 4. OUTREACH И ПЕРЕГОВОРЫ: КАК ВЫСТРАИВАТЬ ПЕРВЫЙ КОНТАКТ С KOL И ПАРТНЕРОМ",
        "text_url": "https://telegra.ph/UROK-4-OUTREACH-I-PEREGOVORY-KAK-VYSTRAIVAT-PERVYJ-KONTAKT-S-KOL-I-PARTNEROM-03-19",
    },
    5: {
        "title": "УРОК 5. BROKER / VIP BD: КАК ПРОДАВАТЬ УСЛОВИЯМИ, ЦИФРАМИ И ОБЪЕМОМ",
        "text_url": "https://telegra.ph/UROK-5-BROKER--VIP-BD-KAK-PRODAVAT-USLOVIYAMI-CIFRAMI-I-OBEMOM-03-19",
    },
    6: {
        "title": "УРОК 6. СИСТЕМА РАБОТЫ BD: PIPELINE, ОТЧЕТНОСТЬ, ВНУТРЕННЯЯ КУХНЯ И ПЛАН 30/60/90",
        "text_url": "https://telegra.ph/UROK-6-SISTEMA-RABOTY-BD-PIPELINE-OTCHETNOST-VNUTRENNYAYA-KUHNYA-I-PLAN-306090-03-19",
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

    # Привязка урока к сообщению в канале-источнике
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS lesson_videos (
            lesson_id INTEGER PRIMARY KEY,
            source_chat_id INTEGER NOT NULL,
            source_message_id INTEGER NOT NULL,
            source_label TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    # Какое видео сейчас считается активным в диалоге пользователя
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS active_video_messages (
            chat_id INTEGER PRIMARY KEY,
            lesson_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
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


def upsert_lesson_video(lesson_id: int, source_chat_id: int, source_message_id: int, source_label: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO lesson_videos(lesson_id, source_chat_id, source_message_id, source_label, updated_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(lesson_id) DO UPDATE SET
            source_chat_id = excluded.source_chat_id,
            source_message_id = excluded.source_message_id,
            source_label = excluded.source_label,
            updated_at = excluded.updated_at
        """,
        (
            lesson_id,
            source_chat_id,
            source_message_id,
            source_label,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_lesson_video(lesson_id: int) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT lesson_id, source_chat_id, source_message_id, source_label, updated_at
        FROM lesson_videos
        WHERE lesson_id = ?
        """,
        (lesson_id,),
    ).fetchone()
    conn.close()
    return row


def get_all_lesson_videos() -> Dict[int, sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT lesson_id, source_chat_id, source_message_id, source_label, updated_at
        FROM lesson_videos
        ORDER BY lesson_id
        """
    ).fetchall()
    conn.close()
    return {int(row["lesson_id"]): row for row in rows}


def set_active_video_message(chat_id: int, lesson_id: int, message_id: int) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO active_video_messages(chat_id, lesson_id, message_id, created_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            lesson_id = excluded.lesson_id,
            message_id = excluded.message_id,
            created_at = excluded.created_at
        """,
        (chat_id, lesson_id, message_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_active_video_message(chat_id: int) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT chat_id, lesson_id, message_id, created_at
        FROM active_video_messages
        WHERE chat_id = ?
        """,
        (chat_id,),
    ).fetchone()
    conn.close()
    return row


def clear_active_video_message(chat_id: int) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM active_video_messages WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# =========================================
# ВСПОМОГАТЕЛЬНОЕ
# =========================================

def parse_int_env(value: str) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_admin_ids(value: str) -> Set[int]:
    result: Set[int] = set()
    if not value:
        return result
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            logger.warning("Некорректный ADMIN_IDS элемент: %s", part)
    return result


PRIVATE_GROUP_ID = parse_int_env(PRIVATE_GROUP_ID_RAW)
VIDEO_CHANNEL_ID = parse_int_env(VIDEO_CHANNEL_ID_RAW)
ADMIN_IDS = parse_admin_ids(ADMIN_IDS_RAW)

# ВАЖНО: если PRIVATE_GROUP_ID не задан, бот НЕ должен открывать курс.
# ВАЖНО: если VIDEO_CHANNEL_ID не задан, бот не сможет отправлять видео из канала.


def is_admin(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not PRIVATE_GROUP_ID:
        logger.error("PRIVATE_GROUP_ID не настроен. Проверка доступа невозможна.")
        return False

    try:
        member = await context.bot.get_chat_member(PRIVATE_GROUP_ID, user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception as e:
        logger.warning("Не удалось проверить доступ user_id=%s: %s", user_id, e)
        return False


def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Проверить доступ", callback_data="check_sub")]]
    )


def lessons_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    rows = []
    for lesson_id in LESSONS:
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

    rows.append([
        InlineKeyboardButton("📖 Текстовый урок", url=lesson["text_url"]),
        InlineKeyboardButton("🎬 Смотреть видео урок", callback_data=f"watch_video:{lesson_id}"),
    ])

    if is_lesson_completed(chat_id, lesson_id):
        rows.append([InlineKeyboardButton("✅ Урок подтвержден", callback_data="noop")])
    else:
        rows.append([InlineKeyboardButton("✅ Подтвердить изучение", callback_data=f"complete:{lesson_id}")])

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

    video_bound = get_lesson_video(lesson_id)
    video_status = "✅ Видео привязано" if video_bound else "▫️ Видео пока не привязано"

    return (
        f"{lesson['title']}\n\n"
        f"Прогресс: {done}/{total}\n"
        f"Статус урока: {status}\n"
        f"Видео: {video_status}\n\n"
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
        "4. При открытии нового видео старое видео в чате удаляется\n"
        "5. После 6 уроков получишь бонусы и переход в бот с тестом"
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


def parse_lesson_alias(value: str) -> Optional[int]:
    """
    Ищет в подписи/тексте канала маркер вида bd1, bd2, BD 3 и т.д.
    """
    if not value:
        return None

    match = re.search(r"(?i)\bbd\s*([1-9]\d*)\b", value.strip())
    if not match:
        return None

    lesson_id = int(match.group(1))
    if lesson_id not in LESSONS:
        return None
    return lesson_id


async def delete_active_video_if_exists(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    row = get_active_video_message(chat_id)
    if not row:
        return

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=row["message_id"])
        logger.info(
            "Удалено активное видео chat_id=%s lesson_id=%s message_id=%s",
            chat_id, row["lesson_id"], row["message_id"]
        )
    except TelegramError as e:
        logger.warning(
            "Не удалось удалить активное видео chat_id=%s message_id=%s: %s",
            chat_id, row["message_id"], e
        )
    finally:
        clear_active_video_message(chat_id)

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
            "Сейчас у тебя нет доступа к курсу.\n\n"
            "Если доступ уже был выдан через Tribute, нажми «Проверить доступ».",
            reply_markup=subscription_keyboard(),
        )
        return

    await delete_active_video_if_exists(chat_id, context)

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
            "Сейчас у тебя нет доступа к курсу.\n\n"
            "Если доступ уже был выдан через Tribute, нажми «Проверить доступ».",
            reply_markup=subscription_keyboard(),
        )
        return

    await delete_active_video_if_exists(chat_id, context)

    await update.message.reply_text(
        main_menu_text(chat_id),
        reply_markup=lessons_menu_keyboard(chat_id),
    )


async def setvideo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    if not VIDEO_CHANNEL_ID:
        await update.message.reply_text("VIDEO_CHANNEL_ID не настроен.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Использование:\n"
            "/setvideo <lesson_id> <channel_message_id>\n\n"
            "Пример:\n"
            "/setvideo 1 245"
        )
        return

    try:
        lesson_id = int(context.args[0])
        source_message_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("lesson_id и channel_message_id должны быть числами.")
        return

    if lesson_id not in LESSONS:
        await update.message.reply_text(f"Урок {lesson_id} не найден.")
        return

    upsert_lesson_video(
        lesson_id=lesson_id,
        source_chat_id=VIDEO_CHANNEL_ID,
        source_message_id=source_message_id,
        source_label=f"manual:bd{lesson_id}",
    )
    await update.message.reply_text(
        f"Готово.\n"
        f"Урок {lesson_id} привязан к сообщению {source_message_id} из канала {VIDEO_CHANNEL_ID}."
    )


async def videos_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    rows = get_all_lesson_videos()
    lines = ["Текущие привязки видео:\n"]
    for lesson_id in LESSONS:
        row = rows.get(lesson_id)
        if row:
            lines.append(
                f"Урок {lesson_id}: message_id={row['source_message_id']} "
                f"| label={row['source_label']}"
            )
        else:
            lines.append(f"Урок {lesson_id}: не привязан")
    await update.message.reply_text("\n".join(lines))


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    post = update.channel_post
    if not post or not post.chat:
        return

    if VIDEO_CHANNEL_ID and post.chat.id != VIDEO_CHANNEL_ID:
        return

    # Берем caption либо text
    raw_text = (post.caption or post.text or "").strip()
    lesson_id = parse_lesson_alias(raw_text)
    if not lesson_id:
        return

    # Привязываем любые новые посты с маркером bdN.
    upsert_lesson_video(
        lesson_id=lesson_id,
        source_chat_id=post.chat.id,
        source_message_id=post.message_id,
        source_label=raw_text[:200] if raw_text else f"bd{lesson_id}",
    )

    logger.info(
        "Автопривязка видео: lesson_id=%s chat_id=%s message_id=%s label=%s",
        lesson_id, post.chat.id, post.message_id, raw_text
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    ensure_user(chat_id)

    data = query.data or ""
    await query.answer()

    if data not in {"check_sub", "noop"} and not await check_membership(user_id, context):
        await delete_active_video_if_exists(chat_id, context)
        await query.edit_message_text(
            "Сейчас у тебя нет доступа к курсу.\n\n"
            "Если доступ уже был выдан через Tribute, нажми «Проверить доступ».",
            reply_markup=subscription_keyboard(),
        )
        return

    if data == "check_sub":
        await delete_active_video_if_exists(chat_id, context)
        if await check_membership(user_id, context):
            await query.edit_message_text(
                main_menu_text(chat_id),
                reply_markup=lessons_menu_keyboard(chat_id),
            )
        else:
            await query.edit_message_text(
                "Доступ пока не найден.\n\n"
                "Если оплата или выдача доступа через Tribute уже прошла, нажми проверку еще раз чуть позже.",
                reply_markup=subscription_keyboard(),
            )
        return

    if data == "menu":
        await delete_active_video_if_exists(chat_id, context)
        await query.edit_message_text(
            main_menu_text(chat_id),
            reply_markup=lessons_menu_keyboard(chat_id),
        )
        return

    if data == "show_progress":
        await delete_active_video_if_exists(chat_id, context)
        await query.edit_message_text(
            progress_text(chat_id),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📚 Назад к урокам", callback_data="menu")]]
            ),
        )
        return

    if data.startswith("open_lesson:"):
        lesson_id = int(data.split(":")[1])
        await delete_active_video_if_exists(chat_id, context)
        await query.edit_message_text(
            lesson_text(chat_id, lesson_id),
            reply_markup=lesson_keyboard(chat_id, lesson_id),
        )
        return

    if data.startswith("watch_video:"):
        lesson_id = int(data.split(":")[1])
        lesson_video = get_lesson_video(lesson_id)

        if not VIDEO_CHANNEL_ID:
            await query.answer("VIDEO_CHANNEL_ID не настроен.", show_alert=True)
            return

        if not lesson_video:
            await query.answer(
                f"Видео для урока {lesson_id} пока не привязано.",
                show_alert=True,
            )
            return

        await delete_active_video_if_exists(chat_id, context)

        try:
            sent_message = await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=lesson_video["source_chat_id"],
                message_id=lesson_video["source_message_id"],
            )
            set_active_video_message(
                chat_id=chat_id,
                lesson_id=lesson_id,
                message_id=sent_message.message_id,
            )
            await query.answer("Видео отправлено.")
        except TelegramError as e:
            logger.exception("Не удалось отправить видео урока %s: %s", lesson_id, e)
            await query.answer(
                "Не удалось открыть видео. Проверь, что бот добавлен в канал с видео и имеет доступ.",
                show_alert=True,
            )
        return

    if data.startswith("complete:"):
        lesson_id = int(data.split(":")[1])
        mark_lesson_completed(chat_id, lesson_id)

        if all_lessons_completed(chat_id):
            await delete_active_video_if_exists(chat_id, context)
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
    app.add_handler(CommandHandler("setvideo", setvideo_command))
    app.add_handler(CommandHandler("videos", videos_command))

    # Обработка новых постов в канале с видео.
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))

    app.add_handler(CallbackQueryHandler(on_callback))
    return app


def main() -> None:
    if BOT_TOKEN == "PASTE_BOT_TOKEN_HERE":
        raise RuntimeError("Укажи BOT_TOKEN в переменных окружения.")

    init_db()
    app = build_application()

    logger.info("PRIVATE_GROUP_ID=%s", PRIVATE_GROUP_ID)
    logger.info("VIDEO_CHANNEL_ID=%s", VIDEO_CHANNEL_ID)
    logger.info("ADMIN_IDS count=%s", len(ADMIN_IDS))

    if WEBHOOK_URL:
        logger.info("Запуск через webhook")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
            webhook_url=f"{WEBHOOK_URL.rstrip('/')}/{WEBHOOK_PATH}",
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Запуск через polling")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

"""
КАК ПОДКЛЮЧИТЬ:

1. Добавь бота админом в канал с видео.
2. Укажи:
   BOT_TOKEN=...
   PRIVATE_GROUP_ID=...
   VIDEO_CHANNEL_ID=-1003723306059
   ADMIN_IDS=твой_telegram_id

3. Для НОВЫХ видео:
   - Загружай видео в канал
   - В подписи пиши bd1, bd2, bd3 ... bd6
   - Бот сам запомнит соответствие

4. Для УЖЕ загруженных СТАРЫХ видео:
   - Узнай message_id поста в канале
   - Отправь боту:
     /setvideo 1 123
     /setvideo 2 124
     ...
   - Проверить можно командой:
     /videos

5. Логика работы:
   - При нажатии "Смотреть видео урок" бот копирует видео из закрытого канала в личный чат
   - Перед отправкой нового видео бот удаляет предыдущее активное видео в этом чате
   - При переходе по меню/урокам активное видео тоже удаляется
"""
