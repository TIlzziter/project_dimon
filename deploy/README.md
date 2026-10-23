# Журнал на сервере (VPS Selectel, Ubuntu 24.04)

Боевой адрес: **https://duty-journal.nicholas-the-great.xyz** (корень `nicholas-the-great.xyz` и `www` временно ведут сюда редиректом 302).
На том же сервере работает бот QuestHub; журнал живёт отдельно: свой пользователь, свой каталог, свой юнит.

| Что | Где на сервере | В репозитории |
|---|---|---|
| код (клон, root, detached HEAD = выкаченный коммит) | `/opt/duty-journal/` | весь репозиторий |
| окружение Python (venv, uv, системный Python 3.12) | `/opt/duty-journal/.venv/` | `requirements.txt` + `deploy/requirements-deploy.txt` (gunicorn) |
| база SQLite | `/var/lib/duty-journal/journal.sqlite` (владелец `duty-journal`, 700) | — |
| настройки и `SECRET_KEY` | `/etc/duty-journal/env` (root, 600) | — (секрет только на сервере) |
| юнит `duty-journal` (gunicorn `--preload`, 2 воркера, 127.0.0.1:8080) | `/etc/systemd/system/duty-journal.service` | `deploy/duty-journal.service` |
| точка входа gunicorn (`TRUST_PROXY=1` → ProxyFix) | — | `wsgi.py` |
| nginx | `/etc/nginx/sites-available/{00-default,duty-journal}.conf` | `deploy/nginx/` |
| сертификат Let's Encrypt (certbot, автопродление `certbot.timer`) | `/etc/letsencrypt/live/duty-journal.nicholas-the-great.xyz/` | — |
| ночной бэкап 03:45, 7 дней | `/usr/local/bin/duty-journal-backup.sh`, `/etc/cron.d/duty-journal-backup` → `/var/backups/duty-journal/` | `deploy/backup.sh`, `deploy/duty-journal-backup.cron` |
| автодеплой | `/usr/local/sbin/duty-journal-deploy`, лог `/var/log/duty-journal-deploy.log`, состояние `/var/lib/duty-journal-deploy/` | `deploy/duty-journal-deploy.sh`, `deploy/update.sh`, `.github/workflows/deploy.yml` |

Переменные в `/etc/duty-journal/env`: `HOST=127.0.0.1`, `PORT=8080`, `DATA_DIR=/var/lib/duty-journal`, `SECRET_KEY=<случайная строка>`, `COOKIE_SECURE=1`, `PDF_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`, `TRUST_PROXY=1`.
`seed-demo` на сервере **не запускался**: демо-пользователей нет, пароль `admin` сменён на случайный.

## Автодеплой

Пуш в `main` → GitHub Actions (`.github/workflows/deploy.yml`):

1. **test**: Python 3.12, `pip install -r requirements.txt`, `python -m pytest -q`. Красные тесты — деплоя нет.
2. **deploy**: `ssh deploy@<DEPLOY_HOST> <sha>` ключом из секрета `DEPLOY_SSH_KEY`, host key закреплён секретом `DEPLOY_KNOWN_HOSTS`.
   На сервере этот ключ привязан к forced command `sudo -n /usr/local/sbin/duty-journal-deploy "<sha>"` (без shell и проброса портов);
   пользователь `deploy` через sudo может запускать только скрипты деплоя.
3. `duty-journal-deploy`: flock → `git fetch` (read-only deploy key `/root/.ssh/duty_journal_deploy`) → sha обязан быть в истории `origin/main` →
   `checkout --detach` → `deploy/update.sh`: зависимости (если сменились), юнит/бэкап/cron (если сменились), рестарт, проверка `GET /health == ok`.
   Проверка не прошла → откат на последний удачный коммит, рестарт, job красный.

Запуск только на `push` в `main` и вручную (`workflow_dispatch`); `pull_request` (в т.ч. из форков) workflow не запускает, секреты им недоступны.
Concurrency `deploy-production`: выкаты не пересекаются.

**Откат:** `git revert <коммит> && git push`, или Actions → deploy → Run workflow с `sha` старого коммита
(`gh workflow run deploy -R TIlzziter/project_dimon -f sha=<sha>`), или на сервере от root: `/usr/local/sbin/duty-journal-deploy <sha>`.

**Выкатить руками** (от root на сервере): `/usr/local/sbin/duty-journal-deploy` — свежий `origin/main` с проверкой и автооткатом.

## Обслуживание

```bash
systemctl status duty-journal; journalctl -u duty-journal -f
curl -s 127.0.0.1:8080/health                                   # ok
curl -s https://duty-journal.nicholas-the-great.xyz/health       # ok (снаружи)
tail /var/log/duty-journal-deploy.log /var/log/duty-journal-backup.log
ls -lh /var/backups/duty-journal/
```

**Восстановить базу из бэкапа:**

```bash
systemctl stop duty-journal
gunzip -c /var/backups/duty-journal/journal_<дата>.sqlite.gz > /var/lib/duty-journal/journal.sqlite
rm -f /var/lib/duty-journal/journal.sqlite-wal /var/lib/duty-journal/journal.sqlite-shm
chown duty-journal:duty-journal /var/lib/duty-journal/journal.sqlite
systemctl start duty-journal
```

**Сменить пароль пользователя без входа в интерфейс** (пароль читается из stdin, в историю не попадает):

```bash
cd /opt/duty-journal && read -rs PW && printf '%s\n' "$PW" | sudo -u duty-journal env DATA_DIR=/var/lib/duty-journal \
  .venv/bin/python -c "import sys; from app.config import load_settings; from app.db import connect; from app.domain import hash_password
s=load_settings(); c=connect(s.db_path); c.execute(\"UPDATE users SET password_hash=? WHERE login='admin'\", (hash_password(sys.stdin.readline().rstrip('\n')),)); c.commit()"; unset PW
```
