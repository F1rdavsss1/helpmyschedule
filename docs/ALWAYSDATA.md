# Бот 24/7 бесплатно на alwaysdata (без банковской карты)

[alwaysdata](https://www.alwaysdata.com) — французский хостинг. У него есть бесплатный
план **Free** для личных некоммерческих проектов. Карта при регистрации не нужна.
На этом плане можно запустить постоянно работающий процесс («Service»): хостинг сам
запускает бота и перезапускает его, если тот упадёт.

Компьютер нужен только на время настройки, примерно 15 минут. Потом его можно выключить.

> Названия пунктов меню в панели могут немного отличаться: интерфейс иногда меняется.

---

## Шаг 1. Регистрация

1. Откройте https://www.alwaysdata.com, нажмите **Sign up** и выберите тариф **Free**
   (раздел *Public Cloud*).
2. Придумайте **имя аккаунта**, например `myschedule`. Дальше в инструкции оно
   обозначено как `ИМЯ`.
3. Подтвердите почту и войдите в панель управления: https://admin.alwaysdata.com

## Шаг 2. Включить вход по SSH

1. В панели откройте **Remote access → SSH**.
2. Нажмите на карандаш рядом с пользователем `ИМЯ`, поставьте галочку
   **Enable password-based login**, задайте пароль и сохраните.
3. Адрес сервера для SSH указан там же. Обычно это `ssh-ИМЯ.alwaysdata.net`.

Подключитесь из PowerShell (Windows) или Терминала (macOS):

```bash
ssh ИМЯ@ssh-ИМЯ.alwaysdata.net
```

## Шаг 3. Установка бота

Выполните на сервере по очереди:

```bash
git clone https://github.com/F1rdavsss1/helpmyschedule.git
cd helpmyschedule
git checkout claude/telegram-schedule-bot-tmxqej   # не нужно, если ветка уже влита в main

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python parser.py        # проверка: должно вывести расписание недели

cp .env.example .env
nano .env                         # впишите BOT_TOKEN=..., затем Ctrl+O, Enter, Ctrl+X
chmod 600 .env
```

Пробный запуск: выполните `.venv/bin/python bot.py` и напишите боту `/start`.
Если бот ответил, остановите его клавишами **Ctrl+C**. Дальше бота будет
запускать хостинг.

## Шаг 4. Запуск бота как службы

1. В панели откройте **Advanced → Services → Add a service**.
2. Заполните поля:
   - **Name**: `helpmyschedule`
   - **Command**: `/home/ИМЯ/helpmyschedule/.venv/bin/python bot.py`
   - **Working directory**: `/home/ИМЯ/helpmyschedule`
3. Сохраните. Служба запустится сразу и будет перезапускаться сама.

Теперь можно закрыть SSH и выключить компьютер.

> ⚠️ Бот должен работать только в одном месте. Если где-то ещё запущена копия
> с тем же токеном, остановите её. Иначе Telegram выдаст ошибку
> *Conflict: terminated by other getUpdates request*.

## Логи и обновление

- **Логи:** раздел **Services** в панели или файлы в папке `~/admin/logs/services/`.
  Каждые 20 минут там появляется строка `Изменений нет (…)`.
- **Обновление бота:**
  ```bash
  ssh ИМЯ@ssh-ИМЯ.alwaysdata.net
  cd helpmyschedule && git pull && .venv/bin/pip install -r requirements.txt
  ```
  Затем в панели: **Services** → `helpmyschedule` → **Restart**.

## Частые проблемы

| Проблема | Что делать |
|---|---|
| `python3: command not found` или старая версия Python | В панели: **Environment → Python** → выберите версию 3.10 или новее |
| Не хватает места при `pip install` | Удалите кэш: `rm -rf ~/.cache/pip` |
| Служба сразу останавливается | Проверьте лог службы; часто причина — неверный путь в **Command** или опечатка в `BOT_TOKEN` |
| `parser.py` не может достучаться до сайта | Напишите мне, разберёмся |
