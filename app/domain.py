from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

KINDS = ("department", "section", "service", "room", "monitoring", "kit")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def split_dt(value: str | None) -> tuple[str, str]:
    if not value:
        return "", ""
    stamp = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return stamp.strftime("%d.%m.%y"), stamp.strftime("%H:%M")


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def check_password(user, password: str) -> bool:
    return check_password_hash(user["password_hash"], password)


def _loads(text: str | None) -> list:
    if not text:
        return []
    return json.loads(text)


def display_name(user) -> str:
    if user is None:
        return ""
    return user["full_name"] or user["login"]


def next_number(conn: sqlite3.Connection, counter: str, prefix: str) -> str:
    conn.execute(
        "INSERT INTO counters (name, value) VALUES (?, 0) ON CONFLICT(name) DO NOTHING",
        (counter,),
    )
    conn.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (counter,))
    value = conn.execute(
        "SELECT value FROM counters WHERE name = ?", (counter,)
    ).fetchone()["value"]
    return f"{prefix}{value:04d}"


def setting_get(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def setting_set(conn, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_user(conn, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_login(conn, login: str):
    return conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()


def list_users(conn):
    return conn.execute("SELECT * FROM users ORDER BY login").fetchall()


def groups_of(conn, user_id: int):
    return conn.execute(
        """SELECT g.* FROM groups g
           JOIN user_groups ug ON ug.group_id = g.id
           WHERE ug.user_id = ?
           ORDER BY g.name""",
        (user_id,),
    ).fetchall()


def list_groups(conn):
    return conn.execute("SELECT * FROM groups ORDER BY name").fetchall()


def shift_group(conn):
    return conn.execute(
        "SELECT * FROM groups WHERE is_shift_group = 1 ORDER BY id LIMIT 1"
    ).fetchone()


def directory(conn, kind: str, active_only: bool = True):
    if kind not in KINDS:
        raise ValueError("Неизвестный справочник")
    if active_only:
        return conn.execute(
            "SELECT * FROM directories WHERE kind = ? AND active = 1 ORDER BY name",
            (kind,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM directories WHERE kind = ? ORDER BY active DESC, name",
        (kind,),
    ).fetchall()


def names_of(conn, kind: str) -> set[str]:
    return {row["name"] for row in directory(conn, kind, active_only=False)}


def open_shift(conn):
    return conn.execute(
        "SELECT * FROM shifts WHERE status = 'open' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def handed_shift(conn):
    return conn.execute(
        "SELECT * FROM shifts WHERE status = 'handed' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def shift_by_id(conn, shift_id: int):
    return conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()


def create_user(conn, login, password, full_name, position, is_admin, can_duty, is_brigadier, group_ids):
    login = login.strip()
    if not login or not password:
        raise ValueError("Нужны логин и пароль")
    if get_user_by_login(conn, login) is not None:
        raise ValueError("Такой логин уже есть")
    cur = conn.execute(
        """INSERT INTO users
           (login, password_hash, full_name, position, is_admin, can_duty, is_brigadier)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            login,
            hash_password(password),
            full_name.strip(),
            position.strip(),
            int(bool(is_admin)),
            int(bool(can_duty)),
            int(bool(is_brigadier)),
        ),
    )
    _set_groups(conn, cur.lastrowid, group_ids)
    return cur.lastrowid


def update_user(conn, user_id, full_name, position, is_admin, can_duty, is_brigadier, password, group_ids, editor_id):
    user = get_user(conn, user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    if user_id == editor_id and not is_admin:
        raise ValueError("Себе нельзя снять права администратора")
    conn.execute(
        """UPDATE users
           SET full_name = ?, position = ?, is_admin = ?, can_duty = ?, is_brigadier = ?
           WHERE id = ?""",
        (
            full_name.strip(),
            position.strip(),
            int(bool(is_admin)),
            int(bool(can_duty)),
            int(bool(is_brigadier)),
            user_id,
        ),
    )
    if password:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user_id),
        )
    _set_groups(conn, user_id, group_ids)


def _set_groups(conn, user_id, group_ids):
    conn.execute("DELETE FROM user_groups WHERE user_id = ?", (user_id,))
    for raw in group_ids:
        conn.execute(
            "INSERT OR IGNORE INTO user_groups (user_id, group_id) VALUES (?, ?)",
            (user_id, int(raw)),
        )


def add_directory(conn, kind: str, name: str) -> None:
    name = name.strip()
    if kind not in KINDS:
        raise ValueError("Неизвестный справочник")
    if not name:
        raise ValueError("Введите название")
    try:
        conn.execute(
            "INSERT INTO directories (kind, name, active) VALUES (?, ?, 1)",
            (kind, name),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Такое значение уже есть") from exc


def rename_directory(conn, item_id: int, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Введите название")
    try:
        conn.execute("UPDATE directories SET name = ? WHERE id = ?", (name, item_id))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Такое значение уже есть") from exc


def deactivate_directory(conn, item_id: int) -> None:
    conn.execute("UPDATE directories SET active = 0 WHERE id = ?", (item_id,))


def add_group(conn, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Введите название группы")
    try:
        conn.execute("INSERT INTO groups (name, is_shift_group) VALUES (?, 0)", (name,))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Такая группа уже есть") from exc


def assign_next(conn, user_id: int) -> None:
    user = get_user(conn, user_id)
    if user is None or not user["can_duty"]:
        raise ValueError("Назначить можно только пользователя с правом дежурства")
    current = open_shift(conn)
    if current is not None and current["duty_user_id"] == user_id:
        raise ValueError("Этот человек уже ведёт открытую смену")
    if handed_shift(conn) is not None:
        raise ValueError("Сначала кто-то должен принять сданную смену")
    setting_set(conn, "next_user_id", str(user_id))


def next_user(conn):
    raw = setting_get(conn, "next_user_id")
    if not raw:
        return None
    return get_user(conn, int(raw))


def ensure_first_shift(conn, user) -> bool:
    """Открывает первую смену, если её назначили этому человеку. Возвращает True, если смена создана."""
    if open_shift(conn) is not None or handed_shift(conn) is not None:
        return False
    nxt = next_user(conn)
    if nxt is None or nxt["id"] != user["id"] or not user["can_duty"]:
        return False
    conn.execute(
        """INSERT INTO shifts (duty_user_id, started_at, status)
           VALUES (?, ?, 'open')""",
        (user["id"], now()),
    )
    setting_set(conn, "next_user_id", None)
    return True


def _known(conn, kind: str, value: str) -> None:
    if value and value not in names_of(conn, kind):
        raise ValueError(f"Значения нет в справочнике: {value}")


def create_event(conn, shift_id: int, data: dict) -> int:
    event_type = data.get("type")
    if event_type not in ("ac", "pr"):
        raise ValueError("Выберите тип события")
    department = (data.get("department") or "").strip()
    section_from = (data.get("section_from") or "").strip()
    section_to = (data.get("section_to") or "").strip()
    _known(conn, "department", department)
    _known(conn, "section", section_from)
    _known(conn, "section", section_to)
    known_services = names_of(conn, "service")
    lost = [item for item in data.get("lost") or [] if item in known_services]
    reserve = [item for item in data.get("reserve") or [] if item in known_services]
    prefix = "AC" if event_type == "ac" else "ПР"
    number = next_number(conn, "ac" if event_type == "ac" else "pr", prefix)
    cur = conn.execute(
        """INSERT INTO events (
            number, shift_id, type, status, created_at, department, line,
            section_from, section_to, damage, reporter_name, reporter_phone,
            services_lost, services_reserve, link_kind, link_key
        ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            number,
            shift_id,
            event_type,
            now(),
            department,
            (data.get("line") or "").strip(),
            section_from,
            section_to,
            (data.get("damage") or "").strip(),
            (data.get("reporter_name") or "").strip(),
            (data.get("reporter_phone") or "").strip(),
            json.dumps(lost, ensure_ascii=False),
            json.dumps(reserve, ensure_ascii=False),
            data.get("link_kind") or None,
            data.get("link_key") or None,
        ),
    )
    return cur.lastrowid


def get_event(conn, event_id: int):
    return conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()


def find_linked(conn, shift_id: int, link_kind: str, link_key: str):
    return conn.execute(
        """SELECT * FROM events
           WHERE shift_id = ? AND link_kind = ? AND link_key = ?
           ORDER BY id DESC LIMIT 1""",
        (shift_id, link_kind, link_key),
    ).fetchone()


def event_comments(conn, event_id: int):
    return conn.execute(
        """SELECT c.*, u.login, u.full_name, u.position
           FROM comments c JOIN users u ON u.id = c.author_id
           WHERE c.event_id = ?
           ORDER BY c.id""",
        (event_id,),
    ).fetchall()


def event_lines(event) -> list[str]:
    lines = ["Аварийное сообщение" if event["type"] == "ac" else "Плановые работы"]
    if event["section_from"] or event["section_to"]:
        left = event["section_from"] or "…"
        right = event["section_to"] or "…"
        if event["section_from"] and not event["section_to"]:
            lines.append(f"Участок {left}")
        else:
            lines.append(f"Участок {left} — {right}")
    if event["damage"]:
        lines.append(event["damage"])
    lost = _loads(event["services_lost"])
    reserve = _loads(event["services_reserve"])
    if lost:
        lines.append("Потеря сервисов: " + ", ".join(lost))
    if reserve:
        lines.append("Резерв сервисов: " + ", ".join(reserve))
    if event["department"]:
        lines.append(event["department"])
    if event["line"]:
        lines.append(event["line"])
    if event["reporter_name"] or event["reporter_phone"]:
        lines.append(
            "Доложил: "
            + " ".join(part for part in (event["reporter_name"], event["reporter_phone"]) if part)
        )
    return lines


def event_tone(event) -> str:
    if event["status"] == "closed":
        return "done"
    if event["type"] == "pr":
        return "planned"
    return "accident"


def status_label(status: str) -> str:
    return {"open": "открыто", "commented": "прокомментировано", "closed": "закрыто"}.get(
        status, status
    )


def add_comment(conn, event_id: int, author_id: int, body: str) -> None:
    event = get_event(conn, event_id)
    if event is None:
        raise ValueError("Событие не найдено")
    if event["status"] == "closed":
        raise ValueError("Событие закрыто")
    text = body.strip()
    if not text:
        raise ValueError("Введите комментарий")
    conn.execute(
        "INSERT INTO comments (event_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
        (event_id, author_id, text, now()),
    )
    if event["status"] == "open":
        conn.execute("UPDATE events SET status = 'commented' WHERE id = ?", (event_id,))


def close_event(conn, event_id: int) -> None:
    event = get_event(conn, event_id)
    if event is None:
        raise ValueError("Событие не найдено")
    if event["status"] == "closed":
        raise ValueError("Событие уже закрыто")
    conn.execute(
        "UPDATE events SET status = 'closed', closed_at = ? WHERE id = ?",
        (now(), event_id),
    )


def unclosed_events(conn):
    return conn.execute(
        "SELECT * FROM events WHERE status != 'closed' ORDER BY created_at"
    ).fetchall()


def unread_orders(conn, user_id: int):
    return conn.execute(
        """SELECT o.* FROM orders o
           WHERE NOT EXISTS (
               SELECT 1 FROM order_reads r
               WHERE r.order_id = o.id AND r.user_id = ?
           )
           ORDER BY o.created_at""",
        (user_id,),
    ).fetchall()


def is_red(conn, user_id: int) -> bool:
    if unclosed_events(conn):
        return True
    return bool(unread_orders(conn, user_id))


def create_round(conn, shift_id: int, checked_ids: list[int], temperatures: dict[int, str]) -> int:
    monitors = directory(conn, "monitoring")
    rooms = directory(conn, "room")
    checked = {int(item) for item in checked_ids}
    mon_map = {row["name"]: row["id"] in checked for row in monitors}
    temp_map = {}
    problems = []
    for row in rooms:
        raw = (temperatures.get(row["id"]) or "").strip().replace(",", ".")
        if raw == "":
            temp_map[row["name"]] = None
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"Температура «{row['name']}» должна быть числом") from exc
        temp_map[row["name"]] = value
        if value >= 42:
            problems.append(f"{row['name']} {value:g}°")
    for row in monitors:
        if row["id"] not in checked:
            problems.append(row["name"])
    ok = not problems
    if ok:
        summary = "Обход — норма"
    else:
        summary = "Обход — есть замечания: " + ", ".join(problems)
    number = next_number(conn, "round", "ОБ")
    cur = conn.execute(
        """INSERT INTO rounds
           (number, shift_id, created_at, ok, summary, monitoring, temperatures)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            number,
            shift_id,
            now(),
            int(ok),
            summary,
            json.dumps(mon_map, ensure_ascii=False),
            json.dumps(temp_map, ensure_ascii=False),
        ),
    )
    return cur.lastrowid


def last_round_of(conn, shift_id: int):
    return conn.execute(
        "SELECT * FROM rounds WHERE shift_id = ? ORDER BY id DESC LIMIT 1",
        (shift_id,),
    ).fetchone()


def create_order(conn, shift_id: int, body: str, user_ids: list[int], group_ids: list[int]) -> int:
    text = body.strip()
    if not text:
        raise ValueError("Введите текст распоряжения")
    number = next_number(conn, "order", "№Р")
    cur = conn.execute(
        "INSERT INTO orders (number, shift_id, body, created_at) VALUES (?, ?, ?, ?)",
        (number, shift_id, text, now()),
    )
    order_id = cur.lastrowid
    seen = set()
    shift = shift_group(conn)
    shift_gid = shift["id"] if shift else None

    def add_person(user, group_name: str, via_shift: bool) -> None:
        if user["id"] in seen and via_shift:
            conn.execute(
                """UPDATE order_people SET via_shift_group = 1, group_name = ?
                   WHERE order_id = ? AND user_id = ?""",
                (group_name, order_id, user["id"]),
            )
            conn.execute(
                "DELETE FROM order_popups WHERE order_id = ? AND user_id = ?",
                (order_id, user["id"]),
            )
            return
        if user["id"] in seen:
            return
        seen.add(user["id"])
        conn.execute(
            """INSERT INTO order_people
               (order_id, user_id, full_name, position, group_name, via_shift_group)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                user["id"],
                display_name(user),
                user["position"],
                group_name,
                int(via_shift),
            ),
        )
        if not via_shift:
            conn.execute(
                "INSERT OR IGNORE INTO order_popups (order_id, user_id) VALUES (?, ?)",
                (order_id, user["id"]),
            )

    for raw in user_ids:
        user = get_user(conn, int(raw))
        if user is None:
            continue
        membership = groups_of(conn, user["id"])
        group_name = membership[0]["name"] if membership else "—"
        add_person(user, group_name, False)
    for raw in group_ids:
        group = conn.execute("SELECT * FROM groups WHERE id = ?", (int(raw),)).fetchone()
        if group is None:
            continue
        members = conn.execute(
            """SELECT u.* FROM users u
               JOIN user_groups ug ON ug.user_id = u.id
               WHERE ug.group_id = ?
               ORDER BY u.login""",
            (group["id"],),
        ).fetchall()
        via_shift = shift_gid is not None and group["id"] == shift_gid
        for user in members:
            add_person(user, group["name"], via_shift)
    return order_id


def get_order(conn, order_id: int):
    return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def order_people(conn, order_id: int):
    return conn.execute(
        "SELECT * FROM order_people WHERE order_id = ? ORDER BY id",
        (order_id,),
    ).fetchall()


def mark_order_read(conn, order_id: int, user_id: int) -> None:
    conn.execute(
        """INSERT INTO order_reads (order_id, user_id, read_at) VALUES (?, ?, ?)
           ON CONFLICT(order_id, user_id) DO NOTHING""",
        (order_id, user_id, now()),
    )


def pending_popup(conn, user_id: int):
    return conn.execute(
        """SELECT o.* FROM order_popups p
           JOIN orders o ON o.id = p.order_id
           WHERE p.user_id = ? AND p.acked_at IS NULL
           ORDER BY o.id LIMIT 1""",
        (user_id,),
    ).fetchone()


def ack_popup(conn, order_id: int, user_id: int) -> None:
    conn.execute(
        """UPDATE order_popups SET acked_at = ?
           WHERE order_id = ? AND user_id = ? AND acked_at IS NULL""",
        (now(), order_id, user_id),
    )


def orders_for_shift_group(conn, handed) -> list:
    return conn.execute(
        """SELECT DISTINCT o.* FROM orders o
           JOIN order_people p ON p.order_id = o.id
           WHERE p.via_shift_group = 1
             AND o.announced_shift_id IS NULL
             AND o.created_at <= ?
           ORDER BY o.created_at""",
        (handed["handed_at"],),
    ).fetchall()


def save_handover(conn, shift, checked_ids: list[int], comments: dict[int, str]) -> None:
    if shift["status"] != "open":
        raise ValueError("Смена уже сдана")
    nxt = next_user(conn)
    if nxt is None:
        raise ValueError("Администратор ещё не назначил следующего дежурного")
    conn.execute("DELETE FROM kit_marks WHERE shift_id = ? AND phase = 'handover'", (shift["id"],))
    checked = {int(item) for item in checked_ids}
    for row in directory(conn, "kit"):
        conn.execute(
            """INSERT INTO kit_marks
               (shift_id, phase, item_id, item_name, checked, comment)
               VALUES (?, 'handover', ?, ?, ?, ?)""",
            (
                shift["id"],
                row["id"],
                row["name"],
                int(row["id"] in checked),
                (comments.get(row["id"]) or "").strip(),
            ),
        )
    conn.execute(
        """UPDATE shifts
           SET status = 'handed', handed_at = ?, next_user_id = ?
           WHERE id = ?""",
        (now(), nxt["id"], shift["id"]),
    )


def accept_shift(conn, handed, user, checked_ids: list[int]) -> int:
    if handed is None or handed["status"] != "handed":
        raise ValueError("Нет смены, которая ждёт приёмки")
    if handed["next_user_id"] != user["id"]:
        raise ValueError("Принять смену может только назначенный дежурный")
    required = [row["id"] for row in directory(conn, "kit")] + [
        row["id"] for row in directory(conn, "monitoring")
    ]
    checked = {int(item) for item in checked_ids}
    if any(item not in checked for item in required):
        raise ValueError("Отметьте все комплекты и системы мониторинга")
    started = now()
    cur = conn.execute(
        """INSERT INTO shifts (duty_user_id, started_at, status, prev_shift_id)
           VALUES (?, ?, 'open', ?)""",
        (user["id"], started, handed["id"]),
    )
    new_id = cur.lastrowid
    for row in directory(conn, "kit") + directory(conn, "monitoring"):
        conn.execute(
            """INSERT INTO kit_marks
               (shift_id, phase, item_id, item_name, checked, comment)
               VALUES (?, 'accept', ?, ?, 1, '')""",
            (new_id, row["id"], row["name"]),
        )
    conn.execute(
        "UPDATE shifts SET status = 'closed', ended_at = ? WHERE id = ?",
        (started, handed["id"]),
    )
    conn.execute(
        """UPDATE orders SET announced_shift_id = ?
           WHERE announced_shift_id IS NULL AND created_at <= ?""",
        (new_id, handed["handed_at"]),
    )
    setting_set(conn, "next_user_id", None)
    return new_id


def kit_marks(conn, shift_id: int, phase: str):
    return conn.execute(
        """SELECT * FROM kit_marks
           WHERE shift_id = ? AND phase = ?
           ORDER BY id""",
        (shift_id, phase),
    ).fetchall()


def create_report(conn, shift_id: int) -> int:
    number = next_number(conn, "report", "№ОТ")
    cur = conn.execute(
        "INSERT INTO reports (number, shift_id, created_at) VALUES (?, ?, ?)",
        (number, shift_id, now()),
    )
    return cur.lastrowid


def _pack_event(conn, event, viewer_is_duty: bool, viewer_is_brig: bool, blocked: bool):
    comments = []
    for row in event_comments(conn, event["id"]):
        date, time = split_dt(row["created_at"])
        comments.append(
            {
                "author": row["full_name"] or row["login"],
                "body": row["body"],
                "date": date,
                "time": time,
            }
        )
    date, time = split_dt(event["created_at"])
    can_write = (not blocked) and event["status"] != "closed" and (viewer_is_duty or viewer_is_brig)
    return {
        "id": event["id"],
        "number": event["number"],
        "lines": event_lines(event),
        "tone": event_tone(event),
        "status": status_label(event["status"]),
        "date": date,
        "time": time,
        "comments": comments,
        "can_comment": can_write,
        "can_close": (not blocked) and viewer_is_duty and event["status"] != "closed",
        "can_open": not blocked,
        "highlight": False,
    }


def feed_for(conn, shift, viewer) -> dict:
    is_duty = shift is not None and shift["status"] == "open" and shift["duty_user_id"] == viewer["id"]
    blocked_orders = unread_orders(conn, viewer["id"]) if is_duty else []
    blocked = bool(blocked_orders)
    duty = get_user(conn, shift["duty_user_id"])
    date, time = split_dt(shift["started_at"])

    own_ids = set()
    items = []

    def add_item(kind, at, title, lines, number, tone, href, event_id=None):
        item_date, item_time = split_dt(at)
        items.append(
            {
                "kind": kind,
                "at": at,
                "title": title,
                "lines": lines,
                "number": number,
                "tone": tone,
                "href": href,
                "date": item_date,
                "time": item_time,
                "event_id": event_id,
            }
        )

    pinned_events = []
    for event in unclosed_events(conn):
        if event["shift_id"] == shift["id"]:
            continue
        packed = _pack_event(conn, event, is_duty, bool(viewer["is_brigadier"]), blocked)
        packed["highlight"] = True
        pinned_events.append(packed)

    closed_here = conn.execute(
        """SELECT * FROM events
           WHERE shift_id != ? AND status = 'closed' AND closed_at >= ?
           ORDER BY closed_at""",
        (shift["id"], shift["started_at"]),
    ).fetchall()
    for event in closed_here:
        packed = _pack_event(conn, event, is_duty, bool(viewer["is_brigadier"]), blocked)
        packed["highlight"] = False
        add_item(
            "event",
            event["closed_at"],
            packed["lines"][0],
            packed["lines"][1:],
            event["number"],
            "done",
            f"/events/{event['id']}",
            event["id"],
        )

    pinned_orders = []
    unread_ids = {row["id"] for row in blocked_orders}
    historical = conn.execute(
        "SELECT * FROM orders WHERE shift_id != ? ORDER BY created_at",
        (shift["id"],),
    ).fetchall()
    for order in historical:
        date_o, time_o = split_dt(order["created_at"])
        card = {
            "id": order["id"],
            "number": order["number"],
            "body": order["body"],
            "date": date_o,
            "time": time_o,
            "highlight": order["id"] in unread_ids,
        }
        if order["id"] in unread_ids:
            pinned_orders.append(card)
        else:
            add_item("order", order["created_at"], "Распоряжение", [order["body"]], order["number"], "order", f"/orders/{order['id']}")

    for event in conn.execute(
        "SELECT * FROM events WHERE shift_id = ? ORDER BY created_at", (shift["id"],)
    ):
        own_ids.add(event["id"])
        packed = _pack_event(conn, event, is_duty, bool(viewer["is_brigadier"]), blocked)
        add_item(
            "event",
            event["created_at"],
            packed["lines"][0],
            packed["lines"][1:],
            event["number"],
            packed["tone"],
            f"/events/{event['id']}",
            event["id"],
        )

    for rnd in conn.execute(
        "SELECT * FROM rounds WHERE shift_id = ? ORDER BY created_at", (shift["id"],)
    ):
        add_item(
            "round",
            rnd["created_at"],
            rnd["summary"],
            [],
            rnd["number"],
            "done" if rnd["ok"] else "accident",
            None,
        )

    for order in conn.execute(
        "SELECT * FROM orders WHERE shift_id = ? ORDER BY created_at", (shift["id"],)
    ):
        if order["id"] in unread_ids:
            date_o, time_o = split_dt(order["created_at"])
            pinned_orders.append(
                {
                    "id": order["id"],
                    "number": order["number"],
                    "body": order["body"],
                    "date": date_o,
                    "time": time_o,
                    "highlight": True,
                }
            )
        else:
            add_item(
                "order",
                order["created_at"],
                "Распоряжение",
                [order["body"]],
                order["number"],
                "order",
                f"/orders/{order['id']}",
            )

    for report in conn.execute(
        "SELECT * FROM reports WHERE shift_id = ? ORDER BY created_at", (shift["id"],)
    ):
        add_item(
            "report",
            report["created_at"],
            "Отчёт",
            [],
            report["number"],
            "report",
            f"/shifts/{shift['id']}/summary",
        )

    items.sort(key=lambda item: item["at"])
    event_cards = {}
    for event_id in own_ids:
        event = get_event(conn, event_id)
        event_cards[event_id] = _pack_event(
            conn, event, is_duty, bool(viewer["is_brigadier"]), blocked
        )
    for event in closed_here:
        event_cards[event["id"]] = _pack_event(
            conn, event, is_duty, bool(viewer["is_brigadier"]), blocked
        )

    nxt = next_user(conn)
    header_action = None
    header_enabled = False
    if is_duty:
        header_action = "handover"
        header_enabled = nxt is not None
    return {
        "shift": shift,
        "duty_name": display_name(duty),
        "date": date,
        "time": time,
        "blocked": blocked,
        "pinned_events": pinned_events,
        "pinned_orders": pinned_orders,
        "entries": items,
        "events": event_cards,
        "can_act": is_duty and not blocked,
        "is_duty": is_duty,
        "header_action": header_action,
        "header_enabled": header_enabled,
        "next_name": display_name(nxt) if nxt else "",
    }


def visible_shift_for(conn, user):
    current = open_shift(conn)
    if current is not None:
        if current["duty_user_id"] == user["id"] or user["is_brigadier"] or user["is_admin"]:
            return current
    handed = handed_shift(conn)
    if handed is not None and (user["is_brigadier"] or user["is_admin"] or handed["duty_user_id"] == user["id"]):
        return handed
    return current


def target_shift_for_event(conn, user):
    handed = handed_shift(conn)
    if handed is not None and handed["next_user_id"] == user["id"]:
        return handed
    current = open_shift(conn)
    if current is not None and current["duty_user_id"] == user["id"]:
        return current
    return None


def can_comment(conn, user, event) -> bool:
    if event["status"] == "closed":
        return False
    if user["is_brigadier"]:
        return True
    current = open_shift(conn)
    return current is not None and current["duty_user_id"] == user["id"]


def can_close(conn, user, event) -> bool:
    if event["status"] == "closed":
        return False
    current = open_shift(conn)
    return current is not None and current["duty_user_id"] == user["id"]


def duty_is_blocked(conn, user) -> bool:
    current = open_shift(conn)
    if current is None or current["duty_user_id"] != user["id"]:
        return False
    return bool(unread_orders(conn, user["id"]))


def room_states(conn, shift_id: int | None):
    rnd = last_round_of(conn, shift_id) if shift_id else None
    temps = _loads(rnd["temperatures"]) if rnd else {}
    if isinstance(temps, dict):
        stored = temps
    else:
        stored = {}
    states = []
    for row in directory(conn, "room"):
        value = stored.get(row["name"])
        states.append(
            {
                "name": row["name"],
                "value": value,
                "hot": value is not None and float(value) >= 42,
            }
        )
    return states


def monitoring_states(conn, shift_id: int | None):
    rnd = last_round_of(conn, shift_id) if shift_id else None
    stored = _loads(rnd["monitoring"]) if rnd else {}
    if not isinstance(stored, dict):
        stored = {}
    return [{"name": row["name"], "checked": bool(stored.get(row["name"]))} for row in directory(conn, "monitoring")]


def unclosed_rows(conn, user_id: int):
    rows = []
    for event in unclosed_events(conn):
        date, time = split_dt(event["created_at"])
        rows.append(
            {
                "number": event["number"],
                "text": event_lines(event)[0],
                "date": date,
                "time": time,
                "kind": "event",
            }
        )
    for order in unread_orders(conn, user_id):
        date, time = split_dt(order["created_at"])
        rows.append(
            {
                "number": order["number"],
                "text": "Распоряжение",
                "date": date,
                "time": time,
                "kind": "order",
            }
        )
    return rows


def summary_document(conn, shift_id: int) -> dict:
    shift = shift_by_id(conn, shift_id)
    if shift is None:
        raise ValueError("Смена не найдена")
    duty = get_user(conn, shift["duty_user_id"])
    date, time = split_dt(shift["started_at"])
    end_date, end_time = split_dt(shift["ended_at"] or shift["handed_at"])
    lines = [f"Смену принял: {display_name(duty)}"]
    for event in conn.execute(
        "SELECT * FROM events WHERE shift_id = ? ORDER BY created_at", (shift_id,)
    ):
        lines.append(event["number"] + " · " + " / ".join(event_lines(event)) + f" · {status_label(event['status'])}")
        for comment in event_comments(conn, event["id"]):
            lines.append(f"    комментарий {comment['full_name'] or comment['login']}: {comment['body']}")
    for rnd in conn.execute(
        "SELECT * FROM rounds WHERE shift_id = ? ORDER BY created_at", (shift_id,)
    ):
        lines.append(f"{rnd['number']} · {rnd['summary']}")
    for order in conn.execute(
        "SELECT * FROM orders WHERE shift_id = ? ORDER BY created_at", (shift_id,)
    ):
        lines.append(f"{order['number']} · {order['body']}")
    for report in conn.execute(
        "SELECT * FROM reports WHERE shift_id = ? ORDER BY created_at", (shift_id,)
    ):
        lines.append(f"{report['number']} · отчёт")
    if shift["handed_at"]:
        lines.append(f"Смену сдал: {display_name(duty)}")
    kits = [
        {"name": row["item_name"], "checked": bool(row["checked"]), "comment": row["comment"]}
        for row in kit_marks(conn, shift_id, "handover")
    ]
    return {
        "shift_id": shift_id,
        "duty_name": display_name(duty),
        "date": date,
        "time": time,
        "end_date": end_date,
        "end_time": end_time,
        "status": shift["status"],
        "lines": lines,
        "unclosed": [
            f"{row['number']} · {row['text']}"
            for row in unclosed_rows(conn, shift["duty_user_id"])
        ],
        "kits": kits,
        "monitoring": monitoring_states(conn, shift_id),
        "rooms": room_states(conn, shift_id),
    }


def seed_demo(conn) -> list[str]:
    created = []
    group = shift_group(conn)
    people = [
        ("duty1", "duty1", "Дежурный первый", "дежурный смены", True, False, True),
        ("duty2", "duty2", "Дежурный второй", "дежурный смены", True, False, True),
        ("brig", "brig", "Бригадир смены", "бригадир", False, True, False),
    ]
    for login, password, full_name, position, can_duty, is_brigadier, in_shift in people:
        if get_user_by_login(conn, login) is not None:
            continue
        groups = [group["id"]] if in_shift and group is not None else []
        create_user(
            conn,
            login,
            password,
            full_name,
            position,
            False,
            can_duty,
            is_brigadier,
            groups,
        )
        created.append(login)
    return created
