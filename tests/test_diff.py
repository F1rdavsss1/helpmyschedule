"""Тесты сравнения расписаний и форматирования сообщений. Запуск: pytest"""

from dataclasses import replace

from diff import diff_lessons
from messages import format_changes, format_morning, format_reminder, plural, split_message
from parser import Lesson, normalize_publication_id, parse_lesson


def make(**kw) -> Lesson:
    base = dict(
        date="2026-11-09", lesson_number=1, start_time="09:00", end_time="10:30",
        subject="МДК.01.04 Системное программирование", teacher="Екимов И.",
        cabinet="513", subgroup="", status="none",
    )
    base.update(kw)
    return Lesson(**base)


def test_no_changes():
    a = [make(), make(lesson_number=2, start_time="10:40", end_time="12:10", subject="Английский")]
    assert diff_lessons(a, list(a)) == []


def test_cabinet_changed():
    old = make()
    new = replace(old, cabinet="404")
    [change] = diff_lessons([old], [new])
    assert change.kind == "changed" and change.old == old and change.new == new


def test_time_moved_is_one_change():
    old = make()
    new = replace(old, lesson_number=3, start_time="12:40", end_time="14:10")
    [change] = diff_lessons([old], [new])
    assert change.kind == "changed"


def test_added_and_removed():
    a = make()
    b = make(lesson_number=2, start_time="10:40", end_time="12:10", subject="Физкультура")
    c = make(lesson_number=4, start_time="14:20", end_time="15:50", subject="История")
    changes = diff_lessons([a, b], [a, c])
    # b и c в разных слотах и с разными предметами → удаление + добавление
    assert sorted(ch.kind for ch in changes) == ["added", "removed"]


def test_cancel_detected():
    old = make()
    [change] = diff_lessons([old], [replace(old, status="cancel")])
    assert change.kind == "changed" and change.new.is_cancelled
    assert "отменена" in format_changes([change])


def test_other_day_not_mixed():
    old = make(date="2026-11-09")
    new = make(date="2026-11-10")
    kinds = sorted(c.kind for c in diff_lessons([old], [new]))
    assert kinds == ["added", "removed"]


def test_format_changes_header():
    text = format_changes(diff_lessons([make()], [make(cabinet="404")]))
    assert text.startswith("⚠️ <b>Изменение в расписании!</b>")
    assert "Было:" in text and "Стало:" in text and "каб. 404" in text


def test_morning_and_reminder():
    lessons = [make(start_time="10:40", lesson_number=2), make(), make(start_time="12:40", status="cancel")]
    text = format_morning(lessons)
    assert "Сегодня у тебя 2 пары. Первая в 09:00." in text
    assert format_morning([]).startswith("☀️ Доброе утро! Сегодня пар нет")
    r = format_reminder(make(lesson_number=5, subject="Классный час", cabinet="204", teacher="Доброхотова Т.В."))
    assert r.startswith("🔔 Следующая пара: 5-я пара — Классный час, каб. 204, Доброхотова Т.В.")


def test_html_is_escaped():
    assert "&lt;b&gt;" in format_reminder(make(subject="<b>"))


def test_plural():
    assert [plural(n, "пара", "пары", "пар") for n in (1, 2, 5, 11, 21, 22, 25)] == [
        "пара", "пары", "пар", "пар", "пара", "пары", "пар"]


def test_split_message():
    text = "\n\n".join("x" * 100 for _ in range(100))
    parts = split_message(text, limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")


def test_parse_lesson_from_api():
    raw = {
        "date": "2026-11-09", "lessonNumber": 1, "startTime": "09:00", "endTime": "10:30",
        "subject": {"name": "Обеспечение   качества"}, "cabinet": {"name": "404"},
        "teachers": [{"fio": "Палладий Н."}],
        "unionGroups": [{"group": {"id": 304}, "subgroup": {"name": "1 п/г"}}],
        "replacementType": "substitute",
    }
    l = parse_lesson(raw, 304)
    assert (l.subject, l.cabinet, l.teacher, l.subgroup, l.status) == (
        "Обеспечение качества", "404", "Палладий Н.", "1 п/г", "substitute")


def test_normalize_publication_id():
    assert normalize_publication_id("01a00f53d32773b5b396bf3eb6f57ce2") == "01a00f53-d327-73b5-b396-bf3eb6f57ce2"
