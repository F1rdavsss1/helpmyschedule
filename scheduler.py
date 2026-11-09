"""
scheduler.py — фоновые задачи (APScheduler).

Задачи:
  * check_changes   — каждые CHECK_INTERVAL_MIN минут скачивает расписание на
                      TRACK_DAYS дней вперёд, сравнивает со снимком в БД и
                      рассылает уведомления об изменениях;
  * morning_summary — каждый день в MORNING_TIME: «Доброе утро! Сегодня у тебя N пар»;
  * send_reminders  — раз в минуту смотрит, не начинается ли пара через
                      REMIND_BEFORE_MIN минут, и присылает напоминание.

Почему напоминания проверяются раз в минуту, а не ставятся отдельной задачей
на каждую пару: расписание может поменяться в любой момент, и тогда
пришлось бы пересоздавать задачи. Проверка «по факту» всегда опирается на
свежий снимок и переживает перезапуск бота.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import Config
from database import Database
from diff import Change, diff_lessons
from messages import format_changes, format_morning, format_reminder, split_message
from parser import Lesson, ScheduleError, ScheduleParser

log = logging.getLogger(__name__)


class ScheduleService:
    """Вся «бизнес-логика» бота: получение расписания, сравнение, рассылки."""

    def __init__(self, bot: Bot, db: Database, parser: ScheduleParser, cfg: Config) -> None:
        self.bot = bot
        self.db = db
        self.parser = parser
        self.cfg = cfg
        # Защита от одновременного запуска двух проверок (по таймеру и по команде /check).
        self._check_lock = asyncio.Lock()
        # Сколько раз подряд сайт вернул пустое расписание там, где раньше были пары.
        self._empty_strikes = 0

    def today(self) -> date:
        return datetime.now(self.cfg.tz).date()

    # ------------------------------------------------------------------ получение расписания

    async def get_lessons(self, start: date, end: date) -> tuple[list[Lesson], bool]:
        """
        Расписание для команд /today, /week и т.д.
        Сначала пробуем сайт (самые свежие данные), при ошибке — снимок из БД.
        Возвращает (пары, данные_с_сайта: bool).

        Важно: снимок здесь НЕ обновляется — иначе проверка изменений не
        заметила бы правку, и уведомление не пришло бы.
        """
        try:
            return await self.parser.fetch(start, end), True
        except ScheduleError as e:
            log.warning("Сайт недоступен, отдаю данные из БД: %s", e)
            return self.db.get_lessons(start, end), False

    # ------------------------------------------------------------------ проверка изменений

    async def check_changes(self) -> list[Change] | None:
        """
        Скачивает расписание, сравнивает со снимком, рассылает изменения.
        Возвращает список изменений или None, если проверить не удалось.
        """
        async with self._check_lock:
            start = self.today()
            end = start + timedelta(days=self.cfg.track_days)
            try:
                new_lessons = await self.parser.fetch(start, end)
            except ScheduleError as e:
                log.error("Проверка изменений не удалась: %s", e)
                return None

            old_range = self.db.get_snapshot_range()
            if old_range is None:
                # Первый запуск: сравнивать не с чем, просто запоминаем.
                self.db.save_snapshot(new_lessons, start, end)
                log.info("Сохранён первый снимок: %s пар (%s – %s)", len(new_lessons), start, end)
                return []

            # Сравниваем только пересечение периодов старого и нового снимка
            # и только начиная с сегодняшнего дня. Иначе «уехавшие» в прошлое
            # дни выглядели бы как удалённые пары, а новые дни в конце периода —
            # как добавленные.
            cmp_start = max(old_range[0], start)
            cmp_end = min(old_range[1], end)
            old_cmp = self.db.get_lessons(cmp_start, cmp_end) if cmp_start <= cmp_end else []
            new_cmp = [l for l in new_lessons if cmp_start.isoformat() <= l.date <= cmp_end.isoformat()]

            # Защита от сбоев сайта: если вдруг всё расписание пропало, не спешим
            # рассылать «все пары удалены» — ждём подтверждения при следующей проверке.
            if old_cmp and not new_cmp:
                self._empty_strikes += 1
                if self._empty_strikes < 2:
                    log.warning("Сайт вернул пустое расписание — жду подтверждения при следующей проверке")
                    return None
            self._empty_strikes = 0

            changes = diff_lessons(old_cmp, new_cmp)
            self.db.save_snapshot(new_lessons, start, end)

            if changes:
                log.info("Найдено изменений: %s", len(changes))
                await self.broadcast(format_changes(changes))
            else:
                log.info("Изменений нет (%s пар в периоде %s – %s)", len(new_lessons), start, end)
            return changes

    # ------------------------------------------------------------------ утренняя сводка

    async def morning_summary(self) -> None:
        today = self.today()
        if not self.db.mark_sent("morning", today.isoformat()):
            return  # уже отправляли сегодня (например, бот перезапускался)
        # Перед сводкой обновляем данные, чтобы утром не прислать устаревшее.
        await self.check_changes()
        lessons = self.db.get_lessons(today, today)
        await self.broadcast(format_morning(lessons))
        self.db.cleanup_sent_log()

    # ------------------------------------------------------------------ напоминания

    async def send_reminders(self) -> None:
        now = datetime.now(self.cfg.tz)
        window = timedelta(minutes=self.cfg.remind_before_min)
        for lesson in self.db.get_lessons(now.date(), now.date()):
            if lesson.is_cancelled or not lesson.start_time:
                continue
            hours, minutes = map(int, lesson.start_time.split(":"))
            starts_at = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            # Напоминаем, если до начала пары осталось от 0 до REMIND_BEFORE_MIN минут.
            if timedelta(0) < starts_at - now <= window:
                key = f"{lesson.date}|{lesson.start_time}|{lesson.subgroup}|{lesson.subject}"
                if self.db.mark_sent("reminder", key):
                    await self.broadcast(format_reminder(lesson))

    # ------------------------------------------------------------------ рассылка

    async def broadcast(self, text: str) -> None:
        """Отправляет сообщение всем подписчикам."""
        for chat_id in self.db.get_subscribers():
            for part in split_message(text):
                await self._send(chat_id, part)

    async def _send(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id, text)
        except TelegramRetryAfter as e:
            # Telegram просит подождать (слишком много сообщений) — ждём и пробуем снова.
            await asyncio.sleep(e.retry_after)
            await self.bot.send_message(chat_id, text)
        except TelegramForbiddenError:
            # Пользователь заблокировал бота — отключаем ему рассылку.
            log.info("Пользователь %s заблокировал бота, отписываю", chat_id)
            self.db.unsubscribe(chat_id)
        except Exception:
            log.exception("Не удалось отправить сообщение пользователю %s", chat_id)


def setup_scheduler(service: ScheduleService) -> AsyncIOScheduler:
    """Создаёт планировщик и регистрирует задачи. Запускать нужно внутри event loop."""
    cfg = service.cfg
    scheduler = AsyncIOScheduler(timezone=cfg.tz)

    # Проверка изменений: сразу после старта и далее каждые N минут.
    scheduler.add_job(
        service.check_changes,
        IntervalTrigger(minutes=cfg.check_interval_min),
        id="check_changes",
        next_run_time=datetime.now(cfg.tz),
        max_instances=1,
        coalesce=True,
    )
    # Утренняя сводка. misfire_grace_time — если бот был выключен в нужную
    # минуту и включился в течение часа, сводка всё равно придёт.
    scheduler.add_job(
        service.morning_summary,
        CronTrigger(hour=cfg.morning_time.hour, minute=cfg.morning_time.minute),
        id="morning_summary",
        misfire_grace_time=3600,
        coalesce=True,
    )
    # Напоминания перед парами — проверка каждую минуту.
    scheduler.add_job(
        service.send_reminders,
        IntervalTrigger(minutes=1),
        id="send_reminders",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
