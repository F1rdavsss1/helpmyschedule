"""
diff.py — сравнение старого и нового расписания.

Задача: по двум спискам пар понять, что именно поменялось, и описать это
по-человечески — «было вот так, стало вот так», а не «одна пара удалена,
другая добавлена».

Алгоритм для каждого дня:
  1. Пары, совпадающие полностью, считаем неизменными и откладываем.
  2. Оставшиеся пары сопоставляем по «слоту» (время начала + подгруппа):
     в том же слоте сменилась аудитория, преподаватель, предмет или пару
     отменили → это «изменение».
  3. Затем сопоставляем по предмету (+ подгруппа): предмет тот же, а время
     другое → это «перенос по времени», тоже «изменение».
  4. Всё, что осталось без пары: в старом расписании — «удалена»,
     в новом — «добавлена».
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Literal

from parser import Lesson

ChangeKind = Literal["added", "removed", "changed"]


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    old: Lesson | None   # None для добавленной пары
    new: Lesson | None   # None для удалённой пары

    @property
    def date(self) -> str:
        return (self.new or self.old).date  # type: ignore[union-attr]

    @property
    def sort_key(self) -> tuple:
        lesson = self.new or self.old
        return (lesson.date, lesson.start_time, lesson.lesson_number, lesson.subgroup)  # type: ignore[union-attr]


def _pair_by(
    old: list[Lesson], new: list[Lesson], key: Callable[[Lesson], tuple]
) -> tuple[list[tuple[Lesson, Lesson]], list[Lesson], list[Lesson]]:
    """
    Сопоставляет пары из old и new с одинаковым ключом (по одной на ключ).
    Возвращает найденные пары и то, что осталось без соответствия.
    """
    buckets: dict[tuple, list[Lesson]] = defaultdict(list)
    for lesson in new:
        buckets[key(lesson)].append(lesson)

    matched: list[tuple[Lesson, Lesson]] = []
    old_left: list[Lesson] = []
    for lesson in old:
        candidates = buckets.get(key(lesson))
        if candidates:
            matched.append((lesson, candidates.pop(0)))
        else:
            old_left.append(lesson)
    new_left = [l for bucket in buckets.values() for l in bucket]
    return matched, old_left, new_left


def diff_day(old: list[Lesson], new: list[Lesson]) -> list[Change]:
    """Изменения в пределах одного дня."""
    # Шаг 1: полностью одинаковые пары (Lesson — неизменяемый dataclass, сравнивается по всем полям).
    _, old, new = _pair_by(old, new, key=lambda l: (l,))

    changes: list[Change] = []
    # Шаг 2: тот же слот, но что-то поменялось внутри.
    matched, old, new = _pair_by(old, new, key=lambda l: (l.start_time, l.subgroup))
    changes += [Change("changed", o, n) for o, n in matched]
    # Шаг 3: тот же предмет, но другое время.
    matched, old, new = _pair_by(old, new, key=lambda l: (l.subject, l.subgroup))
    changes += [Change("changed", o, n) for o, n in matched]
    # Шаг 4: всё остальное.
    changes += [Change("removed", o, None) for o in old]
    changes += [Change("added", None, n) for n in new]
    return changes


def diff_lessons(old: list[Lesson], new: list[Lesson]) -> list[Change]:
    """Изменения между двумя расписаниями (за любое количество дней)."""
    old_by_day: dict[str, list[Lesson]] = defaultdict(list)
    new_by_day: dict[str, list[Lesson]] = defaultdict(list)
    for l in old:
        old_by_day[l.date].append(l)
    for l in new:
        new_by_day[l.date].append(l)

    changes: list[Change] = []
    for day in sorted(set(old_by_day) | set(new_by_day)):
        changes += diff_day(old_by_day.get(day, []), new_by_day.get(day, []))
    return sorted(changes, key=lambda c: c.sort_key)
