"""
Сквозной тест логики бота без Telegram и без сайта:
поддельный парсер отдаёт расписание, поддельный бот складывает сообщения в список.
"""

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta

from config import config
from database import Database
from parser import Lesson
from scheduler import ScheduleService


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeParser:
    def __init__(self, lessons):
        self.lessons = lessons

    async def fetch(self, start, end):
        return [l for l in self.lessons if start.isoformat() <= l.date <= end.isoformat()]


def lesson(day: date, start="09:00", **kw) -> Lesson:
    base = dict(date=day.isoformat(), lesson_number=1, start_time=start, end_time="10:30",
                subject="Программирование", teacher="Екимов И.", cabinet="513", subgroup="", status="none")
    base.update(kw)
    return Lesson(**base)


def make_service(tmp_path, lessons):
    db = Database(str(tmp_path / "test.db"))
    db.subscribe(1, "me")
    bot, parser = FakeBot(), FakeParser(lessons)
    return ScheduleService(bot, db, parser, config), bot, parser


def test_check_changes_flow(tmp_path):
    today = datetime.now(config.tz).date()
    tomorrow = today + timedelta(days=1)
    original = [lesson(tomorrow)]
    service, bot, parser = make_service(tmp_path, original)

    # Первый запуск — только сохраняем снимок, ничего не шлём.
    assert asyncio.run(service.check_changes()) == []
    assert bot.sent == []

    # Повторная проверка без изменений — бот молчит.
    assert asyncio.run(service.check_changes()) == []
    assert bot.sent == []

    # Сменилась аудитория — приходит уведомление «Было/Стало».
    parser.lessons = [replace(original[0], cabinet="404")]
    changes = asyncio.run(service.check_changes())
    assert len(changes) == 1
    [(chat_id, text)] = bot.sent
    assert chat_id == 1 and "Изменение в расписании" in text and "каб. 513" in text and "каб. 404" in text


def test_empty_response_needs_confirmation(tmp_path):
    tomorrow = datetime.now(config.tz).date() + timedelta(days=1)
    service, bot, parser = make_service(tmp_path, [lesson(tomorrow)])
    asyncio.run(service.check_changes())

    parser.lessons = []
    assert asyncio.run(service.check_changes()) is None   # первый «пустой» ответ игнорируем
    assert bot.sent == []
    assert len(asyncio.run(service.check_changes())) == 1  # второй подряд — считаем правдой
    assert "пара убрана" in bot.sent[0][1]


def test_reminder_sent_once(tmp_path):
    now = datetime.now(config.tz)
    soon = now + timedelta(minutes=10)
    if soon.date() != now.date():
        return  # тест около полуночи не имеет смысла
    service, bot, _ = make_service(tmp_path, [lesson(now.date(), start=soon.strftime("%H:%M"))])
    asyncio.run(service.check_changes())
    asyncio.run(service.send_reminders())
    asyncio.run(service.send_reminders())
    assert len(bot.sent) == 1 and bot.sent[0][1].startswith("🔔 Следующая пара")


def test_morning_summary_once(tmp_path):
    today = datetime.now(config.tz).date()
    service, bot, _ = make_service(tmp_path, [lesson(today), lesson(today, start="10:40", lesson_number=2)])
    asyncio.run(service.morning_summary())
    asyncio.run(service.morning_summary())
    assert len(bot.sent) == 1
    assert "Сегодня у тебя 2 пары. Первая в 09:00." in bot.sent[0][1]
