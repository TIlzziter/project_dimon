#!/bin/bash
# Ночной бэкап базы журнала: sqlite3 .backup (корректно с WAL и при работающем сайте), храним 7 дней.
# Ставится в /usr/local/bin/duty-journal-backup.sh, запускается из /etc/cron.d/duty-journal-backup.
set -euo pipefail
cd /
umask 077
DB=/var/lib/duty-journal/journal.sqlite
OUT=/var/backups/duty-journal
install -d -m 700 "$OUT"
f="$OUT/journal_$(date +%F_%H%M).sqlite"
sqlite3 "$DB" ".backup '$f'"
sqlite3 "$f" "PRAGMA integrity_check;" | grep -qx ok
gzip -f "$f"
find "$OUT" -name 'journal_*.sqlite.gz' -mtime +6 -delete
echo "$(date '+%F %T') ok $f.gz"
