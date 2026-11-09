"""
messages.py — тексты сообщений бота.

Все сообщения форматируются в HTML (parse_mode=HTML в aiogram), поэтому любые
данные с сайта обязательно экранируются через html.escape — иначе символы
вроде «<» в названии предмета сломают сообщение.
"""

from __future__ import annotations

from datetime import date
from html import escape

from diff import Change
from parser import REPLACEMENT_LABELS, WEEKDAYS, Lesson

# Лимит Telegram на длину одного сообщения.
TELEGRAM_LIMIT = 4096

WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def plural(n: int, one: str, few: str, many: str) -> str:
    """Склонение по числу: 1 пара, 2 пары, 5 пар."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _day_title(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day:%d.%m}"


def _short_day(iso_date: str) -> str:
    d = date.fromisoformat(iso_date)
    return f"{WEEKDAYS_SHORT[d.weekday()]}, {d:%d.%m}"


def _details(lesson: Lesson) -> str:
    """«Предмет (подгруппа), каб. 513, Екимов И.» — без пустых частей."""
    parts = [escape(lesson.subject) + (f" ({escape(lesson.subgroup)})" if lesson.subgroup else "")]
    if lesson.cabinet:
        parts.append(f"каб. {escape(lesson.cabinet)}")
    if lesson.teacher:
        parts.append(escape(lesson.teacher))
    return ", ".join(parts)


def lesson_short(lesson: Lesson) -> str:
    """Короткое описание пары для блока «Было/Стало»."""
    text = f"{lesson.lesson_number}-я пара {lesson.start_time}–{lesson.end_time}, {_details(lesson)}"
    if lesson.is_cancelled:
        text += " — <b>отменена</b>"
    return text


def lesson_line(lesson: Lesson) -> str:
    """Строка пары в расписании на день."""
    line = f"<b>{lesson.lesson_number}.</b> {lesson.start_time}–{lesson.end_time}  {_details(lesson)}"
    label = REPLACEMENT_LABELS.get(lesson.status)
    if lesson.is_cancelled:
        line = f"<s>{line}</s>  ❌ отменена"
    elif label:
        line += f"  <i>({label.lower()})</i>"
    return line


def format_day(day: date, lessons: list[Lesson], title: str | None = None) -> str:
    """Расписание на один день."""
    header = f"📅 <b>{title + ' — ' if title else ''}{_day_title(day)}</b>"
    day_lessons = [l for l in lessons if l.date == day.isoformat()]
    if not day_lessons:
        return f"{header}\nПар нет 🎉"
    return header + "\n" + "\n".join(lesson_line(l) for l in day_lessons)


def format_week(monday: date, lessons: list[Lesson], title: str = "Расписание на неделю") -> str:
    """Расписание на неделю: только дни, в которые есть пары."""
    sunday = date.fromordinal(monday.toordinal() + 6)
    blocks = [f"🗓 <b>{title}</b> ({monday:%d.%m} – {sunday:%d.%m})"]
    for offset in range(7):
        day = date.fromordinal(monday.toordinal() + offset)
        if any(l.date == day.isoformat() for l in lessons):
            blocks.append(format_day(day, lessons))
    if len(blocks) == 1:
        blocks.append("На этой неделе пар нет 🎉")
    return "\n\n".join(blocks)


def format_changes(changes: list[Change]) -> str:
    """Уведомление об изменениях: заголовок и блоки «Было / Стало»."""
    blocks = ["⚠️ <b>Изменение в расписании!</b>"]
    for change in changes:
        day = _short_day(change.date)
        if change.kind == "added":
            body = f"Было: —\nСтало: {lesson_short(change.new)}"
            icon = "➕"
        elif change.kind == "removed":
            body = f"Было: {lesson_short(change.old)}\nСтало: пара убрана из расписания"
            icon = "➖"
        else:
            body = f"Было: {lesson_short(change.old)}\nСтало: {lesson_short(change.new)}"
            icon = "🔄"
        blocks.append(f"{icon} <b>{day}</b>\n{body}")
    return "\n\n".join(blocks)


def format_morning(lessons: list[Lesson]) -> str:
    """Утренняя сводка. Отменённые пары не считаем."""
    active = [l for l in lessons if not l.is_cancelled]
    if not active:
        return "☀️ Доброе утро! Сегодня пар нет — можно отдохнуть 😊"
    n = len(active)
    first = min(active, key=lambda l: l.start_time)
    text = (
        f"☀️ Доброе утро! Сегодня у тебя {n} {plural(n, 'пара', 'пары', 'пар')}. "
        f"Первая в {first.start_time}."
    )
    return text + "\n\n" + "\n".join(lesson_line(l) for l in lessons)


def format_reminder(lesson: Lesson) -> str:
    """Напоминание перед парой, как на скриншоте."""
    return (
        f"🔔 Следующая пара: {lesson.lesson_number}-я пара — {_details(lesson)}\n"
        f"🕐 {lesson.start_time}–{lesson.end_time}"
    )


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """
    Делит длинный текст на части не длиннее limit, стараясь резать по пустым
    строкам (между блоками), чтобы не разорвать HTML-теги посередине.
    """
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        # Отдельный блок длиннее лимита — режем по строкам.
        while len(block) > limit:
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(block[:cut])
            block = block[cut:].lstrip("\n")
        current = block
    if current:
        parts.append(current)
    return parts
