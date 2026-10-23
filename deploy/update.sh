#!/bin/bash
# Выкат журнала на сервере (от root). Обычно вызывается из /usr/local/sbin/duty-journal-deploy
# (GitHub Actions по пушу в main) уже после git checkout нужного коммита в /opt/duty-journal.
#   bash /opt/duty-journal/deploy/update.sh            # зависимости (если сменились), юнит/бэкап/nginx (если сменились), рестарт, проверка
#   bash /opt/duty-journal/deploy/update.sh --restart  # то же, но перезапустить в любом случае (используется при откате)
# В конце — проверка: сервис active и GET http://127.0.0.1:8080/health == ok. Иначе код выхода 1.
set -euo pipefail
cd /
umask 022
APP=/opt/duty-journal
D=$APP/deploy
STATE=/var/lib/duty-journal-deploy
FORCE=0; [[ ${1:-} == --restart ]] && FORCE=1
[[ $EUID -eq 0 ]] || { echo "Запустите от root"; exit 1; }
install -d -m 755 "$STATE"

# 1) зависимости: ставим, если сменился requirements.txt или requirements-deploy.txt
REQ_HASH=$(cat "$APP/requirements.txt" "$D/requirements-deploy.txt" | sha256sum | cut -d' ' -f1)
if [[ ! -x $APP/.venv/bin/python ]]; then
  echo "создаю venv"; uv venv -q --python /usr/bin/python3 "$APP/.venv"; rm -f "$STATE/req.sha256"
fi
if [[ $REQ_HASH != "$(cat "$STATE/req.sha256" 2>/dev/null)" ]]; then
  echo "зависимости изменились, ставлю"
  UV_CACHE_DIR=/var/cache/duty-journal-uv uv pip install -q --python "$APP/.venv/bin/python" -r "$APP/requirements.txt" -r "$D/requirements-deploy.txt"
  echo "$REQ_HASH" > "$STATE/req.sha256"; FORCE=1
fi

# 2) systemd-юнит, бэкап, cron — если отличаются от установленных
if ! cmp -s "$D/duty-journal.service" /etc/systemd/system/duty-journal.service; then
  install -m 644 "$D/duty-journal.service" /etc/systemd/system/duty-journal.service
  systemctl daemon-reload; systemctl enable -q duty-journal; echo "юнит обновлён"; FORCE=1
fi
cmp -s "$D/backup.sh" /usr/local/bin/duty-journal-backup.sh || { install -m 755 "$D/backup.sh" /usr/local/bin/duty-journal-backup.sh; echo "бэкап-скрипт обновлён"; }
cmp -s "$D/duty-journal-backup.cron" /etc/cron.d/duty-journal-backup || { install -m 644 "$D/duty-journal-backup.cron" /etc/cron.d/duty-journal-backup; echo "cron обновлён"; }

# 3) код: перезапуск, если сменился коммит
HEAD=$(git -C "$APP" rev-parse HEAD)
[[ $HEAD != "$(cat "$STATE/running" 2>/dev/null)" ]] && FORCE=1
if (( FORCE )); then echo "перезапуск duty-journal"; systemctl restart duty-journal; else echo "ничего не изменилось, перезапуск не нужен"; fi

# 4) проверка
ok=0
for i in $(seq 1 20); do [[ $(curl -s -m 3 http://127.0.0.1:8080/health) == ok* ]] && { ok=1; break; }; sleep 1; done
systemctl is-active --quiet duty-journal || ok=0
if (( ok )); then echo "$HEAD" > "$STATE/running"; echo "health: duty-journal active, /health ok"; exit 0; fi
echo "health: FAIL duty-journal ($(systemctl is-active duty-journal)), /health не отвечает ok"
journalctl -u duty-journal -n 30 --no-pager -o cat || true
exit 1
