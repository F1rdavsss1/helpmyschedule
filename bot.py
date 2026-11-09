"""
bot.py — точка входа и обработчики команд Telegram (aiogram 3).

Запуск:  python bot.py

Команды:
  /start    — приветствие и подписка на уведомления
  /today    — расписание на сегодня
  /tomorrow — расписание на завтра
  /week     — расписание на текущую неделю
  /nextweek — расписание на следующую неделю
  /check    — проверить изменения прямо сейчас
  /stop     — отписаться от уведомлений
  /help     — список команд
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup

from config import config
from database import Database
from messages import format_day, format_week, split_message
from parser import ScheduleParser
from scheduler import ScheduleService, setup_scheduler

log = logging.getLogger(__name__)
router = Router()

# Кнопки под полем ввода — чтобы не набирать команды руками.
BTN_TODAY, BTN_TOMORROW, BTN_WEEK, BTN_NEXT_WEEK = "📅 Сегодня", "➡️ Завтра", "🗓 Неделя", "⏭ След. неделя"
KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_TOMORROW)],
        [KeyboardButton(text=BTN_WEEK), KeyboardButton(text=BTN_NEXT_WEEK)],
    ],
    resize_keyboard=True,
)

HELP_TEXT = (
    "Что я умею:\n"
    "/today — расписание на сегодня\n"
    "/tomorrow — расписание на завтра\n"
    "/week — расписание на неделю\n"
    "/nextweek — расписание на следующую неделю\n"
    "/check — проверить изменения прямо сейчас\n"
    "/stop — отключить уведомления\n\n"
    "Автоматически присылаю:\n"
    "⚠️ изменения в расписании (переносы, замены, отмены);\n"
    "☀️ утреннюю сводку в {morning};\n"
    "🔔 напоминание за {before} мин до начала пары."
)


async def _reply_long(message: Message, text: str) -> None:
    for part in split_message(text):
        await message.answer(part, reply_markup=KEYBOARD)


def _offline_note(from_site: bool) -> str:
    return "" if from_site else "\n\n<i>⚠️ Сайт сейчас недоступен — показываю последнюю сохранённую версию.</i>"


# ---------------------------------------------------------------------- команды


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, parser: ScheduleParser) -> None:
    db.subscribe(message.chat.id, message.from_user.username if message.from_user else None)
    group = escape(parser.group_name or f"группа {parser.group_id}")
    await message.answer(
        f"👋 Привет! Я слежу за расписанием <b>{group}</b> и пришлю уведомление, "
        f"если что-то поменяется.\n\n✅ Ты подписан на уведомления.\n\n"
        + HELP_TEXT.format(morning=config.morning_time.strftime("%H:%M"), before=config.remind_before_min)
        + f'\n\n<a href="{parser.page_url}">Расписание на сайте</a>',
        reply_markup=KEYBOARD,
        disable_web_page_preview=True,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        HELP_TEXT.format(morning=config.morning_time.strftime("%H:%M"), before=config.remind_before_min),
        reply_markup=KEYBOARD,
    )


@router.message(Command("stop"))
async def cmd_stop(message: Message, db: Database) -> None:
    db.unsubscribe(message.chat.id)
    await message.answer("🔕 Уведомления отключены. Чтобы включить снова — /start")


@router.message(Command("today"))
@router.message(F.text == BTN_TODAY)
async def cmd_today(message: Message, service: ScheduleService) -> None:
    day = service.today()
    lessons, from_site = await service.get_lessons(day, day)
    await _reply_long(message, format_day(day, lessons, title="Сегодня") + _offline_note(from_site))


@router.message(Command("tomorrow"))
@router.message(F.text == BTN_TOMORROW)
async def cmd_tomorrow(message: Message, service: ScheduleService) -> None:
    day = service.today() + timedelta(days=1)
    lessons, from_site = await service.get_lessons(day, day)
    await _reply_long(message, format_day(day, lessons, title="Завтра") + _offline_note(from_site))


@router.message(Command("week"))
@router.message(F.text == BTN_WEEK)
async def cmd_week(message: Message, service: ScheduleService) -> None:
    today = service.today()
    monday = today - timedelta(days=today.weekday())
    lessons, from_site = await service.get_lessons(monday, monday + timedelta(days=6))
    await _reply_long(message, format_week(monday, lessons) + _offline_note(from_site))


@router.message(Command("nextweek"))
@router.message(F.text == BTN_NEXT_WEEK)
async def cmd_next_week(message: Message, service: ScheduleService) -> None:
    today = service.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
    lessons, from_site = await service.get_lessons(monday, monday + timedelta(days=6))
    await _reply_long(
        message, format_week(monday, lessons, title="Следующая неделя") + _offline_note(from_site)
    )


@router.message(Command("check"))
async def cmd_check(message: Message, service: ScheduleService) -> None:
    await message.answer("🔍 Проверяю сайт…")
    changes = await service.check_changes()
    if changes is None:
        await message.answer("😕 Не получилось проверить — сайт не ответил. Попробую позже автоматически.")
    elif not changes:
        await message.answer("✅ Изменений нет.")
    # Если изменения есть, они уже разосланы всем подписчикам (включая тебя).


# ---------------------------------------------------------------------- запуск


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not config.bot_token:
        raise SystemExit("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather.")

    db = Database(config.db_path)
    parser = ScheduleParser()
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    service = ScheduleService(bot, db, parser, config)

    dp = Dispatcher()
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="today", description="Расписание на сегодня"),
        BotCommand(command="tomorrow", description="Расписание на завтра"),
        BotCommand(command="week", description="Расписание на неделю"),
        BotCommand(command="nextweek", description="Следующая неделя"),
        BotCommand(command="check", description="Проверить изменения сейчас"),
        BotCommand(command="start", description="Подписаться на уведомления"),
        BotCommand(command="stop", description="Отписаться"),
    ])

    scheduler = setup_scheduler(service)
    scheduler.start()
    log.info("Бот запущен. Слежу за %s", parser.page_url)
    try:
        # Объекты db, parser и service передаются в обработчики по имени аргумента.
        await dp.start_polling(bot, db=db, parser=parser, service=service)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code not in (None, 0):
            raise
