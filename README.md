# helpmyschedule — Telegram-бот с расписанием занятий

Бот следит за расписанием группы на
[site.mstimetables.ru](https://site.mstimetables.ru/01a00f53d32773b5b396bf3eb6f57ce2/groups/304).
Он присылает:

- ⚠️ **изменения в расписании**: переносы, замены, отмены, смену аудитории или преподавателя. Формат — «Было: … Стало: …»;
- ☀️ **утреннюю сводку**: «Доброе утро! Сегодня у тебя 3 пары. Первая в 09:00.»;
- 🔔 **напоминание за 15 минут до пары**: «Следующая пара: 5-я пара — Классный час, каб. 204, Доброхотова Т.В.».

Если изменений нет, бот молчит.

## Команды

| Команда | Что делает |
|---|---|
| `/start` | приветствие и подписка на уведомления |
| `/today` | расписание на сегодня |
| `/tomorrow` | расписание на завтра |
| `/week` | расписание на текущую неделю |
| `/nextweek` | расписание на следующую неделю |
| `/check` | проверить изменения прямо сейчас |
| `/stop` | отписаться от уведомлений |

Под полем ввода есть кнопки «Сегодня / Завтра / Неделя / След. неделя».

## Как бот получает расписание

Сайт сделан на Nuxt (Vue) и берёт данные из открытого JSON API:

```
GET https://site.mstimetables.ru/api/publications/<UUID>/groups/<ID>/lessons?startDate=2026-11-09&endDate=2026-11-15
```

Бот обращается к этому API напрямую. **Playwright и браузер не нужны**:
JSON надёжнее разбора HTML, работает быстрее и не тратит память. API отдаёт
не больше 31 дня за запрос. Более длинные периоды `parser.py` запрашивает по частям.

У каждой пары берутся дата и день недели, номер, время начала и конца, предмет,
преподаватель, аудитория, подгруппа и тип замены (`replacementType`). Тип замены
бывает обычной парой, отменой, заменой, переносом и т. д.

## Структура проекта

```
config.py      — настройки из переменных окружения / .env
parser.py      — запросы к API сайта → список объектов Lesson
database.py    — SQLite: подписчики, снимок расписания, журнал отправленных уведомлений
diff.py        — сравнение старого и нового расписания (что добавилось/удалилось/изменилось)
messages.py    — тексты сообщений (HTML), деление длинных сообщений
scheduler.py   — фоновые задачи APScheduler: проверка изменений, утренняя сводка, напоминания
bot.py         — обработчики команд aiogram 3 и точка входа (python bot.py)
tests/         — тесты (pytest)
```

### Как работает отслеживание изменений

1. Каждые `CHECK_INTERVAL_MIN` минут (по умолчанию 20) бот скачивает расписание
   на `TRACK_DAYS` дней вперёд (по умолчанию 14).
2. Затем сравнивает его со снимком в SQLite. Сравниваются только дни, которые есть
   в обоих снимках, начиная с сегодняшнего. Поэтому прошедшие дни и новые дни
   в конце периода не считаются изменениями.
3. Сначала пары сопоставляются по времени. Затем по предмету: если сменилось только
   время, это один «перенос», а не «удалена + добавлена».
4. При первом запуске бот только сохраняет снимок и ничего не рассылает.
5. Бывает, что сайт вдруг вернул пустое расписание, хотя раньше пары были. Тогда бот
   ждёт подтверждения при следующей проверке, чтобы сбой на сайте не превратился
   в рассылку «все пары отменены».

## Установка и запуск локально

Нужен Python 3.10 или новее.

```bash
git clone https://github.com/f1rdavsss1/helpmyschedule.git
cd helpmyschedule

python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -r requirements.txt
```

### Проверка парсера (токен не нужен)

```bash
python parser.py              # текущая неделя
python parser.py 2026-11-16   # неделя, в которую входит указанная дата
```

Пример вывода:

```
Группа: 09-23.ИСИП.ОФ.9 10-23.ИСИП.ОФ.9

=== Понедельник, 09.11.2026 ===
1. 09:00-10:30  МДК.01.04 Системное программирование | Екимов И. | каб. 513
2. 10:40-12:10  Иностранный язык в профессиональной деятельности | Некрасов М.В. | каб. 511
```

### Получение токена в BotFather

1. Откройте в Telegram [@BotFather](https://t.me/BotFather) и нажмите **Start**.
2. Отправьте `/newbot`.
3. Введите имя бота, например «Моё расписание».
4. Введите username. Он должен заканчиваться на `bot`, например `my_schedule_304_bot`.
5. BotFather пришлёт токен вида `1234567890:AAH...`. **Никому его не показывайте**
   и не коммитьте в git.

### Настройка и запуск

```bash
cp .env.example .env      # Windows: copy .env.example .env
# откройте .env и впишите BOT_TOKEN
python bot.py
```

Откройте своего бота в Telegram и отправьте `/start`.

Чтобы следить за другой группой, поменяйте в `.env` переменные `PUBLICATION_ID`
и `GROUP_ID`. Обе берутся из ссылки `https://site.mstimetables.ru/<PUBLICATION_ID>/groups/<GROUP_ID>`.

### Все настройки

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | токен от @BotFather (обязательно) |
| `PUBLICATION_ID` | `01a00f53-d327-73b5-b396-bf3eb6f57ce2` | идентификатор публикации из ссылки |
| `GROUP_ID` | `304` | номер группы из ссылки |
| `TIMEZONE` | `Europe/Moscow` | часовой пояс колледжа |
| `CHECK_INTERVAL_MIN` | `20` | период проверки изменений, минуты |
| `MORNING_TIME` | `07:30` | время утренней сводки |
| `REMIND_BEFORE_MIN` | `15` | за сколько минут напоминать о паре |
| `TRACK_DAYS` | `14` | на сколько дней вперёд следить |
| `DB_PATH` | `schedule.db` | путь к файлу SQLite |

### Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Тесты не обращаются ни к Telegram, ни к сайту.

## Развёртывание

Бот работает через long polling. Ему не нужны домен, вебхук или открытый порт:
достаточно процесса, который работает постоянно.

### Railway

1. Загрузите код в GitHub. Файл `.env` в репозиторий не попадёт: он в `.gitignore`.
2. На [railway.com](https://railway.com) выберите **New Project → Deploy from GitHub repo**
   и укажите репозиторий.
3. Во вкладке **Variables** добавьте `BOT_TOKEN`. Остальные переменные можно
   добавить по желанию.
4. Railway сам найдёт `requirements.txt`. Версию Python задаёт `.python-version`.
   Команду запуска задаёт `Procfile` (`worker: python bot.py`). Если Railway её
   не подхватит, укажите в **Settings → Deploy → Start Command**: `python bot.py`.
5. **Важно про базу.** Файловая система контейнера очищается при каждом деплое.
   Чтобы не терять подписчиков и снимок:
   - добавьте **Volume**: правый клик по сервису → *Attach Volume*, путь монтирования `/data`;
   - задайте переменную `DB_PATH=/data/schedule.db`.
6. Логи смотрите во вкладке **Deployments → View Logs**. Там видно
   «Изменений нет» / «Найдено изменений: N».

### PythonAnywhere

1. Зарегистрируйтесь на [pythonanywhere.com](https://www.pythonanywhere.com) и откройте **Consoles → Bash**.
2. Выполните:
   ```bash
   git clone https://github.com/f1rdavsss1/helpmyschedule.git
   cd helpmyschedule
   python3.10 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env && nano .env      # впишите BOT_TOKEN
   python parser.py                       # проверка, что сайт доступен
   ```
3. Во вкладке **Tasks → Always-on tasks** добавьте команду:
   ```
   /home/<ваш_логин>/helpmyschedule/.venv/bin/python /home/<ваш_логин>/helpmyschedule/bot.py
   ```
   Always-on задачи доступны только на платных аккаунтах.

> **Ограничение бесплатного аккаунта PythonAnywhere.** Интернет там доступен
> только к сайтам из белого списка и только через прокси. `api.telegram.org`
> в списке есть, а `site.mstimetables.ru`, скорее всего, нет. Если
> `python parser.py` выдаёт ошибку подключения, нужен платный аккаунт или
> другой хостинг. Бот учитывает переменные `HTTP(S)_PROXY`, поэтому прокси
> PythonAnywhere подхватится сам.

### Свой сервер / VPS (systemd)

```ini
# /etc/systemd/system/helpmyschedule.service
[Unit]
Description=helpmyschedule Telegram bot
After=network-online.target

[Service]
WorkingDirectory=/opt/helpmyschedule
ExecStart=/opt/helpmyschedule/.venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now helpmyschedule
journalctl -u helpmyschedule -f
```

## Если сайт изменится

Если разработчики сайта поменяют API, нужно поправить только `parser.py`:
функцию `parse_lesson` и адрес в `ScheduleParser.api_url`. Остальной код
работает с объектами `Lesson` и от формата сайта не зависит. Если API совсем
закроют, можно перейти на Playwright (`pip install playwright && playwright install chromium`)
и брать данные из `window.__NUXT__` на странице. Сейчас это не нужно.
