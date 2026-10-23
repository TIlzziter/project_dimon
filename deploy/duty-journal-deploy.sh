#!/bin/bash
# Точка входа автодеплоя журнала. Ставится в /usr/local/sbin/duty-journal-deploy (root:root 755).
# Пользователь deploy запускает её через sudo (только её и questhub-deploy, /etc/sudoers.d/deploy);
# ключ GitHub Actions этого репозитория в authorized_keys привязан к forced command.
#   duty-journal-deploy [<sha>]   выкатить коммит (по умолчанию — свежий origin/main); коммит обязан быть в истории main
# flock -> git fetch -> checkout --detach <sha> -> deploy/update.sh. Если проверка не прошла —
# откат на последний удачный коммит (скриптами того коммита) и код выхода 1.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
APP=/opt/duty-journal
STATE=/var/lib/duty-journal-deploy
LOG=/var/log/duty-journal-deploy.log
cd /
umask 022
install -d -m 755 "$STATE"
exec 9>"$STATE/lock"
flock -w 600 9 || { echo "другой деплой не закончился за 10 минут"; exit 1; }
exec > >(tee -a "$LOG") 2>&1
echo "===== $(date '+%F %T %Z') duty-journal-deploy ${1:-}"

ARG=${1:-}
[[ -z $ARG || $ARG =~ ^[0-9a-f]{7,40}$ ]] || { echo "ожидается sha коммита (hex 7-40), получено: ${ARG:0:60}"; exit 2; }
git -C "$APP" fetch -q origin main
SHA=$(git -C "$APP" rev-parse --verify "${ARG:-origin/main}^{commit}") || { echo "коммит $ARG не найден"; exit 2; }
git -C "$APP" merge-base --is-ancestor "$SHA" origin/main || { echo "коммит $SHA не в истории origin/main — отказ"; exit 2; }
PREV=$(cat "$STATE/last-good" 2>/dev/null || git -C "$APP" rev-parse HEAD)
echo "выкат: ${PREV:0:7} -> ${SHA:0:7} $(git -C "$APP" log -1 --format=%s "$SHA")"

git -C "$APP" checkout -q --detach "$SHA"
if bash "$APP/deploy/update.sh"; then
  echo "$SHA" > "$STATE/last-good"
  cmp -s "$APP/deploy/duty-journal-deploy.sh" /usr/local/sbin/duty-journal-deploy || install -m 755 "$APP/deploy/duty-journal-deploy.sh" /usr/local/sbin/duty-journal-deploy
  echo "DEPLOY OK $SHA"; exit 0
fi
echo "!!! выкат $SHA не прошёл проверку — откат на $PREV"
git -C "$APP" checkout -q --detach "$PREV"
if [[ -f $APP/deploy/update.sh ]] && bash "$APP/deploy/update.sh" --restart; then echo "ROLLBACK OK: работает $PREV"
else echo "!!! ОТКАТ ТОЖЕ НЕ ПРОШЁЛ — нужен человек (journalctl -u duty-journal)"; fi
echo "DEPLOY FAILED $SHA"; exit 1
