"""
database.py — работа с SQLite.

Что храним:
  * users      — подписчики бота (chat_id и признак подписки);
  * lessons    — последний сохранённый «снимок» расписания, с ним сравниваем
                 свежие данные с сайта;
  * meta       — служебные значения, например за какой период сделан снимок;
  * sent_log   — какие уведомления уже отправлены (утренняя сводка за день,
                 напоминание о конкретной паре), чтобы после перезапуска бота
                 не прислать их второй раз.

Используем стандартный модуль sqlite3. Запросы крошечные и выполняются за
доли миллисекунды, поэтому вызывать их прямо из асинхронного кода допустимо.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

from parser import Lesson

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id     INTEGER PRIMARY KEY,
    username    TEXT,
    subscribed  INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    date           TEXT NOT NULL,
    lesson_number  INTEGER NOT NULL,
    start_time     TEXT NOT NULL,
    end_time       TEXT NOT NULL,
    subject        TEXT NOT NULL,
    teacher        TEXT NOT NULL,
    cabinet        TEXT NOT NULL,
    subgroup       TEXT NOT NULL,
    status         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lessons_date ON lessons(date);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sent_log (
    kind     TEXT NOT NULL,   -- 'morning' или 'reminder'
    key      TEXT NOT NULL,   -- дата или идентификатор пары
    sent_at  TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
"""

LESSON_FIELDS = (
    "date", "lesson_number", "start_time", "end_time",
    "subject", "teacher", "cabinet", "subgroup", "status",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str) -> None:
        # check_same_thread=False — на случай, если APScheduler вызовет код из другого потока.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ пользователи

    def subscribe(self, chat_id: int, username: str | None) -> None:
        """Добавляет пользователя или снова включает ему подписку."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO users (chat_id, username, subscribed, created_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(chat_id) DO UPDATE SET subscribed = 1, username = excluded.username
                """,
                (chat_id, username, _now()),
            )

    def unsubscribe(self, chat_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE users SET subscribed = 0 WHERE chat_id = ?", (chat_id,))

    def get_subscribers(self) -> list[int]:
        rows = self.conn.execute("SELECT chat_id FROM users WHERE subscribed = 1").fetchall()
        return [row["chat_id"] for row in rows]

    # ------------------------------------------------------------------ снимок расписания

    def save_snapshot(self, lessons: list[Lesson], start: date, end: date) -> None:
        """
        Полностью заменяет снимок. Всё делается в одной транзакции: если что-то
        пойдёт не так, старый снимок останется нетронутым.
        """
        with self.conn:
            self.conn.execute("DELETE FROM lessons")
            self.conn.executemany(
                f"INSERT INTO lessons ({', '.join(LESSON_FIELDS)}) "
                f"VALUES ({', '.join('?' * len(LESSON_FIELDS))})",
                [tuple(getattr(l, f) for f in LESSON_FIELDS) for l in lessons],
            )
            for key, value in (
                ("snapshot_start", start.isoformat()),
                ("snapshot_end", end.isoformat()),
                ("snapshot_updated_at", _now()),
            ):
                self.conn.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

    def get_snapshot_range(self) -> tuple[date, date] | None:
        """Период, за который сделан снимок, или None, если снимка ещё нет."""
        rows = dict(self.conn.execute(
            "SELECT key, value FROM meta WHERE key IN ('snapshot_start', 'snapshot_end')"
        ).fetchall())
        if "snapshot_start" not in rows or "snapshot_end" not in rows:
            return None
        return date.fromisoformat(rows["snapshot_start"]), date.fromisoformat(rows["snapshot_end"])

    def get_lessons(self, start: date, end: date) -> list[Lesson]:
        """Пары из снимка за период [start; end]."""
        rows = self.conn.execute(
            "SELECT * FROM lessons WHERE date BETWEEN ? AND ? "
            "ORDER BY date, start_time, lesson_number, subgroup, subject",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [Lesson(**{f: row[f] for f in LESSON_FIELDS}) for row in rows]

    # ------------------------------------------------------------------ журнал уведомлений

    def mark_sent(self, kind: str, key: str) -> bool:
        """
        Отмечает уведомление как отправленное.
        Возвращает True, если отметка новая (значит, отправлять нужно),
        и False, если такое уведомление уже было.
        """
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO sent_log (kind, key, sent_at) VALUES (?, ?, ?)",
                (kind, key, _now()),
            )
        return cur.rowcount == 1

    def cleanup_sent_log(self, keep_days: int = 14) -> None:
        """Удаляет старые записи журнала, чтобы база не росла бесконечно."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM sent_log WHERE sent_at < datetime('now', ?)", (f"-{keep_days} days",)
            )
