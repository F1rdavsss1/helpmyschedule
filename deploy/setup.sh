#!/usr/bin/env bash
# =============================================================================
# Установка бота на сервер с Ubuntu (Oracle Cloud Always Free или любой VPS).
#
# Запуск (из папки репозитория на сервере):
#     bash deploy/setup.sh
#
# Что делает скрипт:
#   1. ставит Python и venv;
#   2. создаёт виртуальное окружение .venv и ставит зависимости;
#   3. спрашивает токен бота и создаёт файл .env (если его ещё нет);
#   4. проверяет токен и доступ к сайту с расписанием;
#   5. регистрирует бота как службу systemd — он запускается сам при
#      включении сервера и перезапускается, если упадёт.
#
# Скрипт можно запускать повторно: уже сделанные шаги он не ломает.
# =============================================================================
set -euo pipefail

SERVICE="helpmyschedule"
# Папка репозитория — на уровень выше папки, где лежит этот скрипт.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"

cd "$APP_DIR"

echo "==> [1/5] Устанавливаю Python и нужные пакеты"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip git curl

echo "==> [2/5] Создаю виртуальное окружение и ставлю зависимости"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "==> [3/5] Настройки (.env)"
if [ ! -f .env ]; then
    cp .env.example .env
    # Читаем токен с клавиатуры (ввод не отображается на экране).
    read -rsp "Вставьте токен бота от @BotFather и нажмите Enter: " TOKEN </dev/tty
    echo
    if ! [[ "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        echo "Токен выглядит неправильно (ожидается вид 1234567890:AAH...). Удаляю .env, запустите скрипт ещё раз." >&2
        rm -f .env
        exit 1
    fi
    sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=${TOKEN}|" .env
    chmod 600 .env   # токен — секрет, читать файл может только владелец
    echo "Файл .env создан. Остальные настройки можно поменять командой: nano $APP_DIR/.env"
else
    echo "Файл .env уже есть — оставляю как есть."
fi

echo "==> [4/5] Проверяю токен и доступ к сайту"
TOKEN="$(grep -E '^BOT_TOKEN=' .env | cut -d= -f2-)"
if curl -fsS "https://api.telegram.org/bot${TOKEN}/getMe" | grep -q '"ok":true'; then
    echo "Токен рабочий."
else
    echo "Telegram не принял токен. Проверьте BOT_TOKEN в $APP_DIR/.env и запустите скрипт снова." >&2
    exit 1
fi
if .venv/bin/python parser.py >/dev/null; then
    echo "Сайт с расписанием доступен."
else
    echo "ВНИМАНИЕ: не удалось получить расписание с сайта. Бот запустится, но проверьте сеть сервера." >&2
fi

echo "==> [5/5] Регистрирую службу systemd: $SERVICE"
sudo tee "/etc/systemd/system/${SERVICE}.service" >/dev/null <<EOF
[Unit]
Description=helpmyschedule Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE" >/dev/null 2>&1
sudo systemctl restart "$SERVICE"
sleep 3

if systemctl is-active --quiet "$SERVICE"; then
    echo
    echo "✅ Бот запущен и будет работать постоянно (в том числе после перезагрузки сервера)."
    echo "   Откройте бота в Telegram и отправьте /start."
    echo
    echo "   Логи:        journalctl -u $SERVICE -f"
    echo "   Статус:      sudo systemctl status $SERVICE"
    echo "   Перезапуск:  sudo systemctl restart $SERVICE"
    echo "   Обновление:  bash $APP_DIR/deploy/update.sh"
else
    echo "❌ Служба не запустилась. Последние строки лога:" >&2
    sudo journalctl -u "$SERVICE" -n 30 --no-pager >&2
    exit 1
fi
