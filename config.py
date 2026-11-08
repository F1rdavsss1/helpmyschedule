"""
config.py — настройки бота.

Все параметры читаются из переменных окружения (или из файла .env в корне
проекта). Так токен не попадает в код и в git, а на сервере (Railway,
PythonAnywhere) настройки задаются через панель управления.
"""

import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Подгружаем .env, если он есть. Уже заданные переменные окружения не перезаписываются.
load_dotenv()


def _get_int(name: str, default: int) -> int:
    """Читает целое число из окружения, при ошибке берёт значение по умолчанию."""
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        raise SystemExit(f"Переменная {name} должна быть целым числом, получено: {raw!r}")


def _get_time(name: str, default: str) -> time:
    """Читает время в формате ЧЧ:ММ (например, 07:30)."""
    raw = os.getenv(name, default).strip()
    try:
        hours, minutes = raw.split(":")
        return time(int(hours), int(minutes))
    except ValueError:
        raise SystemExit(f"Переменная {name} должна быть в формате ЧЧ:ММ, получено: {raw!r}")


@dataclass(frozen=True)
class Config:
    # Токен от @BotFather. Нужен только боту; parser.py работает и без него.
    bot_token: str
    # Адрес сайта с расписанием.
    base_url: str
    # Идентификатор публикации (UUID из ссылки) и номер группы.
    publication_id: str
    group_id: int
    # Часовой пояс колледжа: в нём считаются «сегодня», утренняя сводка и напоминания.
    tz: ZoneInfo
    # Как часто (в минутах) проверять изменения на сайте.
    check_interval_min: int
    # Во сколько присылать утреннюю сводку.
    morning_time: time
    # За сколько минут до начала пары присылать напоминание.
    remind_before_min: int
    # На сколько дней вперёд следить за изменениями (от сегодняшнего дня).
    track_days: int
    # Путь к файлу базы SQLite.
    db_path: str


def load_config() -> Config:
    return Config(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        base_url=os.getenv("SCHEDULE_BASE_URL", "https://site.mstimetables.ru").rstrip("/"),
        publication_id=os.getenv("PUBLICATION_ID", "01a00f53-d327-73b5-b396-bf3eb6f57ce2").strip(),
        group_id=_get_int("GROUP_ID", 304),
        tz=ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
        check_interval_min=_get_int("CHECK_INTERVAL_MIN", 20),
        morning_time=_get_time("MORNING_TIME", "07:30"),
        remind_before_min=_get_int("REMIND_BEFORE_MIN", 15),
        track_days=_get_int("TRACK_DAYS", 14),
        db_path=os.getenv("DB_PATH", "schedule.db"),
    )


config = load_config()
