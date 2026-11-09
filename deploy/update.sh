#!/usr/bin/env bash
# Обновление бота на сервере до последней версии из GitHub.
# Запуск:  bash deploy/update.sh
# Настройки (.env) и база (schedule.db) при обновлении не затрагиваются.
set -euo pipefail

SERVICE="helpmyschedule"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

echo "==> Скачиваю обновления"
git pull --ff-only

echo "==> Обновляю зависимости"
.venv/bin/pip install -r requirements.txt -q

echo "==> Перезапускаю бота"
sudo systemctl restart "$SERVICE"
sleep 3
if systemctl is-active --quiet "$SERVICE"; then
    echo "✅ Готово, бот работает. Логи: journalctl -u $SERVICE -f"
else
    echo "❌ Бот не запустился:" >&2
    sudo journalctl -u "$SERVICE" -n 30 --no-pager >&2
    exit 1
fi
