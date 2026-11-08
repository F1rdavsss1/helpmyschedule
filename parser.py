"""
parser.py — получение расписания с сайта mstimetables.ru.

Как устроен сайт
----------------
Страница https://site.mstimetables.ru/<публикация>/groups/<группа> собрана на
Nuxt (Vue). Данные она берёт из открытого JSON API:

    GET /api/publications/<UUID публикации>/groups/<id группы>/lessons
        ?startDate=ГГГГ-ММ-ДД&endDate=ГГГГ-ММ-ДД

Ответ выглядит так (сокращённо):

    {
      "group": {"id": 304, "name": "09-23.ИСИП.ОФ.9 10-23.ИСИП.ОФ.9"},
      "lessons": [
        {
          "date": "2026-11-09", "weekday": 1, "lessonNumber": 1,
          "startTime": "09:00", "endTime": "10:30",
          "subject": {"name": "МДК.01.04 Системное программирование"},
          "cabinet": {"name": "513"},
          "teachers": [{"fio": "Екимов И."}],
          "unionGroups": [{"group": {...}, "subgroup": null}],
          "replacementType": "none"   # none / cancel / substitute / move / ad_hoc / joint
        }, ...
      ]
    }

Поэтому ни Playwright, ни BeautifulSoup не нужны: запрос к API надёжнее и
быстрее, чем разбор HTML. Ограничение API: окно дат не длиннее 31 дня, поэтому
длинные периоды запрашиваются по кускам.

Запуск для проверки:  python parser.py            — текущая неделя
                      python parser.py 2026-11-16 — неделя, в которую входит дата
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

import aiohttp

from config import config

log = logging.getLogger(__name__)

# Максимальная длина окна дат, которую принимает API (проверено опытным путём).
MAX_WINDOW_DAYS = 31

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

# Подписи для типов замен — те же, что показывает сам сайт.
REPLACEMENT_LABELS = {
    "substitute": "Замена",
    "move": "Перенос",
    "ad_hoc": "Внеплановое",
    "joint": "Общий урок",
    "cancel": "Отменена",
}


@dataclass(frozen=True)
class Lesson:
    """Одна пара. frozen=True — объект неизменяемый и его можно класть в set/dict."""

    date: str            # дата в формате ГГГГ-ММ-ДД
    lesson_number: int   # номер пары в дне (1, 2, 3 ...)
    start_time: str      # "09:00"
    end_time: str        # "10:30"
    subject: str         # название предмета
    teacher: str         # преподаватель (если несколько — через запятую)
    cabinet: str         # аудитория
    subgroup: str        # подгруппа ("" — вся группа)
    status: str          # replacementType из API: none / cancel / substitute / ...

    @property
    def weekday(self) -> str:
        """День недели словом, например «Понедельник»."""
        return WEEKDAYS[date.fromisoformat(self.date).weekday()]

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancel"

    def to_dict(self) -> dict:
        return asdict(self)


class ScheduleError(Exception):
    """Не удалось получить расписание (сеть, ошибка сервера, неожиданный ответ)."""


def normalize_publication_id(raw: str) -> str:
    """
    Приводит идентификатор публикации к виду UUID с дефисами.
    На сайте встречаются оба варианта: 01a00f53d327... и 01a00f53-d327-...
    """
    hex_only = re.sub(r"[^0-9a-fA-F]", "", raw).lower()
    if len(hex_only) != 32:
        raise ValueError(f"Некорректный идентификатор публикации: {raw!r}")
    h = hex_only
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _clean(text: str | None) -> str:
    """Убирает лишние пробелы: в названиях на сайте бывает «функционирования    компьютерных»."""
    return " ".join((text or "").split())


def parse_lesson(raw: dict, group_id: int) -> Lesson:
    """Превращает один элемент из JSON API в объект Lesson."""
    teachers = ", ".join(_clean(t.get("fio")) for t in raw.get("teachers") or [] if t.get("fio"))

    # Подгруппа: ищем запись именно для нашей группы (пара может быть общей для нескольких групп).
    subgroup = ""
    for union in raw.get("unionGroups") or []:
        if (union.get("group") or {}).get("id") == group_id and union.get("subgroup"):
            sg = union["subgroup"]
            subgroup = _clean(sg.get("name") if isinstance(sg, dict) else str(sg))
            break

    return Lesson(
        date=raw["date"],
        lesson_number=int(raw.get("lessonNumber") or 0),
        start_time=raw.get("startTime") or "",
        end_time=raw.get("endTime") or "",
        subject=_clean((raw.get("subject") or {}).get("name")),
        teacher=teachers,
        cabinet=_clean((raw.get("cabinet") or {}).get("name")),
        subgroup=subgroup,
        status=raw.get("replacementType") or "none",
    )


class ScheduleParser:
    """Клиент к API расписания одной группы."""

    def __init__(
        self,
        base_url: str = config.base_url,
        publication_id: str = config.publication_id,
        group_id: int = config.group_id,
        timeout: float = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.publication_id = normalize_publication_id(publication_id)
        self.group_id = group_id
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.group_name: str | None = None

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/api/publications/{self.publication_id}/groups/{self.group_id}/lessons"

    @property
    def page_url(self) -> str:
        """Обычная ссылка на страницу группы (для кнопки «Открыть на сайте»)."""
        return f"{self.base_url}/{self.publication_id.replace('-', '')}/groups/{self.group_id}"

    async def _fetch_window(self, session: aiohttp.ClientSession, start: date, end: date) -> list[Lesson]:
        """Один запрос к API за период не длиннее MAX_WINDOW_DAYS."""
        params = {"startDate": start.isoformat(), "endDate": end.isoformat()}
        # Делаем до 3 попыток: сайт иногда отвечает медленно или с ошибкой 5xx.
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                async with session.get(self.api_url, params=params) as resp:
                    if resp.status != 200:
                        body = (await resp.text())[:300]
                        raise ScheduleError(f"HTTP {resp.status}: {body}")
                    data = await resp.json(content_type=None)
                break
            except (aiohttp.ClientError, asyncio.TimeoutError, ScheduleError) as e:
                last_error = e
                log.warning("Попытка %s получить расписание не удалась: %s", attempt, e)
                await asyncio.sleep(2 * attempt)
        else:
            raise ScheduleError(f"Не удалось получить расписание: {last_error}")

        if not isinstance(data, dict) or not isinstance(data.get("lessons"), list):
            raise ScheduleError(f"Неожиданный формат ответа API: {str(data)[:300]}")

        self.group_name = (data.get("group") or {}).get("name") or self.group_name
        return [parse_lesson(item, self.group_id) for item in data["lessons"]]

    async def fetch(self, start: date, end: date) -> list[Lesson]:
        """
        Расписание за период [start; end] включительно.
        Длинные периоды автоматически режутся на окна по 31 дню.
        """
        if end < start:
            raise ValueError("end не может быть раньше start")

        lessons: list[Lesson] = []
        async with aiohttp.ClientSession(
            timeout=self.timeout,
            headers={"User-Agent": "helpmyschedule-bot/1.0"},
            trust_env=True,  # учитывать HTTP(S)_PROXY из окружения
        ) as session:
            cursor = start
            while cursor <= end:
                window_end = min(end, cursor + timedelta(days=MAX_WINDOW_DAYS - 1))
                lessons += await self._fetch_window(session, cursor, window_end)
                cursor = window_end + timedelta(days=1)

        # Сортируем по дате и времени — так удобнее выводить и сравнивать.
        lessons.sort(key=lambda l: (l.date, l.start_time, l.lesson_number, l.subgroup, l.subject))
        return lessons

    async def fetch_day(self, day: date) -> list[Lesson]:
        return await self.fetch(day, day)

    async def fetch_week(self, day: date) -> list[Lesson]:
        """Неделя (пн–вс), в которую входит указанный день."""
        monday = day - timedelta(days=day.weekday())
        return await self.fetch(monday, monday + timedelta(days=6))


def print_lessons(lessons: list[Lesson]) -> None:
    """Вывод расписания в консоль, сгруппированного по дням."""
    current_date = None
    for lesson in lessons:
        if lesson.date != current_date:
            current_date = lesson.date
            print(f"\n=== {lesson.weekday}, {date.fromisoformat(lesson.date):%d.%m.%Y} ===")
        mark = f"  [{REPLACEMENT_LABELS[lesson.status]}]" if lesson.status in REPLACEMENT_LABELS else ""
        sub = f" ({lesson.subgroup})" if lesson.subgroup else ""
        print(
            f"{lesson.lesson_number}. {lesson.start_time}-{lesson.end_time}  {lesson.subject}{sub}"
            f" | {lesson.teacher or '—'} | каб. {lesson.cabinet or '—'}{mark}"
        )
    if not lessons:
        print("Занятий нет.")


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(config.tz).date()
    parser = ScheduleParser()
    lessons = await parser.fetch_week(day)
    print(f"Группа: {parser.group_name}")
    print(f"Источник: {parser.api_url}")
    print_lessons(lessons)


if __name__ == "__main__":
    asyncio.run(_main())
